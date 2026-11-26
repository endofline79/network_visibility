import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app import app
from backend.client import QueryError
from backend.filterlog import parse_filterlog
from backend.network import (
    BLOCK_SAMPLE,
    Directory,
    _port_text,
    attribute_sites,
    category_for,
    client_expr,
    dns_queries,
    find_spike,
    firewall_queries,
    host_queries,
    live_overview,
    overview_queries,
    reduce_dns,
    reduce_firewall_sample,
    reduce_host,
)
from backend.service import stamp

UTC = timezone.utc
NOW = datetime(2026, 11, 14, 20, 15, tzinfo=UTC)
BLOCK = "5,,,rule-uuid,igc1,match,block,in,4,0x0,,64,12345,0,DF,17,udp,60,192.168.5.50,198.51.100.20,54321,443,0,S,123456,,64240,,mss"
PASS = BLOCK.replace(",block,", ",pass,", 1)


class Queries(unittest.TestCase):
    def test_long_windows_do_not_group_event_id(self):
        for seconds in (86400, 7 * 86400):
            start = NOW - timedelta(seconds=seconds)
            bundles = (
                overview_queries(start, NOW, seconds),
                host_queries(start, NOW, seconds, "192.168.5.10", '(client_ip:="192.168.5.10")'),
                firewall_queries(start, NOW, seconds),
                dns_queries(start, NOW, seconds),
            )
            for bundle in bundles:
                for name, query in bundle.items():
                    self.assertNotIn("event_id", query, name)
            self.assertTrue(any("limit 64" in query for query in overview_queries(start, NOW, seconds).values()))
            self.assertTrue(any("_time:1h" in query or "_time:15m" in query for query in overview_queries(start, NOW, seconds).values()))

    def test_hour_window_dedupes_event_id(self):
        start = NOW - timedelta(seconds=3600)
        upload = overview_queries(start, NOW, 3600)["upload"]
        self.assertIn("event_id", upload)
        self.assertIn("src_addr", upload)
        series = host_queries(start, NOW, 3600, "192.168.5.142", '(client_ip:="192.168.5.142")')["series"]
        self.assertIn("event_id", series)
        self.assertIn('src_addr:="192.168.5.142"', series)
        self.assertIn("_time:5m", series)

    def test_client_expr_skips_unsafe_names(self):
        expr = client_expr({
            "ip": "192.168.5.10",
            "name": 'bad"name',
            "dns_names": ["Living-Room.occido.net", "has space"],
        })
        self.assertIn('client_ip:="192.168.5.10"', expr)
        self.assertIn('client_name:="Living-Room.occido.net"', expr)
        self.assertNotIn('bad"name', expr)
        self.assertNotIn("has space", expr)

    def test_directory_avoids_colliding_and_pihole_client_names(self):
        directory = Directory.build([], [
            {"ip": "192.168.5.119", "name": "iPhone.occido.net", "source": "pihole"},
            {"ip": "192.168.5.131", "name": "iPhone.occido.net", "source": "pihole"},
            {"ip": "192.168.5.140", "name": "SharedTV", "source": "unifi"},
            {"ip": "192.168.5.141", "name": "SharedTV", "source": "unifi"},
            {"ip": "192.168.5.142", "name": "UniqueHost", "source": "unifi"},
        ])
        self.assertEqual(client_expr(directory.known("192.168.5.119")), '(client_ip:="192.168.5.119")')
        self.assertEqual(client_expr(directory.known("192.168.5.131")), '(client_ip:="192.168.5.131")')
        self.assertEqual(client_expr(directory.known("192.168.5.140")), '(client_ip:="192.168.5.140")')
        self.assertIn('client_name:="UniqueHost"', client_expr(directory.known("192.168.5.142")))

    def test_directory_and_queries_support_multi_ip_known_hosts(self):
        directory = Directory.build([], [
            {
                "id": "opnsense",
                "name": "OPNsense",
                "ip": "192.168.5.1",
                "ips": ["192.168.5.1", "10.10.20.1"],
                "class": "router",
                "source": "known-hosts",
                "notes": "Core firewall",
            },
        ])
        rec_lan = directory.known("192.168.5.1")
        rec_infra = directory.known("10.10.20.1")
        self.assertIs(rec_lan, rec_infra)
        self.assertEqual(rec_lan["id"], "opnsense")
        self.assertEqual(rec_lan["icon"], "router")
        self.assertEqual(rec_lan["type"], "Firewall")
        expr = client_expr(rec_lan)
        self.assertIn('client_ip:="192.168.5.1"', expr)
        self.assertIn('client_ip:="10.10.20.1"', expr)
        start = NOW - timedelta(seconds=3600)
        q = host_queries(start, NOW, 3600, rec_lan["ips"], expr)
        self.assertIn('(src_addr:="192.168.5.1" OR src_addr:="10.10.20.1")', q["upload"])
        self.assertIn('(src:="192.168.5.1" OR src:="10.10.20.1")', q["fw_blocks"])
        from backend.network import merge_host_traffic
        hosts, _other, _oh, _state, _cap = merge_host_traffic(
            [{"src_addr": "192.168.5.1", "bytes": "100"}, {"src_addr": "10.10.20.1", "bytes": "250"}],
            [{"dst_addr": "192.168.5.1", "bytes": "400"}],
            directory,
            750,
        )
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]["id"], "opnsense")
        self.assertEqual(hosts[0]["upload_bytes"], 350)
        self.assertEqual(hosts[0]["download_bytes"], 400)

    def test_firewall_queries_use_parsed_action_and_host_series_excludes_lan_dst(self):
        start = NOW - timedelta(seconds=3600)
        ov = overview_queries(start, NOW, 3600)
        fw = firewall_queries(start, NOW, 3600)
        host = host_queries(start, NOW, 3600, "192.168.5.142", '(client_ip:="192.168.5.142")')
        self.assertIn("action:=block", ov["blocks"])
        self.assertNotIn('",block,"', ov["blocks"])
        self.assertIn("action:=block", fw["blocked"])
        self.assertIn("action:=pass", fw["allowed"])
        self.assertIn("action:=block", fw["series"])
        self.assertIn("action:=block", fw["sample"])
        self.assertIn('action:=block src:="192.168.5.142"', host["fw_blocks"])
        self.assertIn("NOT src_addr:ipv4_range", host["series"])
        self.assertIn("blocked_dns_total", host)
        dns = dns_queries(start, NOW, 3600)
        self.assertIn("stats by (client_ip) count() queries, max(client_name) client_name", dns["clients"])


