"""Add an insert-only vmauth user without printing or rotating the operator token.

The token is read from stdin. Existing operator settings are preserved. If an
alert-inserter entry already exists and differs, the file is left unchanged.
"""

import json
import os
import re
import sys
from pathlib import Path

NAME = "alert-inserter"
INSERT_PATHS = ["^/insert/jsonline$", "^/insert/.*"]


def build_user(token):
    return {
        "name": NAME,
        "bearer_token": token,
        "url_map": [{
            "src_paths": INSERT_PATHS,
            "url_prefix": "http://logs:9428",
            "headers": ["Authorization:"],
        }],
    }


def install(path, token):
    file = Path(path)
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]{32,8192}", token):
        raise SystemExit("Missing or invalid token; nothing installed.")
    raw = file.read_text(encoding="utf-8") if file.exists() else ""
    try:
        config = json.loads(raw) if raw else {"users": []}
    except json.JSONDecodeError:
        raise SystemExit("Auth config is not the expected JSON object; nothing changed.")
    users = config.get("users")
    if not isinstance(users, list):
        raise SystemExit("Auth config has no user list; nothing changed.")
    operator = next((user for user in users if user.get("name") == "operator"), None)
    if operator is None:
        raise SystemExit("Operator user is missing; refusing to edit auth config.")
    if any(user.get("bearer_token") == token and user.get("name") != NAME for user in users):
        raise SystemExit("Refusing to reuse an existing token for alert-inserter.")
    proposed = build_user(token)
    current = next((user for user in users if user.get("name") == NAME), None)
    if current == proposed:
        return "matches"
    if current is not None:
        raise SystemExit("alert-inserter already exists and differs; refusing to rotate it.")
    before = json.dumps(operator, sort_keys=True)
    users.append(proposed)
    after = json.dumps(next(user for user in users if user.get("name") == "operator"), sort_keys=True)
    if before != after:
        raise SystemExit("Operator user would change; nothing written.")
    file.parent.mkdir(mode=0o700, exist_ok=True)
    temporary = file.with_suffix(".tmp")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as out:
        json.dump(config, out)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, file)
    os.chmod(file, 0o600)
    return "installed"


def main():
    root = Path(os.environ.get(
        "TELEMETRY_API_SECRETS_DIR", "/home/klab/.local/share/visibility/telemetry-api"))
    token = sys.stdin.read(8193).strip()
    result = install(root / "auth.yaml", token)
    if result == "matches":
        print("Existing alert-inserter config matches; operator user unchanged.")
    else:
        print("Insert-only alert-inserter user installed; operator user unchanged.")


if __name__ == "__main__":
    main()
