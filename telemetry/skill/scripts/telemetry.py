"""Native HTTPS VictoriaLogs client. Secrets stay in memory, never argv/output."""
import argparse
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit

DEFAULT_URL = 'https://192.168.5.230:9429'
DEFAULT_CA = Path(__file__).resolve().parents[1] / 'references/server.crt'


def token():
    value = os.environ.get('TELEMETRY_API_TOKEN')
    if not value:
        result = subprocess.run(['phase', 'secrets', 'get', 'TELEMETRY_API_TOKEN',
            '--app', 'agents', '--env', 'Production', '--path', '/', '--generate-leases', 'false'],
            capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise ValueError('Phase could not retrieve TELEMETRY_API_TOKEN (output suppressed).')
        data = json.loads(result.stdout)
        if data.get('key') != 'TELEMETRY_API_TOKEN' or data.get('path') != '/':
            raise ValueError('Unexpected Phase secret metadata.')
        value = data.get('value')
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError('Invalid telemetry token.')
    return value


def connect(base_url, ca_file):
    target = urlsplit(base_url)
    if (target.scheme != 'https' or not target.hostname or target.username or target.password
            or target.path not in ('', '/') or target.query or target.fragment):
        raise ValueError('Base URL must be an HTTPS origin without credentials or a path.')
    context = ssl.create_default_context(cafile=str(ca_file))
    return http.client.HTTPSConnection(target.hostname, target.port or 443, context=context, timeout=15)


def request(path, params=(), *, method='POST', seconds=30, base_url=DEFAULT_URL,
            ca_file=DEFAULT_CA, bearer=None):
    """Yield response byte chunks; no redirects, endpoint filters or retry of mutations."""
    if not path.startswith('/') or path.startswith('//') or any(c in path for c in '\r\n'):
        raise ValueError('Expected a native API path beginning with one slash.')
    if seconds <= 0:
        raise ValueError('Request duration must be positive.')
    credential = token() if bearer is None else bearer
    conn = connect(base_url, ca_file)
    body = urlencode(params).encode()
    if method in ('GET', 'HEAD'):
        if body:
            path += ('&' if '?' in path else '?') + body.decode()
        body = None
    deadline = time.monotonic() + seconds
    conn.timeout = min(15, seconds)
    try:
        conn.request(method, path, body, {'Authorization': 'Bearer ' + credential,
                     'Content-Type': 'application/x-www-form-urlencoded'})
        response = conn.getresponse()
        if not 200 <= response.status < 300:
            # No upstream body/headers in errors; they may echo submitted content.
            raise ValueError(f'Telemetry API returned HTTP {response.status}.')
        streaming = urlsplit(path).path == '/select/logsql/tail'
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if streaming:
                    return
                raise TimeoutError('Query exceeded the requested duration; output may be incomplete.')
            if conn.sock:
                conn.sock.settimeout(remaining)
            try:
                chunk = response.read1(65536)
            except (socket.timeout, TimeoutError):
                if streaming:
                    return
                raise TimeoutError('Query timed out; output may be incomplete.') from None
            if not chunk:
                return
            yield chunk
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', default='/select/logsql/query', help='Any native backend endpoint')
    parser.add_argument('--method', default='POST', choices=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'])
    parser.add_argument('--query', help='Unmodified native LogsQL')
    parser.add_argument('--param', action='append', default=[], metavar='NAME=VALUE', help='Repeatable native parameter')
    parser.add_argument('--tail', action='store_true', help='Stream NDJSON from /select/logsql/tail')
    parser.add_argument('--seconds', type=float, default=30, help='Query deadline / finite tail duration')
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--ca', default=str(DEFAULT_CA))
    parser.add_argument('--parse-firewall', action='store_true', help='Decode raw filterlog NDJSON using the existing parser')
    args = parser.parse_args()
    params = []
    if args.query is not None:
        params.append(('query', args.query))
    for item in args.param:
        name, sep, value = item.partition('=')
        if not sep:
            parser.error('--param requires NAME=VALUE')
        params.append((name, value))
    path = '/select/logsql/tail' if args.tail else args.path
    try:
        chunks = request(path, params, method=args.method, seconds=args.seconds,
                         base_url=args.url, ca_file=args.ca)
        if args.parse_firewall:
            from filterlog import parse_filterlog
            networks = tuple(ipaddress.ip_network(n) for n in ('192.168.5.0/24','10.10.10.0/24','10.10.20.0/24'))
            pending = b''
            for chunk in chunks:
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    if line:
                        print(json.dumps(parse_filterlog(json.loads(line), networks)), flush=True)
            if pending.strip():
                # Finite tails can end mid-record; incomplete trailing rows are not fabricated.
                try:
                    value = json.loads(pending)
                except ValueError:
                    raise ValueError('Stream ended with an incomplete record; rerun a historical query.') from None
                print(json.dumps(parse_filterlog(value, networks)))
        else:
            for chunk in chunks:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        return 0
    except (ValueError, OSError, http.client.HTTPException, subprocess.SubprocessError) as exc:
        # Errors generated by this client are secret-free. Suppress transport/Phase details.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else type(exc).__name__
        print('Telemetry request failed: ' + message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
