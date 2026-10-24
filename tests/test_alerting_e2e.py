"""Synthetic dry-run records render on the console and match the webhook body."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "alerter"))
sys.path.insert(0, str(ROOT / "dashboard" / "backend"))
sys.path.insert(0, str(ROOT / "presentation"))

from backend.alerts import reduce_alerts
from checker import run_dry, stream_record
from config import load
from machine import blank_state
from times import iso

UTC = timezone.utc
NOW = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
WEBHOOK_KEYS = {
    "fingerprint", "rule", "severity", "state", "subject", "summary",
    "first_seen", "last_seen", "evidence_query", "console_url", "details",
}


class SyntheticDryRun(unittest.TestCase):
    def test_warning_and_critical_reach_stream_panel_and_webhook(self):
        config = load(ROOT / "alerter" / "rules.json")
        inserted = []
        posted = []
        state, records, sent = run_dry(config, blank_state(), NOW, inserted.append, posted.append)
        self.assertGreaterEqual(sent, 2)
        self.assertEqual(len(inserted), 1)
        batch = inserted[0]
        self.assertTrue(any(row["kind"] == "heartbeat" for row in batch))
        transitions = [row for row in batch if row["kind"] == "transition"]
        subjects = {row["subject"] for row in transitions}
        self.assertEqual(subjects, {"synthetic-warning", "synthetic-critical"})
        heartbeat = next(row for row in batch if row["kind"] == "heartbeat")
        view = reduce_alerts(transitions, heartbeat, True, NOW)
        panel = {
            "mode": "live",
            "as_of": iso(NOW),
            "illustrative": False,
            **view,
        }
        for key in ("mode", "checker", "open", "resolved", "illustrative"):
            self.assertIn(key, panel)
        open_subjects = {item["subject"]: item for item in panel["open"]}
        self.assertEqual(set(open_subjects), {"synthetic-warning", "synthetic-critical"})
        self.assertEqual(open_subjects["synthetic-warning"]["severity"], "warning")
        self.assertEqual(open_subjects["synthetic-warning"]["rule"], "dry-run")
        self.assertEqual(open_subjects["synthetic-critical"]["severity"], "critical")
        self.assertLess(open_subjects["synthetic-warning"]["first_seen"], iso(NOW))
        self.assertGreater(open_subjects["synthetic-warning"]["age_seconds"], 1800)
        self.assertEqual(panel["checker"], "ok")
        self.assertEqual(panel["resolved"], [])
        for payload in posted:
            self.assertTrue(WEBHOOK_KEYS <= set(payload))
            self.assertEqual(payload["state"], "firing")
            self.assertTrue(payload["details"]["synthetic"])
            self.assertIn(payload["subject"], open_subjects)
            self.assertEqual(payload["fingerprint"], open_subjects[payload["subject"]]["fingerprint"])
            self.assertEqual(payload["evidence_query"], open_subjects[payload["subject"]]["evidence_query"])
        critical = state["alerts"][open_subjects["synthetic-critical"]["fingerprint"]]
        rendered = stream_record(critical, config["hostname"], NOW)
        self.assertEqual(rendered["app_name"], "visibility-alert")
        self.assertEqual(rendered["state"], "firing")
        self.assertNotIn("webhook", json_blob(posted))


def json_blob(payloads):
    import json
    return json.dumps(payloads)


if __name__ == "__main__":
    unittest.main()
