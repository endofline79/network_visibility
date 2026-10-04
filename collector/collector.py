"""Source-gated NetFlow v9 -> GoFlow2 -> bounded durable spool -> VictoriaLogs.

No payload capture, no firewall credentials, and no external service calls.
UDP is best effort; retries after ambiguous HTTP acknowledgements are deduplicated
by event_id in the dashboard. Records are NOT connection/session counts.
"""
import hashlib
import ipaddress
import json
import os
import signal
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EXPORTER = os.getenv("FLOW_EXPORTER", "192.168.5.1")
LOG_URL = os.getenv("VICTORIALOGS_URL", "http://logs:9428")
STATE = Path(os.getenv("FLOW_STATE_DIR", "/state"))
MAX_PENDING = 100000
stop = threading.Event()
lock = threading.Lock()
stats = {"started_at": time.time(), "datagrams": 0, "rejected_datagrams": 0,
         "decoded_records": 0, "invalid_records": 0, "overflow_records": 0,
         "inserted_records": 0, "last_datagram": None, "last_decoded": None,
         "last_insert": None, "insert_error": False, "pending_records": 0}


def normalize(raw):
    if raw.get("type") != "NETFLOW_V9" or raw.get("sampler_address") != "127.0.0.1":
        raise ValueError("Unexpected decoder source or protocol")
    src, dst = str(ipaddress.ip_address(raw["src_addr"])), str(ipaddress.ip_address(raw["dst_addr"]))
    # ng_netflow exports unsampled counters. Refuse unexpected sampling rather
    # than silently turn sample counts into precise-looking traffic totals.
    if int(raw.get("sampling_rate", 0)) not in (0, 1):
        raise ValueError("Unexpected sampling")
    def number(key, maximum=2**63-1):
        n = int(raw.get(key, 0))
        if not 0 <= n <= maximum:
            raise ValueError("Out of range")
        return n
    end = number("time_flow_end_ns")
    received = number("time_received_ns")
    if not end or abs(end-received) > 86400 * 10**9:
        raise ValueError("Invalid exporter timestamp")
    event = {"app_name": "opnsense-flow", "hostname": "OPNsense", "remote_ip": EXPORTER,
             "src_addr": src, "dst_addr": dst, "proto": str(raw.get("proto", ""))[:20],
             "src_port": number("src_port", 65535), "dst_port": number("dst_port", 65535),
             "bytes": number("opnsense_bytes"), "packets": number("opnsense_packets"),
             "in_if": number("in_if", 65535), "out_if": number("out_if", 65535),
             "flow_start_ns": number("time_flow_start_ns"), "flow_end_ns": end,
             "sequence_num": number("sequence_num"), "observation_domain_id": number("observation_domain_id"),
             "sampling_rate": 1, "observation": "egress-only", "schema": "2"}
    if not event['bytes'] or not event['packets']:
        raise ValueError('Missing FreeBSD counters')
    event["event_id"] = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
    event["_time"] = datetime.fromtimestamp(end / 1e9, timezone.utc).isoformat()
    event["_msg"] = f"{src}:{event['src_port']} -> {dst}:{event['dst_port']} {event['proto']} {event['bytes']} bytes"
    return event


def database(path):
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA journal_size_limit=4194304")
    db.execute("CREATE TABLE IF NOT EXISTS pending (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
    return db


def enqueue(db, event):
    if db.execute("SELECT count(*) FROM pending").fetchone()[0] >= MAX_PENDING:
        return False
    with db:
        db.execute("INSERT OR IGNORE INTO pending VALUES (?,?)", (event["event_id"], json.dumps(event)))
    return True


def writer():
    db = database(STATE / "pending.sqlite3")
    while not stop.is_set():
        rows = db.execute("SELECT id,body FROM pending ORDER BY rowid LIMIT 500").fetchall()
        with lock:
            stats["pending_records"] = db.execute("SELECT count(*) FROM pending").fetchone()[0]
        if not rows:
            stop.wait(1)
            continue
        try:
            request = urllib.request.Request(LOG_URL + "/insert/jsonline?_stream_fields=hostname,app_name",
                data=("\n".join(row[1] for row in rows)+"\n").encode(),
                headers={"Content-Type": "application/stream+json"}, method="POST")
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError("Insert rejected")
                response.read(4096)
            with db:
                db.executemany("DELETE FROM pending WHERE id=?", [(r[0],) for r in rows])
            with lock:
                stats["inserted_records"] += len(rows)
                stats["last_insert"] = time.time()
                stats["insert_error"] = False
        except Exception:
            with lock:
                stats["insert_error"] = True
            stop.wait(5)
    db.close()


def proxy():
    incoming = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    incoming.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4*1024*1024)
    incoming.bind(("0.0.0.0", 2056))
    incoming.settimeout(1)
    outgoing = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while not stop.is_set():
        try:
            packet, peer = incoming.recvfrom(65535)
        except socket.timeout:
            continue
        if peer[0] != EXPORTER or len(packet) < 20 or packet[:2] != b"\x00\x09":
            with lock:
                stats["rejected_datagrams"] += 1
            continue
        outgoing.sendto(packet, ("127.0.0.1", 2055))
        with lock:
            stats["datagrams"] += 1
            stats["last_datagram"] = time.time()
    incoming.close()
    outgoing.close()


def main():
    os.umask(0o077)
    STATE.mkdir(exist_ok=True)
    db = database(STATE / "pending.sqlite3")
    decoder = subprocess.Popen(["goflow2", "-listen", "netflow://127.0.0.1:2055",
        "-addr", "127.0.0.1:8080", "-mapping", "/app/mapping.yaml", "-loglevel", "error"], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    workers = [threading.Thread(target=f, daemon=True) for f in (proxy, writer)]
    for worker in workers:
        worker.start()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/health", "/status"):
                self.send_error(404)
                return
            with lock:
                status = dict(stats)
            status["running"] = decoder.poll() is None and all(t.is_alive() for t in workers)
            status["exporter"] = EXPORTER
            status["stale"] = not status["last_decoded"] or time.time()-status["last_decoded"] > 180
            status["buffer_limit"] = MAX_PENDING
            status["decoder_errors"] = None
            status["udp_receive_errors"] = None
            try:
                with urllib.request.urlopen('http://127.0.0.1:8080/metrics', timeout=2) as metrics:
                    lines = metrics.read(1024*1024).decode().splitlines()
                status['decoder_errors'] = sum(int(float(line.rsplit(' ', 1)[1])) for line in lines
                    if line.startswith('goflow2_flow_decoder_error_total{'))
                udp = [line.split()[1:] for line in Path('/proc/net/snmp').read_text().splitlines() if line.startswith('Udp:')]
                status['udp_receive_errors'] = int(dict(zip(udp[0], udp[1]))['InErrors'])
            except Exception:
                pass
            self.send_response(200 if status["running"] else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(("0.0.0.0", 8081), Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    def shutdown(*args):
        stop.set()
        decoder.terminate()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        for line in decoder.stdout:
            try:
                event = normalize(json.loads(line))
                accepted = enqueue(db, event)
                with lock:
                    stats["decoded_records"] += 1
                    stats["last_decoded"] = time.time()
                    if not accepted:
                        stats["overflow_records"] += 1
            except (ValueError, KeyError, TypeError, OverflowError):
                with lock:
                    stats["invalid_records"] += 1
    finally:
        stop.set()
        if decoder.poll() is None:
            decoder.terminate()
        decoder.wait(timeout=10)
        for worker in workers:
            worker.join(timeout=12)
        db.close()
        http.shutdown()
    if decoder.returncode not in (0, -15):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
