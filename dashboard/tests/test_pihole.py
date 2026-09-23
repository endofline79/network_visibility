import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from backend.pihole import (Config, DnsError, DnsSource, ReadOnlyApi, collect_queries,
                            collect_summary, forward, query_record)


def row(query_id=1, when=1500.25, status="GRAVITY"):
    return {"id": query_id, "time": when, "domain": "example.test", "type": "A", "status": status,
            "client": {"ip": "192.168.5.10", "name": "<script>text</script>"},
            "reply": {"type": "NXDOMAIN"}, "secret": "never included"}


def page(rows, total=None):
    return {"queries": rows, "recordsFiltered": len(rows) if total is None else total,
            "cursor": 10000, "earliest_timestamp": 100}


class FakeApi:
    def __init__(self):
        self.calls = []

    def get(self, path, deadline):
        self.calls.append(path)
        if path == "/api/stats/summary":
            return {"queries": {"total": 10, "blocked": 2, "cached": 6, "forwarded": 2}, "clients": {"active": 3}}
        if path == "/api/info/ftl":
            return {"ftl": {"privacy_level": 0, "pid": 111}}
        if path == "/api/history":
            return {"history": [{"timestamp": 1000, "total": 10, "blocked": 2, "cached": 6, "forwarded": 2}]}
        if path.startswith("/api/stats/top_domains"):
            return {"domains": [{"domain": "example.test", "count": 3}]}
        if path.startswith("/api/stats/top_clients"):
            return {"clients": [{"ip": "192.168.5.10", "count": 10}]}
        if path == "/api/dns/blocking":
            return {"blocking": "enabled"}
        if path.startswith("/api/queries"):
            return page([row()])
        raise AssertionError(path)

    def close(self):
        pass


