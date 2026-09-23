"""Bounded Pi-hole v6 reader and local DNS log forwarding. No DNS control or AI."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import math
import os
from pathlib import Path
import re
import ssl
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit

HOST = "192.168.5.238"
POLL_SECONDS, STALE_SECONDS = 60, 150
MAX_BODY, PAGE_SIZE, MAX_QUERIES = 4 * 1024 * 1024, 500, 5000
SETTLE_SECONDS = 60
READ_PATH = re.compile(r"/api/(?:stats/summary|stats/top_domains\?count=8&blocked=(?:true|false)|"
                       r"stats/top_clients\?count=8|history|info/ftl|dns/blocking|"
                       r"queries\?length=500&from=\d+&until=\d+(?:&cursor=\d+&start=\d+)?)")
BLOCKED = frozenset(("GRAVITY", "REGEX", "DENYLIST", "GRAVITY_CNAME", "REGEX_CNAME",
                     "DENYLIST_CNAME", "SPECIAL_DOMAIN", "EXTERNAL_BLOCKED_IP",
                     "EXTERNAL_BLOCKED_NULL", "EXTERNAL_BLOCKED_NXRA", "EXTERNAL_BLOCKED_EDE15"))


class DnsError(Exception):
    pass


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def number(value):
    return value if type(value) in (float, int) and math.isfinite(value) and value >= 0 else None


def text(value, limit=255):
    return "".join(c for c in value if c.isprintable())[:limit] if isinstance(value, str) else ""


def objects(value, limit):
    if not isinstance(value, list) or len(value) > limit or not all(isinstance(v, dict) for v in value):
        raise DnsError("Pi-hole returned an unexpected data format.")
    return value


def obj(value):
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    fingerprint: str = ""
    key_file: str = "/run/visibility-secrets/pihole_app_password"
    log_url: str = "http://logs:9428"

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("PIHOLE_ENABLED", "false").lower() == "true",
                   os.environ.get("PIHOLE_CERT_SHA256", ""),
                   os.environ.get("PIHOLE_PASSWORD_FILE", cls.key_file),
                   os.environ.get("VICTORIALOGS_URL", cls.log_url))


class ReadOnlyApi:
    def __init__(self, config):
        if not re.fullmatch(r"[a-fA-F0-9]{64}", config.fingerprint):
            raise DnsError("Pi-hole certificate pin is missing or invalid.")
        self.pin, self.sid = config.fingerprint.lower(), None
        try:
            with open(config.key_file, encoding="utf-8") as source:
                self.password = source.read(8193).strip()
        except (OSError, UnicodeError):
            raise DnsError("Pi-hole credential file is unavailable.") from None
        if not self.password or len(self.password) > 8192 or any(ord(c) < 32 for c in self.password):
            raise DnsError("Pi-hole credential file is invalid.")

    def _request(self, method, path, deadline, body=None):
        if not ((method == "GET" and READ_PATH.fullmatch(path)) or
                (path == "/api/auth" and method in ("POST", "DELETE"))):
            raise DnsError("Endpoint is outside the DNS collection scope.")

        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise DnsError("DNS collection exceeded its time budget.")
            return min(4, value)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(HOST, 443, context=context, timeout=remaining())
        try:
            conn.connect()
            if not hmac.compare_digest(hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest(), self.pin):
                raise DnsError("Pi-hole certificate changed; no credential was sent.")
            conn.sock.settimeout(remaining())
            headers = {"Accept": "application/json"}
            if self.sid:
                headers["X-FTL-SID"] = self.sid
            if body is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, path, json.dumps(body) if body is not None else None, headers)
            response = conn.getresponse()
            if response.status == 401:
                self.sid = None
            if response.status not in ((204,) if method == "DELETE" else (200,)):
                raise DnsError(f"Pi-hole returned HTTP {response.status}.")
            chunks, size = [], 0
            while True:
                timeout = remaining()
                if conn.sock is not None:
                    conn.sock.settimeout(timeout)
                chunk = response.read1(min(65536, MAX_BODY + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BODY:
                    raise DnsError("Pi-hole response exceeded the size bound.")
            payload = json.loads(b"".join(chunks)) if chunks else {}
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except DnsError:
            raise
        except (OSError, http.client.HTTPException):
            raise DnsError("Pi-hole is unreachable or the request timed out.") from None
        except (ValueError, UnicodeError):
            raise DnsError("Pi-hole returned an invalid response.") from None
        finally:
            conn.close()

    def get(self, path, deadline):
        if not READ_PATH.fullmatch(path):
            raise DnsError("Endpoint is outside the DNS collection scope.")
        if self.sid is None:
            session = obj(self._request("POST", "/api/auth", deadline, {"password": self.password}).get("session"))
            sid = session.get("sid")
            if session.get("valid") is not True or not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9+/=_-]{8,256}", sid):
                raise DnsError("Pi-hole authentication did not create a valid session.")
            self.sid = sid
        return self._request("GET", path, deadline)

    def close(self):
        if self.sid:
            try:
                self._request("DELETE", "/api/auth", time.monotonic() + 4)
            except DnsError:
                pass
            finally:
                self.sid = None


def collect_summary(api, deadline, now):
    summary = api.get("/api/stats/summary", deadline)
    queries, clients = obj(summary.get("queries")), obj(summary.get("clients"))
    if any(number(queries.get(k)) is None for k in ("total", "blocked", "cached", "forwarded")):
        raise DnsError("Pi-hole summary is incomplete.")
    ftl = obj(api.get("/api/info/ftl", deadline).get("ftl"))
    history = objects(api.get("/api/history", deadline).get("history"), 300)
    domains = {}
    for blocked in (False, True):
        rows = objects(api.get(f"/api/stats/top_domains?count=8&blocked={str(blocked).lower()}", deadline).get("domains"), 8)
        domains["blocked" if blocked else "permitted"] = [
            {"domain": text(r.get("domain")), "count": number(r.get("count"))} for r in rows]
    top = objects(api.get("/api/stats/top_clients?count=8", deadline).get("clients"), 8)
    blocking = api.get("/api/dns/blocking", deadline).get("blocking")
    return {"observed_at": stamp(now), "queries": {k: number(queries.get(k)) for k in
            ("total", "blocked", "cached", "forwarded", "percent_blocked", "unique_domains")},
            "clients": number(clients.get("active")), "privacy_level": number(ftl.get("privacy_level")),
            "blocking": blocking if blocking in ("enabled", "disabled", "failed", "unknown") else "unknown",
            "history": [{k: number(r.get(k)) for k in ("timestamp", "total", "blocked", "cached", "forwarded")}
                        for r in history if number(r.get("timestamp")) is not None],
            "top_domains": domains, "top_clients": [{"ip": text(r.get("ip"), 64), "name": text(r.get("name")),
                                                      "count": number(r.get("count"))} for r in top]}


def query_record(row):
    query_id, when = row.get("id"), row.get("time")
    if type(query_id) is not int or query_id < 0 or number(when) is None or when <= 0:
        raise DnsError("Pi-hole query identity or timestamp is invalid.")
    status = text(row.get("status"), 50) or "UNKNOWN"
    outcome = "blocked" if status in BLOCKED else "cached" if status in ("CACHE", "CACHE_STALE") else "forwarded" if status == "FORWARDED" else "other"
    client, reply = obj(row.get("client")), obj(row.get("reply"))
    result = {"_time": stamp(when), "event_id": f"{HOST}:{query_id}:{when:.6f}", "query_id": str(query_id),
              "hostname": "ns0", "app_name": "pihole-dns", "remote_ip": HOST, "source_kind": "dns",
              "domain": text(row.get("domain")), "query_type": text(row.get("type"), 30),
              "status": status, "outcome": outcome, "client_ip": text(client.get("ip"), 64),
              "client_name": text(client.get("name")), "reply_type": text(reply.get("type"), 40),
              "upstream": text(row.get("upstream")), "dnssec": text(row.get("dnssec"), 40)}
    result["_msg"] = f'{result["client_ip"]} {result["client_name"]} {result["query_type"]} {result["domain"]} {status} {result["reply_type"]}'
    # Preserve source status, including unresolved IN_PROGRESS. No threat inference.
    return result


def collect_queries(api, start, end, deadline):
    rows, seen, cursor, expected = [], set(), None, None
    while True:
        path = f"/api/queries?length={PAGE_SIZE}&from={start}&until={end}"
        if cursor is not None:
            # Pi-hole repeats a snapshot anchor; start advances within that anchor.
            path += f"&cursor={cursor}&start={len(rows)}"
        payload = api.get(path, deadline)
        batch = objects(payload.get("queries"), PAGE_SIZE)
        total, anchor = payload.get("recordsFiltered"), payload.get("cursor")
        if type(total) is not int or total < 0 or total > MAX_QUERIES:
            raise DnsError("DNS query window is unavailable or exceeds 5,000 records; checkpoint preserved.")
        earliest = number(payload.get("earliest_timestamp"))
        if earliest is None or earliest <= 0 or earliest > start:
            raise DnsError("Pi-hole no longer has the checkpoint's in-memory history; collection needs review.")
        if (type(anchor) is not int or anchor < 0 or
                (expected is not None and (expected != total or cursor != anchor)) or len(rows) + len(batch) > total):
            raise DnsError("Pi-hole query pagination changed; checkpoint preserved.")
        expected, cursor = total, anchor
        for row in batch:
            record = query_record(row)
            if record["event_id"] in seen or not start <= row["time"] <= end:
                raise DnsError("Pi-hole query page is inconsistent; checkpoint preserved.")
            seen.add(record["event_id"])
            rows.append(record)
        if len(rows) == expected:
            # API bounds are inclusive; our checkpoint windows are half-open.
            return [r for r in rows if datetime.fromisoformat(r["_time"]).timestamp() < end]
        if not batch:
            raise DnsError("Pi-hole query page is incomplete; checkpoint preserved.")


def forward(config, rows, deadline):
    if not rows:
        return
    target = urlsplit(config.log_url)
    if target.scheme != "http" or target.hostname not in ("logs", "127.0.0.1", "localhost") or target.username or target.query or target.fragment or target.path not in ("", "/"):
        raise DnsError("DNS archive destination must be the local collector.")
    timeout = min(5, deadline - time.monotonic())
    if timeout <= 0:
        raise DnsError("DNS collection exceeded its time budget.")
    body = b"".join((json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n").encode() for row in rows)
    if len(body) > 8 * 1024 * 1024:
        raise DnsError("DNS archive batch exceeded its size bound.")
    conn = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=timeout)
    try:
        conn.request("POST", "/insert/jsonline?" + urlencode({"_stream_fields": "hostname,app_name"}), body,
                     {"Content-Type": "application/stream+json"})
        response = conn.getresponse()
        if response.status != 200:
            raise DnsError(f"Local DNS archive returned HTTP {response.status}; batch retained for retry.")
        response.read(1024)
    except (OSError, http.client.HTTPException):
        raise DnsError("Local DNS archive is unavailable; batch retained for retry.") from None
    finally:
        conn.close()


class DnsSource:
    def __init__(self, path, config=None, api_factory=ReadOnlyApi, sender=forward, clock=time.time):
        self.path, self.config = Path(path), config or Config.from_env()
        self.api_factory, self.sender, self.clock = api_factory, sender, clock
        self.lock, self.poll_lock, self.stop = threading.Lock(), threading.Lock(), threading.Event()
        self.worker, self.api = None, None
        self.state = {"version": 1, "snapshot": None, "since": None, "through": None, "pending": None}
        self.error, self.archive_error, self.last_attempt, self.next_poll = None, None, None, None
        self.storage_error = False
        try:
            if self.path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError()
            value = json.loads(self.path.read_text())
            if value.get("version") != 1 or any(k not in value for k in self.state):
                raise ValueError()
            for key in ("since", "through"):
                if number(value[key]) is None:
                    raise ValueError()
            pending = value["pending"]
            if pending is not None and (not isinstance(pending, dict) or number(pending.get("end")) is None or
                                        not isinstance(pending.get("rows"), list) or len(pending["rows"]) > MAX_QUERIES):
                raise ValueError()
            self.state = value
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError):
            self.storage_error = True
            self.error = "Saved DNS checkpoint could not be read; collection stopped to preserve it."

    def _save(self, state):
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, prefix=".pihole-", delete=False) as temp:
            try:
                json.dump(state, temp, allow_nan=False)
                temp.flush()
                os.fsync(temp.fileno())
                os.replace(temp.name, self.path)
                with self.lock:
                    self.state = state
            finally:
                if os.path.exists(temp.name):
                    os.unlink(temp.name)

    def poll_once(self):
        if not self.config.enabled or self.storage_error or not self.poll_lock.acquire(blocking=False):
            return
        deadline = time.monotonic() + 22
        self.last_attempt = stamp(self.clock())
        try:
            if self.api is None:
                self.api = self.api_factory(self.config)
            if self.state["through"] is None:
                since = int(self.clock()) - 900
                self._save({**self.state, "since": since, "through": since})
            try:
                snapshot = collect_summary(self.api, deadline, self.clock())
                self._save({**self.state, "snapshot": snapshot})
                self.error = None
            except DnsError as exc:
                self.error = str(exc)
            # A failed summary never advances the archive checkpoint by itself.
            pending = self.state["pending"]
            if pending is None:
                start = self.state["through"]
                end = min(int(self.clock()) - SETTLE_SECONDS, start + 300)
                if end <= start:
                    return
                rows = collect_queries(self.api, start, end, deadline)
                pending = {"end": end, "rows": rows}
                self._save({**self.state, "pending": pending})
            # Persist the exact batch before send, so an ambiguous retry is identical.
            self.sender(self.config, pending["rows"], deadline)
            self._save({**self.state, "through": pending["end"], "pending": None})
            self.archive_error = None
        except DnsError as exc:
            self.archive_error = str(exc)
        except Exception:
            self.archive_error = "DNS collection or local checkpoint storage failed; checkpoint preserved."
        finally:
            self.next_poll = stamp(self.clock() + POLL_SECONDS)
            self.poll_lock.release()

    def status(self):
        with self.lock:
            snapshot = self.state["snapshot"]
            age = max(0, self.clock() - datetime.fromisoformat(snapshot["observed_at"]).timestamp()) if snapshot else None
            lag = max(0, self.clock() - self.state["through"]) if self.state["through"] else None
            stale = age is None or age > STALE_SECONDS or bool(self.error) or not self.config.enabled
            state = ("disabled" if not self.config.enabled else "stale" if stale and snapshot else
                     "unavailable" if self.error else "starting" if not snapshot else "fresh")
            return {"state": state, "stale": stale, "age_seconds": round(age) if age is not None else None,
                    "host": HOST, "name": "ns0", "poll_seconds": POLL_SECONDS,
                    "last_attempt": self.last_attempt, "next_poll": self.next_poll, "error": self.error,
                    "snapshot": snapshot, "archive": {"since": stamp(self.state["since"]) if self.state["since"] else None,
                    "through": stamp(self.state["through"]) if self.state["through"] else None,
                    "lag_seconds": round(lag) if lag is not None else None, "error": self.archive_error,
                    "pending_records": len(self.state["pending"]["rows"]) if self.state["pending"] else 0,
                    "retention_days": 30, "settle_seconds": SETTLE_SECONDS}}

    def start_worker(self):
        if not self.config.enabled or self.storage_error or (self.worker and self.worker.is_alive()):
            return
        self.stop.clear()

        def run():
            try:
                while not self.stop.is_set():
                    self.poll_once()
                    self.stop.wait(POLL_SECONDS)
            finally:
                if self.api:
                    self.api.close()

        self.worker = threading.Thread(target=run, name="pihole-dns", daemon=True)
        self.worker.start()

    def stop_worker(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=27)
