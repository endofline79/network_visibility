import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import app
from backend.client import QueryError
from backend.models import OpsHome
from backend.ops import (
    BLOCK_CAP,
    DNS_FETCH,
    TALKER_FETCH,
    demo_ops,
    live_ops,
    ops_queries,
    reduce_blocks,
    reduce_dns,
    reduce_freshness,
    reduce_gateway,
    reduce_talkers,
)
from backend.service import NETWORKS, stamp

UTC = timezone.utc
NOW = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
BLOCK = "5,,,rule-uuid,igc1,match,block,in,4,0x0,,64,12345,0,DF,6,tcp,60,192.168.5.50,198.51.100.20,54321,443,0,S,123456,,64240,,mss"
BLOCK_OTHER = "5,,,rule-uuid,igc0,match,block,in,4,0x0,,64,12345,0,DF,6,tcp,60,203.0.113.8,192.168.5.50,443,22,0,S,123456,,64240,,mss"
PASS = BLOCK.replace(",block,", ",pass,", 1)


def seen(seconds):
    return [{"_time": stamp(NOW - timedelta(seconds=seconds))}]


class Reducers(unittest.TestCase):
    def test_freshness_matches_alerter_tiers(self):
        observations = {
            "filterlog": seen(5 * 60),
            "opnsense-flow": seen(200),
            "unifi-snapshot": seen(16 * 60),
            "pihole-dns": seen(31 * 60),
            "pihole-snapshot": [],
            "opnsense-syslog": seen(40),
            "visibility-alert": seen(181),
        }
        view = {item["id"]: item for item in reduce_freshness(observations, NOW)}
        self.assertEqual(view["filterlog"]["state"], "info")
        self.assertEqual(view["opnsense-flow"]["state"], "fresh")
        self.assertEqual(view["unifi-snapshot"]["state"], "warning")
        self.assertEqual(view["pihole-dns"]["state"], "critical")
        self.assertEqual(view["pihole-snapshot"]["state"], "critical")
        self.assertEqual(view["pihole-snapshot"]["age_seconds"], 6 * 3600)
        self.assertEqual(view["opnsense-syslog"]["state"], "fresh")
        self.assertEqual(view["visibility-alert"]["state"], "critical")
        self.assertIn("3 minutes", view["visibility-alert"]["note"])

    def test_failed_freshness_stays_unavailable(self):
        observations = {spec: None for spec in (
            "filterlog", "opnsense-flow", "unifi-snapshot", "pihole-dns",
            "pihole-snapshot", "opnsense-syslog", "visibility-alert",
        )}
        observations["filterlog"] = [{"_time": "not-a-time"}]
        view = {item["id"]: item for item in reduce_freshness(observations, NOW)}
        self.assertEqual(view["filterlog"]["state"], "unavailable")
        self.assertEqual(view["opnsense-flow"]["state"], "unavailable")
        self.assertIsNone(view["opnsense-flow"]["age_seconds"])

    def test_talkers_credit_lan_source_else_destination(self):
        src = [
            {"src_addr": "192.168.5.10", "bytes": "1000"},
            {"src_addr": "8.8.8.8", "bytes": "99999"},
            {"src_addr": "10.10.20.5", "bytes": "50"},
        ]
        dst = [
            {"dst_addr": "192.168.5.10", "bytes": "25"},
            {"dst_addr": "10.10.10.8", "bytes": "400"},
            {"dst_addr": "203.0.113.9", "bytes": "80"},
        ]
        view = reduce_talkers(src, dst, NETWORKS)
        self.assertEqual(view["state"], "available")
        ranked = {row["ip"]: row["bytes"] for row in view["rows"]}
        self.assertEqual(ranked["192.168.5.10"], 1025)
        self.assertEqual(ranked["10.10.20.5"], 50)
        self.assertEqual(ranked["10.10.10.8"], 400)
        self.assertNotIn("8.8.8.8", ranked)
        self.assertNotIn("203.0.113.9", ranked)

    def test_talker_failure_and_cap(self):
        self.assertEqual(reduce_talkers(None, None)["state"], "unavailable")
        partial = reduce_talkers(None, [{"dst_addr": "192.168.5.9", "bytes": "10"}])
        self.assertEqual(partial["state"], "partial")
        self.assertEqual(partial["rows"][0]["ip"], "192.168.5.9")
        capped = reduce_talkers(
            [{"src_addr": f"192.168.5.{index}", "bytes": "1"} for index in range(TALKER_FETCH)],
            [],
        )
        self.assertEqual(capped["state"], "partial")
        self.assertLessEqual(len(capped["rows"]), 10)

    def test_blocks_group_interface_tuple_and_skip_passes(self):
        rows = [
            {"_time": stamp(NOW), "_msg": BLOCK},
            {"_time": stamp(NOW), "_msg": BLOCK},
            {"_time": stamp(NOW), "_msg": BLOCK_OTHER},
            {"_time": stamp(NOW), "_msg": PASS},
            {"_time": stamp(NOW), "_msg": "block,not,csv"},
        ]
        view = reduce_blocks(rows)
        self.assertEqual(view["state"], "available")
        self.assertEqual(view["unparsed"], 1)
        self.assertEqual(view["rows"][0]["interface"], "igc1")
        self.assertEqual(view["rows"][0]["source"], "192.168.5.50")
        self.assertEqual(view["rows"][0]["destination"], "198.51.100.20")
        self.assertEqual(view["rows"][0]["destination_port"], 443)
        self.assertEqual(view["rows"][0]["protocol"], "TCP")
        self.assertEqual(view["rows"][0]["count"], 2)
        self.assertEqual(view["rows"][1]["destination_port"], 22)
        self.assertEqual(len(view["rows"]), 2)
        capped = reduce_blocks([{"_time": stamp(NOW), "_msg": BLOCK}] * BLOCK_CAP)
        self.assertEqual(capped["state"], "partial")
        self.assertEqual(reduce_blocks(None)["rows"], [])
        self.assertEqual(reduce_blocks(None)["state"], "unavailable")

    def test_dns_deduped_counts_and_gateway_reading(self):
        view = reduce_dns(
            [{"domain": "example.com", "queries": "4"}, {"domain": "", "queries": "9"}, {"domain": "b.example", "queries": "2"}],
            [{"client_ip": "192.0.2.10", "client_name": "TV", "queries": "3"}, {"client_ip": "not-an-ip", "queries": "8"}],
        )
        self.assertEqual(view["state"], "available")
        self.assertEqual([row["name"] for row in view["domains"]], ["example.com", "b.example"])
        self.assertEqual(view["clients"][0]["name"], "TV")
        self.assertEqual(reduce_dns(None, None)["state"], "unavailable")
        self.assertEqual(reduce_dns(None, [])["state"], "partial")
        capped = reduce_dns([{"domain": f"n{i}.example", "queries": "1"} for i in range(DNS_FETCH)], [])
        self.assertEqual(capped["state"], "partial")
        self.assertEqual(reduce_gateway([{"_time": stamp(NOW), "_msg": "dpinger: WAN_DHCP 203.0.113.1: Alarm latency 0us loss 100%"}])["state"], "down")
        self.assertEqual(reduce_gateway([{"_time": stamp(NOW), "_msg": "dpinger: WAN_DHCP 203.0.113.1: Clear latency 1ms loss 0%"}])["state"], "up")
        self.assertEqual(reduce_gateway([{"_time": stamp(NOW), "_msg": "dpinger: Alarm then Clear"}])["state"], "down")
        self.assertEqual(reduce_gateway([])["state"], "unknown")
        self.assertEqual(reduce_gateway(None)["state"], "unavailable")


