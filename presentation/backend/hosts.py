"""In-memory host-name cache for a later planner.

Merge priority, highest first:
1. iot-hosts.yaml (hand overrides, keyed by MAC and IP)
2. UniFi snapshot clients (MAC is the identity; IP is the latest sample)
3. Pi-hole client_name (IP only)

There is no OPNsense DHCP or ARP feed. Wired clients that UniFi does not see
stay unnamed unless Pi-hole has a client_name or the allowlist lists them.
Refresh is about five minutes. Queries are fixed strings; allowlist values are
validated and are not interpolated into LogsQL.
"""

import copy
import ipaddress
import os
import re
import threading
import time
from pathlib import Path


DHCP_GAP = (
    'No OPNsense DHCP or ARP feed. Wired clients that UniFi does not see '
    'stay unnamed unless Pi-hole has a client_name or iot-hosts.yaml lists them.'
)
UNIFI_CLIENTS = (
    '_time:15m app_name:=unifi-snapshot entity_kind:=client'
    ' | stats by (mac) any(ip) ip, any(name) name, max(_time) seen'
    ' | limit 501'
)
PIHOLE_CLIENTS = (
    '_time:1h app_name:=pihole-dns client_name:!=""'
    ' | stats by (client_ip) any(client_name) name, max(_time) seen'
    ' | limit 501'
)
MAX_HOSTS = 16
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,31}$')
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._'()-]{0,79}$")
DNS_RE = re.compile(
    r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$'
)


def refresh_interval(raw=None):
    text = os.getenv('HOST_CACHE_REFRESH_SECONDS', '300') if raw is None else str(raw)
    try:
        value = int(text)
    except (TypeError, ValueError):
        return 300
    if value < 30 or value > 3600:
        return 300
    return value


def normalize_mac(value):
    if not isinstance(value, str):
        return None
    raw = value.strip().lower().replace('-', ':')
    if re.fullmatch(r'[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}', raw):
        raw = raw.replace('.', '')
    if re.fullmatch(r'[0-9a-f]{12}', raw):
        raw = ':'.join(raw[i:i + 2] for i in range(0, 12, 2))
    if re.fullmatch(r'([0-9a-f]{2}:){5}[0-9a-f]{2}', raw):
        return raw
    return None


def normalize_ip(value):
    if not isinstance(value, str):
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def packaged_iot_hosts():
    return Path(__file__).resolve().parents[1] / 'config' / 'iot-hosts.yaml'


def resolve_iot_hosts_path():
    configured = os.getenv('IOT_HOSTS_FILE')
    packaged = packaged_iot_hosts()
    if configured:
        path = Path(configured)
        if path.is_file():
            return path, None
        if packaged.is_file():
            return packaged, 'mounted iot-hosts.yaml is absent; using the packaged empty allowlist'
    if packaged.is_file():
        return packaged, None
    return None, None


def _parse_scalar(value, lineno):
    if value is None:
        raise ValueError(f'line {lineno}: missing value')
    if value.startswith('"'):
        if len(value) < 2 or not value.endswith('"'):
            raise ValueError(f'line {lineno}: bad quotes')
        out = []
        index = 1
        while index < len(value) - 1:
            char = value[index]
            if char == '\\':
                if index + 1 >= len(value) - 1 or value[index + 1] not in '\\"':
                    raise ValueError(f'line {lineno}: bad escape')
                out.append(value[index + 1])
                index += 2
                continue
            if char == '"':
                raise ValueError(f'line {lineno}: bad quotes')
            out.append(char)
            index += 1
        return ''.join(out)
    if value == '' or any(char in value for char in '\\"#') or value != value.strip():
        raise ValueError(f'line {lineno}: unsupported scalar')
    return value


