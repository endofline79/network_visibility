#!/usr/bin/env python3
"""Inspect, apply, or roll back the :514 filterlog trim on OPNsense.

OPNsense's :514 destination (ad8bb8eb-...) previously forwarded every program,
causing filterlog to be stored twice once :1515 (filterlog-relay) was enabled.
Because OPNsense's `program` dropdown omits core system streams (`/usr/sbin/cron`,
`syslog-ng`, `sshd-session`, `sudo`, `dhclient`), trimming via `program` would
drop non-filterlog logs. Instead, this helper sets `facility` on :514 to all 22
non-`local0` facilities (OPNsense filterlog logs exclusively on `local0`), keeping
every other program flowing to :514 while filterlog flows solely via :1515.

Run through Phase so API credentials stay in the short-lived process environment.
Only the known :514 target is modified. Output never includes credentials or log
bodies.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import opnsense_filterlog_relay as relay  # noqa: E402
import opnsense_forwarding as fw  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "opnsense-trim-514.json"
EXCLUDED_FACILITY = "local0"
NON_FILTERLOG_FACILITIES = (
    "kern,user,mail,daemon,auth,syslog,lpr,news,uucp,cron,authpriv,"
    "ftp,ntp,security,console,local1,local2,local3,local4,local5,local6,local7"
)
UNTRIMMED = dict(fw.DESIRED)
TRIMMED = {**fw.DESIRED, "facility": NON_FILTERLOG_FACILITIES}


def _facility_set(value):
    return {item.strip() for item in value.split(",") if item.strip()}


def _has_active_relay(rows):
    return any(
        r.get("enabled") == "1"
        and r.get("hostname") == relay.DESIRED["hostname"]
        and r.get("port") == relay.DESIRED["port"]
        and "filterlog" in _facility_set(r.get("program", ""))
        for r in rows
    )


def _matches_target(actual, expected):
    for key in fw.FIELDS:
        if key == "facility":
            if _facility_set(actual.get(key, "")) != _facility_set(expected.get(key, "")):
                return False
        elif actual.get(key, "") != expected.get(key, ""):
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "apply", "rollback"))
    args = parser.parse_args()

    current, raw = relay.read(fw.TARGET)
    rows = relay.destinations()
    relay_active = _has_active_relay(rows)
    facility_opts = raw.get("facility") if isinstance(raw.get("facility"), dict) else {}

    if args.action == "inspect":
        print(json.dumps({
            "uuid": fw.TARGET,
            "destination": current,
            "trimmed": _matches_target(current, TRIMMED),
            "relay_active": relay_active,
            "excluded_facility": EXCLUDED_FACILITY,
            "facility_option_count": len(facility_opts),
            "service": fw.api("/api/syslog/service/status"),
        }, indent=2))
        return

    if args.action == "apply":
        if not relay_active:
            raise RuntimeError("Active filterlog-relay (:1515) destination not found; refusing to trim :514")
        if not _matches_target(current, UNTRIMMED):
            raise RuntimeError("Target differs from expected untrimmed :514 settings; inspect before changing it")
        if STATE.exists():
            raise RuntimeError("Rollback state already exists; inspect the previous operation first")
        wanted = _facility_set(NON_FILTERLOG_FACILITIES)
        available = set(facility_opts.keys())
        if not wanted.issubset(available) or EXCLUDED_FACILITY not in available:
            raise RuntimeError("OPNsense facility options do not match expected schema; stopped")
        if available - wanted != {EXCLUDED_FACILITY}:
            raise RuntimeError(
                f"Unexpected extra facilities in OPNsense schema: {sorted(available - wanted - {EXCLUDED_FACILITY})}"
            )
        fingerprint = fw.protected_fingerprint()
        os.umask(0o077)
        STATE.parent.mkdir(mode=0o700, exist_ok=True)
        state = {
            "uuid": fw.TARGET,
            "before": current,
            "after": TRIMMED,
            "excluded_facility": EXCLUDED_FACILITY,
            "protected_sha256": fingerprint,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with STATE.open("x") as output:
            json.dump(state, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        fw.write_target({"facility": NON_FILTERLOG_FACILITIES})
        expected = TRIMMED
    else:
        state = json.loads(STATE.read_text())
        if state.get("uuid") != fw.TARGET or not _matches_target(state.get("before", {}), UNTRIMMED):
            raise RuntimeError("Unexpected rollback state; stopped")
        if not (_matches_target(current, TRIMMED) or _matches_target(current, UNTRIMMED)):
            raise RuntimeError("Target has newer changes; refusing to overwrite them")
        fingerprint = fw.protected_fingerprint()
        fw.write_target({"facility": ""})
        expected = UNTRIMMED

    readback, _ = relay.read(fw.TARGET)
    if not _matches_target(readback, expected):
        raise RuntimeError("Destination readback differs from expected settings")
    if fw.protected_fingerprint() != fingerprint:
        raise RuntimeError("Configuration outside this destination changed; inspect before further action")
    if args.action == "rollback":
        STATE.rename(STATE.with_suffix(".rolledback.json"))
    print("PASS: destination readback matches; other config is unchanged except save/revision metadata.")
    print("Service:", json.dumps(fw.api("/api/syslog/service/status")))
    print("Rollback state:", STATE)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError) as error:
        raise SystemExit(str(error)) from None
