import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import app as module


class FlowTests(unittest.TestCase):
    @patch('backend.flows.collector_status', return_value={})
    def test_empty_nan_stats_are_zero(self, status):
        from backend.flows import build_traffic
        def query(statement):
            return [{"bytes": "NaN", "packets": "NaN", "records": "0"}] if statement.endswith('count() records') else []
        self.assertEqual(build_traffic(query, '5m')['totals'], {'bytes': 0, 'packets': 0, 'records': 0})

    def setUp(self):
        module.cache.clear()
        self.client = TestClient(module.app)

    @patch('backend.flows.collector_status', return_value={"running": False, "stale": True})
    @patch.object(module, 'query_logs', return_value=[])
    def test_read_only_validated_separate_source_and_dedup(self, query, status):
        self.assertEqual(self.client.get('/api/traffic?window=bad').status_code, 422)
        query.assert_not_called()
        self.assertEqual(self.client.post('/api/traffic').status_code, 405)
        with patch.object(module.trial, 'run') as ai:
            response = self.client.get('/api/traffic?window=1h')
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['collector']['running'])
            self.assertEqual(response.json()['totals']['bytes'], 0)
            ai.assert_not_called()
        statements = [call.args[0] for call in query.call_args_list]
        self.assertTrue(all('app_name:="opnsense-flow"' in q for q in statements))
        self.assertIn('stats by (event_id,', statements[0])
        self.client.get('/api/traffic?window=1h')
        self.assertEqual(query.call_count, 6)
