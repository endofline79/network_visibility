import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import app
from backend.client import QueryError
from backend.destinations import (
    DOMAIN_FETCH,
    client_filter,
    destination_queries,
    reduce_host,
    site_name,
)
from backend.inventory import InventoryError, load_inventory
from backend.models import DestinationsView
from backend.service import stamp

UTC = timezone.utc
NOW = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)
INVENTORY = Path(__file__).resolve().parents[1] / "config" / "iot-hosts.yaml"
SEED = (
    ("roku-premiere", "streaming", "RokuPremiere", "192.168.5.107", "d8:31:34:8a:bf:b3"),
    ("living-room", "streaming", "Living-Room-Apple-TV", "192.168.5.142", "c0:95:6d:72:de:d6"),
    ("ring-113237", "iot", "Ring-113237", "192.168.5.116", "64:9a:63:11:32:37"),
    ("sonos-zp", "streaming", "SonosZP", "192.168.5.130", "38:42:0b:b6:2e:7a"),
    ("google-nest-mini", "iot", "Google-Nest-Mini", "192.168.5.129", "f8:0f:f9:4a:c6:e3"),
    ("samsung-bedroom-tv", "streaming", "Samsung-Bedroom-TV", "192.168.5.134", "c0:48:e6:c0:dd:9b"),
    ("esp-ca34f5", "iot", "ESP_CA34F5", "192.168.5.113", "68:c6:3a:ca:34:f5"),
    ("esp-ca2ced", "iot", "ESP_CA2CED", "192.168.5.114", "68:c6:3a:ca:2c:ed"),
)
HELD_BACK = (
    "192.168.5.149", "192.168.5.119", "192.168.5.131", "192.168.5.105",
    "192.168.5.108", "192.168.5.127", "192.168.5.145", "192.168.5.133",
)


def write_inventory(directory, body):
    path = Path(directory) / "hosts.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class InventoryLoad(unittest.TestCase):
    def test_checked_in_allowlist_and_held_back_devices_stay_comments(self):
        inventory = load_inventory(INVENTORY)
        self.assertEqual(
            [(host.id, host.device_class, host.name, host.ip, host.mac) for host in inventory.hosts],
            list(SEED),
        )
        self.assertEqual(inventory.hosts[0].dns_names, ("RokuPremiere.occido.net",))
        living = inventory.by_id("living-room")
        self.assertEqual(living.dns_names, ("Living-Room.occido.net", "Living-Room"))
        self.assertIn("Apple TV", living.notes)
        self.assertEqual(inventory.by_id("sonos-zp").device_class, "streaming")
        self.assertEqual(inventory.by_id("google-nest-mini").dns_names, ("Google-Nest-Mini.occido.net",))
        esp_notes = [inventory.by_id(host_id).notes for host_id in ("esp-ca34f5", "esp-ca2ced")]
        self.assertEqual(esp_notes[0], esp_notes[1])
        self.assertIn("Tuya/Smart Life", esp_notes[0])
        self.assertIn("front-door light switch", esp_notes[0])
        self.assertIn("unconfirmed", esp_notes[0])
        self.assertNotIn("192.168.5.113 is", esp_notes[0])
        self.assertNotIn("192.168.5.114 is", esp_notes[0])
        text = INVENTORY.read_text(encoding="utf-8")
        active = {host.ip for host in inventory.hosts}
        for ip in HELD_BACK:
            self.assertIn(ip, text)
            self.assertNotIn(ip, active)
        self.assertIn("MYCAR", text)
        self.assertIn("Leslie's URMC work laptop BLN4N74", text)
        self.assertNotIn("mycar", [host.id for host in inventory.hosts])

    def test_rejects_injection_and_scope_mistakes(self):
        with self.assertRaises(InventoryError):
            load_inventory(write_inventory(self._dir(), """
version: 1
hosts:
  - id: bad-host
    class: iot
    name: 'evil" OR client_ip:="192.168.5.149'
    dns_names: [evil.example]
    ip: 192.168.5.150
    mac: "aa:bb:cc:dd:ee:ff"
"""))
        with self.assertRaises(InventoryError):
            load_inventory(write_inventory(self._dir(), """
version: 1
hosts:
  - id: phone-1
    class: phone
    name: Phone
    dns_names: [Phone.occido.net]
    ip: 192.168.5.151
    mac: "aa:bb:cc:dd:ee:ff"
"""))
        with self.assertRaises(InventoryError):
            load_inventory(write_inventory(self._dir(), """
version: 1
hosts:
  - id: dup-a
    class: iot
    name: DupA
    dns_names: [DupA.occido.net]
    ip: 192.168.5.107
    mac: "aa:bb:cc:dd:ee:01"
  - id: dup-b
    class: iot
    name: DupB
    dns_names: [DupB.occido.net]
    ip: 192.168.5.107
    mac: "aa:bb:cc:dd:ee:02"
"""))

    def test_fifth_host_is_yaml_only(self):
        path = write_inventory(self._dir(), INVENTORY.read_text(encoding="utf-8") + """
  - id: extra-cam
    class: iot
    name: ExtraCam
    dns_names: [ExtraCam.occido.net]
    ip: 192.168.5.180
    mac: "aa:bb:cc:dd:ee:01"
    notes: added without a code change
""")
        inventory = load_inventory(path)
        self.assertEqual(inventory.hosts[-1].id, "extra-cam")
        queries = destination_queries(NOW - timedelta(days=7), NOW, inventory.hosts, False)
        self.assertEqual(len(queries), 18)
        blob = "\n".join(queries.values())
        self.assertIn('client_ip:="192.168.5.180"', blob)
        self.assertIn('client_name:="ExtraCam"', blob)
        self.assertNotIn("event_id", blob)

    def _dir(self):
        import tempfile
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        return handle.name


