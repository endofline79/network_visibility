"""Local UniFi inventory. Fixed GET endpoints, pinned TLS, no model calls."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import ssl
import tempfile
import threading
import time
import uuid

HOST, PORT = "10.10.20.50", 11443
PREFIX = "/proxy/network/integration/v1"
SITE = "88f7af54-98f8-306a-a1c7-c9349722b1f6"
POLL_SECONDS, STALE_SECONDS = 60, 150
MAX_BODY = 4 * 1024 * 1024
UUID = r"[a-f0-9-]{36}"
READ_PATH = re.compile(PREFIX + rf"/sites(?:/{UUID}/(?:devices|clients|networks)(?:/{UUID}(?:/statistics/latest)?)?)?(?:\?limit=\d+&offset=\d+)?")


class InventoryError(Exception):
    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    site_id: str = SITE
    fingerprint: str = ""
    key_file: str = "/run/visibility-secrets/unifi_api_key"

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("UNIFI_INVENTORY_ENABLED", "false").lower() == "true",
                   os.environ.get("UNIFI_SITE_ID", SITE), os.environ.get("UNIFI_CERT_SHA256", ""),
                   os.environ.get("UNIFI_API_KEY_FILE", cls.key_file))


class ReadOnlyApi:
    def __init__(self, config):
        if not re.fullmatch(r"[a-fA-F0-9]{64}", config.fingerprint):
            raise InventoryError("Controller certificate pin is missing or invalid.", True)
        self.fingerprint = config.fingerprint.lower()
        try:
            with open(config.key_file, encoding="utf-8") as source:
                self.key = source.read(8193).strip()
        except (OSError, UnicodeError):
            raise InventoryError("Controller credential file is unavailable.", True) from None
        if not self.key or len(self.key) > 8192 or any(c.isspace() or not c.isascii() or ord(c) < 33 for c in self.key):
            raise InventoryError("Controller credential file is invalid.", True)

    def get(self, path, deadline):
        if not READ_PATH.fullmatch(path):
            raise InventoryError("Read endpoint is outside the inventory scope.", True)

        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise InventoryError("Inventory poll exceeded its time budget.")
            return min(5, seconds)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(HOST, PORT, context=context, timeout=remaining())
        try:
            connection.connect()
            actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if not hmac.compare_digest(actual, self.fingerprint):
                raise InventoryError("Controller certificate changed; no credential was sent.", True)
            connection.sock.settimeout(remaining())
            connection.request("GET", path, headers={"X-API-Key": self.key, "Accept": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                # No redirects, raw upstream bodies, or immediate retries.
                raise InventoryError(f"Controller returned HTTP {response.status}.", response.status in (401, 403) or 300 <= response.status < 400)
            chunks, size = [], 0
            while True:
                timeout = remaining()
                if connection.sock is not None:
                    connection.sock.settimeout(timeout)
                chunk = response.read1(min(65536, MAX_BODY + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BODY:
                    raise InventoryError("Controller response exceeded the size bound.")
            payload = json.loads(b"".join(chunks))
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except InventoryError:
            raise
        except (OSError, http.client.HTTPException):
            raise InventoryError("Controller is unreachable or the request timed out.") from None
        except (ValueError, UnicodeError):
            raise InventoryError("Controller returned an invalid inventory response.") from None
        finally:
            connection.close()


def identifier(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise InventoryError("Controller returned an invalid inventory identifier.") from None


def optional_id(value):
    return identifier(value) if value else None


def text(value, limit=160):
    return "".join(c for c in value if c.isprintable())[:limit] if isinstance(value, str) else None


def number(value, maximum=None):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return value if maximum is None or value <= maximum else None
    return None


def date(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except (ValueError, AttributeError):
        return None


def address(value):
    try:
        return str(ipaddress.ip_address(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def obj(value):
    return value if isinstance(value, dict) else {}


def objects(value, maximum):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum or not all(isinstance(row, dict) for row in value):
        raise InventoryError("Controller returned an unexpected inventory schema.")
    return value


def page_all(api, path, cap, deadline):
    """Reject incomplete/unstable pages rather than declaring missing hosts gone."""
    rows, seen, expected = [], set(), None
    while True:
        page = api.get(f"{path}?limit={min(200, cap)}&offset={len(rows)}", deadline)
        if not isinstance(page.get("data"), list):
            raise InventoryError("Controller returned an unexpected inventory page.")
        batch = objects(page.get("data"), min(200, cap))
        total = page.get("totalCount")
        if (type(total) is not int or total < 0 or total > cap or
                page.get("offset") != len(rows) or page.get("count") != len(batch) or
                (expected is not None and total != expected) or len(rows) + len(batch) > total):
            raise InventoryError("Inventory pagination changed or exceeded its bound; retrying next poll.")
        expected = total
        for row in batch:
            row_id = identifier(row.get("id"))
            if row_id in seen:
                raise InventoryError("Inventory changed during pagination; retrying next poll.")
            seen.add(row_id)
        rows.extend(batch)
        if len(rows) == total:
            return rows
        if not batch:
            raise InventoryError("Controller returned an incomplete inventory page.")


def device_summary(row, detail=None, statistics=None, errors=None):
    detail, statistics = obj(detail), obj(statistics)
    features = detail.get("features", row.get("features", []))
    feature_names = {str(k).lower() for k in features} if isinstance(features, (dict, list)) else set()
    interfaces = obj(detail.get("interfaces"))
    ports = [{"index": number(p.get("idx")), "state": text(p.get("state"), 40),
              "speed_mbps": number(p.get("speedMbps")), "max_speed_mbps": number(p.get("maxSpeedMbps")),
              "poe_state": text(obj(p.get("poe")).get("state"), 40)}
             for p in objects(interfaces.get("ports"), 128)]
    radios = [{"band": text(r.get("frequencyGHz"), 30) if isinstance(r.get("frequencyGHz"), str) else number(r.get("frequencyGHz")),
               "channel": number(r.get("channel")), "width_mhz": number(r.get("channelWidthMHz")),
               "standard": text(r.get("wlanStandard"), 40)}
              for r in objects(interfaces.get("radios"), 16)]
    return {"id": identifier(row.get("id")), "name": text(row.get("name")), "model": text(row.get("model")),
            "ip": address(row.get("ipAddress")), "mac": text(row.get("macAddress"), 40),
            "state": text(row.get("state"), 40), "firmware": text(row.get("firmwareVersion"), 80),
            "kind": "switch" if "switching" in feature_names else "ap" if "accesspoint" in feature_names or "access_point" in feature_names else "device",
            "uplink_id": optional_id(obj(detail.get("uplink")).get("deviceId")),
            "ports": ports, "radios": radios, "cpu_pct": number(statistics.get("cpuUtilizationPct"), 100),
            "memory_pct": number(statistics.get("memoryUtilizationPct"), 100), "uptime_seconds": number(statistics.get("uptimeSec")),
            "last_heartbeat": date(statistics.get("lastHeartbeatAt")), "errors": errors or []}


def collect(api, config, clock=time.time):
    deadline, started = time.monotonic() + 20, clock()
    site_id = identifier(config.site_id)
    sites = page_all(api, PREFIX + "/sites", 50, deadline)
    site = next((s for s in sites if identifier(s["id"]) == site_id), None)
    if not site:
        raise InventoryError("Configured UniFi site was not found.", True)
    base = f"{PREFIX}/sites/{site_id}"
    device_rows = page_all(api, base + "/devices", 32, deadline)
    client_rows = page_all(api, base + "/clients", 2000, deadline)
    network_rows = page_all(api, base + "/networks", 100, deadline)
    clients = [{"id": identifier(c.get("id")), "name": text(c.get("name")), "ip": address(c.get("ipAddress")),
                "mac": text(c.get("macAddress"), 40), "type": text(c.get("type"), 40),
                "uplink_id": optional_id(c.get("uplinkDeviceId")), "connected_at": date(c.get("connectedAt"))}
               for c in client_rows]
    networks = [{"id": identifier(n.get("id")), "name": text(n.get("name")), "vlan": number(n.get("vlanId"), 4094),
                 "enabled": n.get("enabled") if type(n.get("enabled")) is bool else None}
                for n in network_rows]
    devices = []
    for row in device_rows:
        endpoint = base + "/devices/" + identifier(row.get("id"))
        detail, stats, errors = None, None, []
        for label, path in [("Device details", endpoint), ("Telemetry", endpoint + "/statistics/latest")]:
            try:
                result = api.get(path, deadline)
                if label == "Device details":
                    if identifier(result.get("id")) != identifier(row["id"]):
                        raise InventoryError("Device details did not match the requested device.")
                    detail = result
                else:
                    stats = result
            except InventoryError as exc:
                if exc.fatal:
                    raise
                errors.append(label + " unavailable.")
        try:
            devices.append(device_summary(row, detail, stats, errors))
        except InventoryError:
            devices.append(device_summary(row, statistics=stats, errors=errors + ["Device details have an unexpected schema."]))
    return {"site": {"id": site_id, "name": text(site.get("name"))}, "observed_from": timestamp(started),
            "observed_at": timestamp(clock()), "devices": devices, "clients": clients, "networks": networks,
            "partial": any(d["errors"] for d in devices)}


class Inventory:
    def __init__(self, path, config=None, api_factory=ReadOnlyApi, clock=time.time):
        self.path, self.config, self.api_factory, self.clock = Path(path), config or Config.from_env(), api_factory, clock
        self.lock, self.poll_lock, self.stop = threading.Lock(), threading.Lock(), threading.Event()
        self.worker, self.snapshot = None, None
        self.last_error, self.last_attempt, self.next_poll, self.polling = None, None, None, False
        try:
            with self.path.open() as source:
                saved = json.loads(source.read(MAX_BODY + 1))
            data = saved["snapshot"]
            if (saved["version"] == 1 and data["site"]["id"] == self.config.site_id and date(data["observed_at"]) and
                    type(data["partial"]) is bool and date(data["observed_from"]) and
                    all(isinstance(data[k], list) and all(isinstance(row, dict) for row in data[k])
                        for k in ["devices", "clients", "networks"])):
                self.snapshot = data
            else:
                raise ValueError()
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            self.last_error = "Saved inventory could not be read; waiting for a fresh poll."

    def _persist(self, snapshot):
        # Atomic, private latest-state file; never persist raw API responses or keys.
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, prefix=".unifi-", delete=False) as temp:
            name = temp.name
            try:
                json.dump({"version": 1, "snapshot": snapshot}, temp, allow_nan=False)
                temp.flush()
                os.fsync(temp.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def poll_once(self):
        if not self.config.enabled or not self.poll_lock.acquire(blocking=False):
            return
        with self.lock:
            self.last_attempt, self.polling = timestamp(self.clock()), True
        try:
            snapshot = collect(self.api_factory(self.config), self.config, self.clock)
            self._persist(snapshot)
            with self.lock:
                self.snapshot, self.last_error = snapshot, None
        except InventoryError as exc:
            with self.lock:
                self.last_error = str(exc)
        except Exception:
            with self.lock:
                self.last_error = "Inventory collection or local snapshot storage failed."
        finally:
            with self.lock:
                self.polling, self.next_poll = False, timestamp(self.clock() + POLL_SECONDS)
            self.poll_lock.release()

    def status(self):
        with self.lock:
            age = max(0, self.clock() - datetime.fromisoformat(self.snapshot["observed_at"]).timestamp()) if self.snapshot else None
            stale = age is None or age > STALE_SECONDS or bool(self.last_error) or not self.config.enabled
            state = ("disabled" if not self.config.enabled else "stale" if self.snapshot and stale else
                     "unavailable" if self.last_error else "starting" if not self.snapshot else
                     "partial" if self.snapshot["partial"] else "fresh")
            return {"state": state, "stale": stale, "age_seconds": round(age) if age is not None else None,
                    "controller": f"https://{HOST}:{PORT}", "poll_seconds": POLL_SECONDS, "stale_seconds": STALE_SECONDS,
                    "last_attempt": self.last_attempt, "next_poll": self.next_poll, "polling": self.polling,
                    "error": self.last_error, "snapshot": self.snapshot}

    def start_worker(self):
        if not self.config.enabled or (self.worker and self.worker.is_alive()):
            return
        self.stop.clear()

        def run():
            while not self.stop.is_set():
                self.poll_once()
                self.stop.wait(POLL_SECONDS)

        self.worker = threading.Thread(target=run, name="unifi-inventory", daemon=True)
        self.worker.start()

    def stop_worker(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=25)
