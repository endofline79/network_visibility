import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import renew_dashboard_cert as rdc  # noqa: E402


class RenewCertTests(unittest.TestCase):
    def _make_ca(self, work: Path):
        ca_key = work / "ca.key"
        ca_cert = work / "ca.crt"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(ca_key), "-out", str(ca_cert),
             "-days", "365", "-subj", "/CN=test-ca",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign"],
            check=True, capture_output=True,
        )
        return ca_cert, ca_key

    def test_dry_run_and_apply_preserve_permissions_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ca_cert, ca_key = self._make_ca(root)
            out_dir = root / "presentation"

            dry = rdc.renew_cert(ca_cert, ca_key, out_dir, days=90, apply=False)
            self.assertEqual(dry["status"], "dry-run-ok")
            self.assertGreater(dry["candidate"]["days_remaining"], 85)
            self.assertFalse((out_dir / "dashboard.crt").exists())

            first = rdc.renew_cert(ca_cert, ca_key, out_dir, days=90, apply=True)
            self.assertEqual(first["status"], "renewed")
            self.assertEqual((out_dir / "dashboard.key").stat().st_mode & 0o777, 0o600)
            self.assertEqual((out_dir / "dashboard.crt").stat().st_mode & 0o777, 0o644)
            self.assertEqual(first["backups"], [])

            second = rdc.renew_cert(ca_cert, ca_key, out_dir, days=90, apply=True)
            self.assertEqual(second["status"], "renewed")
            self.assertEqual(len(second["backups"]), 2)
            self.assertNotEqual(first["cert"]["sha256"], second["cert"]["sha256"])


if __name__ == "__main__":
    unittest.main()
