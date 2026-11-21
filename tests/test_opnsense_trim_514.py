import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import opnsense_forwarding as fw  # noqa: E402
import opnsense_trim_514 as trim  # noqa: E402


ALL_FACILITIES = {
    name: {"value": name, "selected": 0}
    for name in (
        "kern", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
        "uucp", "cron", "authpriv", "ftp", "ntp", "security", "console",
        "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7",
    )
}

RELAY_ROW = {
    "uuid": "81dbb23c-afc9-451a-bc91-6f863e55a611",
    "enabled": "1",
    "transport": "tcp4",
    "program": "filterlog",
    "level": "",
    "facility": "",
    "hostname": "192.168.5.230",
    "certificate": "",
    "port": "1515",
    "rfc5424": "1",
    "description": "AI-02 filterlog-relay",
}


class OpnsenseTrim514Test(unittest.TestCase):
    def test_non_filterlog_facilities_excludes_only_local0(self):
        selected = trim._facility_set(trim.NON_FILTERLOG_FACILITIES)
        self.assertEqual(set(ALL_FACILITIES.keys()) - selected, {"local0"})
        self.assertNotIn("local0", selected)

    def test_apply_refuses_without_active_relay(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "opnsense-trim-514.json"
            with mock.patch.object(trim, "STATE", state_path), \
                 mock.patch.object(trim.relay, "read", return_value=(dict(trim.UNTRIMMED), {"facility": ALL_FACILITIES})), \
                 mock.patch.object(trim.relay, "destinations", return_value=[]), \
                 mock.patch.object(sys, "argv", ["opnsense_trim_514.py", "apply"]):
                with self.assertRaises(RuntimeError) as ctx:
                    trim.main()
            self.assertIn("filterlog-relay", str(ctx.exception))
            self.assertFalse(state_path.exists())

    def test_apply_and_rollback_happy_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "opnsense-trim-514.json"
            writes = []
            read_results = [
                (dict(trim.UNTRIMMED), {"facility": ALL_FACILITIES}),
                (dict(trim.TRIMMED), {"facility": ALL_FACILITIES}),
            ]
            with mock.patch.object(trim, "STATE", state_path), \
                 mock.patch.object(trim.relay, "read", side_effect=read_results), \
                 mock.patch.object(trim.relay, "destinations", return_value=[RELAY_ROW]), \
                 mock.patch.object(fw, "protected_fingerprint", return_value="abc123"), \
                 mock.patch.object(fw, "write_target", side_effect=writes.append), \
                 mock.patch.object(fw, "api", return_value={"status": "running"}), \
                 mock.patch.object(sys, "argv", ["opnsense_trim_514.py", "apply"]):
                trim.main()

            self.assertEqual(writes, [{"facility": trim.NON_FILTERLOG_FACILITIES}])
            self.assertTrue(state_path.exists())
            saved = json.loads(state_path.read_text())
            self.assertEqual(saved["uuid"], fw.TARGET)
            self.assertEqual(saved["excluded_facility"], "local0")
            self.assertEqual(saved["protected_sha256"], "abc123")

            rb_writes = []
            rb_reads = [
                (dict(trim.TRIMMED), {"facility": ALL_FACILITIES}),
                (dict(trim.UNTRIMMED), {"facility": ALL_FACILITIES}),
            ]
            with mock.patch.object(trim, "STATE", state_path), \
                 mock.patch.object(trim.relay, "read", side_effect=rb_reads), \
                 mock.patch.object(trim.relay, "destinations", return_value=[RELAY_ROW]), \
                 mock.patch.object(fw, "protected_fingerprint", return_value="abc123"), \
                 mock.patch.object(fw, "write_target", side_effect=rb_writes.append), \
                 mock.patch.object(fw, "api", return_value={"status": "running"}), \
                 mock.patch.object(sys, "argv", ["opnsense_trim_514.py", "rollback"]):
                trim.main()

            self.assertEqual(rb_writes, [{"facility": ""}])
            self.assertFalse(state_path.exists())
            self.assertTrue(state_path.with_suffix(".rolledback.json").exists())


if __name__ == "__main__":
    unittest.main()
