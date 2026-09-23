#!/usr/bin/env python3
"""Apply the approved single-host UniFi syslog allowance, or disable it.

Run with the existing Phase /opnsense environment. Never exports plaintext
configuration, credentials, or API error bodies. No rule deletion is implemented.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from opnsense_forwarding import api, selected

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state/unifi-syslog-rule-applied.json"
BLOCK_ID = "ac8317c3-b436-4b15-80f8-0f4863c30974"
SECRET = "OPNSENSE_RECOVERY_PASSPHRASE_20260913"
EXPECTED = {
    "enabled": "1", "sequence": "350", "action": "pass", "quick": "1",
    "interface": "opt2", "direction": "in", "ipprotocol": "inet", "protocol": "UDP",
    "source_net": "10.10.20.50", "source_not": "0", "source_port": "",
    "destination_net": "192.168.5.230", "destination_not": "0", "destination_port": "514",
    "gateway": "", "log": "1", "statetype": "keep",
    "description": "INFRA allow UniFi controller syslog to AI-02",
}


def ssh(command):
    result = subprocess.run([
        "ssh", "-F", str(Path.home() / ".ssh/config"), "-i", str(Path.home() / ".ssh/id_ed25519"),
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=yes", "codex@192.168.5.1", command,
    ], capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError("Firewall SSH command failed; output suppressed")
    return result.stdout


def config():
    raw = ssh("sudo -n cat /conf/config.xml")
    root = ET.fromstring(raw)
    if root.tag != "opnsense":
        raise RuntimeError("Unexpected firewall configuration")
    return raw, root


def protected(root, exclude=None):
    # Only the new rule and normal model-save metadata may differ.
    root = ET.fromstring(ET.tostring(root))
    if exclude:
        matches = [node for node in root.iter() if node.get("uuid") == exclude]
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one new rule")
        parent = next(node for node in root.iter() if matches[0] in list(node))
        parent.remove(matches[0])
    for node in root.iter():
        if node.tag == "Filter":
            node.attrib.pop("persisted_at", None)
    for revision in root.findall("revision"):
        root.remove(revision)

    def normalized(node):
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(),
                tuple(normalized(child) for child in node))

    return hashlib.sha256(json.dumps(normalized(root)).encode()).hexdigest()


def preflight(root):
    block = next((n for n in root.iter() if n.get("uuid") == BLOCK_ID), None)
    if block is None or any(block.findtext(k) != v for k, v in {
        "enabled": "1", "sequence": "400", "action": "block", "quick": "1",
        "interface": "opt2", "direction": "in", "source_net": "opt2", "destination_net": "lan",
    }.items()):
        raise RuntimeError("Blocking rule changed; inspect before applying")
    parent = next(n for n in root.iter() if block in list(n))
    for rule in parent:
        if rule.findtext("description") == EXPECTED["description"]:
            raise RuntimeError("A rule with this description already exists; inspect instead of adding")
        if rule.findtext("interface") == "opt2" and rule.findtext("sequence") == "350":
            raise RuntimeError("Sequence 350 is occupied; inspect before applying")
    if root.findtext("interfaces/opt2/if") != "bridge0":
        raise RuntimeError("INFRA interface changed; inspect before applying")


def crypt(secret, args, data):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, secret.encode() + b"\n")
        os.close(write_fd)
        result = subprocess.run([
            "gpg", "--batch", "--pinentry-mode", "loopback", "--no-symkey-cache",
            "--passphrase-fd", str(read_fd), *args,
        ], input=data, capture_output=True, pass_fds=(read_fd,), timeout=45,
            env={k: v for k, v in os.environ.items() if not k.startswith("OPNSENSE_")})
        if result.returncode:
            raise RuntimeError("Encrypted checkpoint operation failed; output suppressed")
        return result.stdout
    finally:
        os.close(read_fd)


def checkpoint(raw):
    secret = os.environ.get(SECRET)
    if not secret:
        raise RuntimeError("Recovery passphrase is unavailable; no changes made")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "state" / f"opnsense-{stamp}-before-unifi-syslog.xml.gpg"
    encrypted = crypt(secret, ["--symmetric", "--cipher-algo", "AES256", "--s2k-mode", "3", "--s2k-count", "65011712"], raw)
    with path.open("xb") as output:
        output.write(encrypted)
        output.flush()
        os.fsync(output.fileno())
    if crypt(secret, ["--decrypt"], encrypted) != raw:
        raise RuntimeError("Encrypted checkpoint verification failed")
    return str(path)


def save_state(state, first=False):
    with STATE.open("x" if first else "w") as output:
        json.dump(state, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def read_rule(rule_id, enabled="1"):
    response = api("/api/firewall/filter/get_rule/" + rule_id)
    row = response.get("rule", {})
    actual = {k: selected(row.get(k)) for k in EXPECTED}
    if actual != {**EXPECTED, "enabled": enabled}:
        raise RuntimeError("Rule readback differs from the approved fields")
    return actual


def reload_filter():
    response = api("/api/firewall/filter/apply", {})
    if str(response.get("status", "")).strip().lower() != "ok":
        raise RuntimeError("Filter reload did not return OK; inspect runtime state")


def verify(state, enabled="1"):
    read_rule(state["uuid"], enabled)
    _, current = config()
    if protected(current, state["uuid"]) != state["protected_sha256"]:
        raise RuntimeError("Configuration outside the new rule changed; inspect before further edits")
    runtime = ssh("sudo -n pfctl -sr").decode()
    matches = [line for line in runtime.splitlines() if state["uuid"] in line]
    if enabled == "1":
        # pfctl renders UDP/514 by its /etc/services name, "syslog".
        pattern = (r"pass in log quick on bridge0 inet proto udp from 10\.10\.20\.50 "
                   r"to 192\.168\.5\.230 port = (?:514|syslog) keep state\b")
        if len(matches) != 1 or not re.search(pattern, matches[0]):
            raise RuntimeError("Active filter does not contain the exact intended rule")
        block_lines = [i for i, line in enumerate(runtime.splitlines()) if BLOCK_ID in line]
        new_line = next(i for i, line in enumerate(runtime.splitlines()) if state["uuid"] in line)
        if len(block_lines) != 1 or new_line >= block_lines[0]:
            raise RuntimeError("New rule is not before the active INFRA block")
    elif matches:
        raise RuntimeError("Disabled rule is still present in the active filter")
    print(json.dumps({"uuid": state["uuid"], "enabled": enabled, "protected_config_unchanged": True, "active_rule": matches}))


def disable(state):
    # Reject edits to a changed rule; only enabled may be toggled for rollback.
    read_rule(state["uuid"])
    response = api("/api/firewall/filter/set_rule/" + state["uuid"], {"rule": {"enabled": "0"}})
    if response.get("result") != "saved":
        raise RuntimeError("Could not disable the new rule; inspect state")
    reload_filter()
    state["status"] = "disabled"
    save_state(state)
    verify(state, "0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "apply", "verify", "disable"])
    action = parser.parse_args().action
    os.umask(0o077)
    STATE.parent.mkdir(mode=0o700, exist_ok=True)
    if action in ("verify", "disable"):
        state = json.loads(STATE.read_text())
        if action == "verify":
            verify(state, "0" if state["status"] == "disabled" else "1")
            if state["status"] != "disabled":
                state["status"] = "applied_verified"
                save_state(state)
        else:
            disable(state)
        return
    raw, root = config()
    preflight(root)
    if action == "check":
        print(json.dumps({"preflight": "passed", "proposed_rule": EXPECTED}))
        return
    if STATE.exists():
        raise RuntimeError("Prior operation state exists; inspect it before retrying")
    backup = checkpoint(raw)
    digest = protected(root)
    if protected(config()[1]) != digest:
        raise RuntimeError("Firewall changed during backup; no rule added")
    state = {"status": "prepared", "protected_sha256": digest, "config_sha256": hashlib.sha256(raw).hexdigest(),
             "backup": backup, "rule": EXPECTED, "created_at": datetime.now(timezone.utc).isoformat()}
    save_state(state, first=True)
    response = api("/api/firewall/filter/add_rule", {"rule": EXPECTED})
    if response.get("result") != "saved" or not response.get("uuid"):
        raise RuntimeError("Rule creation was not confirmed; inspect before retrying")
    state.update(uuid=response["uuid"], status="saved_not_applied")
    save_state(state)
    try:
        read_rule(state["uuid"])
        if protected(config()[1], state["uuid"]) != digest:
            raise RuntimeError("Configuration outside the new rule changed; filter was not reloaded")
        reload_filter()
        verify(state)
    except Exception:
        # Preserve exact state for inspection/scoped disable; never replay an add.
        state["status"] = "verification_failed"
        save_state(state)
        raise
    state["status"] = "applied_verified"
    save_state(state)
    print("Encrypted checkpoint and rollback state:", STATE)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        # RuntimeError messages are fixed/credential-safe, all other errors are redacted.
        raise SystemExit(str(error) if isinstance(error, RuntimeError) else type(error).__name__ + "; details suppressed") from None