class Queries(unittest.TestCase):
    def test_flow_window_dedupes_before_sum_and_stays_short(self):
        start = NOW - timedelta(hours=1)
        queries = ops_queries(start, NOW, NOW)
        src = queries["talkers_src"]
        self.assertIn("app_name:=opnsense-flow schema:=2", src)
        self.assertLess(src.index("stats by (event_id, src_addr) max(bytes) bytes"), src.index("sum(bytes)"))
        self.assertIn(stamp(start), src)
        self.assertNotIn(stamp(NOW - timedelta(hours=6)), src)
        for network in NETWORKS:
            self.assertIn(f'ipv4_range("{network}")', src)
        self.assertNotIn("_time:24h", src)
        self.assertNotIn("_time:7d", src)
        dst = queries["talkers_dst"]
        self.assertIn("stats by (event_id, dst_addr) max(bytes) bytes", dst)
        self.assertIn("NOT src_addr:ipv4_range", dst)
        self.assertIn(f"limit {BLOCK_CAP}", queries["blocks"])
        self.assertIn("stats by (event_id, domain)", queries["dns_domains"])
        self.assertIn("stats by (event_id, client_ip, client_name)", queries["dns_clients"])
        self.assertIn('"dpinger"', queries["gateway"])
        self.assertIn("limit 1", queries["fresh:visibility-alert"])
        self.assertIn("kind:=heartbeat", queries["fresh:visibility-alert"])
        self.assertIn(stamp(NOW - timedelta(hours=6)), queries["fresh:filterlog"])
        short = ops_queries(NOW - timedelta(minutes=15), NOW, NOW)
        self.assertIn(stamp(NOW - timedelta(minutes=15)), short["talkers_src"])

    def test_frontend_does_not_hardcode_lan_cidrs(self):
        root = Path(__file__).resolve().parents[1] / "frontend" / "src"
        text = "\n".join(path.read_text() for path in root.rglob("*") if path.suffix in {".ts", ".tsx", ".css"})
        for cidr in ("192.168.5.0/24", "10.10.10.0/24", "10.10.20.0/24"):
            self.assertNotIn(cidr, text)


