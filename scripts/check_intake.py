#!/usr/bin/env python3
"""Send synthetic syslog fixtures and verify only those records via the query API.

Uses the Python standard library. Never prints unrelated collected logs.
"""

import argparse
from datetime import datetime, timezone
import json
import socket
import time
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo


def fixtures(token):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    # Reserved documentation addresses; this does not describe real traffic.
    packet = (
        "5,,,visibility-test,igb1,match,pass,in,4,0x0,,64,12345,0,DF,6,tcp,"
        "60,192.0.2.10,198.51.100.20,54321,443,0,S,123456,,64240,,mss"
    )
    # Match the collector's configured timezone for legacy messages without one.
    local = now.astimezone(ZoneInfo("America/New_York"))
    month = ("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())[local.month - 1]
    legacy_stamp = f"{month} {local.day:2} {local:%H:%M:%S}"
    return [
        ("tcp", f'<134>1 {stamp} visibility-test visibility-smoke 1 - - {token} tcp-newline'),
        ("tcp-octet", f'<134>1 {stamp} visibility-test visibility-smoke 1 - - {token} tcp-octet'),
        ("udp", f'<134>{legacy_stamp} visibility-test visibility-smoke[1]: {token} udp-rfc3164'),
        ("udp", f'<134>1 {stamp} visibility-test filterlog 1 {token} [meta sequenceId="1"] {packet}'),
    ], packet


def query_records(url, token):
    encoded = json.dumps(token)
    query = f'hostname:="visibility-test" AND (_msg:{encoded} OR msg_id:={encoded})'
    body = urllib.parse.urlencode({"query": query, "limit": 20}).encode()
    request = urllib.request.Request(
        url.rstrip("/") + "/select/logsql/query", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return [json.loads(line) for line in response if line.strip()]


def verify(url, token, packet, timeout):
    deadline = time.monotonic() + timeout
    records = []
    while time.monotonic() < deadline:
        records = query_records(url, token)
        messages = {row.get("_msg", "") for row in records}
        expected = {f"{token} tcp-newline", f"{token} tcp-octet", f"{token} udp-rfc3164", packet}
        if expected <= messages:
            firewall = next(row for row in records if row.get("_msg") == packet)
            if firewall.get("app_name") != "filterlog" or firewall.get("msg_id") != token:
                raise RuntimeError("OPNsense syslog fields were not preserved")
            print(f"PASS: TCP newline, TCP octet-counting, UDP RFC3164, OPNsense RFC5424; token={token}")
            return
        time.sleep(0.5)
    raise RuntimeError(f"Expected four synthetic records; found {len(records)} for token={token}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Syslog receiver address")
    parser.add_argument("--port", type=int, default=514)
    parser.add_argument("--query-url", default="http://127.0.0.1:9428")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--token", default=None, help="Reuse a printed token after a restart")
    parser.add_argument("--verify-only", action="store_true", help="Query previously sent fixtures")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.verify_only and not args.token:
        parser.error("--verify-only requires --token")
    token = args.token or "visibility-" + uuid.uuid4().hex
    messages, packet = fixtures(token)
    if not args.verify_only:
        for transport, message in messages:
            data = message.encode()
            if transport == "udp":
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.sendto(data, (args.host, args.port))
            else:
                frame = (str(len(data)).encode() + b" " + data) if transport == "tcp-octet" else data + b"\n"
                with socket.create_connection((args.host, args.port), timeout=5) as sock:
                    sock.sendall(frame)
    verify(args.query_url, token, packet, args.timeout)


if __name__ == "__main__":
    main()
