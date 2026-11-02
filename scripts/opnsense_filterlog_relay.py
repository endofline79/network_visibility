#!/usr/bin/env python3
"""Add, inspect, or remove the filterlog-only OPNsense syslog destination.

Separate from opnsense_forwarding.py, which owns the all-programs :514 target
(ad8bb8eb-...). This helper only creates/deletes one destination:
TCP/IPv4, RFC5424, 192.168.5.230:1515, program filterlog -> filterlog-relay.

Run through Phase so API credentials stay in the process environment. TLS is
verified against the pinned Home Management CA 2026 (OPNSENSE_CA_FILE).
Output never includes credentials or log bodies.
"""

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import opnsense_forwarding as fw  # noqa: E402  (shared api(), tls pin, fingerprint)

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "opnsense-filterlog-relay.json"
FIELDS = fw.FIELDS
DESIRED = {"enabled": "1", "transport": "tcp4", "program": "filterlog",
           "level": "", "facility": "", "hostname": "192.168.5.230",
           "certificate": "", "port": "1515", "rfc5424": "1",
           "description": "AI-02 filterlog-relay"}


def destinations():
    rows = fw.api("/api/syslog/settings/search_destinations?rowCount=-1").get("rows", [])
    return [{k: str(r.get(k, "")) for k in ("uuid",) + FIELDS} for r in rows]


def read(uuid):
    value = fw.api("/api/syslog/settings/get_destination/" + uuid)
    d = value.get("destination")
    if not isinstance(d, dict):
        raise RuntimeError("Destination not found; stopped")
    return {k: fw.selected(d.get(k)) for k in FIELDS}, d


def full_fingerprint():
    # Fingerprint with no destination removed: reuse helper by removing the
    # long-standing :514 target, which this helper never edits.
    return fw.protected_fingerprint()


def reconfigure():
    r = fw.api("/api/syslog/service/reconfigure", {})
    if r.get("status") not in ("ok", "OK"):
        raise RuntimeError("Syslog reconfigure did not return OK; inspect state")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("inspect", "apply", "rollback"))
    a = p.parse_args()
    rows = destinations()
    relay = [r for r in rows if r["hostname"] == DESIRED["hostname"] and r["port"] == DESIRED["port"]]

    if a.action == "inspect":
        _, raw = read(fw.TARGET)
        prog = raw.get("program") if isinstance(raw.get("program"), dict) else {}
        print(json.dumps({"destinations": rows,
                          "filterlog_program_option": "filterlog" in prog,
                          "program_option_count": len(prog),
                          "service": fw.api("/api/syslog/service/status")}, indent=2))
        return

    if a.action == "apply":
        if relay:
            raise RuntimeError("A 192.168.5.230:1515 destination already exists; inspect first")
        if STATE.exists():
            raise RuntimeError("Rollback state already exists; inspect first")
        _, raw = read(fw.TARGET)
        if not (isinstance(raw.get("program"), dict) and "filterlog" in raw["program"]):
            raise RuntimeError("filterlog is not a valid program option; stopped")
        before = full_fingerprint()
        r = fw.api("/api/syslog/settings/add_destination", {"destination": DESIRED})
        uuid = r.get("uuid")
        if r.get("result") != "saved" or not uuid:
            raise RuntimeError("Destination was not saved; response withheld")
        os.umask(0o077)
        STATE.parent.mkdir(mode=0o700, exist_ok=True)
        with STATE.open("x") as out:
            json.dump({"uuid": uuid, "after": DESIRED, "pre_add_sha256": before,
                       "created_at": datetime.now(timezone.utc).isoformat()}, out, indent=2)
        print("Destination added:", uuid, "; reconfiguring syslog only.")
        reconfigure()
        got, _ = read(uuid)
        if got != DESIRED:
            raise RuntimeError("Readback differs from desired settings: " +
                               json.dumps({k: got[k] for k in FIELDS if got[k] != DESIRED[k]}))
        # before: config minus :514 target; after: minus :514 target and new node.
        after = _fingerprint_excluding(uuid)
        if after != before:
            raise RuntimeError("Configuration outside the new destination changed; inspect")
        print("PASS: new destination readback matches; rest of config unchanged (save/revision metadata excluded).")
    else:
        state = json.loads(STATE.read_text())
        uuid = state["uuid"]
        got, _ = read(uuid)
        if got != DESIRED:
            raise RuntimeError("Relay destination has newer changes; refusing to delete")
        r = fw.api("/api/syslog/settings/del_destination/" + uuid, {})
        if r.get("result") != "deleted":
            raise RuntimeError("Delete not confirmed; response withheld")
        reconfigure()
        STATE.rename(STATE.with_suffix(".rolledback.json"))
        print("Relay destination removed:", uuid)
    print("Service:", json.dumps(fw.api("/api/syslog/service/status")))


def _fingerprint_excluding(extra_uuid):
    """Fingerprint config with both the :514 target and extra_uuid removed."""
    import hashlib
    import subprocess
    import xml.etree.ElementTree as ET
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
    for uuid in (fw.TARGET, extra_uuid):
        m = [n for n in parent if n.get("uuid") == uuid]
        if len(m) != 1:
            raise RuntimeError("Unexpected destination count in configuration")
        parent.remove(m[0])
    root.find("OPNsense/Syslog").attrib.pop("persisted_at", None)
    for rev in root.findall("revision"):
        root.remove(rev)

    def normalized(node):
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(),
                tuple(sorted(normalized(c) for c in node)))
    return hashlib.sha256(json.dumps(normalized(root)).encode()).hexdigest()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError) as error:
        raise SystemExit(str(error)) from None
