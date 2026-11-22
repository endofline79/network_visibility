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
    normalize_dhcp,
    normalize_mac,
    parse_iot_hosts,
    parse_known_hosts,
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
            {'mac': 'aa:bb:cc:dd:ee:50', 'ip': '10.10.20.10', 'name': 'USW Flex 2.5G 8 PoE', 'kind': 'switch', 'seen': '2026-11-01T21:00:01Z'},
        ]
        self.dhcp = [
            {'_msg': 'DHCPACK(bridge0) 10.10.20.10 aa:bb:cc:dd:ee:50 unifi-flex', 'seen': '2026-11-01T20:00:00Z'},
            {'_msg': 'DHCPACK(igc1) 192.168.5.60 aa:bb:cc:dd:ee:60 wired-nas', 'seen': '2026-11-01T21:00:00Z'},
        ]
        self.pihole = [
            {'client_ip': '192.168.5.20', 'name': 'pihole-phone', 'seen': '2026-11-01T21:00:02Z'},
            {'client_ip': '192.168.5.30', 'name': 'Only Pihole', 'seen': '2026-11-01T21:00:03Z'},
            {'client_ip': '192.168.5.60', 'name': 'pihole-nas', 'seen': '2026-11-01T21:00:04Z'},
        ]

    def query(self, query, deadline):
        if self.fail:
            raise RuntimeError('CANARY-SECRET')
        if 'unifi-snapshot' in query:
            return self.unifi
        if 'dnsmasq-dhcp' in query:
            return self.dhcp
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
        switch = cache.lookup(ip='10.10.20.10')
        self.assertEqual((switch['name'], switch['source'], switch['class']), ('USW Flex 2.5G 8 PoE', 'unifi', 'switch'))
        wired = cache.lookup(ip='192.168.5.60')
        self.assertEqual((wired['name'], wired['source'], wired['mac']), ('wired-nas', 'dhcp', 'aa:bb:cc:dd:ee:60'))
        self.assertEqual(view['sources']['dhcp']['state'], 'ok')
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

    def test_normalize_dhcp_and_ambiguity_with_dhcp(self):
        leases, note = normalize_dhcp([
            {'_msg': 'DHCPACK(bridge0) 10.10.20.11 aa:bb:cc:dd:ee:51 unifi-kitchen', 'seen': '2026-11-20T20:04:25Z'},
            {'_msg': 'DHCPACK(bridge0) 10.10.20.99 aa:bb:cc:dd:ee:51 old-name', 'seen': '2026-11-20T19:00:00Z'},
            {'_msg': 'no address range available for DHCP request via igc1', 'seen': '2026-11-20T20:05:00Z'},
        ])
        self.assertEqual(len(leases), 1)
        self.assertEqual(leases[0]['ip'], '10.10.20.11')
        self.assertEqual(leases[0]['name'], 'unifi-kitchen')
        self.assertIsNotNone(note)
        hosts, ambiguous = merge_hosts(
            [],
            [{'mac': 'aa:bb:cc:dd:ee:10', 'ip': '192.168.5.70', 'name': 'One', 'seen': 't'}],
            [],
            dhcp=[{'mac': 'aa:bb:cc:dd:ee:11', 'ip': '192.168.5.70', 'name': 'Two', 'seen': 't'}],
        )
        self.assertEqual(ambiguous, ['192.168.5.70'])
        self.assertTrue(all(host['ip'] is None for host in hosts))

    def test_known_hosts_priority_multi_ip_and_mac_enrichment(self):
        known = parse_known_hosts("""
version: 1
hosts:
  - id: opnsense
    class: router
    name: OPNsense
    ips: [192.168.5.1, 10.10.20.1]
    notes: Core firewall/router
  - id: synology
    class: nas
    name: Synology-NAS
    ip: 192.168.5.240
    mac: 00:11:32:2d:20:95
    notes: Storage, primary NAS
  - id: overlap
    class: server
    name: ShouldNotOverrideIot
    ip: 192.0.2.10
    mac: aa:bb:cc:dd:ee:01
""")
        iot = parse_iot_hosts(ALLOW)
        unifi = [
            {'mac': '00:11:32:2d:20:95', 'ip': None, 'name': '00:11:32:2d:20:95', 'seen': '2026-11-22T20:00:00Z'},
        ]
        pihole = [
            {'ip': '192.168.5.1', 'name': 'opnsense.internal', 'seen': '2026-11-22T20:00:00Z'},
        ]
        hosts, ambiguous = merge_hosts(iot, unifi, pihole, known=known)
        self.assertEqual(ambiguous, [])
        by_id = {h['id']: h for h in hosts if h.get('id')}
        self.assertEqual(by_id['handset']['source'], 'iot-hosts')
        self.assertNotIn('overlap', by_id)
        self.assertEqual(by_id['opnsense']['ips'], ['192.168.5.1', '10.10.20.1'])
        self.assertEqual(by_id['opnsense']['source'], 'known-hosts')
        self.assertEqual(by_id['synology']['name'], 'Synology-NAS')
        self.assertEqual(by_id['synology']['seen'], '2026-11-22T20:00:00Z')
        self.assertEqual(by_id['synology']['ip'], '192.168.5.240')

    def test_known_hosts_validation_and_cache_integration(self):
        with self.assertRaises(ValueError):
            parse_known_hosts('version: 2\nhosts: []\n')
        with self.assertRaises(ValueError):
            parse_known_hosts('hosts:\n  - id: bad\n    class: server\n    name: NoAddr\n')
        with self.assertRaises(ValueError):
            parse_known_hosts(
                'hosts:\n'
                '  - id: a\n    class: server\n    name: A\n    ips: [192.0.2.1, 192.0.2.2]\n'
                '  - id: b\n    class: server\n    name: B\n    ip: 192.0.2.2\n'
            )
        with tempfile.TemporaryDirectory() as tmp:
            known_path = Path(tmp) / 'known-hosts.yaml'
            known_path.write_text(
                'version: 1\nhosts:\n'
                '  - id: opnsense\n    class: router\n    name: OPNsense\n'
                '    ips: [192.168.5.1, 10.10.20.1]\n'
            )
            iot_path = Path(tmp) / 'iot-hosts.yaml'
            iot_path.write_text('hosts: []\n')
            with patch.dict(os.environ, {'IOT_HOSTS_FILE': str(iot_path), 'KNOWN_HOSTS_FILE': str(known_path)}):
                cache = HostCache(clients=[FakeQueries()], clock=lambda: 1_700_000_000, refresh_seconds=300)
                view = cache.refresh()
                self.assertEqual(view['sources']['known-hosts']['state'], 'ok')
                self.assertEqual(view['sources']['known-hosts']['count'], 1)
                self.assertEqual(cache.lookup(ip='10.10.20.1')['name'], 'OPNsense')
                self.assertEqual(cache.lookup(ip='192.168.5.1')['id'], 'opnsense')
            known_path.write_text('hosts: [not-a-dict]\n')
            with patch.dict(os.environ, {'IOT_HOSTS_FILE': str(iot_path), 'KNOWN_HOSTS_FILE': str(known_path)}):
                cache = HostCache(clients=[FakeQueries()], clock=lambda: 1_700_000_000, refresh_seconds=300)
                view = cache.refresh()
                self.assertEqual(view['sources']['known-hosts']['state'], 'error')
                self.assertFalse(view['stale'])


if __name__ == '__main__':
    unittest.main()
