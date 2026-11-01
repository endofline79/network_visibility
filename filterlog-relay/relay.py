"""TCP RFC5424 relay that parses OPNsense filterlog before VictoriaLogs insert.

VictoriaLogs' syslog listener stores the CSV body in `_msg` and cannot extract
its fields. This process listens on its own port, reuses
`presentation/backend/filterlog.py`, and POSTs JSON lines to `/insert/jsonline`
with stream fields `hostname,app_name` only.

Starting the service does not change OPNsense. Cutover is documented in
`docs/phase0-planner-prep.md` and needs an explicit OK.
"""

import http.client
import ipaddress
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path


MAX_FRAME = 65536
INSERT_HOSTS = {'logs', '127.0.0.1', 'localhost'}


class FramingError(ValueError):
    pass


def load_parse_filterlog():
    try:
        from filterlog import parse_filterlog
        return parse_filterlog
    except ImportError:
        backend = Path(__file__).resolve().parents[1] / 'presentation' / 'backend'
        sys.path.insert(0, str(backend))
        from filterlog import parse_filterlog
        return parse_filterlog


parse_filterlog = load_parse_filterlog()


def load_networks(value=None):
    raw = value if value is not None else os.getenv(
        'LOCAL_NETWORKS', '192.168.5.0/24,10.10.10.0/24,10.10.20.0/24')
    networks = []
    for part in raw.split(','):
        part = part.strip()
        if part:
            networks.append(ipaddress.ip_network(part))
    return tuple(networks)


