import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from backend.unifi import (Config, HOST, Inventory, InventoryError, PREFIX, ReadOnlyApi, SITE,
                           collect, page_all)

SWITCH = "11111111-1111-4111-8111-111111111111"
AP = "22222222-2222-4222-8222-222222222222"
CLIENT = "33333333-3333-4333-8333-333333333333"
NETWORK = "44444444-4444-4444-8444-444444444444"


class FixtureApi:
    def __init__(self):
        self.calls = []
        self.fail_stats = False
        self.fail_auth = False

    def get(self, path, deadline):
        self.calls.append(path)
        if self.fail_auth:
            raise InventoryError("Controller returned HTTP 401.", True)
        if "statistics/latest" in path:
            if self.fail_stats:
                raise InventoryError("Controller returned HTTP 404.")
            return {"cpuUtilizationPct": 0, "memoryUtilizationPct": 32.1, "uptimeSec": 50,
                    "lastHeartbeatAt": "2026-09-20T22:00:00Z", "unwanted": "secret"}
        if "?" not in path:
            device_id = path.rsplit("/", 1)[-1]
            return {"id": device_id, "features": {"accessPoint": {}} if device_id == AP else {"switching": {}},
                    "uplink": {"deviceId": SWITCH} if device_id == AP else {},
                    "interfaces": {"radios": [{"frequencyGHz": "5", "channel": 60, "channelWidthMHz": 40}]} if device_id == AP else
                    {"ports": [{"idx": 1, "state": "UP", "speedMbps": 100, "poe": {"state": "UP"}}]}}
        endpoint = path.split("?")[0].rsplit("/", 1)[-1]
        data = {
            "sites": [{"id": SITE, "name": "Home"}],
            "devices": [{"id": SWITCH, "name": "Flex", "state": "ONLINE", "features": ["SWITCHING"]},
                        {"id": AP, "name": "Kitchen", "state": "ONLINE", "features": ["ACCESS_POINT"]}],
            "clients": [{"id": CLIENT, "name": "<script>safe text</script>", "type": "WIRELESS",
                         "uplinkDeviceId": AP, "connectedAt": "2026-09-20T20:00:00Z", "extra": "secret"}],
            "networks": [{"id": NETWORK, "name": "INFRA", "vlanId": 20, "enabled": True}],
        }[endpoint]
        return {"offset": 0, "count": len(data), "totalCount": len(data), "data": data}


