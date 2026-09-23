#!/usr/bin/env python3
"""Inspect, connect, or restore this lab's existing OPNsense syslog target.

Run through Phase so API credentials stay in the short-lived process environment.
Only the known target is modified. Output never includes credentials or log bodies.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "opnsense-forwarding.json"
TARGET = "ad8bb8eb-1abc-4a3d-9d2c-8f36577da137"
FIELDS = ("enabled", "transport", "program", "level", "facility", "hostname",
          "certificate", "port", "rfc5424", "description")
ORIGINAL = dict(zip(FIELDS, ("0", "tcp4", "", "", "", "192.168.5.230", "",
                             "1514", "0", "telemetry-alloy")))
CHANGES = {"enabled": "1", "port": "514", "rfc5424": "1",
           "description": "AI-02 Visibility"}
DESIRED = {**ORIGINAL, **CHANGES}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Unexpected API redirect; stopped")


def api(path, body=None):
    base = os.environ["OPNSENSE_URL"].rstrip("/")
    target = urllib.parse.urlparse(base)
    if (target.scheme != "https" or target.hostname != "192.168.5.1"
            or target.port not in (None, 443) or target.path or target.query
            or target.fragment or target.username or target.password):
        raise RuntimeError("Unexpected firewall API URL; stopped")
    credentials = os.environ["OPNSENSE_API_KEY"] + ":" + os.environ["OPNSENSE_API_SECRET"]
    authorization = base64.b64encode(credentials.encode()).decode()
    headers = {"Authorization": "Basic " + authorization}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base + path, data=None if body is None else json.dumps(body).encode(),
        headers=headers,
        method="GET" if body is None else "POST",
    )
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"API request failed: {path}, HTTP {error.code}; body suppressed") from None
    except urllib.error.URLError:
        raise RuntimeError(f"API connection failed: {path}; details suppressed") from None


def selected(value):
    if isinstance(value, dict):
        return ",".join(key for key, option in value.items()
                        if isinstance(option, dict) and str(option.get("selected")) in ("1", "True"))
    if value is None:
        return ""
    return str(value)


def destination():
    value = api("/api/syslog/settings/get_destination/" + TARGET)
    if not isinstance(value.get("destination"), dict):
        raise RuntimeError("Existing destination not found; stopped")
    return {key: selected(value["destination"].get(key)) for key in FIELDS}


def protected_fingerprint():
    # Read sensitive XML only into memory; never print or persist the full config.
    command = ["ssh", "-F", str(Path.home() / ".ssh/config"),
               "-i", str(Path.home() / ".ssh/id_ed25519"),
               "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=yes",
               "codex@192.168.5.1", "sudo -n cat /conf/config.xml"]
    result = subprocess.run(command, capture_output=True, timeout=15)
    if result.returncode:
        raise RuntimeError("SSH configuration read failed; output suppressed")
    root = ET.fromstring(result.stdout)
    parent = root.find("OPNsense/Syslog/destinations")
    matches = [] if parent is None else [n for n in parent if n.get("uuid") == TARGET]
    if len(matches) != 1:
        raise RuntimeError("Unexpected target count in configuration")
    parent.remove(matches[0])
    # The model updates this timestamp on every save, including a rollback.
    root.find("OPNsense/Syslog").attrib.pop("persisted_at", None)
    for revision in root.findall("revision"):
        root.remove(revision)

    def normalized(node):
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(),
                tuple(sorted(normalized(child) for child in node)))

    return hashlib.sha256(json.dumps(normalized(root)).encode()).hexdigest()


def write_target(values):
    result = api("/api/syslog/settings/set_destination/" + TARGET, {"destination": values})
    if result.get("result") != "saved":
        raise RuntimeError("Destination was not saved; response withheld")
    print("Destination saved; reconfiguring syslog only.")
    result = api("/api/syslog/service/reconfigure", {})
    if result.get("status") not in ("ok", "OK"):
        raise RuntimeError("Syslog reconfigure did not return OK; inspect state before retrying")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "apply", "rollback"))
    args = parser.parse_args()
    current = destination()
    if args.action == "inspect":
        print(json.dumps({"uuid": TARGET, "destination": current,
                          "service": api("/api/syslog/service/status")}, indent=2))
        return

    if args.action == "apply":
        if current != ORIGINAL:
            raise RuntimeError("Target differs from the reviewed original; inspect before changing it")
        if STATE.exists():
            raise RuntimeError("Rollback state already exists; inspect the previous operation first")
        fingerprint = protected_fingerprint()
        os.umask(0o077)
        STATE.parent.mkdir(mode=0o700, exist_ok=True)
        state = {"uuid": TARGET, "before": current, "after": DESIRED,
                 "protected_sha256": fingerprint,
                 "created_at": datetime.now(timezone.utc).isoformat()}
        with STATE.open("x") as output:
            json.dump(state, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        write_target(CHANGES)
        expected = DESIRED
    else:
        state = json.loads(STATE.read_text())
        if state.get("uuid") != TARGET or state.get("before") != ORIGINAL or state.get("after") != DESIRED:
            raise RuntimeError("Unexpected rollback state; stopped")
        if current not in (DESIRED, ORIGINAL):
            raise RuntimeError("Target has newer changes; refusing to overwrite them")
        fingerprint = protected_fingerprint()
        write_target({key: ORIGINAL[key] for key in CHANGES})
        expected = ORIGINAL

    if destination() != expected:
        raise RuntimeError("Destination readback differs from the expected settings")
    if protected_fingerprint() != fingerprint:
        raise RuntimeError("Configuration outside this destination changed; inspect before further action")
    print("PASS: destination readback matches; other config is unchanged except save/revision metadata.")
    print("Service:", json.dumps(api("/api/syslog/service/status")))
    print("Rollback state:", STATE)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError) as error:
        raise SystemExit(str(error)) from None
