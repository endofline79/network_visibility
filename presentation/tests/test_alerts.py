import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.alerts import demo_alerts, fingerprint, live_alerts, reduce_alerts
from backend.app import app
from backend.client import QueryError
from backend.models import Alerts

UTC = timezone.utc
NOW = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)


def row(rule, subject, severity, state, minutes, summary="evidence"):
    moment = NOW - timedelta(minutes=minutes)
    stamp = moment.isoformat().replace("+00:00", "Z")
    return {
        "_time": stamp,
        "kind": "transition",
        "fingerprint": fingerprint(rule, subject),
        "rule": rule,
        "severity": severity,
        "state": state,
        "subject": subject,
        "summary": summary,
        "first_seen": stamp,
        "last_seen": stamp,
        "evidence_query": "app_name:=filterlog",
        "details": "{}",
    }


class Reduce(unittest.TestCase):
    def test_open_resolved_and_newest_transition_wins(self):
        older = row("disk-usage", "data-volume", "warning", "firing", 40)
        newer = row("disk-usage", "data-volume", "warning", "resolved", 5, "Resolved: disk")
        fresh = row("wan-ingress", "192.168.5.50", "critical", "firing", 1)
        heartbeat = {"_time": NOW.isoformat().replace("+00:00", "Z"), "kind": "heartbeat"}
        view = reduce_alerts([older, newer, fresh, heartbeat], heartbeat, True, NOW)
        self.assertEqual(view["checker"], "ok")
        self.assertEqual([item["subject"] for item in view["open"]], ["192.168.5.50"])
        self.assertEqual(view["resolved"][0]["summary"], "Resolved: disk")
        self.assertEqual(view["resolved"][0]["state"], "resolved")

    def test_stale_heartbeat_is_a_synthetic_critical(self):
        seen = (NOW - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        view = reduce_alerts([], {"_time": seen}, True, NOW, stale_seconds=180)
        self.assertEqual(view["checker"], "silent")
        self.assertEqual(view["open"][0]["rule"], "checker-silent")
        self.assertEqual(view["open"][0]["severity"], "critical")
        self.assertEqual(view["open"][0]["fingerprint"], fingerprint("checker-silent", "alerter"))
        self.assertGreaterEqual(view["open"][0]["age_seconds"], 600)

    def test_unknown_heartbeat_does_not_invent_silence(self):
        firing = row("container-health", "visibility-logs-1", "critical", "firing", 2)
        view = reduce_alerts([firing], None, False, NOW)
        self.assertEqual(view["checker"], "unknown")
        self.assertEqual([item["rule"] for item in view["open"]], ["container-health"])

    def test_old_resolved_alerts_drop_off(self):
        old = row("cert-expiry", "telemetry-api", "warning", "resolved", 48 * 60)
        view = reduce_alerts([old], {"_time": NOW.isoformat().replace("+00:00", "Z")}, True, NOW)
        self.assertEqual(view["resolved"], [])

    def test_demo_contract(self):
        payload = demo_alerts(NOW)
        Alerts.model_validate(payload)
        self.assertTrue(payload["illustrative"])
        self.assertEqual({item["severity"] for item in payload["open"]}, {"warning", "info"})
        self.assertEqual(payload["resolved"][0]["state"], "resolved")


class LiveQuery(unittest.TestCase):
    def test_transition_failure_raises_and_heartbeat_failure_is_unknown(self):
        class Client:
            def query(self, query, deadline):
                if "kind:=heartbeat" in query:
                    raise QueryError("heartbeat")
                return [row("gateway-down", "wan", "critical", "firing", 1)]

        view = live_alerts(Client(), NOW)
        self.assertEqual(view["mode"], "live")
        self.assertFalse(view["illustrative"])
        self.assertEqual(view["checker"], "unknown")
        self.assertEqual(view["open"][0]["rule"], "gateway-down")

        class Down:
            def query(self, query, deadline):
                raise QueryError("down")

        with self.assertRaises(QueryError):
            live_alerts(Down(), NOW)


class Route(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_demo_route_is_read_only(self):
        response = self.client.get("/api/alerts")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mode"], "demo")
        self.assertTrue(body["illustrative"])
        self.assertEqual(self.client.post("/api/alerts", json={}).status_code, 405)
        self.assertEqual(self.client.get("/api/health").json()["version"], "0.4.1")

    def test_live_query_failure_is_503(self):
        with patch("backend.alerts.live_alerts", side_effect=QueryError("down")), patch("backend.app.MODE", "live"):
            response = self.client.get("/api/alerts")
        self.assertEqual(response.status_code, 503)
