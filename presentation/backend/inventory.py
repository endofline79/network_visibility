"""Hand-edited IoT and streaming allowlist.

The console does not infer this set from the flat LAN. A host is queried only
when it is listed here. Values are checked before they are copied into LogsQL.
"""
import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

MAX_HOSTS = 16
_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
_CLASS = re.compile(r"iot|streaming")
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?")
_MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
_FIELDS = {"id", "class", "name", "dns_names", "ip", "mac", "notes"}


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class Host:
    id: str
    device_class: str
    name: str
    dns_names: tuple[str, ...]
    ip: str
    mac: str
    notes: str

    def match_names(self):
        names = []
        for name in (self.name, *self.dns_names):
            if name not in names:
                names.append(name)
        return tuple(names)


@dataclass(frozen=True)
class Inventory:
    version: int
    hosts: tuple[Host, ...]

    def by_id(self, host_id):
        for host in self.hosts:
            if host.id == host_id:
                return host
        return None


def inventory_path():
    override = os.getenv("IOT_HOSTS_FILE", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "config" / "iot-hosts.yaml"


def _name(value, label):
    if not isinstance(value, str) or not _NAME.fullmatch(value) or ".." in value:
        raise InventoryError(f"invalid {label}")
    return value


def _host(row, seen_ids, seen_ips, seen_macs, seen_names):
    if not isinstance(row, dict):
        raise InventoryError("host entry must be a mapping")
    extra = set(row) - _FIELDS
    if extra:
        raise InventoryError("unknown host field")
    host_id = row.get("id")
    if not isinstance(host_id, str) or not _ID.fullmatch(host_id) or host_id == "all":
        raise InventoryError("invalid id")
    if host_id in seen_ids:
        raise InventoryError("duplicate id")
    device_class = row.get("class")
    if not isinstance(device_class, str) or not _CLASS.fullmatch(device_class):
        raise InventoryError(f"{host_id}: invalid class")
    name = _name(row.get("name"), "name")
    raw_names = row.get("dns_names")
    if not isinstance(raw_names, list) or not 1 <= len(raw_names) <= 8:
        raise InventoryError(f"{host_id}: invalid dns_names")
    dns_names = tuple(_name(item, "dns_names") for item in raw_names)
    if len(set(dns_names)) != len(dns_names):
        raise InventoryError(f"{host_id}: duplicate dns_names")
    try:
        ip = ipaddress.ip_address(row.get("ip"))
    except (ValueError, TypeError):
        raise InventoryError(f"{host_id}: invalid ip") from None
    if ip.version != 4 or ip.is_unspecified or ip.is_multicast or int(ip) == 0xFFFFFFFF:
        raise InventoryError(f"{host_id}: invalid ip")
    ip_text = str(ip)
    mac = row.get("mac")
    if not isinstance(mac, str) or not _MAC.fullmatch(mac.strip().lower()):
        raise InventoryError(f"{host_id}: invalid mac")
    mac = mac.strip().lower()
    notes = row.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str) or len(notes) > 240 or any(not ch.isprintable() for ch in notes):
        raise InventoryError(f"{host_id}: invalid notes")
    tokens = {part.casefold() for part in (name, *dns_names)}
    if ip_text in seen_ips or mac in seen_macs or tokens & seen_names:
        raise InventoryError(f"{host_id}: duplicate address or name")
    seen_ids.add(host_id)
    seen_ips.add(ip_text)
    seen_macs.add(mac)
    seen_names.update(tokens)
    return Host(host_id, device_class, name, dns_names, ip_text, mac, notes.strip())


def load_inventory(path=None):
    file = Path(path) if path is not None else inventory_path()
    try:
        loaded = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise InventoryError("inventory file cannot be read") from None
    if not isinstance(loaded, dict) or set(loaded) != {"version", "hosts"}:
        raise InventoryError("inventory must contain version and hosts")
    if loaded.get("version") != 1:
        raise InventoryError("inventory version must be 1")
    rows = loaded.get("hosts")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_HOSTS:
        raise InventoryError("inventory needs 1 to 16 hosts")
    hosts = []
    seen_ids, seen_ips, seen_macs, seen_names = set(), set(), set(), set()
    for row in rows:
        hosts.append(_host(row, seen_ids, seen_ips, seen_macs, seen_names))
    return Inventory(1, tuple(hosts))