def iso_z(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def pop_frames(buf):
    """Remove complete RFC6587 frames from buf. Remainder stays in buf."""
    frames = []
    while buf:
        if buf[:1].isdigit():
            space = buf.find(b' ')
            if space == -1:
                if len(buf) > 10:
                    raise FramingError('octet count')
                break
            if space == 0 or space > 10:
                raise FramingError('octet count')
            try:
                length = int(buf[:space])
            except ValueError:
                raise FramingError('octet count') from None
            if length < 1 or length > MAX_FRAME:
                raise FramingError('octet count')
            start = space + 1
            if len(buf) < start + length:
                break
            frames.append(bytes(buf[start:start + length]))
            del buf[:start + length]
            continue
        newline = buf.find(b'\n')
        if newline == -1:
            if len(buf) > MAX_FRAME:
                raise FramingError('unterminated frame')
            break
        if newline > MAX_FRAME:
            raise FramingError('frame too long')
        frame = bytes(buf[:newline]).rstrip(b'\r')
        del buf[:newline + 1]
        if frame:
            frames.append(frame)
    return frames


def _fallback(raw):
    return {'raw': raw, 'msg': raw, 'hostname': '-', 'app_name': '-', 'time': None}


def _split_header_fields(rest):
    fields = []
    for _ in range(5):
        if rest.startswith('- '):
            fields.append('-')
            rest = rest[2:]
            continue
        if rest == '-':
            fields.append('-')
            return fields, ''
        space = rest.find(' ')
        if space <= 0:
            return None
        fields.append(rest[:space])
        rest = rest[space + 1:]
    return fields, rest


def _split_structured_data(rest):
    if rest.startswith('-'):
        if rest == '-':
            return '-', ''
        if rest.startswith('- '):
            return '-', rest[2:]
        return None
    if not rest.startswith('['):
        return None
    index = 0
    size = len(rest)
    while index < size and rest[index] == '[':
        index += 1
        closed = False
        while index < size:
            char = rest[index]
            if char == '\\':
                index += 2
                continue
            if char == '"':
                index += 1
                while index < size:
                    if rest[index] == '\\':
                        index += 2
                        continue
                    if rest[index] == '"':
                        index += 1
                        break
                    index += 1
                continue
            if char == ']':
                index += 1
                closed = True
                break
            index += 1
        if not closed:
            return None
    structured = rest[:index]
    if index == size:
        return structured, ''
    if rest[index] != ' ':
        return None
    return structured, rest[index + 1:]


def _parse_time(value):
    if not value or value == '-':
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return iso_z(parsed)


def parse_rfc5424(frame):
    text = frame.decode('utf-8', errors='replace')
    if text.startswith('\ufeff'):
        text = text[1:]
    if not text.startswith('<') or '>' not in text[:5]:
        return _fallback(text)
    pri_end = text.index('>')
    pri = text[1:pri_end]
    if not pri.isdigit():
        return _fallback(text)
    body = text[pri_end + 1:]
    if not body.startswith('1 '):
        return _fallback(text)
    header = _split_header_fields(body[2:])
    if header is None:
        return _fallback(text)
    fields, rest = header
    structured = _split_structured_data(rest)
    if structured is None:
        message = rest
    else:
        _, message = structured
    if message.startswith('\ufeff'):
        message = message[1:]
    timestamp, hostname, app_name, _procid, _msgid = fields
    return {
        'raw': text,
        'msg': message,
        'hostname': hostname if hostname != '-' else '-',
        'app_name': app_name if app_name != '-' else '-',
        'time': _parse_time(timestamp),
    }


def row_from_frame(frame, networks, now=None):
    parsed = parse_rfc5424(frame)
    moment = now or datetime.now(timezone.utc)
    hostname = str(parsed.get('hostname') or '-')[:255] or '-'
    app_name = str(parsed.get('app_name') or '-')[:48] or '-'
    message = parsed.get('msg')
    if not isinstance(message, str):
        message = parsed.get('raw') or ''
    row = {
        '_time': parsed.get('time') or iso_z(moment),
        'hostname': hostname,
        'app_name': app_name,
        '_msg': message,
    }
    if app_name != 'filterlog':
        return row
    event = parse_filterlog(
        {'_time': row['_time'], 'hostname': hostname, '_msg': message}, networks)
    if event.get('parse_error'):
        row['parse_error'] = event['parse_error']
        return row
    mapping = (
        ('action', 'action'), ('interface', 'iface'), ('direction', 'dir'),
        ('protocol', 'proto'), ('source', 'src'), ('destination', 'dst'),
        ('source_port', 'sport'), ('destination_port', 'dport'),
        ('rule', 'rule'), ('reason', 'reason'), ('ip_version', 'ip_version'),
        ('packet_bytes', 'packet_bytes'), ('source_local', 'src_local'),
        ('destination_local', 'dst_local'),
    )
    for source, dest in mapping:
        value = event.get(source)
        if value is None or value == '':
            continue
        row[dest] = value
    return row


def insert_path():
    return '/insert/jsonline?' + urllib.parse.urlencode({
        '_stream_fields': 'hostname,app_name',
        '_time_field': '_time',
        '_msg_field': '_msg',
    })


def encode_batch(rows):
    return b''.join(
        (json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
        for row in rows
    )


def check_insert_url(url):
    target = urllib.parse.urlsplit(url)
    if (target.scheme != 'http' or target.hostname not in INSERT_HOSTS
            or target.username or target.password or target.query or target.fragment
            or target.path not in ('', '/')):
        raise RuntimeError('refusing insert target')
    return target


def post_jsonlines(url, rows, attempts=3):
    if not rows:
        return
    target = check_insert_url(url)
    body = encode_batch(rows)
    if len(body) > 4 * 1024 * 1024:
        raise RuntimeError('batch too large')
    path = insert_path()
    port = target.port or 80
    last = 'unavailable'
    for attempt in range(attempts):
        conn = http.client.HTTPConnection(target.hostname, port, timeout=5)
        try:
            conn.request('POST', path, body, {'Content-Type': 'application/stream+json'})
            response = conn.getresponse()
            status = response.status
            response.read(1024)
            if status == 200:
                return
            last = status
        except (OSError, http.client.HTTPException):
            last = 'unavailable'
        finally:
            conn.close()
        if attempt + 1 < attempts:
            time.sleep(0.2 * (attempt + 1))
    raise RuntimeError(f'insert failed: {last}')


class Relay:
    def __init__(self, insert, networks):
        self.insert = insert
        self.networks = tuple(networks)

    def handle(self, conn):
        buf = bytearray()
        pending = []
        conn.settimeout(0.25)
        try:
            while True:
                try:
                    chunk = conn.recv(8192)
                except socket.timeout:
                    chunk = None
                if chunk == b'':
                    break
                if chunk:
                    buf.extend(chunk)
                    try:
                        frames = pop_frames(buf)
                    except FramingError:
                        print('filterlog-relay closed a connection after a framing error', flush=True)
                        return
                    for frame in frames:
                        pending.append(row_from_frame(frame, self.networks))
                if len(pending) >= 50 or (chunk is None and pending):
                    self._flush(pending)
                    pending = []
            if pending:
                self._flush(pending)
        finally:
            conn.close()

    def _flush(self, pending):
        while True:
            try:
                self.insert(pending)
                return
            except Exception:
                print('filterlog-relay insert failed; holding the batch', flush=True)
                time.sleep(0.5)


def peer_allowed(peer, allow_from):
    try:
        address = ipaddress.ip_address(peer[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    if not allow_from:
        return True
    allowed = []
    for item in allow_from:
        try:
            allowed.append(ipaddress.ip_address(item))
        except ValueError:
            return False
    return address in allowed


def serve(relay, host, port, allow_from=(), stop=None):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(16)
    sock.settimeout(1.0)
    bound = sock.getsockname()
    print(f'filterlog-relay listening on {bound[0]}:{bound[1]}', flush=True)
    stopper = stop or threading.Event()

    def shutdown(*_args):
        stopper.set()
        sock.close()

    signal.signal(signal.SIGTERM, shutdown)
    try:
        while not stopper.is_set():
            try:
                conn, peer = sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            if not peer_allowed(peer, allow_from):
                conn.close()
                continue
            threading.Thread(target=relay.handle, args=(conn,), daemon=True).start()
    finally:
        sock.close()
    return bound


def main():
    networks = load_networks()
    url = os.getenv('VICTORIALOGS_URL', 'http://logs:9428')
    check_insert_url(url)
    allow = [item.strip() for item in os.getenv('RELAY_ALLOW_FROM', '').split(',') if item.strip()]
    relay = Relay(lambda rows: post_jsonlines(url, rows), networks)
    host = os.getenv('RELAY_BIND', '0.0.0.0')
    port = int(os.getenv('RELAY_PORT', '1515'))
    serve(relay, host, port, allow_from=allow)


if __name__ == '__main__':
    main()
