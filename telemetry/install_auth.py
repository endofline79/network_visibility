"""Read the Phase token on stdin; create private backend config without logging it."""
import json
import os
from pathlib import Path
import re
import sys

root = Path('/home/klab/.local/share/visibility/telemetry-api')
root.mkdir(mode=0o700, exist_ok=True)
token = sys.stdin.read(8193).strip()
if not re.fullmatch(r'[A-Za-z0-9_+/=-]{32,8192}', token):
    raise SystemExit('Missing or invalid token; nothing installed.')
config = {'users': [{'name': 'operator', 'bearer_token': token,
                    'url_prefix': 'http://logs:9428/', 'headers': ['Authorization:']}]}
path = root / 'auth.yaml'
if path.exists():
    if json.loads(path.read_text()) != config:
        raise SystemExit('Existing auth config differs; refusing to rotate or overwrite.')
    print('Existing auth config matches Phase.')
else:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
        json.dump(config, out)
        out.flush()
        os.fsync(out.fileno())
    print('Phase-managed token installed privately; no endpoint restrictions configured.')
