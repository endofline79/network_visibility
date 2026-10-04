import http.client
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent / 'skill/scripts'))
import telemetry


class ClientTests(unittest.TestCase):
    def test_https_origin_required(self):
        for origin in ['http://192.168.5.230:9429', 'https://user:pass@example.com',
                       'https://example.com/path', 'https://example.com/?token=x']:
            with self.assertRaises(ValueError):
                telemetry.connect(origin, '/nonexistent')

    def test_invalid_path_or_duration_does_not_fetch_secret(self):
        with patch.object(telemetry, 'token') as token:
            for path in ['https://other.example', '//other.example', '/bad\r\nheader']:
                with self.assertRaises(ValueError):
                    list(telemetry.request(path))
            with self.assertRaises(ValueError):
                list(telemetry.request('/health', seconds=0))
            token.assert_not_called()

    def test_phase_fetch_is_captured_and_named(self):
        result = MagicMock(returncode=0, stdout=json.dumps(
            {'key': 'TELEMETRY_API_TOKEN', 'path': '/', 'value': 'test-only-placeholder'}))
        with patch.dict(telemetry.os.environ, {}, clear=True), patch.object(telemetry.subprocess, 'run', return_value=result) as run:
            self.assertEqual(telemetry.token(), 'test-only-placeholder')
            self.assertTrue(run.call_args.kwargs['capture_output'])
            self.assertNotIn('test-only-placeholder', run.call_args.args[0])
            self.assertIn('TELEMETRY_API_TOKEN', run.call_args.args[0])

    def test_phase_error_does_not_echo_output(self):
        result = MagicMock(returncode=1, stdout='private-output', stderr='private-error')
        with patch.dict(telemetry.os.environ, {}, clear=True), patch.object(telemetry.subprocess, 'run', return_value=result):
            with self.assertRaises(ValueError) as raised:
                telemetry.token()
            self.assertNotIn('private', str(raised.exception))

    def test_arbitrary_native_endpoint_and_parameters_pass_through(self):
        conn = MagicMock()
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.read1.side_effect = [b'OK', b'']
        with patch.object(telemetry, 'connect', return_value=conn):
            self.assertEqual(b''.join(telemetry.request('/metrics', [('extra', 'a b')],
                             method='GET', bearer='test-only')), b'OK')
        args = conn.request.call_args.args
        self.assertEqual(args[:3], ('GET', '/metrics?extra=a+b', None))
        self.assertEqual(args[3]['Authorization'], 'Bearer test-only')
        conn.close.assert_called_once()

    def test_redirect_not_followed_and_error_body_not_read(self):
        conn = MagicMock()
        conn.getresponse.return_value.status = 302
        with patch.object(telemetry, 'connect', return_value=conn):
            with self.assertRaisesRegex(ValueError, 'HTTP 302'):
                list(telemetry.request('/select/logsql/query', bearer='test-only'))
        conn.request.assert_called_once()
        conn.getresponse.return_value.read1.assert_not_called()
        conn.close.assert_called_once()