class DnsTests(unittest.TestCase):
    def test_normalization_preserves_evidence_without_threat_claims(self):
        for status, outcome in [("GRAVITY", "blocked"), ("SPECIAL_DOMAIN", "blocked"),
                                ("EXTERNAL_BLOCKED_EDE15", "blocked"), ("CACHE_STALE", "cached"),
                                ("FORWARDED", "forwarded"), ("IN_PROGRESS", "other"), ("NEW_STATUS", "other")]:
            result = query_record(row(status=status))
            self.assertEqual(result["outcome"], outcome)
            self.assertEqual(result["status"], status)
            self.assertNotIn("secret", result)
            self.assertIn("<script>", result["client_name"])
        for bad in [float("nan"), -1, True]:
            with self.assertRaises(DnsError):
                query_record(row(when=bad))

    def test_summary_whitelist_and_missing_counts(self):
        result = collect_summary(FakeApi(), time.monotonic() + 5, 2000)
        self.assertEqual(result["queries"]["blocked"], 2)
        self.assertEqual(result["clients"], 3)
        self.assertEqual(result["privacy_level"], 0)
        self.assertNotIn("pid", json.dumps(result))
        bad = MagicMock()
        bad.get.return_value = {"queries": {"total": 0}}
        with self.assertRaises(DnsError):
            collect_summary(bad, time.monotonic() + 5, 2000)

    def test_fixed_cursor_with_advancing_offset_and_half_open_bounds(self):
        api = MagicMock()
        api.get.side_effect = [page([row(i, 1500+i/10000) for i in range(500)], 502),
                               page([row(500, 1501), row(501, 1600)], 502)]
        records = collect_queries(api, 1400, 1600, time.monotonic() + 5)
        self.assertEqual(len(records), 501)
        self.assertIn("cursor=10000&start=500", api.get.call_args.args[0])
        self.assertTrue(all(r["_time"] < "1970-01-01T00:26:40" for r in records))

    def test_incomplete_duplicate_changed_or_expired_pages_fail(self):
        for payloads in ([page([row(), row()])], [page([], 1)],
                         [{**page([]), "recordsFiltered": 5001}],
                         [{**page([]), "earliest_timestamp": 1450}],
                         [{"queries": [], "cursor": None}],
                         [page([row(i) for i in range(500)], 501), page([row(501)], 502)]):
            api = MagicMock()
            api.get.side_effect = payloads
            with self.assertRaises(DnsError):
                collect_queries(api, 1400, 1600, time.monotonic()+5)

    def test_durable_batch_retries_identically_then_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dns.json"
            api, sender = FakeApi(), MagicMock(side_effect=DnsError("temporary archive failure"))
            source = DnsSource(path, Config(enabled=True), lambda c: api, sender, lambda: 2400)
            source.poll_once()
            self.assertEqual(source.state["through"], 1500)
            pending = source.state["pending"]
            self.assertEqual(pending["end"], 1800)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("pending", source.status())
            self.assertIn("temporary", source.status()["archive"]["error"])
            saved_calls = len([p for p in api.calls if "/queries?" in p])
            second_sender = MagicMock()
            restored = DnsSource(path, Config(enabled=True), lambda c: api, second_sender, lambda: 2410)
            restored.poll_once()
            self.assertEqual(second_sender.call_args.args[1], sender.call_args.args[1])
            self.assertEqual(len([p for p in api.calls if "/queries?" in p]), saved_calls)
            self.assertEqual(restored.state["through"], 1800)
            self.assertIsNone(restored.state["pending"])
            self.assertIsNone(restored.status()["archive"]["error"])

    def test_disabled_corrupt_state_and_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dns.json"
            factory = MagicMock()
            source = DnsSource(path, Config(), factory)
            source.poll_once()
            self.assertEqual(source.status()["state"], "disabled")
            factory.assert_not_called()
            path.write_text("bad state")
            corrupt = DnsSource(path, Config(enabled=True), factory)
            corrupt.poll_once()
            self.assertTrue(corrupt.storage_error)
            self.assertEqual(path.read_text(), "bad state")
            factory.assert_not_called()
            source.state["snapshot"] = collect_summary(FakeApi(), time.monotonic()+5, 1000)
            source.config = Config(enabled=True)
            source.clock = lambda: 1200
            self.assertTrue(source.status()["stale"])

    def test_missing_history_never_advances_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = DnsSource(Path(tmp) / "dns.json", Config(enabled=True), lambda c: FakeApi(), MagicMock(), lambda: 2400)
            with patch("backend.pihole.collect_queries", side_effect=DnsError("history unavailable")):
                source.poll_once()
            self.assertEqual(source.state["through"], 1500)
            self.assertIsNone(source.state["pending"])
            source.sender.assert_not_called()

    def test_certificate_precedes_credentials_and_read_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "key"
            path.write_text("not-a-real-secret")
            api = ReadOnlyApi(Config(fingerprint="a" * 64, key_file=str(path)))
            with patch("backend.pihole.http.client.HTTPSConnection") as connection:
                conn = connection.return_value
                conn.sock.getpeercert.return_value = b"wrong certificate"
                with self.assertRaisesRegex(DnsError, "no credential was sent"):
                    api.get("/api/stats/summary", time.monotonic() + 5)
                conn.request.assert_not_called()
                conn.close.assert_called_once()
            with patch.object(api, "_request") as request:
                with self.assertRaises(DnsError):
                    api.get("/api/config", time.monotonic()+5)
                request.assert_not_called()

    def test_session_reuse_auth_failure_and_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "key"
            path.write_text("not-a-real-secret")
            api = ReadOnlyApi(Config(fingerprint="a"*64, key_file=str(path)))
            with patch.object(api, "_request") as request:
                request.side_effect = [{"session": {"valid": True, "sid": "session123"}}, {}, {}, {}]
                api.get("/api/stats/summary", time.monotonic()+5)
                api.get("/api/history", time.monotonic()+5)
                api.close()
                self.assertEqual([c.args[0] for c in request.call_args_list], ["POST", "GET", "GET", "DELETE"])
                self.assertEqual(request.call_args.args[1], "/api/auth")
                self.assertIsNone(api.sid)
            with patch.object(api, "_request", return_value={"session": {"valid": False}}):
                with self.assertRaises(DnsError):
                    api.get("/api/history", time.monotonic()+5)

    def test_redirect_does_not_follow_or_leak_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "key"
            path.write_text("not-a-real-secret")
            api = ReadOnlyApi(Config(fingerprint=hashlib.sha256(b"certificate").hexdigest(), key_file=str(path)))
            with patch("backend.pihole.http.client.HTTPSConnection") as connection:
                conn = connection.return_value
                conn.sock.getpeercert.return_value = b"certificate"
                conn.getresponse.return_value.status = 302
                with self.assertRaisesRegex(DnsError, "HTTP 302"):
                    api.get("/api/history", time.monotonic()+5)
                self.assertEqual(conn.request.call_count, 1)

    def test_no_external_log_destination(self):
        with patch("backend.pihole.http.client.HTTPConnection") as conn:
            with self.assertRaises(DnsError):
                forward(Config(log_url="http://example.com:9428"), [query_record(row())], time.monotonic()+5)
            conn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
