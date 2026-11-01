import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import app
from backend.hosts import (
    DHCP_GAP,
    HostCache,
    merge_hosts,
    normalize_mac,
    parse_iot_hosts,
    _unique,
)


ALLOW = """
# example only
hosts:
  - id: handset
    class: phone
    name: Handset
    ip: 192.0.2.10
    mac: AA-BB-CC-DD-EE-01
    notes: Example handset
    dns_names:
      - phone.lab.test
"""


class FakeQueries:
    def __init__(self):
        self.fail = False
        self.unifi = [
            {'mac': 'AA:BB:CC:DD:EE:01', 'ip': '192.168.5.20', 'name': 'UniFi phone', 'seen': '2026-11-01T21:00:00Z'},
            {'mac': 'aa:bb:cc:dd:ee:02', 'ip': '192.168.5.21', 'name': 'Camera', 'seen': '2026-11-01T21:00:01Z'},
        ]
        self.pihole = [
            {'client_ip': '192.168.5.20', 'name': 'pihole-phone', 'seen': '2026-11-01T21:00:02Z'},
            {'client_ip': '192.168.5.30', 'name': 'Only Pihole', 'seen': '2026-11-01T21:00:03Z'},
        ]

    def query(self, query, deadline):
        if self.fail:
            raise RuntimeError('CANARY-SECRET')
        if 'unifi-snapshot' in query:
            return self.unifi
        if 'pihole-dns' in query:
            return self.pihole
        raise AssertionError(query)


