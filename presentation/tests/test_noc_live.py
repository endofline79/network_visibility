import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import app
from backend.network import Directory
from backend.noc_live import build_live, demo_live


class FakeGeo:
    def lookup(self, ip):
        table = {
            "1.1.1.1": {
                "code": "US",
                "name": "United States",
                "region": "Virginia",
                "city": "Ashburn",
                "latitude": 39.04,
                "longitude": -77.49,
            },
            "8.8.8.8": {
                "code": "NL",
                "name": "Netherlands",
                "region": "North Holland",
                "city": "Amsterdam",
                "latitude": 52.37,
                "longitude": 4.90,
            },
        }
        return table.get(ip)

    def status(self):
        return {"available": True, "provider": "FakeGeo", "age_days": 1}


class NocLiveTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.end = datetime(2026, 11, 25, 22, 0, tzinfo=timezone.utc)

    def test_demo_live_route_shape_and_arcs(self):
        resp = self.client.get("/api/network/live")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["mode"], "demo")
        self.assertTrue(body["illustrative"])
        self.assertEqual(body["window"]["seconds"], 900)
        self.assertEqual(len(body["throughput"]["points"]), 15)
        self.assertGreater(len(body["map"]["flows"]), 3)
        self.assertGreater(len(body["map"]["blocks"]), 3)
        self.assertGreater(len(body["hosts"]), 5)
        for host in body["hosts"]:
            self.assertEqual(len(host["spark"]), 15)
            self.assertIn(host["status"], ("active", "idle"))
            self.assertGreaterEqual(host["bytes"], 0)

    def test_build_live_separates_active_idle_and_flow_vs_block_arcs(self):
        end = self.end
        t_recent = (end - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        t_older = (end - timedelta(minutes=11)).isoformat().replace("+00:00", "Z")
        directory = Directory.build(
            [],
            [
                {"id": "ai-02", "name": "AI-02", "ip": "192.168.5.230", "ips": ["192.168.5.230"], "class": "server"},
                {"id": "nas", "name": "Synology", "ip": "192.168.5.236", "ips": ["192.168.5.236"], "class": "nas"},
            ],
        )
        results = {
            "fresh_flow": [{"_time": t_recent}],
            "fresh_dns": [{"_time": t_recent}],
            "fresh_fw": [{"_time": t_recent}],
            "upload_buckets": [
                {"_time": t_recent, "src_addr": "192.168.5.230", "bytes": "2000000"},
                {"_time": t_older, "src_addr": "192.168.5.236", "bytes": "500000"},
            ],
            "download_buckets": [
                {"_time": t_recent, "dst_addr": "192.168.5.230", "bytes": "8000000"},
            ],
            "total_series": [
                {"_time": t_older, "bytes": "500000"},
                {"_time": t_recent, "bytes": "10000000"},
            ],
            "block_series": [
                {"_time": t_recent, "blocks": "7"},
            ],
            "host_blocks": [
                {"src": "192.168.5.230", "blocks": "3"},
            ],
            "flow_pairs": [
                {"src_addr": "192.168.5.230", "dst_addr": "1.1.1.1", "last_seen": t_recent},
            ],
            "block_pairs": [
                {"src": "8.8.8.8", "dst": "192.168.5.1", "hits": "7", "last_seen": t_recent},
            ],
        }
        payload = build_live(end, results, directory, geo=FakeGeo())
        self.assertEqual(payload["health"]["state"], "healthy")
        self.assertEqual(payload["totals"]["active_hosts"], 1)
        self.assertEqual(payload["totals"]["listed_hosts"], 2)
        self.assertEqual(payload["totals"]["flow_endpoints"], 1)
        self.assertEqual(payload["totals"]["block_endpoints"], 1)
        self.assertEqual(payload["totals"]["firewall_blocks"], 7)

        hosts_by_id = {h["id"]: h for h in payload["hosts"]}
        self.assertEqual(hosts_by_id["ai-02"]["status"], "active")
        self.assertEqual(hosts_by_id["ai-02"]["bytes"], 10_000_000)
        self.assertEqual(hosts_by_id["ai-02"]["blocked"], 3)
        self.assertEqual(hosts_by_id["nas"]["status"], "idle")
        self.assertEqual(hosts_by_id["nas"]["bytes"], 500_000)

        self.assertEqual(len(payload["map"]["flows"]), 1)
        self.assertEqual(payload["map"]["flows"][0]["country_code"], "US")
        self.assertEqual(len(payload["map"]["blocks"]), 1)
        self.assertEqual(payload["map"]["blocks"][0]["country_code"], "NL")

    def test_live_route_returns_503_on_failure_without_demo_fallback(self):
        with patch("backend.app.MODE", "live"), patch("backend.noc_live.live_noc", side_effect=RuntimeError("down")):
            resp = self.client.get("/api/network/live")
            self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
