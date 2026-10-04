#!/usr/bin/env python3
"""Scoped, reversible NetFlow configuration. Run using Phase /opnsense.

Before apply, run hom-network/scripts/opnsense_encrypted_backup.py.
No filter, routing, bridge, NAT, DHCP, syslog or switch settings are changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from opnsense_forwarding import api, selected

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "opnsense-netflow.json"
ORIGINAL = {"capture": {"interfaces": "", "egress_only": "", "version": "v9", "targets": ""},
            "collect": {"enable": "0"}, "activeTimeout": "1800", "inactiveTimeout": "15"}
DESIRED = {"capture": {"interfaces": "lan,opt1,opt2,wan", "egress_only": "lan,opt1,opt2,wan",
                       "version": "v9", "targets": "192.168.5.230:2056"},
           "collect": {"enable": "0"}, "activeTimeout": "60", "inactiveTimeout": "15"}


def config():
    raw = api('/api/diagnostics/netflow/getconfig')['netflow']
    capture = {k: selected(raw['capture'][k]) for k in ORIGINAL['capture']}
    for key in ('interfaces', 'egress_only'):
        capture[key] = ','.join(sorted(filter(None, capture[key].split(','))))
    return {"capture": capture, "collect": {"enable": str(raw['collect']['enable'])},
            "activeTimeout": str(raw['activeTimeout']), "inactiveTimeout": str(raw['inactiveTimeout'])}


def fingerprint():
    result = subprocess.run(['ssh', '-F', '/dev/null', '-i', str(Path.home()/'.ssh/id_ed25519'),
        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
        'codex@192.168.5.1', 'sudo -n cat /conf/config.xml'], capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError('Cannot verify protected configuration; diagnostics suppressed')
    root = ET.fromstring(result.stdout)
    parent = root.find('OPNsense')
    target = parent.find('Netflow')
    if target is not None:
        parent.remove(target)
    for revision in root.findall('revision'):
        root.remove(revision)
    def normalized(n):
        return n.tag, sorted(n.attrib.items()), (n.text or '').strip(), sorted(normalized(c) for c in n)
    return hashlib.sha256(json.dumps(normalized(root)).encode()).hexdigest()


def write(value):
    if api('/api/diagnostics/netflow/setconfig', {"netflow": value}).get('result') != 'saved':
        raise RuntimeError('NetFlow save rejected; response suppressed')
    if api('/api/diagnostics/netflow/reconfigure', {}).get('status') != 'ok':
        raise RuntimeError('NetFlow reconfigure failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'apply', 'refresh', 'rollback'])
    args = parser.parse_args()
    current = config()
    if args.action == 'inspect':
        print(json.dumps({"config": current, "status": api('/api/diagnostics/netflow/status')}))
        return
    if args.action == 'apply':
        if current != ORIGINAL or STATE.exists():
            raise RuntimeError('Baseline changed or rollback checkpoint exists; stopped')
        protected = fingerprint()
        os.umask(0o077)
        STATE.parent.mkdir(exist_ok=True)
        with STATE.open('x') as target:
            json.dump({"before": current, "after": DESIRED, "protected": protected}, target)
        write(DESIRED)
        if config() != DESIRED or fingerprint() != protected:
            raise RuntimeError('Postchange verification failed; inspect before proceeding')
    else:
        checkpoint = json.loads(STATE.read_text())
        if current != checkpoint['after'] or fingerprint() != checkpoint['protected']:
            raise RuntimeError('Configuration drift since checkpoint; stopped')
        if args.action == 'refresh':
            if api('/api/diagnostics/netflow/reconfigure', {}).get('status') != 'ok':
                raise RuntimeError('Template refresh failed')
            expected = checkpoint['after']
        else:
            write(checkpoint['before'])
            expected = checkpoint['before']
        if config() != expected or fingerprint() != checkpoint['protected']:
            raise RuntimeError('Rollback verification failed')
    print(json.dumps({"config": config(), "status": api('/api/diagnostics/netflow/status'),
                      "protected_configuration_unchanged": True}))


if __name__ == '__main__':
    main()
