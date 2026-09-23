import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import app as module
from test_filterlog import V4, record


class ApiTests(unittest.TestCase):
    def setUp(self):
        module.cache.clear()
        self.client = TestClient(module.app)

    def test_health_and_browser_boundaries(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("connect-src 'self'", response.headers["content-security-policy"])
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertEqual(self.client.get("/api/health", headers={"host": "untrusted.example"}).status_code, 400)
        self.assertEqual(self.client.post("/api/snapshot").status_code, 405)

    @patch.object(module.inventory, "poll_once")
    def test_inventory_is_cached_read_only_and_separate_from_jev(self, poll):
        with patch.object(module.trial, "run") as run:
            response = self.client.get("/api/inventory")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(self.client.post("/api/inventory").status_code, 405)
            self.assertNotIn("fingerprint", response.text)
            poll.assert_not_called()
            run.assert_not_called()

    @patch.object(module.dns, "poll_once")
    def test_dns_status_is_cached_read_only_and_no_metered_work(self, poll):
        with patch.object(module.trial, "run") as run:
            response = self.client.get("/api/dns")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(self.client.post("/api/dns").status_code, 405)
            self.assertNotIn("password", response.text)
            self.assertNotIn("fingerprint", response.text)
            poll.assert_not_called()
            run.assert_not_called()

    @patch.object(module, "query_logs")
    def test_dns_search_validation_and_duplicate_receipts(self, query):
        self.assertEqual(self.client.get("/api/dns/queries?outcome=bad").status_code, 422)
        self.assertEqual(self.client.get("/api/dns/queries?window=bad").status_code, 422)
        query.assert_not_called()
        query.return_value = [{"event_id": "one", "domain": "<script>safe</script>", "_time": "2026-09-20T02:00:00Z"}]*2
        search = '\" OR * | stats count()'
        response = self.client.get("/api/dns/queries", params={"search": search, "outcome": "blocked"})
        self.assertEqual(len(response.json()["queries"]), 1)
        self.assertIn("_msg:" + json.dumps(search.strip()), query.call_args.args[0])
        self.assertIn('outcome:="blocked"', query.call_args.args[0])
        self.assertEqual(response.json()["queries"][0]["domain"], "<script>safe</script>")

    @patch.object(module, "query_logs")
    def test_window_and_query_input_validation(self, query):
        self.assertEqual(self.client.get("/api/snapshot", params={"window": "1h | delete"}).status_code, 422)
        self.assertEqual(self.client.get("/api/logs", params={"search": "x" * 161}).status_code, 422)
        query.assert_not_called()

    @patch.object(module, "refresh_geo")
    @patch.object(module, "query_logs")
    def test_capped_results_and_cache(self, query, geo):
        query.side_effect = [[record(V4)] * (module.MAX_EVENTS + 1), [{"total": "7000"}], []]
        response = self.client.get("/api/snapshot?window=15m")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["capped"])
        self.assertEqual(len(result["events"]), module.MAX_EVENTS)
        self.assertEqual(result["total"], 7000)
        self.assertEqual(result["parse_errors"], 0)
        self.client.get("/api/snapshot?window=15m")
        self.assertEqual(query.call_count, 3)
        self.assertIn("desc limit 5001", query.call_args_list[0].args[0])
        self.assertEqual(query.call_args_list[0].args[0].split(" | ")[0], query.call_args_list[1].args[0].split(" | ")[0])
        self.assertIn("_time:[", query.call_args_list[0].args[0])

    @patch.object(module, "query_logs")
    def test_search_is_quoted_and_raw_text_is_preserved(self, query):
        search = '\" | stats count() OR * <script>'
        query.return_value = [{"_time": "2026-09-20T02:00:00Z", "_msg": "<script>alert(1)</script>", "app_name": "test"}]
        response = self.client.get("/api/logs", params={"search": search, "application": 'test\" OR *'})
        self.assertEqual(response.status_code, 200)
        self.assertIn("_msg:" + json.dumps(search), query.call_args.args[0])
        self.assertIn("app_name:=" + json.dumps('test\" OR *'), query.call_args.args[0])
        self.assertEqual(response.json()["logs"][0]["message"], "<script>alert(1)</script>")

    @patch.object(module, "query_logs", side_effect=RuntimeError("private upstream detail"))
    def test_failure_does_not_look_like_empty_success_or_leak_details(self, query):
        result = self.client.get("/api/snapshot")
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private upstream detail", result.text)

    @patch.object(module, "refresh_geo")
    @patch.object(module, "query_logs")
    def test_bad_records_are_counted_and_retained(self, query, geo):
        query.side_effect = [[record("unknown-format")], []]
        body = self.client.get("/api/snapshot").json()
        self.assertEqual(body["parse_errors"], 1)
        self.assertEqual(body["events"][0]["raw"], "unknown-format")
        self.assertEqual(body["total"], len(body["events"]))
        self.assertEqual(query.call_count, 2)


if __name__ == "__main__":
    unittest.main()