class LiveRead(unittest.TestCase):
    def test_live_ops_shapes_panels_and_drops_public_sources(self):
        class Client:
            def __init__(self):
                self.queries = []

            def query(self, query, deadline):
                self.queries.append(query)
                if "dpinger" in query:
                    return [{"_time": stamp(NOW), "_msg": "dpinger: WAN_DHCP 203.0.113.1: Clear latency 1ms loss 0%"}]
                if '"block"' in query:
                    return [{"_time": stamp(NOW), "_msg": BLOCK}]
                if "stats by (domain)" in query:
                    return [{"domain": "example.com", "queries": "3"}]
                if "client_ip" in query:
                    return [{"client_ip": "192.168.5.10", "client_name": "phone", "queries": "2"}]
                if "stats by (src_addr)" in query:
                    return [{"src_addr": "192.168.5.10", "bytes": "1500"}, {"src_addr": "8.8.8.8", "bytes": "9"}]
                if "stats by (dst_addr)" in query:
                    return [{"dst_addr": "192.168.5.20", "bytes": "400"}]
                if "limit 1" in query and "app_name:=filterlog" in query:
                    return [{"_time": stamp(NOW - timedelta(minutes=16))}]
                if "limit 1" in query:
                    return [{"_time": stamp(NOW - timedelta(seconds=20))}]
                raise AssertionError(query)

        client = Client()
        view = live_ops(client, NOW, 3600, NOW)
        OpsHome.model_validate(view)
        self.assertEqual(view["mode"], "live")
        self.assertFalse(view["illustrative"])
        self.assertEqual(view["window"]["label"], "Last hour")
        states = {item["id"]: item["state"] for item in view["freshness"]}
        self.assertEqual(states["filterlog"], "warning")
        self.assertEqual(states["visibility-alert"], "fresh")
        ranked = {row["ip"]: row["bytes"] for row in view["talkers"]["rows"]}
        self.assertEqual(ranked, {"192.168.5.10": 1500, "192.168.5.20": 400})
        self.assertIn("192.168.5.0/24", view["talkers"]["note"])
        self.assertEqual(view["blocks"]["rows"][0]["count"], 1)
        self.assertEqual(view["dns"]["domains"][0]["name"], "example.com")
        self.assertEqual(view["gateway"]["state"], "up")
        self.assertTrue(all("schema:=2" in query or "opnsense-flow" not in query for query in client.queries))
        self.assertTrue(any("stats by (event_id, src_addr)" in query for query in client.queries))

    def test_one_failed_panel_stays_partial_and_total_failure_raises(self):
        class Client:
            def query(self, query, deadline):
                if "stats by (dst_addr)" in query:
                    raise QueryError("dst")
                if "dpinger" in query:
                    return []
                if '"block"' in query or "stats by (domain)" in query or "client_ip" in query:
                    return []
                if "stats by (src_addr)" in query:
                    return [{"src_addr": "192.168.5.10", "bytes": "10"}]
                if "limit 1" in query:
                    return [{"_time": stamp(NOW)}]
                raise AssertionError(query)

        view = live_ops(Client(), NOW, 900, NOW)
        self.assertEqual(view["talkers"]["state"], "partial")
        self.assertEqual(view["talkers"]["rows"][0]["ip"], "192.168.5.10")
        self.assertEqual(view["window"]["seconds"], 900)

        class Down:
            def query(self, query, deadline):
                raise QueryError("down")

        with self.assertRaises(QueryError):
            live_ops(Down(), NOW, 3600, NOW)
        with self.assertRaises(ValueError):
            live_ops(Down(), NOW, 86400, NOW)


