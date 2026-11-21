"""Load the declarative alert rules. Full-line // comments are allowed."""

import json
from pathlib import Path


REQUIRED = (
    "version",
    "interval_seconds",
    "hostname",
    "console_url",
    "warning_notify_after_seconds",
    "renotify_seconds",
    "webhook_max_per_hour",
    "webhook_timeout_seconds",
    "webhook_backoff_seconds",
    "webhook_header",
    "webhook_header_prefix",
    "heartbeat_stale_seconds",
    "sources",
    "staleness",
    "disk",
    "certificates",
    "rules",
)


def loads(text):
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("//"):
            continue
        lines.append(line)
    data = json.loads("\n".join(lines))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Alert rules must be a version 1 object")
    missing = [key for key in REQUIRED if key not in data]
    if missing:
        raise ValueError("Alert rules missing: " + ", ".join(missing))
    header = str(data["webhook_header"])
    if not header or any(c in header for c in "\r\n:"):
        raise ValueError("Webhook header name is invalid")
    prefix = str(data["webhook_header_prefix"])
    if any(c in prefix for c in "\r\n"):
        raise ValueError("Webhook header prefix is invalid")
    return data


def load(path):
    file = Path(path)
    try:
        return loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Cannot load alert rules from {file.name}: {exc}") from None