class Reducers(unittest.TestCase):
    def test_categories_use_the_longest_suffix(self):
        self.assertEqual(category_for("www.netflix.com"), "Streaming")
        self.assertEqual(category_for("googleapis.com"), "Cloud storage")
        self.assertEqual(category_for("music.youtube.com"), "Music")
        self.assertEqual(category_for("not-akamai.net"), "Other")
        self.assertEqual(category_for("evilakamai.net"), "Other")
        self.assertEqual(category_for("stun.l.google.com"), "STUN")

    def test_site_bytes_follow_query_weight(self):
        sites, count, capped = attribute_sites(1000, 400, [
            {"domain": "www.netflix.com", "queries": "3"},
            {"domain": "a.youtube.com", "queries": "1"},
        ])
        self.assertEqual(count, 2)
        self.assertFalse(capped)
        by_name = {site["name"]: site for site in sites}
        self.assertEqual(by_name["netflix.com"]["category"], "Streaming")
        self.assertEqual(by_name["netflix.com"]["download_bytes"], 750)
        self.assertEqual(by_name["youtube.com"]["download_bytes"], 250)
        self.assertEqual(sum(site["upload_bytes"] for site in sites), 400)
        self.assertNotIn("doubleclick.net", by_name)

    def test_blocked_domains_stay_out_of_the_bars(self):
        sites, _count, _capped = attribute_sites(80, 20, [
            {"domain": "netflix.com", "queries": "4"},
        ])
        self.assertEqual([site["name"] for site in sites], ["netflix.com"])
        self.assertTrue(all("queries" in site for site in sites))

    def test_attribute_sites_preserves_subdomain_categories(self):
        sites, _count, _capped = attribute_sites(1000, 200, [
            {"domain": "music.youtube.com", "queries": "10"},
            {"domain": "stun.l.google.com", "queries": "5"},
        ])
        by_name = {site["name"]: site for site in sites}
        self.assertEqual(by_name["youtube.com"]["category"], "Music")
        self.assertEqual(by_name["google.com"]["category"], "STUN")

    def test_reduce_host_uses_blocked_dns_total_beyond_tag_cap(self):
        record = Directory.build([], []).resolve("h-192-168-5-10")
        view = reduce_host(
            record,
            {
                "download": [{"bytes": "1000"}],
                "upload": [{"bytes": "200"}],
                "series": [],
                "sites": [{"domain": "example.com", "queries": "10"}],
                "blocked_dns": [{"domain": f"ad{i}.example", "queries": "10"} for i in range(12)],
                "blocked_dns_total": [{"queries": "450"}],
                "fw_blocks": [{"blocks": "3"}],
            },
            NOW,
            3600,
            NOW,
        )
        self.assertEqual(view["blocked_total"], 450)
        self.assertEqual(view["firewall_blocks"], 3)

    def test_reduce_dns_merges_duplicate_client_ips(self):
        view = reduce_dns(
            {
                "fresh": [{"_time": stamp(NOW)}],
                "series": [],
                "domains": [],
                "clients": [
                    {"client_ip": "192.168.5.107", "client_name": "", "queries": "100"},
                    {"client_ip": "192.168.5.107", "client_name": "RokuPremiere.occido.net", "queries": "50"},
                ],
                "blocked_clients": [{"client_ip": "192.168.5.107", "queries": "120"}],
                "unique": [{"domains": "5"}],
                "totals": [{"outcome": "blocked", "queries": "120"}, {"outcome": "cached", "queries": "30"}],
            },
            Directory.build([], []),
            NOW,
            3600,
            NOW,
        )
        self.assertEqual(len(view["clients"]), 1)
        self.assertEqual(view["clients"][0]["queries"], 150)
        self.assertEqual(view["clients"][0]["blocked"], 120)
        self.assertEqual(view["clients"][0]["name"], "RokuPremiere.occido.net")

    def test_port_text_empty_and_portless_multicast_service_label(self):
        self.assertEqual(_port_text([]), ("", None))
        icmp_mcast = "5,,,rule-uuid,igc1,match,block,in,4,0x0,,1,12345,0,none,2,igmp,32,192.168.5.50,224.0.0.22,datalength=8"
        sample = reduce_firewall_sample([{"_time": stamp(NOW), "_msg": icmp_mcast}], Directory.build([], []))
        self.assertEqual(sample["destinations"][0]["label"], "Multicast")

    def test_firewall_sample_groups_blocks_and_skips_passes(self):
        rows = [
            {"_time": stamp(NOW), "_msg": BLOCK},
            {"_time": stamp(NOW), "_msg": BLOCK},
            {"_time": stamp(NOW), "_msg": PASS},
            {"_time": stamp(NOW), "_msg": "block,not,csv"},
        ]
        sample = reduce_firewall_sample(rows, Directory.build([], []), cap=BLOCK_SAMPLE)
        self.assertEqual(sample["unparsed"], 1)
        self.assertEqual(sample["sources"][0]["ip"], "192.168.5.50")
        self.assertEqual(sample["sources"][0]["count"], 2)
        self.assertTrue(sample["sources"][0]["link"])
        self.assertEqual(sample["destinations"][0]["name"], "198.51.100.20")
        self.assertEqual(sample["destinations"][0]["protocol"], "UDP")
        self.assertEqual(sample["destinations"][0]["port"], "443")
        self.assertEqual(sample["destinations"][0]["count"], 2)
        self.assertEqual(sample["top_rule"]["label"], "#5")
        self.assertIsNone(sample["top_rule"]["name"])
        self.assertFalse(sample["capped"])
        self.assertEqual(parse_filterlog({"_msg": PASS})["action"], "pass")

    def test_spike_needs_a_real_outlier(self):
        self.assertIsNone(find_spike([10] * 12))
        self.assertEqual(find_spike([10] * 11 + [400]), 11)
        self.assertIsNone(find_spike([10, 400]))

    def test_public_address_is_not_a_host_id(self):
        directory = Directory.build([], [])
        self.assertIsNone(directory.resolve("h-8-8-8-8"))
        self.assertEqual(directory.resolve("h-192-168-5-10")["ip"], "192.168.5.10")
        self.assertIsNone(directory.resolve('quote"'))

    def test_live_overview_credits_lan_download_and_upload(self):
        start = NOW - timedelta(seconds=3600)
        queries = overview_queries(start, NOW, 3600)
        rows = {
            "upload": [{"src_addr": "192.168.5.10", "bytes": "1000"}],
            "download": [
                {"dst_addr": "192.168.5.10", "bytes": "250"},
                {"dst_addr": "8.8.8.8", "bytes": "9"},
            ],
            "series": [{"_time": stamp(start), "bytes": "1250"}],
            "total": [{"bytes": "1300"}],
            "blocks": [{"blocks": "4"}],
            "dns_blocked": [{"queries": "2"}],
            "fresh_flow": [{"_time": stamp(NOW)}],
            "fresh_dns": [{"_time": stamp(NOW)}],
            "fresh_fw": [{"_time": stamp(NOW)}],
        }

        class Client:
            def query(self, query, deadline):
                for name, text in queries.items():
                    if query == text:
                        return rows[name]
                raise AssertionError(query)

        directory = Directory.build([], [{
            "id": "work",
            "name": "Workstation",
            "ip": "192.168.5.10",
            "class": "",
            "dns_names": [],
            "notes": "Office desk",
        }])
        view = live_overview(Client(), NOW, 3600, directory, now=NOW)
        self.assertEqual(view["hosts"][0]["name"], "Workstation")
        self.assertEqual(view["hosts"][0]["upload_bytes"], 1000)
        self.assertEqual(view["hosts"][0]["download_bytes"], 250)
        self.assertEqual(view["hosts"][0]["location"], "Office desk")
        self.assertNotIn("8.8.8.8", [host["ip"] for host in view["hosts"]])
        self.assertEqual(view["totals"]["bytes"], 1300)
        self.assertEqual(view["totals"]["firewall_blocks"], 4)
        self.assertEqual(view["totals"]["dns_blocked"], 2)
        self.assertEqual(view["health"]["state"], "healthy")
        self.assertTrue(view["deduped"])
        self.assertTrue(view["throughput"]["points"])

    def test_total_query_failure_raises(self):
        class Down:
            def query(self, query, deadline):
                raise QueryError("down")

        with self.assertRaises(QueryError):
            live_overview(Down(), NOW, 3600, Directory.build([], []), now=NOW)