class Route(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_demo_route_is_labelled_and_read_only(self):
        response = self.client.get("/api/ops")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        OpsHome.model_validate(body)
        self.assertEqual(body["mode"], "demo")
        self.assertTrue(body["illustrative"])
        self.assertEqual(body["window"]["label"], "Last hour")
        states = {item["id"]: item["state"] for item in body["freshness"]}
        self.assertEqual(states["filterlog"], "warning")
        self.assertEqual(states["opnsense-flow"], "fresh")
        self.assertEqual(states["visibility-alert"], "fresh")
        self.assertEqual(body["gateway"]["state"], "up")
        self.assertTrue(body["talkers"]["rows"])
        self.assertIn("Illustrative", body["talkers"]["note"])
        self.assertNotIn("192.168.5.0/24", body["talkers"]["note"])
        self.assertEqual(self.client.get("/api/ops?window=15m").json()["window"]["seconds"], 900)
        self.assertEqual(self.client.get("/api/ops?window=24h").status_code, 422)
        self.assertEqual(self.client.post("/api/ops", json={}).status_code, 405)
        self.assertEqual(self.client.get("/api/health").json()["version"], "0.4.2")
        stale = self.client.get("/api/ops?scenario=stale").json()
        self.assertTrue(all(item["state"] == "critical" for item in stale["freshness"]))
        self.assertEqual(stale["gateway"]["state"], "unknown")
        self.assertTrue(stale["illustrative"])
        blank = self.client.get("/api/ops?scenario=unavailable").json()
        self.assertTrue(all(item["state"] == "unavailable" for item in blank["freshness"]))
        self.assertEqual(blank["talkers"]["state"], "unavailable")
        self.assertEqual(blank["blocks"]["state"], "unavailable")
        self.assertEqual(blank["dns"]["state"], "unavailable")
        self.assertEqual(self.client.get("/api/ops?scenario=error").status_code, 503)
        future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        self.assertEqual(self.client.get("/api/ops", params={"end": future}).status_code, 422)
        self.assertEqual(self.client.get("/api/ops", params={"end": "2026-10-24T16:00:00"}).status_code, 422)

    def test_live_failure_is_503_and_scenarios_are_rejected(self):
        with patch("backend.ops.live_ops", side_effect=QueryError("down")), patch("backend.app.MODE", "live"):
            self.assertEqual(self.client.get("/api/ops").status_code, 503)
            self.assertEqual(self.client.get("/api/ops?scenario=stale").status_code, 422)

    def test_demo_contract_helper(self):
        payload = demo_ops(NOW, 3600, "normal", NOW)
        OpsHome.model_validate(payload)
        self.assertTrue(payload["illustrative"])
        self.assertEqual(payload["mode"], "demo")
