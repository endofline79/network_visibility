import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import app as module
from backend.jev import JevTrial, MODEL, PURPOSES, PATTERNS, DAILY_LIMIT, group_snapshot
from backend.filterlog import parse_filterlog
from test_filterlog import V4, record, LOCAL


def fixture():
    event = parse_filterlog(record(V4), LOCAL)
    return {"as_of": "2026-09-20T02:05:00Z", "events": [event], "local_networks": [str(n) for n in LOCAL],
            "total": 1, "capped": False, "parse_errors": 0}


def answer(payload, key):
    return {"model": MODEL, "usage": {"input_tokens": 1200, "output_tokens": 50}, "answers": {
        name: {"type": "choice", "choice": "unknown", "confidence": 0.9,
               "probabilities": {category: 1.0 if category == "unknown" else 0.0 for category in question["criteria"]}}
        for name, question in payload["questions"].items()}}


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "trial.sqlite3"
        self.sender = Mock(side_effect=answer)
        self.trial = JevTrial(self.path, key_loader=lambda: "private-test-key", sender=self.sender)
        self.preview = self.trial.preview(fixture())
        self.selections = [{"id": self.preview["groups"][0]["id"], "role": "unknown", "context": ""}]

    def run_trial(self, context=""):
        selection = [{**self.selections[0], "context": context}]
        return self.trial.run(self.preview["id"], selection)

    def test_defaults_off_and_free_preview_and_control_never_call_provider(self):
        self.assertFalse(self.trial.status()["enabled"])
        self.trial.request_preview(self.preview["id"], self.selections)
        with self.assertRaises(HTTPException) as error:
            self.run_trial()
        self.assertEqual(error.exception.status_code, 409)
        self.trial.control(True)
        self.trial.control(False)
        self.assertEqual(self.trial.status()["used_today"], 0)
        self.sender.assert_not_called()

    def test_automatic_expiry_blocks_another_request(self):
        self.trial.control(True)
        self.trial.enabled_until = 1
        with self.assertRaises(HTTPException):
            self.run_trial()
        self.assertFalse(self.trial.status()["enabled"])
        self.sender.assert_not_called()

    def test_payload_omits_raw_logs_addresses_names_and_exact_times(self):
        prepared = self.trial.request_preview(self.preview["id"], self.selections)
        text = json.dumps(prepared["payload"])
        for secret in ["192.168.5.50", "198.51.100.20", "fixture", "2026-09-20", V4, "private-test-key", "54321"]:
            self.assertNotIn(secret, text)
        self.assertEqual(prepared["api_requests"], 1)
        self.assertEqual(len(prepared["payload"]["questions"]), 2)
        self.assertIn("443 alone", text)
        self.sender.assert_not_called()

    def test_cache_review_and_history_are_free_and_survive_restart(self):
        self.trial.control(True)
        first = self.run_trial()
        self.assertFalse(first["cached"])
        self.assertTrue(self.run_trial()["cached"])
        self.trial.control(False)
        self.assertTrue(self.run_trial()["cached"])
        self.trial.review(first["run"]["id"], self.selections[0]["id"], "software_updates")
        restarted = JevTrial(self.path, key_loader=lambda: "key", sender=self.sender)
        status = restarted.status()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["input_tokens"], 1200)
        self.assertEqual(status["used_today"], 1)
        self.assertEqual(status["runs"][0]["reviews"][self.selections[0]["id"]], "software_updates")
        self.assertEqual(status["runs"][0]["answers"][self.selections[0]["id"]]["purpose"]["choice"], "unknown")
        self.assertEqual(self.sender.call_count, 1)

    def test_daily_budget_is_reserved_and_cannot_be_reset_by_toggle_or_restart(self):
        self.trial.control(True)
        for i in range(DAILY_LIMIT):
            self.run_trial(f"Example context {i}")
        with self.assertRaises(HTTPException) as error:
            self.run_trial("One more")
        self.assertEqual(error.exception.status_code, 429)
        self.trial.control(False)
        with self.assertRaises(HTTPException):
            self.trial.control(True)
        restarted = JevTrial(self.path, key_loader=lambda: "key", sender=self.sender)
        self.assertEqual(restarted.status()["remaining_today"], 0)
        self.assertEqual(self.sender.call_count, DAILY_LIMIT)

    def test_timeout_counts_and_never_retries_or_leaks_exception(self):
        self.sender.side_effect = TimeoutError("private-test-key upstream body")
        self.trial.control(True)
        result = self.run_trial()
        self.assertEqual(result["run"]["status"], "failed")
        self.assertNotIn("private-test-key", json.dumps(result))
        self.assertTrue(self.run_trial()["cached"])
        self.assertEqual(self.sender.call_count, 1)
        self.assertEqual(self.trial.status()["used_today"], 1)
        self.assertEqual(self.trial.status()["usage_unconfirmed"], 1)

    def test_invalid_answer_does_not_look_like_success_but_records_usage(self):
        def malformed(payload, key):
            result = answer(payload, key)
            result["answers"]["purpose_0"]["probabilities"]["streaming"] = 0.8
            return result
        self.sender.side_effect = malformed
        self.trial.control(True)
        result = self.run_trial()["run"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["answers"], {})
        self.assertEqual(self.trial.status()["input_tokens"], 1200)

    def test_concurrent_run_rejected_and_off_does_not_wait_for_inflight(self):
        started, finish = threading.Event(), threading.Event()
        def slow(payload, key):
            started.set()
            self.assertTrue(finish.wait(3))
            return answer(payload, key)
        self.sender.side_effect = slow
        self.trial.control(True)
        thread = threading.Thread(target=self.run_trial)
        thread.start()
        try:
            self.assertTrue(started.wait(3))
            with self.assertRaises(HTTPException) as error:
                self.run_trial("Different context")
            self.assertEqual(error.exception.status_code, 409)
            self.assertFalse(self.trial.control(False)["enabled"])
            with self.assertRaises(HTTPException):
                self.run_trial("Still off")
        finally:
            finish.set()
            thread.join(3)
        self.assertEqual(self.sender.call_count, 1)

    def test_bad_selections_rejected_before_provider(self):
        for selections in [[], self.selections * 4, self.selections * 2,
                           [{**self.selections[0], "id": "0" * 16}],
                           [{**self.selections[0], "role": "invented"}]]:
            with self.assertRaises(HTTPException):
                self.trial.run(self.preview["id"], selections)
        self.sender.assert_not_called()

    def test_diverse_groups_and_missing_or_capped_data_are_explicit(self):
        data = fixture()
        data["events"] = [copy.deepcopy(data["events"][0]) for _ in range(20)]
        data["events"] += [{**data["events"][0], "destination_port": p} for p in [53, 123, 22]]
        data["capped"], data["total"] = True, 10000
        preview = group_snapshot(data)
        self.assertEqual({g["destination_port"] for g in preview["groups"]}, {443, 53, 123, 22})
        self.assertEqual(preview["groups"][0]["count"], 20)
        self.assertEqual(len(preview["groups"][0]["examples"]), 3)
        self.assertTrue(preview["capped"])

    def test_storage_failure_blocks_paid_work(self):
        trial = JevTrial(self.path / "nonexistent" / "trial.db", key_loader=lambda: "key", sender=self.sender)
        with self.assertRaises(HTTPException) as error:
            trial.control(True)
        self.assertEqual(error.exception.status_code, 503)
        self.sender.assert_not_called()

    def test_many_ports_on_one_peer_do_not_hide_quieter_services(self):
        data = fixture()
        event = data["events"][0]
        data["events"] = [{**event, "destination_port": p} for p in range(10000, 10020) for _ in range(10)]
        data["events"] += [{**event, "source": "192.168.5.51", "protocol": "ICMP", "destination_port": None}]
        self.assertIn("ICMP", [g["protocol"] for g in group_snapshot(data)["groups"][:3]])

    def test_interrupted_run_stays_unconfirmed_and_is_not_replayed(self):
        self.trial.control(True)
        result = self.run_trial()["run"]
        result["status"], result["usage"] = "started", None
        with self.trial.db() as db:
            db.execute("UPDATE runs SET status='started',data=?,input_tokens=NULL,output_tokens=NULL WHERE id=?",
                       (json.dumps(result), result["id"]))
        restarted = JevTrial(self.path, key_loader=lambda: "key", sender=self.sender)
        cached = restarted.run(self.preview["id"], self.selections)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["run"]["status"], "unconfirmed")
        self.assertEqual(restarted.status()["usage_unconfirmed"], 1)
        self.assertEqual(self.sender.call_count, 1)


class TrialApiTests(unittest.TestCase):
    setUp = TrialTests.setUp
    def test_post_requires_same_origin_json_and_custom_header(self):
        client = TestClient(module.app)
        with patch.object(module, "trial", self.trial):
            self.assertEqual(client.get("/api/jev/status").status_code, 200)
            self.assertEqual(client.post("/api/jev/control", json={"enabled": True}).status_code, 403)
            headers = {"X-Visibility-Trial": "1", "Origin": "http://evil.example"}
            self.assertEqual(client.post("/api/jev/control", headers=headers, json={"enabled": True}).status_code, 403)
            headers["Origin"] = "http://testserver"
            self.assertEqual(client.post("/api/jev/control", headers=headers, json={"enabled": True}).status_code, 200)
            self.assertEqual(client.post("/api/jev/control", headers=headers, json={"enabled": "false"}).status_code, 422)
            response = client.post("/api/jev/run", headers=headers, json={"preview_id": self.preview["id"], "groups": self.selections * 4})
            self.assertEqual(response.status_code, 422)
        self.sender.assert_not_called()
