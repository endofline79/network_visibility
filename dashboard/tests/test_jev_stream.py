import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import app as module
from backend.jev import ARM_SECONDS, DAILY_LIMIT, JevTrial
from test_jev import answer, fixture
from test_filterlog import V4, record


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = 1800489600.0
        self.sender = Mock(side_effect=answer)
        self.loader = Mock(side_effect=self.snapshot)
        self.trial = JevTrial(Path(self.directory.name) / "trial.sqlite3", key_loader=lambda: "secret-key",
                              sender=self.sender, snapshot_loader=self.loader, clock=lambda: self.clock)

    def snapshot(self, start, end):
        data = fixture()
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
        data.update(as_of=iso(end), window_start=iso(start), window="continuous", window_seconds=round(end - start))
        data["events"][0]["time"] = iso(end - 1)
        return data

    def start(self):
        return self.trial.control(True, "continuous")

    def test_on_runs_fresh_batches_without_manual_run_and_off_stops(self):
        self.trial.tick()
        self.loader.assert_not_called()
        self.start()
        self.trial.tick()
        first_bounds = self.loader.call_args.args
        self.assertEqual(first_bounds[1] - first_bounds[0], 60)
        self.assertEqual(self.sender.call_count, 1)
        self.trial.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.clock += 60
        self.trial.tick()
        self.assertEqual(self.loader.call_args.args[0], first_bounds[1])
        status = self.trial.status()
        self.assertEqual(status["used_today"], 2)
        self.assertEqual({r["trigger"] for r in status["runs"]}, {"continuous"})
        self.assertEqual(self.sender.call_args.args[0]["state"]["groups"][0]["observation_window_seconds"], 60)
        self.assertNotIn("192.168.", json.dumps(self.sender.call_args.args[0]))
        self.trial.control(False)
        self.clock += 60
        self.trial.tick()
        self.assertEqual(self.sender.call_count, 2)

    def test_idempotent_on_cannot_extend_session_and_expiry_is_enforced(self):
        self.start()
        expiry = self.trial.enabled_until
        self.clock += 60
        self.start()
        self.assertEqual(self.trial.enabled_until, expiry)
        self.clock += ARM_SECONDS
        self.trial.tick()
        self.assertFalse(self.trial.status()["enabled"])
        self.assertIn("session ended", self.trial.status()["stream"]["message"])
        self.sender.assert_not_called()

    def test_turning_off_during_collection_prevents_dispatch(self):
        entered, finish = threading.Event(), threading.Event()
        def slow(start, end):
            entered.set()
            self.assertTrue(finish.wait(3))
            return self.snapshot(start, end)
        self.loader.side_effect = slow
        self.start()
        thread = threading.Thread(target=self.trial.tick)
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            self.trial.control(False)
            with self.assertRaises(HTTPException):
                self.start()
        finally:
            finish.set()
            thread.join(3)
        self.sender.assert_not_called()
        self.assertFalse(self.trial.status()["stream"]["capturing"])

    def test_off_during_provider_call_saves_that_batch_and_stops_next(self):
        entered, finish = threading.Event(), threading.Event()
        def slow(payload, key):
            entered.set()
            self.assertTrue(finish.wait(3))
            return answer(payload, key)
        self.sender.side_effect = slow
        self.start()
        thread = threading.Thread(target=self.trial.tick)
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertFalse(self.trial.control(False)["enabled"])
        finally:
            finish.set()
            thread.join(3)
        self.clock += 60
        self.trial.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.assertEqual(self.trial.status()["runs"][0]["status"], "complete")

    def test_failure_stops_stream_without_retry(self):
        self.sender.side_effect = TimeoutError("secret-key")
        self.start()
        self.trial.tick()
        self.clock += 60
        self.trial.tick()
        status = self.trial.status()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["used_today"], 1)
        self.assertNotIn("secret-key", json.dumps(status))
        self.assertEqual(self.sender.call_count, 1)

    def test_collection_failure_and_empty_window_do_not_spend(self):
        self.loader.side_effect = RuntimeError("private collector details")
        self.start()
        self.trial.tick()
        self.assertFalse(self.trial.status()["enabled"])
        self.assertNotIn("private collector", json.dumps(self.trial.status()))
        empty = self.snapshot(self.clock - 60, self.clock)
        empty.update(events=[], total=0)
        self.loader.side_effect = lambda start, end: empty
        self.start()
        self.trial.tick()
        self.assertTrue(self.trial.status()["enabled"])
        self.assertEqual(self.trial.status()["stream"]["last_sample"]["selected_groups"], 0)
        self.sender.assert_not_called()

    def test_shared_daily_limit_stops_stream_and_survives_restart(self):
        self.trial.control(True)
        preview = self.trial.preview(fixture())
        for i in range(DAILY_LIMIT - 1):
            self.trial.run(preview["id"], [{"id": preview["groups"][0]["id"], "role": "unknown", "context": str(i)}])
        self.trial.control(False)
        self.start()
        self.trial.tick()
        self.assertFalse(self.trial.status()["enabled"])
        self.clock += 60
        self.trial.tick()
        self.assertEqual(self.sender.call_count, DAILY_LIMIT)
        restarted = JevTrial(self.trial.path, key_loader=lambda: "key", snapshot_loader=self.loader)
        self.assertFalse(restarted.status()["enabled"])
        with self.assertRaises(HTTPException):
            restarted.control(True, "continuous")

    def test_live_sampling_rotates_candidates_and_discloses_caps_and_gaps(self):
        def many(start, end):
            data = self.snapshot(start, end)
            event = data["events"][0]
            data["events"] = [{**copy.deepcopy(event), "source": f"192.168.5.{i}", "destination_port": 50 + i}
                              for i in range(10)]
            data.update(capped=True, total=6000, parse_errors=1)
            return data
        self.loader.side_effect = many
        self.start()
        self.trial.tick()
        first = {g["id"] for g in self.trial.status()["runs"][0]["groups"]}
        self.clock += 300
        self.trial.tick()
        status = self.trial.status()
        second = {g["id"] for g in status["runs"][0]["groups"]}
        self.assertFalse(first & second)
        sample = status["stream"]["last_sample"]
        self.assertEqual(sample["skipped_seconds"], 180)
        self.assertTrue(sample["capped"])
        self.assertEqual(sample["parse_errors"], 1)
        self.assertEqual(sample["selected_groups"], 3)
        self.assertEqual(sample["total_groups"], 10)

    def test_manual_requests_and_session_changes_cannot_race_stream(self):
        self.start()
        preview = self.trial.preview(fixture())
        with self.assertRaises(HTTPException):
            self.trial.control(True, "manual")
        with self.assertRaises(HTTPException):
            self.trial.run(preview["id"], [{"id": preview["groups"][0]["id"], "role": "unknown", "context": ""}])
        with self.assertRaises(HTTPException):
            self.trial.run(preview["id"], [{"id": preview["groups"][0]["id"], "role": "unknown", "context": ""}],
                           trigger="continuous", session_id="stale-session")
        self.sender.assert_not_called()

    def test_app_worker_runs_from_switch_without_browser_polling_and_stops_on_shutdown(self):
        called = threading.Event()
        def send(payload, key):
            called.set()
            return answer(payload, key)
        self.sender.side_effect = send
        with patch.object(module, "trial", self.trial):
            with TestClient(module.app) as client:
                response = client.post("/api/jev/control", headers={"X-Visibility-Trial": "1"},
                                       json={"enabled": True, "mode": "continuous"})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(called.wait(3))
            self.assertFalse(self.trial.worker.is_alive())
            self.assertFalse(self.trial.status()["enabled"])
        self.assertEqual(self.sender.call_count, 1)


class WindowTests(unittest.TestCase):
    def test_absolute_nonoverlapping_query_and_cap_count_share_bounds(self):
        with patch.object(module, "MAX_EVENTS", 2), patch.object(module, "query_logs", side_effect=[
                [record(V4)] * 3, [{"total": "999"}]]) as query:
            data = module.build_jev_window(1800489540, 1800489600)
        self.assertEqual(data["window_seconds"], 60)
        self.assertEqual(len(data["events"]), 2)
        self.assertEqual(data["total"], 999)
        self.assertTrue(data["capped"])
        bases = [call.args[0].split(" | ")[0] for call in query.call_args_list]
        self.assertEqual(bases[0], bases[1])
        self.assertIn('app_name:="filterlog"', bases[0])
        self.assertIn(") AND remote_ip", bases[0])