class Routes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_overview_demo_shape(self):
        response = self.client.get("/api/network/overview", params={"range": "24h"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["illustrative"])
        self.assertIsNone(body["health"]["emphasis"])
        self.assertEqual(body["range"], "24h")
        self.assertEqual(body["totals"]["active_hosts"], 38)
        self.assertGreater(body["totals"]["bytes"], 100 * 10**9)
        self.assertTrue(any(host["id"] == "apple-tv" for host in body["hosts"]))
        self.assertGreater(len(body["throughput"]["points"]), 2)
        self.assertIn("bytes", body["throughput"]["points"][0])
        self.assertEqual(self.client.get("/api/health").json()["version"], "0.6.1")

    def test_host_keeps_blocked_sites_off_the_bars(self):
        response = self.client.get("/api/network/host/apple-tv", params={"range": "24h"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        names = [site["name"] for site in body["sites"]]
        self.assertIn("netflix.com", names)
        self.assertNotIn("doubleclick.net", names)
        blocked = {item["name"]: item["queries"] for item in body["blocked"]}
        self.assertEqual(blocked["doubleclick.net"], 248)
        self.assertGreater(body["host"]["download_bytes"], body["host"]["upload_bytes"])
        self.assertIn("not a per-flow join", body["site_note"])

    def test_unknown_host_and_bad_range(self):
        self.assertEqual(self.client.get("/api/network/host/not-a-host").status_code, 404)
        self.assertEqual(self.client.get("/api/network/host/h-8-8-8-8").status_code, 404)
        self.assertEqual(self.client.get('/api/network/host/foo"or').status_code, 404)
        self.assertEqual(self.client.get("/api/network/overview", params={"range": "2h"}).status_code, 422)
        self.assertEqual(self.client.post("/api/network/overview", json={}).status_code, 405)
        self.assertEqual(self.client.post("/api/network/dns", json={}).status_code, 405)

    def test_firewall_and_dns_demo(self):
        day = self.client.get("/api/network/firewall", params={"range": "24h"})
        self.assertEqual(day.status_code, 200)
        firewall = day.json()
        self.assertEqual(firewall["blocked"], 18400)
        self.assertEqual(firewall["allowed"], 2100000)
        self.assertEqual(firewall["top_rule"]["name"], "default deny")
        self.assertEqual(firewall["top_rule"]["percent"], 86)
        self.assertIsNotNone(firewall["spike"])
        self.assertIn("unifi-os", firewall["spike"]["detail"])
        self.assertTrue(firewall["sources"])
        self.assertTrue(firewall["destinations"])
        self.assertEqual(firewall["destinations"][0]["protocol"], "UDP")
        hour = self.client.get("/api/network/firewall", params={"range": "1h"}).json()
        self.assertIsNone(hour["spike"])
        dns = self.client.get("/api/network/dns", params={"range": "24h"}).json()
        self.assertEqual(dns["queries"], 84200)
        self.assertEqual(dns["blocked"], 9515)
        self.assertEqual(dns["unique_domains"], 3912)
        self.assertEqual(dns["domains"][0]["name"], "apple.com")
        self.assertTrue(dns["series"]["points"])
        self.assertIn("answered", dns["series"]["points"][0])
        self.assertIn("blocked", dns["series"]["points"][0])
        self.assertGreater(dns["clients"][0]["blocked"], 0)
        self.assertIsNone(dns["host"])
        host_dns = self.client.get("/api/network/dns", params={"range": "24h", "host": "apple-tv"})
        self.assertEqual(host_dns.status_code, 200)
        host_dns_body = host_dns.json()
        self.assertEqual(host_dns_body["host"]["id"], "apple-tv")
        self.assertEqual(len(host_dns_body["clients"]), 1)
        self.assertEqual(self.client.get("/api/network/dns", params={"host": "not-a-host"}).status_code, 404)
        filtered_q = dns_queries(NOW - timedelta(seconds=3600), NOW, 3600, expr='(client_ip:="192.168.5.142")')
        self.assertIn('client_ip:="192.168.5.142"', filtered_q["domains"])
        self.assertIn('client_ip:="192.168.5.142"', filtered_q["totals"])

    def test_week_stays_aggregated(self):
        body = self.client.get("/api/network/overview", params={"range": "7d"}).json()
        self.assertEqual(body["range"], "7d")
        self.assertFalse(body["deduped"])
        self.assertGreater(body["totals"]["bytes"], body["hosts"][0]["download_bytes"])

    def test_live_network_cache_reuses_and_isolates_copies(self):
        from backend.app import _network_cache, _network_cached
        from backend.inventory import load_inventory

        _network_cache.clear()
        calls = []

        def build():
            calls.append(1)
            return {"count": len(calls), "items": [1]}

        first = _network_cached(("test", "1h"), build)
        first["items"].append(2)
        second = _network_cached(("test", "1h"), build)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second["items"], [1])
        inv1 = load_inventory()
        inv2 = load_inventory()
        self.assertIs(inv1, inv2)


if __name__ == "__main__":
    unittest.main()
