import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.planner import PINNED_MODEL, local_base, planner_call, status


class PlannerTests(unittest.TestCase):
    def test_status_pins_the_local_alias(self):
        with patch.dict(os.environ, {'PLANNER_MODEL': PINNED_MODEL, 'LLM_BASE_URL': 'http://172.17.0.1:8081/v1'}, clear=False):
            body = status()
        self.assertTrue(body['configured'])
        self.assertEqual(body['model'], 'visibility-planner')
        self.assertEqual(body['parallel'], 1)
        self.assertTrue(body['queued'])
        self.assertFalse(body['cloud_fallback'])
        self.assertIsNone(local_base('https://api.openai.com/v1'))

    def test_remote_base_url_is_not_advertised(self):
        secret = 'https://user:super-secret@api.openai.com/v1'
        with patch.dict(os.environ, {'LLM_BASE_URL': secret, 'PLANNER_MODEL': 'visibility-planner'}):
            body = status()
        encoded = json.dumps(body)
        self.assertFalse(body['configured'])
        self.assertIsNone(body['base_url'])
        self.assertNotIn('super-secret', encoded)
        self.assertNotIn('openai', encoded)

    def test_token_file_is_reported_as_a_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'planner-token'
            path.write_text('not-a-real-token\n')
            with patch.dict(os.environ, {'PLANNER_TOKEN_FILE': str(path)}):
                body = status()
            self.assertTrue(body['token_configured'])
            self.assertNotIn('not-a-real-token', json.dumps(body))

    def test_planner_call_queues_on_one_slot(self):
        started = threading.Event()
        release = threading.Event()
        order = []

        def hold():
            with planner_call():
                started.set()
                release.wait(2)
                order.append('first')

        thread = threading.Thread(target=hold)
        thread.start()
        self.assertTrue(started.wait(1))

        def follow():
            with planner_call():
                order.append('second')

        follower = threading.Thread(target=follow)
        follower.start()
        follower.join(0.1)
        self.assertEqual(order, [])
        release.set()
        thread.join(2)
        follower.join(2)
        self.assertEqual(order, ['first', 'second'])


if __name__ == '__main__':
    unittest.main()
