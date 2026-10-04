import json
from pathlib import Path
import tempfile
import unittest
from worker import SnapshotArchive, records


class ArchiveTests(unittest.TestCase):
    def snapshot(self, stamp="2026-09-24T23:00:00+00:00"):
        return {"observed_at": stamp, "site": {"id": "site"}, "partial": False,
                "devices": [{"id": "ap", "name": "Kitchen", "ports": [], "cpu_pct": 0}],
                "clients": [], "networks": []}

    def test_entities_identity_and_full_snapshot(self):
        snapshot = self.snapshot()
        rows = records("unifi", snapshot)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["entity_kind"], "device")
        self.assertEqual(rows[1]["cpu_pct"], 0)
        self.assertEqual(json.loads(rows[0]["snapshot_json"]), snapshot)
        self.assertEqual(rows, records("unifi", snapshot))
        self.assertNotEqual(rows[0]["event_id"], rows[1]["event_id"])

    def test_retry_restart_and_checkpoint_no_duplicate_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive.json"
            calls = []
            def fail(config, rows, deadline):
                calls.append(rows)
                raise OSError()
            archive = SnapshotArchive(path, "unifi", None, fail)
            archive.poll(self.snapshot())
            self.assertTrue(archive.status()["pending"])
            self.assertTrue(archive.error)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            recovered = SnapshotArchive(path, "unifi", None, lambda c, r, d: calls.append(r))
            recovered.poll(self.snapshot("2026-09-24T23:01:00+00:00"))
            self.assertEqual(calls[0], calls[1])
            recovered.poll(self.snapshot())
            self.assertEqual(len(calls), 2)
            recovered.poll(self.snapshot("2026-09-24T23:01:00+00:00"))
            self.assertEqual(len(calls), 3)

    def test_corrupt_checkpoint_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive.json"
            path.write_text('{"version":2}')
            with self.assertRaises(ValueError):
                SnapshotArchive(path, "unifi", None)
            self.assertEqual(path.read_text(), '{"version":2}')
