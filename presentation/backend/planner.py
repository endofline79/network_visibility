"""Planner settings for a later `/api/ask`. This module does not call a model.

The pinned llama-swap alias is `visibility-planner` (qwen38-27b-ud-q8-k-xl-llama
on AI-02). That model is started with `--parallel 1`, so this process queues
callers on one in-process slot. Run uvicorn with a single worker; extra workers
would each open their own slot. Cloud LLM fallback is not configured.
"""

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


PINNED_MODEL = 'visibility-planner'
DEFAULT_BASE = 'http://172.17.0.1:8081/v1'
LOCAL_HOSTS = {'172.17.0.1', '127.0.0.1', 'localhost'}
TOKEN_FILE = '/run/visibility/planner-token'
# One decode slot. Do not raise this without changing llama-swap --parallel.
PLANNER_PARALLEL = 1
_SLOT = threading.BoundedSemaphore(PLANNER_PARALLEL)


def local_base(url):
    """Accept only the on-host OpenAI-compatible llama-swap listener."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.scheme != 'http' or parts.hostname not in LOCAL_HOSTS or parts.port != 8081
            or parts.username or parts.password or parts.query or parts.fragment):
        return None
    if parts.path.rstrip('/') != '/v1':
        return None
    return f'http://{parts.hostname}:8081/v1'


def _model(value):
    if not isinstance(value, str) or not value or len(value) > 80:
        return None
    if any(not (char.isalnum() or char in '._-') for char in value):
        return None
    return value


def token_configured(path=None):
    file = Path(path or os.getenv('PLANNER_TOKEN_FILE', TOKEN_FILE))
    try:
        data = file.read_bytes()
    except OSError:
        return False
    text = data.strip()
    if not text or len(data) > 8192 or any(byte in b' \t\r\n' for byte in text):
        return False
    return True


def status():
    """Non-secret planner pin. Never includes the bearer token or a remote URL."""
    requested_model = _model(os.getenv('PLANNER_MODEL', PINNED_MODEL))
    base = local_base(os.getenv('LLM_BASE_URL', DEFAULT_BASE))
    pinned = requested_model == PINNED_MODEL and base is not None
    body = {
        'configured': pinned,
        'model': PINNED_MODEL if requested_model == PINNED_MODEL else None,
        'pinned_model': PINNED_MODEL,
        'base_url': base,
        'parallel': PLANNER_PARALLEL,
        'queued': True,
        'cloud_fallback': False,
        'token_configured': token_configured(),
        'token_file': os.getenv('PLANNER_TOKEN_FILE', TOKEN_FILE),
    }
    if not pinned:
        body['note'] = 'Planner stays on the local visibility-planner alias. Cloud fallback is disabled.'
    return body


@contextmanager
def planner_call():
    """Hold the single planner slot. The caller supplies the LLM request later."""
    _SLOT.acquire()
    try:
        yield
    finally:
        _SLOT.release()