def _split_key(text, lineno):
    if ':' not in text:
        raise ValueError(f'line {lineno}: expected key')
    key, rest = text.split(':', 1)
    if not re.fullmatch(r'[a-z_]+', key):
        raise ValueError(f'line {lineno}: invalid key')
    if rest == '':
        return key, None
    if not rest.startswith(' '):
        raise ValueError(f'line {lineno}: expected space after colon')
    return key, rest[1:]


def parse_iot_hosts(text):
    """Strict subset of YAML. No tags, anchors, or nested surprises."""
    if len(text.encode()) > 65536:
        raise ValueError('iot-hosts.yaml is too large')
    if '\t' in text:
        raise ValueError('tabs are not allowed in iot-hosts.yaml')
    content = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.rstrip()
        if stripped == '' or stripped.lstrip().startswith('#'):
            continue
        if stripped.lstrip() != stripped and not stripped.startswith(('  ', '- ')):
            raise ValueError(f'line {lineno}: unexpected indent')
        content.append((lineno, stripped))
    if not content:
        raise ValueError('iot-hosts.yaml is missing hosts')
    _lineno, first = content[0]
    key, value = _split_key(first, _lineno)
    if key != 'hosts':
        raise ValueError('iot-hosts.yaml must start with hosts')
    if value == '[]':
        if len(content) != 1:
            raise ValueError('unexpected content after hosts')
        return []
    if value is not None:
        raise ValueError('hosts must be a list')
    hosts = []
    current = None
    in_dns = False
    for lineno, line in content[1:]:
        if line.startswith('  - '):
            body = line[4:]
            item_key, item_value = _split_key(body, lineno)
            if item_key != 'id':
                raise ValueError(f'line {lineno}: host must start with id')
            current = {'id': _parse_scalar(item_value, lineno), 'dns_names': []}
            hosts.append(current)
            in_dns = False
            continue
        if line.startswith('      - '):
            if current is None or not in_dns:
                raise ValueError(f'line {lineno}: list item outside dns_names')
            current['dns_names'].append(_parse_scalar(line[8:], lineno))
            continue
        if current is None or not line.startswith('    ') or line.startswith('     '):
            raise ValueError(f'line {lineno}: unexpected content')
        field, field_value = _split_key(line[4:], lineno)
        if field in current and field != 'dns_names':
            raise ValueError(f'line {lineno}: duplicate {field}')
        if field == 'dns_names':
            if field_value is not None:
                raise ValueError(f'line {lineno}: dns_names must be a list')
            in_dns = True
            continue
        in_dns = False
        current[field] = _parse_scalar(field_value, lineno)
    return [_validate_host(host, index) for index, host in enumerate(hosts, 1)]


def _validate_host(host, index):
    if index > MAX_HOSTS:
        raise ValueError(f'iot-hosts.yaml allows at most {MAX_HOSTS} hosts')
    allowed = {'id', 'class', 'name', 'dns_names', 'ip', 'mac', 'notes'}
    extra = set(host) - allowed
    if extra:
        raise ValueError(f'host {index}: unknown field')
    for key in ('id', 'class', 'name'):
        if key not in host:
            raise ValueError(f'host {index}: {key} is required')
    if not ID_RE.fullmatch(host['id']) or not ID_RE.fullmatch(host['class']):
        raise ValueError(f'host {index}: id and class must be short tokens')
    if not NAME_RE.fullmatch(host['name']):
        raise ValueError(f'host {index}: name has unsupported characters')
    dns_names = host.get('dns_names') or []
    if len(dns_names) > 4:
        raise ValueError(f'host {index}: too many dns names')
    cleaned_dns = []
    for name in dns_names:
        lowered = name.lower()
        if len(lowered) > 253 or not DNS_RE.fullmatch(lowered):
            raise ValueError(f'host {index}: dns name is invalid')
        cleaned_dns.append(lowered)
    ip = normalize_ip(host['ip']) if 'ip' in host else None
    if 'ip' in host and ip is None:
        raise ValueError(f'host {index}: ip is invalid')
    mac = normalize_mac(host['mac']) if 'mac' in host else None
    if 'mac' in host and mac is None:
        raise ValueError(f'host {index}: mac is invalid')
    if not ip and not mac:
        raise ValueError(f'host {index}: ip or mac is required')
    notes = host.get('notes')
    if notes is not None and (len(notes) > 200 or not NAME_RE.fullmatch(notes)):
        raise ValueError(f'host {index}: notes have unsupported characters')
    return {
        'id': host['id'],
        'class': host['class'],
        'name': host['name'],
        'dns_names': cleaned_dns,
        'ip': ip,
        'mac': mac,
        'notes': notes,
    }


