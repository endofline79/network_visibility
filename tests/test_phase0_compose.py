import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Phase0ComposeTests(unittest.TestCase):
    def text(self, relative):
        return (ROOT / relative).read_text(encoding='utf-8')

    def test_logs_memory_and_services(self):
        compose = self.text('compose.yaml')
        self.assertIn('-memory.allowedBytes=3GiB', compose)
        self.assertNotIn('-memory.allowedBytes=1GiB', compose)
        self.assertIn('mem_limit: 4g', compose)
        self.assertIn('memswap_limit: 4g', compose)
        self.assertIn('\n  filterlog-relay:\n', compose)
        self.assertIn('\n  alerter:\n', compose)
        self.assertIn(':1515/tcp', compose)
        self.assertIn('_stream_fields=hostname,app_name', compose)
        self.assertNotIn('hooks.slack.com', compose)
        self.assertNotIn('xoxb-', compose)

    def test_live_overlay_wires_planner_without_secrets(self):
        live = self.text('deploy/compose.live.yaml')
        demo = self.text('compose.presentation.yaml')
        for text in (live, demo):
            self.assertIn('PLANNER_TOKEN_FILE: /run/visibility/planner-token', text)
            self.assertIn('PLANNER_MODEL: visibility-planner', text)
            self.assertIn('LLM_BASE_URL: http://172.17.0.1:8081/v1', text)
            self.assertIn('--parallel 1', text)
        self.assertIn('visibility-console:0.4.3', live)
        self.assertIn('PRESENTATION_MODE: live', live)
        self.assertIn('docker compose -f deploy/compose.live.yaml up -d', live)
        self.assertNotIn('bearer_token', live.lower())
        self.assertNotIn('BEGIN ', live)
        self.assertNotRegex(live, r'[0-9a-f]{64}')

    def test_demo_file_stays_a_demo(self):
        demo = self.text('compose.presentation.yaml')
        self.assertIn('PRESENTATION_MODE: demo', demo)
        self.assertIn('127.0.0.1:8096:8096', demo)
        self.assertIn('visibility-console:0.1.0', demo)


if __name__ == '__main__':
    unittest.main()