class QueryShape(unittest.TestCase):
    def setUp(self):
        self.inventory = load_inventory(INVENTORY)

    def test_allowlist_filter_is_exact_and_not_a_lan_cidr(self):
        roku = self.inventory.by_id("roku-premiere")
        self.assertEqual(
            client_filter(roku),
            '(client_ip:="192.168.5.107" OR client_name:="RokuPremiere" OR client_name:="RokuPremiere.occido.net")',
        )
        start = NOW - timedelta(hours=1)
        queries = destination_queries(start, NOW, (roku,), True)
        domain = queries["domains:roku-premiere"]
        span = queries["span:roku-premiere"]
        self.assertLess(domain.index("stats by (event_id, domain)"), domain.index("stats by (domain)"))
        self.assertIn("app_name:=pihole-dns", domain)
        self.assertIn(stamp(start), domain)
        self.assertIn(f"limit {DOMAIN_FETCH}", domain)
        self.assertNotIn("event_id", span)
        self.assertIn("min(_time) first_seen", span)
        self.assertIn("max(_time) last_seen", span)
        self.assertNotIn("ipv4_range", domain + span)
        self.assertNotIn("192.168.5.149", domain + span)

    def test_long_windows_do_not_group_by_event_id(self):
        for seconds in (86400, 604800):
            queries = destination_queries(
                NOW - timedelta(seconds=seconds), NOW, self.inventory.hosts, False,
            )
            self.assertEqual(len(queries), 16)
            for query in queries.values():
                self.assertIn("app_name:=pihole-dns", query)
                self.assertNotIn("event_id", query)
                self.assertNotIn("192.168.5.149", query)
                self.assertIn(stamp(NOW - timedelta(seconds=seconds)), query)
            ips = [host.ip for host in self.inventory.hosts]
            blob = "\n".join(queries.values())
            for ip in ips:
                self.assertIn(f'client_ip:="{ip}"', blob)

    def test_sites_roll_up_registrable_domains(self):
        self.assertEqual(site_name("scribe.logs.roku.com"), "roku.com")
        self.assertEqual(site_name("www.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(site_name("init.itunes.apple.com"), "apple.com")
        self.assertEqual(site_name("192.168.5.1"), "192.168.5.1")
        host = self.inventory.by_id("roku-premiere")
        rows = [
            {"domain": "scribe.logs.roku.com", "queries": "4"},
            {"domain": "www.roku.com", "queries": "2"},
            {"domain": "www.bbc.co.uk", "queries": "3"},
            {"domain": "bbc.co.uk", "queries": "1"},
        ]
        span = [{
            "first_seen": stamp(NOW - timedelta(minutes=30)),
            "last_seen": stamp(NOW - timedelta(minutes=1)),
            "queries": "100",
        }]
        deduped = reduce_host(host, rows, span, True)
        self.assertEqual(deduped["queries"], 10)
        self.assertEqual(deduped["sites"][0]["name"], "roku.com")
        self.assertEqual(deduped["sites"][0]["queries"], 6)
        self.assertEqual({row["name"]: row["queries"] for row in deduped["sites"]}["bbc.co.uk"], 4)
        receipts = reduce_host(host, rows, span, False)
        self.assertEqual(receipts["queries"], 100)
        self.assertEqual(receipts["state"], "available")
        capped = reduce_host(
            host,
            [{"domain": f"n{index}.roku.com", "queries": "1"} for index in range(DOMAIN_FETCH)],
            [{"queries": "999", "first_seen": stamp(NOW), "last_seen": stamp(NOW)}],
            True,
        )
        self.assertEqual(capped["state"], "partial")
        self.assertEqual(len(capped["domains"]), 12)
        self.assertEqual(capped["sites"][0], {"name": "roku.com", "queries": DOMAIN_FETCH})
        self.assertEqual(capped["queries"], DOMAIN_FETCH)
        self.assertNotEqual(capped["queries"], 999)

    def test_live_read_scopes_each_allowlisted_host(self):
        class Client:
            def __init__(self):
                self.queries = []

            def query(self, query, deadline):
                self.queries.append(query)
                if "min(_time)" in query:
                    if "192.168.5.130" in query:
                        raise QueryError("span")
                    return [{
                        "first_seen": stamp(NOW - timedelta(minutes=20)),
                        "last_seen": stamp(NOW - timedelta(minutes=1)),
                        "queries": "9",
                    }]
                if "192.168.5.107" in query:
                    return [
                        {"domain": "scribe.logs.roku.com", "queries": "4"},
                        {"domain": "www.roku.com", "queries": "2"},
                    ]
                return [{"domain": "example.com", "queries": "1"}]

        from backend.destinations import live_destinations

        client = Client()
        view = live_destinations(client, self.inventory, NOW, 86400, "all", NOW)
        DestinationsView.model_validate(view)
        self.assertEqual(view["mode"], "live")
        self.assertFalse(view["deduped"])
        self.assertEqual(len(client.queries), 16)
        self.assertTrue(all("event_id" not in query for query in client.queries))
        self.assertTrue(all("192.168.5.149" not in query for query in client.queries))
        roku = view["hosts"][0]
        self.assertEqual(roku["queries"], 9)
        self.assertEqual(roku["sites"][0]["name"], "roku.com")
        self.assertEqual(roku["sites"][0]["queries"], 6)
        self.assertEqual(view["hosts"][3]["state"], "partial")
        self.assertIsNotNone(view["hosts"][3]["queries"])
        one = live_destinations(Client(), self.inventory, NOW, 3600, "roku-premiere", NOW)
        self.assertTrue(one["deduped"])
        self.assertEqual(one["hosts"][0]["queries"], 6)
        self.assertEqual(len(one["inventory"]), 8)

        class Down:
            def query(self, query, deadline):
                raise QueryError("down")

        with self.assertRaises(QueryError):
            live_destinations(Down(), self.inventory, NOW, 3600, "all", NOW)


class Route(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_demo_route_uses_the_allowlist_and_stays_read_only(self):
        response = self.client.get("/api/destinations")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        DestinationsView.model_validate(body)
        self.assertEqual(body["mode"], "demo")
        self.assertTrue(body["illustrative"])
        self.assertFalse(body["deduped"])
        self.assertEqual(body["window"]["label"], "Last 24 hours")
        self.assertEqual([host["id"] for host in body["hosts"]], [item[0] for item in SEED])
        self.assertEqual(body["hosts"][0]["class"], "streaming")
        self.assertEqual(body["hosts"][0]["sites"][0], {"name": "roku.com", "queries": 60})
        self.assertNotIn("192.168.5.149", json.dumps(body))
        self.assertIn("iot-hosts.yaml", " ".join(body["notes"]))
        hour = self.client.get("/api/destinations?window=1h").json()
        self.assertTrue(hour["deduped"])
        self.assertEqual(hour["hosts"][0]["queries"], 95)
        week = self.client.get("/api/destinations?window=7d").json()
        self.assertEqual(week["window"]["seconds"], 604800)
        self.assertFalse(week["deduped"])
        one = self.client.get("/api/destinations?host=ring-113237").json()
        self.assertEqual([host["id"] for host in one["hosts"]], ["ring-113237"])
        self.assertEqual(len(one["inventory"]), 8)
        self.assertEqual(one["hosts"][0]["sites"][0]["name"], "ring.com")
        self.assertEqual(self.client.get("/api/destinations?window=15m").status_code, 422)
        self.assertEqual(self.client.get("/api/destinations?host=mycar").status_code, 404)
        self.assertEqual(self.client.post("/api/destinations", json={}).status_code, 405)
        self.assertEqual(self.client.get("/api/destinations?scenario=error").status_code, 503)
        blank = self.client.get("/api/destinations?scenario=unavailable").json()
        self.assertTrue(all(host["state"] == "unavailable" for host in blank["hosts"]))
        self.assertEqual(blank["hosts"][0]["queries"], None)
        future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        self.assertEqual(self.client.get("/api/destinations", params={"end": future}).status_code, 422)

    def test_live_failure_is_503_and_a_bad_inventory_does_not_query(self):
        with patch("backend.destinations.live_destinations", side_effect=QueryError("down")), patch("backend.app.MODE", "live"):
            self.assertEqual(self.client.get("/api/destinations").status_code, 503)
            self.assertEqual(self.client.get("/api/destinations?scenario=stale").status_code, 422)
        with patch("backend.inventory.load_inventory", side_effect=InventoryError("bad")), patch("backend.app.MODE", "live"):
            self.assertEqual(self.client.get("/api/destinations").status_code, 503)


if __name__ == "__main__":
    unittest.main()