def _unique(hosts):
    seen_id, seen_mac, seen_ip = set(), set(), set()
    for host in hosts:
        if host['id'] in seen_id:
            raise ValueError('duplicate host id')
        seen_id.add(host['id'])
        if host['mac']:
            if host['mac'] in seen_mac:
                raise ValueError('duplicate host mac')
            seen_mac.add(host['mac'])
        if host['ip']:
            if host['ip'] in seen_ip:
                raise ValueError('duplicate host ip')
            seen_ip.add(host['ip'])
    if len(hosts) > MAX_HOSTS:
        raise ValueError(f'iot-hosts.yaml allows at most {MAX_HOSTS} hosts')
    return hosts


def load_iot_hosts(path):
    if path is None:
        return [], {'state': 'absent', 'count': 0, 'note': 'No iot-hosts.yaml is configured.'}
    try:
        hosts = _unique(parse_iot_hosts(path.read_text(encoding='utf-8')))
    except OSError:
        return [], {'state': 'absent', 'count': 0, 'note': 'iot-hosts.yaml could not be read.'}
    except (UnicodeError, ValueError):
        return [], {
            'state': 'error',
            'count': 0,
            'note': 'iot-hosts.yaml failed validation; overrides withheld.',
            'path': str(path),
        }
    return hosts, {'state': 'ok', 'count': len(hosts), 'path': str(path)}


def _clean_name(value):
    if not isinstance(value, str):
        return None
    name = ' '.join(value.split())
    if not name or len(name) > 120 or any(ord(char) < 32 for char in name):
        return None
    return name