class HostCacheTests(unittest.TestCase):
    def cache(self, text=ALLOW, client=None):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / 'iot-hosts.yaml'
        path.write_text(text)
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {'IOT_HOSTS_FILE': str(path)})
        env.start()
        self.addCleanup(env.stop)
        clock = {'now': 1_700_000_000}
        cache = HostCache(clients=[client or FakeQueries()], clock=lambda: clock['now'], refresh_seconds=300)
        cache.clock_box = clock
        return cache

    def test_merge_priority_mac_then_ip(self):
        cache = self.cache()
        cache.refresh()
        view = cache.snapshot()
        self.assertFalse(view['stale'])
        self.assertIn('DHCP', view['gaps'][0])
        by_mac = cache.lookup(mac='aa:bb:cc:dd:ee:01')
        self.assertEqual(by_mac['name'], 'Handset')
        self.assertEqual(by_mac['source'], 'iot-hosts')
        self.assertEqual(by_mac['matched_on'], 'mac')
        moved = cache.lookup(ip='192.168.5.20')
        self.assertEqual(moved['name'], 'Handset')
        self.assertEqual(moved['source'], 'iot-hosts')
        self.assertIn('192.168.5.20', moved['ips'])
        camera = cache.lookup(ip='192.168.5.21')
        self.assertEqual((camera['name'], camera['source']), ('Camera', 'unifi'))
        named = cache.lookup(ip='192.168.5.30')
        self.assertEqual((named['name'], named['source']), ('Only Pihole', 'pihole'))
        declared = cache.lookup(ip='192.0.2.10')
        self.assertEqual(declared['name'], 'Handset')
        self.assertNotIn('CANARY', json.dumps(view))

    def test_ambiguous_unifi_ip_is_not_guessed(self):
        client = FakeQueries()
        client.unifi = [
            {'mac': 'aa:bb:cc:dd:ee:10', 'ip': '192.168.5.40', 'name': 'One', 'seen': '2026-11-01T21:00:00Z'},
            {'mac': 'aa:bb:cc:dd:ee:11', 'ip': '192.168.5.40', 'name': 'Two', 'seen': '2026-11-01T21:00:01Z'},
        ]
        client.pihole = [{'client_ip': '192.168.5.40', 'name': 'Should not win', 'seen': '2026-11-01T21:00:02Z'}]
        cache = self.cache(text='hosts: []\n', client=client)
        cache.refresh()
        self.assertIsNone(cache.lookup(ip='192.168.5.40'))
        self.assertEqual(cache.lookup(mac='aa:bb:cc:dd:ee:10')['name'], 'One')
        self.assertEqual(cache.snapshot()['ambiguous_ips'], ['192.168.5.40'])

    def test_query_failure_keeps_previous_names_and_hides_errors(self):
        client = FakeQueries()
        cache = self.cache(client=client)
        cache.refresh()
        client.fail = True
        cache.refresh()
        view = cache.snapshot()
        self.assertEqual(cache.lookup(mac='aa:bb:cc:dd:ee:02')['name'], 'Camera')
        self.assertEqual(view['sources']['unifi']['state'], 'error')
        self.assertNotIn('CANARY', json.dumps(view))
        self.assertTrue(view['stale'])

    def test_age_marks_the_cache_stale(self):
        cache = self.cache(text='hosts: []\n')
        cache.refresh()
        self.assertFalse(cache.snapshot()['stale'])
        cache.clock_box['now'] += 700
        self.assertTrue(cache.snapshot()['stale'])

    def test_validation_rejects_hostile_or_oversized_allowlists(self):
        hosts = parse_iot_hosts(ALLOW)
        self.assertEqual(hosts[0]['mac'], 'aa:bb:cc:dd:ee:01')
        self.assertEqual(normalize_mac('aabb.ccdd.ee01'), 'aa:bb:cc:dd:ee:01')
        with self.assertRaises(ValueError):
            parse_iot_hosts('hosts:\n  - id: bad\n    class: phone\n    name: bad"name\n    mac: aa:bb:cc:dd:ee:01\n')
        body = ['hosts:']
        for index in range(17):
            body.append(f'  - id: host{index}')
            body.append('    class: device')
            body.append(f'    name: Host{index}')
            body.append(f'    mac: aa:bb:cc:dd:ee:{index:02x}')
        with self.assertRaises(ValueError):
            parse_iot_hosts('\n'.join(body) + '\n')
        dup = parse_iot_hosts(
            'hosts:\n'
            '  - id: a\n    class: device\n    name: A\n    mac: aa:bb:cc:dd:ee:01\n'
            '  - id: b\n    class: device\n    name: B\n    mac: aa:bb:cc:dd:ee:01\n'
        )
        with self.assertRaises(ValueError):
            _unique(dup)

    def test_demo_api_exposes_cache_and_planner_pin(self):
        client = TestClient(app)
        hosts = client.get('/api/hosts')
        planner = client.get('/api/planner')
        self.assertEqual(hosts.status_code, 200)
        self.assertEqual(planner.status_code, 200)
        self.assertEqual(client.post('/api/hosts').status_code, 405)
        body = hosts.json()
        self.assertEqual(body['refresh_seconds'], 300)
        self.assertIn('DHCP', body['gaps'][0])
        self.assertEqual(body['sources']['unifi']['state'], 'skipped')
        self.assertEqual(DHCP_GAP, body['gaps'][0])
        pin = planner.json()
        self.assertEqual(pin['model'], 'visibility-planner')
        self.assertEqual(pin['base_url'], 'http://172.17.0.1:8081/v1')
        self.assertEqual(pin['parallel'], 1)
        self.assertTrue(pin['queued'])
        self.assertFalse(pin['cloud_fallback'])
        self.assertFalse(pin['token_configured'])
        self.assertNotIn('sk-', json.dumps(pin))


class MergeTests(unittest.TestCase):
    def test_pihole_does_not_override_unifi(self):
        hosts, ambiguous = merge_hosts(
            [],
            [{'mac': 'aa:bb:cc:dd:ee:02', 'ip': '192.168.5.21', 'name': 'Camera', 'seen': 't'}],
            [{'ip': '192.168.5.21', 'name': 'other', 'seen': 't'}],
        )
        self.assertEqual(ambiguous, [])
        self.assertEqual(hosts[0]['source'], 'unifi')
        self.assertEqual(hosts[0]['name'], 'Camera')


if __name__ == '__main__':
    unittest.main()
