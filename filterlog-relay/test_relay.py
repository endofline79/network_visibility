import ipaddress
import json
import socket
import threading
import time
import unittest
import urllib.parse
from datetime import datetime, timezone

import relay

V4 = (
    "5,,,rule-uuid,igc1,match,pass,in,4,0x0,,64,12345,0,DF,6,tcp,"
    "60,192.168.5.50,198.51.100.20,54321,443,0,S,123456,,64240,,mss"
)
NETWORKS = (ipaddress.ip_network('192.168.5.0/24'), ipaddress.ip_network('10.10.10.0/24'))
STAMP = '2026-11-01T21:00:00Z'
NOW = datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc)


def frame(app, message, stamp=STAMP, hostname='OPNsense.internal'):
    return f'<134>1 {stamp} {hostname} {app} 1 - - {message}'.encode()


class FramingTests(unittest.TestCase):
    def test_newline_and_octet_counted_frames(self):
        first = frame('filterlog', V4)
        second = frame('cron', 'job')
        buf = bytearray(first + b'\n' + str(len(second)).encode() + b' ' + second)
        frames = relay.pop_frames(buf)
        self.assertEqual(frames, [first, second])
        self.assertEqual(buf, bytearray())

    def test_partial_frame_stays_buffered(self):
        payload = frame('filterlog', V4) + b'\n'
        buf = bytearray(payload[:20])
        self.assertEqual(relay.pop_frames(buf), [])
        buf.extend(payload[20:])
        self.assertEqual(relay.pop_frames(buf), [payload[:-1]])

    def test_oversized_octet_count_is_rejected(self):
        buf = bytearray(b'999999 ')
        with self.assertRaises(relay.FramingError):
            relay.pop_frames(buf)


class ParseTests(unittest.TestCase):
    def test_filterlog_fields_keep_raw_message_and_stream_names(self):
        row = relay.row_from_frame(frame('filterlog', V4), NETWORKS, now=NOW)
        self.assertEqual(row['_msg'], V4)
        self.assertEqual(row['hostname'], 'OPNsense.internal')
        self.assertEqual(row['app_name'], 'filterlog')
        self.assertEqual(row['action'], 'pass')
        self.assertEqual(row['iface'], 'igc1')
        self.assertEqual(row['dir'], 'in')
        self.assertEqual(row['proto'], 'TCP')
        self.assertEqual((row['src'], row['dst'], row['sport'], row['dport']),
                         ('192.168.5.50', '198.51.100.20', 54321, 443))
        self.assertEqual(row['rule'], 'rule-uuid')
        self.assertEqual(row['reason'], 'match')
        self.assertEqual(row['ip_version'], 4)
        self.assertEqual(row['packet_bytes'], 60)
        self.assertIs(row['src_local'], True)
        self.assertIs(row['dst_local'], False)
        self.assertNotIn('parse_error', row)
        self.assertTrue(row['_time'].startswith('2026-11-01T21:00:00'))

    def test_structured_data_is_not_part_of_the_message(self):
        payload = f'<134>1 {STAMP} OPNsense.internal filterlog 1 token [meta sequenceId="1"] {V4}'.encode()
        row = relay.row_from_frame(payload, NETWORKS, now=NOW)
        self.assertEqual(row['_msg'], V4)
        self.assertEqual(row['action'], 'pass')

    def test_bad_filterlog_keeps_the_body(self):
        row = relay.row_from_frame(frame('filterlog', 'not,csv'), NETWORKS, now=NOW)
        self.assertEqual(row['_msg'], 'not,csv')
        self.assertIn('parse_error', row)
        self.assertNotIn('src', row)

    def test_other_programs_are_forwarded_without_csv_fields(self):
        row = relay.row_from_frame(frame('syslog-ng', 'startup'), NETWORKS, now=NOW)
        self.assertEqual(set(row), {'_time', 'hostname', 'app_name', '_msg'})
        self.assertEqual(row['app_name'], 'syslog-ng')
        self.assertEqual(row['_msg'], 'startup')

    def test_insert_path_stream_fields_exclude_addresses(self):
        query = urllib.parse.parse_qs(relay.insert_path().split('?', 1)[1])
        self.assertEqual(query['_stream_fields'], ['hostname,app_name'])
        self.assertEqual(query['_msg_field'], ['_msg'])
        self.assertEqual(query['_time_field'], ['_time'])
        self.assertNotIn('src', query['_stream_fields'][0])

    def test_insert_url_rejects_external_hosts(self):
        relay.check_insert_url('http://logs:9428')
        relay.check_insert_url('http://127.0.0.1:9428')
        with self.assertRaises(RuntimeError):
            relay.check_insert_url('https://logs.example/insert')
        with self.assertRaises(RuntimeError):
            relay.check_insert_url('http://user:secret@logs:9428')


class ServerTests(unittest.TestCase):
    def test_connection_inserts_one_batch_and_idle_close_inserts_nothing(self):
        seen = []
        server = relay.Relay(seen.append, NETWORKS)
        stop = threading.Event()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', 0))
        sock.listen(8)
        sock.settimeout(1)
        port = sock.getsockname()[1]

        def accept_loop():
            while not stop.is_set():
                try:
                    conn, peer = sock.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                self.assertTrue(relay.peer_allowed(peer, ['192.168.5.1']))
                threading.Thread(target=server.handle, args=(conn,), daemon=True).start()

        thread = threading.Thread(target=accept_loop, daemon=True)
        thread.start()
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=2):
                pass
            time.sleep(0.1)
            self.assertEqual(seen, [])
            with socket.create_connection(('127.0.0.1', port), timeout=2) as conn:
                conn.sendall(frame('filterlog', V4) + b'\n')
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not seen:
                time.sleep(0.05)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][0]['dst'], '198.51.100.20')
            encoded = relay.encode_batch(seen[0])
            parsed = json.loads(encoded.splitlines()[0])
            self.assertEqual(parsed['app_name'], 'filterlog')
            self.assertNotIn('src', relay.insert_path())
        finally:
            stop.set()
            sock.close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