def _clean_seen(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    if any(ord(char) < 32 for char in value):
        return None
    return value


def normalize_unifi(rows):
    if len(rows) > 500:
        return [], 'UniFi client query hit its row cap; names were withheld.'
    found = {}
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        mac = normalize_mac(row.get('mac'))
        if not mac:
            skipped += 1
            continue
        item = {
            'mac': mac,
            'ip': normalize_ip(row.get('ip')),
            'name': _clean_name(row.get('name')),
            'seen': _clean_seen(row.get('seen')),
        }
        previous = found.get(mac)
        if previous and (previous.get('seen') or '') >= (item.get('seen') or ''):
            continue
        found[mac] = item
    note = 'Some UniFi rows had no usable MAC.' if skipped else None
    return list(found.values()), note


def normalize_pihole(rows):
    if len(rows) > 500:
        return [], 'Pi-hole client query hit its row cap; names were withheld.'
    found = {}
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        ip = normalize_ip(row.get('client_ip') or row.get('ip'))
        name = _clean_name(row.get('name') or row.get('client_name'))
        if not ip or not name:
            skipped += 1
            continue
        found[ip] = {'ip': ip, 'name': name, 'seen': _clean_seen(row.get('seen'))}
    note = 'Some Pi-hole rows had no usable name.' if skipped else None
    return list(found.values()), note


def _blank(name, source, mac=None, ip=None, seen=None, identity=None, host_class=None, dns_names=None, notes=None):
    ips = [ip] if ip else []
    return {
        'name': name,
        'source': source,
        'mac': mac,
        'ip': ip,
        'ips': ips,
        'seen': seen,
        'id': identity,
        'class': host_class,
        'dns_names': list(dns_names or []),
        'notes': notes,
    }


def merge_hosts(iot, unifi, pihole):
    """Return (hosts, ambiguous_ips). Higher-priority names win."""
    records = []
    by_mac = {}
    claimed = {}
    ambiguous = set()

    def claim(ip, record):
        if not ip:
            return
        owner = claimed.get(ip)
        if owner is None:
            if ip not in record['ips']:
                record['ips'].append(ip)
            if not record['ip']:
                record['ip'] = ip
            claimed[ip] = record
            return
        if owner is record:
            return
        if owner['source'] == 'unifi' and record['source'] == 'unifi':
            ambiguous.add(ip)
            owner['ips'] = [item for item in owner['ips'] if item != ip]
            if owner['ip'] == ip:
                owner['ip'] = owner['ips'][0] if owner['ips'] else None
            claimed.pop(ip, None)
            record['ips'] = [item for item in record['ips'] if item != ip]
            if record['ip'] == ip:
                record['ip'] = record['ips'][0] if record['ips'] else None

    for host in iot:
        record = _blank(
            host['name'], 'iot-hosts', host.get('mac'), host.get('ip'),
            identity=host['id'], host_class=host['class'],
            dns_names=host.get('dns_names'), notes=host.get('notes'),
        )
        records.append(record)
        if record['mac']:
            by_mac[record['mac']] = record
        claim(record['ip'], record)

    for client in unifi:
        mac = client['mac']
        if mac in by_mac:
            record = by_mac[mac]
            if client.get('seen') and (not record['seen'] or client['seen'] > record['seen']):
                record['seen'] = client['seen']
            claim(client.get('ip'), record)
            continue
        record = _blank(client.get('name'), 'unifi', mac, seen=client.get('seen'))
        records.append(record)
        by_mac[mac] = record
        claim(client.get('ip'), record)

    for row in pihole:
        ip = row['ip']
        if ip in claimed or ip in ambiguous:
            continue
        record = _blank(row['name'], 'pihole', ip=ip, seen=row.get('seen'))
        records.append(record)
        claimed[ip] = record

    for record in records:
        record['ips'] = sorted(set(record['ips']))
        if record['notes'] is None:
            record.pop('notes')
    records.sort(key=lambda item: ((item['name'] or '').lower(), item['mac'] or '', item['ip'] or ''))
    return records, sorted(ambiguous)


class HostCache:
    """Process-local cache. `lookup` is the entry a later `/api/ask` should use."""

    def __init__(self, clients=(), clock=None, refresh_seconds=None):
        self.clients = list(clients)
        self.clock = clock or time.time
        self.refresh_seconds = refresh_interval() if refresh_seconds is None else refresh_seconds
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._iot, self._iot_state = self._read_iot()
        self._unifi = []
        self._pihole = []
        pending = 'pending' if self.clients else 'skipped'
        note = None if self.clients else 'VictoriaLogs is queried only while the console runs in live mode.'
        self._unifi_state = {'state': pending, 'count': 0, 'note': note}
        self._pihole_state = {'state': pending, 'count': 0, 'note': note}
        self._refreshed_at = None if self.clients else self.clock()
        self._dynamic_ok = not self.clients

    def _read_iot(self):
        path, mounted_note = resolve_iot_hosts_path()
        hosts, state = load_iot_hosts(path)
        if mounted_note and state.get('state') == 'ok':
            state['note'] = mounted_note
        return hosts, state

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name='host-cache', daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception:
                pass
            self._stop.wait(self.refresh_seconds)

    def _query(self, query):
        if not self.clients:
            return None, 'skipped'
        for client in self.clients:
            try:
                rows = client.query(query, time.monotonic() + 8)
            except Exception:
                continue
            if isinstance(rows, list):
                return rows, 'ok'
        return None, 'error'

    def refresh(self):
        iot, iot_state = self._read_iot()
        unifi_rows, unifi_flag = self._query(UNIFI_CLIENTS)
        pihole_rows, pihole_flag = self._query(PIHOLE_CLIENTS)
        with self._lock:
            self._iot, self._iot_state = iot, iot_state
            if unifi_flag == 'ok':
                parsed, note = normalize_unifi(unifi_rows)
                if note and 'cap' in note:
                    self._unifi_state = {
                        'state': 'partial', 'count': len(self._unifi), 'note': note,
                    }
                else:
                    self._unifi = parsed
                    self._unifi_state = {'state': 'ok', 'count': len(parsed), 'note': note}
            elif unifi_flag == 'skipped':
                self._unifi = []
                self._unifi_state = {
                    'state': 'skipped', 'count': 0,
                    'note': 'VictoriaLogs is queried only while the console runs in live mode.',
                }
            else:
                self._unifi_state = {
                    'state': 'error',
                    'count': len(self._unifi),
                    'note': 'UniFi client query failed; the previous sample was kept.',
                }
            if pihole_flag == 'ok':
                parsed, note = normalize_pihole(pihole_rows)
                if note and 'cap' in note:
                    self._pihole_state = {
                        'state': 'partial', 'count': len(self._pihole), 'note': note,
                    }
                else:
                    self._pihole = parsed
                    self._pihole_state = {'state': 'ok', 'count': len(parsed), 'note': note}
            elif pihole_flag == 'skipped':
                self._pihole = []
                self._pihole_state = {
                    'state': 'skipped', 'count': 0,
                    'note': 'VictoriaLogs is queried only while the console runs in live mode.',
                }
            else:
                self._pihole_state = {
                    'state': 'error',
                    'count': len(self._pihole),
                    'note': 'Pi-hole client query failed; the previous sample was kept.',
                }
            self._refreshed_at = self.clock()
            self._dynamic_ok = unifi_flag in ('ok', 'skipped') and pihole_flag in ('ok', 'skipped')
        return self.snapshot()

    def snapshot(self):
        with self._lock:
            hosts, ambiguous = merge_hosts(self._iot, self._unifi, self._pihole)
            refreshed = self._refreshed_at
            age = None if refreshed is None else self.clock() - refreshed
            stale = refreshed is None or not self._dynamic_ok or (
                age is not None and age > self.refresh_seconds * 2
            )
            sources = {
                'iot-hosts': {key: value for key, value in self._iot_state.items() if value is not None},
                'unifi': {key: value for key, value in self._unifi_state.items() if value is not None},
                'pihole': {key: value for key, value in self._pihole_state.items() if value is not None},
            }
            view = {
                'refreshed_at': None if refreshed is None else time.strftime(
                    '%Y-%m-%dT%H:%M:%SZ', time.gmtime(refreshed)),
                'refresh_seconds': self.refresh_seconds,
                'stale': stale,
                'gaps': [DHCP_GAP],
                'ambiguous_ips': ambiguous,
                'sources': sources,
                'hosts': hosts,
            }
        return copy.deepcopy(view)

    def lookup(self, ip=None, mac=None):
        """Resolve one address. MAC wins over IP. Ambiguous IPs return None."""
        view = self.snapshot()
        mac_key = normalize_mac(mac) if mac else None
        ip_key = normalize_ip(ip) if ip else None
        if mac_key:
            hits = [host for host in view['hosts'] if host.get('mac') == mac_key]
            if len(hits) == 1:
                return {**hits[0], 'matched_on': 'mac'}
            if len(hits) > 1:
                preferred = [host for host in hits if host['source'] == 'iot-hosts']
                if len(preferred) == 1:
                    return {**preferred[0], 'matched_on': 'mac'}
                return None
        if ip_key:
            if ip_key in view['ambiguous_ips']:
                return None
            hits = [host for host in view['hosts'] if ip_key in host.get('ips', [])]
            if len(hits) == 1:
                return {**hits[0], 'matched_on': 'ip'}
        return None