class InventoryTests(unittest.TestCase):
    def test_relationships_missing_fields_and_whitelist(self):
        result = collect(FixtureApi(), Config())
        self.assertFalse(result["partial"])
        switch, ap = result["devices"]
        self.assertEqual(switch["ports"][0]["speed_mbps"], 100)
        self.assertEqual(ap["uplink_id"], SWITCH)
        self.assertEqual(ap["radios"][0]["width_mhz"], 40)
        self.assertEqual(ap["cpu_pct"], 0)
        self.assertIsNone(ap["ip"])
        self.assertIsNone(result["clients"][0]["ip"])
        self.assertEqual(result["clients"][0]["uplink_id"], AP)
        self.assertNotIn("secret", json.dumps(result))

    def test_optional_statistics_partial_and_auth_failure_aborts(self):
        api = FixtureApi()
        api.fail_stats = True
        result = collect(api, Config())
        self.assertTrue(result["partial"])
        self.assertIsNone(result["devices"][0]["cpu_pct"])
        api.fail_auth = True
        with self.assertRaises(InventoryError):
            collect(api, Config())

    def test_pagination_and_missing_second_page(self):
        api = MagicMock()
        api.get.side_effect = [
            {"offset": 0, "count": 1, "totalCount": 2, "data": [{"id": AP}]},
            {"offset": 1, "count": 1, "totalCount": 2, "data": [{"id": SWITCH}]},
        ]
        result = page_all(api, PREFIX + "/sites", 50, time.monotonic() + 20)
        self.assertEqual(len(result), 2)
        self.assertIn("offset=1", api.get.call_args.args[0])
        api.get.side_effect = [
            {"offset": 0, "count": 1, "totalCount": 2, "data": [{"id": AP}]},
            {"offset": 1, "count": 0, "totalCount": 2, "data": []},
        ]
        with self.assertRaises(InventoryError):
            page_all(api, PREFIX + "/sites", 50, time.monotonic() + 20)

    def test_changed_duplicate_or_oversize_pages_are_not_committed(self):
        for second in [
            {"offset": 1, "count": 1, "totalCount": 2, "data": [{"id": AP}]},
            {"offset": 1, "count": 1, "totalCount": 3, "data": [{"id": SWITCH}]},
            {"offset": 1, "count": 1, "totalCount": 5000, "data": [{"id": SWITCH}]},
        ]:
            api = MagicMock()
            api.get.side_effect = [{"offset": 0, "count": 1, "totalCount": 2, "data": [{"id": AP}]}, second]
            with self.assertRaises(InventoryError):
                page_all(api, PREFIX + "/sites", 50, time.monotonic() + 20)

    def test_snapshot_survives_failure_restart_and_ages(self):
        with tempfile.TemporaryDirectory() as directory:
            path, api, now = Path(directory) / "inventory.json", FixtureApi(), [1000000]
            config = Config(enabled=True)
            inventory = Inventory(path, config, lambda _: api, lambda: now[0])
            inventory.poll_once()
            self.assertEqual(inventory.status()["state"], "fresh")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            saved = path.read_bytes()
            api.fail_auth = True
            inventory.poll_once()
            self.assertEqual(inventory.status()["state"], "stale")
            self.assertEqual(path.read_bytes(), saved)
            restored = Inventory(path, config, clock=lambda: now[0] + 151)
            self.assertEqual(restored.status()["snapshot"], inventory.status()["snapshot"])
            self.assertEqual(restored.status()["state"], "stale")
            api.fail_auth = False
            now[0] += 200
            inventory.poll_once()
            self.assertEqual(inventory.status()["state"], "fresh")

    def test_disabled_and_status_reads_never_call_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = MagicMock()
            inventory = Inventory(Path(directory) / "inventory.json", Config(), factory)
            inventory.start_worker()
            inventory.poll_once()
            inventory.status()
            factory.assert_not_called()
            self.assertEqual(inventory.status()["state"], "disabled")

    def test_exception_text_never_reaches_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Inventory(Path(directory) / "inventory.json", Config(enabled=True),
                                  MagicMock(side_effect=RuntimeError("private token")))
            inventory.poll_once()
            self.assertNotIn("private token", json.dumps(inventory.status()))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.key = Path(self.directory.name) / "key"
        self.key.write_text("test-credential")
        self.certificate = b"test-certificate"
        self.config = Config(True, fingerprint=hashlib.sha256(self.certificate).hexdigest(), key_file=str(self.key))

    @patch("backend.unifi.http.client.HTTPSConnection")
    def test_pin_checked_before_auth_and_no_redirects(self, connection):
        conn = connection.return_value
        conn.sock.getpeercert.return_value = b"changed"
        with self.assertRaises(InventoryError):
            ReadOnlyApi(self.config).get(PREFIX + "/sites", time.monotonic() + 20)
        conn.request.assert_not_called()
        conn.sock.getpeercert.return_value = self.certificate
        conn.getresponse.return_value.status = 302
        with self.assertRaises(InventoryError):
            ReadOnlyApi(self.config).get(PREFIX + "/sites", time.monotonic() + 20)
        self.assertEqual(conn.request.call_count, 1)
        self.assertEqual(conn.request.call_args.args, ("GET", PREFIX + "/sites"))
        self.assertEqual(connection.call_args.args[0], HOST)

    @patch("backend.unifi.http.client.HTTPSConnection")
    def test_body_and_deadline_bounds_and_endpoint_scope(self, connection):
        conn = connection.return_value
        conn.sock.getpeercert.return_value = self.certificate
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.read1.return_value = b"x" * 65536
        with self.assertRaises(InventoryError):
            ReadOnlyApi(self.config).get(PREFIX + "/sites", time.monotonic() + 20)
        self.assertLessEqual(conn.getresponse.return_value.read1.call_count, 65)
        with self.assertRaises(InventoryError):
            ReadOnlyApi(self.config).get(PREFIX + "/sites", time.monotonic() - 1)
        with self.assertRaises(InventoryError):
            ReadOnlyApi(self.config).get("/proxy/network/api/s/default/rest/setting", time.monotonic() + 20)


if __name__ == "__main__":
    unittest.main()
