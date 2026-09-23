#!/usr/bin/env python3
"""Read-only UniFi readiness probe. Uses a Phase-injected UOS_API_KEY.

Pins the controller certificate obtained over its separately trusted SSH path,
before sending authentication. Only GETs are implemented; response output is
restricted to inventory, schema summaries, and non-secret logging settings.
"""

import argparse
from collections import Counter
import hashlib
import hmac
import http.client
import json
import os
import re
import ssl
import sys
import uuid

HOST = "10.10.20.50"
PORT = 11443
PREFIX = "/proxy/network/integration/v1"


class ReadOnlyApi:
    def __init__(self, fingerprint):
        if not re.fullmatch(r"[a-fA-F0-9]{64}", fingerprint):
            raise ValueError("A SHA-256 certificate fingerprint is required")
        self.fingerprint = fingerprint.lower()
        self.key = os.environ.get("UOS_API_KEY", "")
        if not self.key or any(c.isspace() for c in self.key):
            raise ValueError("UOS_API_KEY is missing or invalid")

    def get(self, path):
        if not path.startswith(PREFIX + "/") and path != "/proxy/network/api/s/default/rest/setting":
            raise ValueError("Read endpoint outside the allowed scope")
        # Authenticate the exact certificate before sending any HTTP headers.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(HOST, PORT, context=context, timeout=10)
        try:
            connection.connect()
            actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if not hmac.compare_digest(actual, self.fingerprint):
                raise ValueError("Controller certificate changed; no API key was sent")
            connection.request("GET", path, headers={"X-API-Key": self.key, "Accept": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError(f"GET returned HTTP {response.status}; body suppressed")
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("Controller response exceeded the size bound")
            return json.loads(raw)
        finally:
            connection.close()


def rows(payload):
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ValueError("Unexpected list response")
    return data


def probe(api):
    sites = rows(api.get(PREFIX + "/sites"))
    if len(sites) != 1:
        raise ValueError("Expected exactly one local site")
    site_id = str(uuid.UUID(sites[0]["id"]))
    base = f"{PREFIX}/sites/{site_id}"
    devices = rows(api.get(base + "/devices?limit=200"))
    clients = api.get(base + "/clients?limit=200")
    client_rows = rows(clients)
    networks = rows(api.get(base + "/networks?limit=200"))
    result = {
        "controller": f"https://{HOST}:{PORT}", "site_id": site_id,
        "devices": [{key: device.get(key) for key in ("id", "name", "model", "ipAddress", "state")}
                    for device in devices],
        "clients": {"loaded": len(client_rows), "reported_total": clients.get("totalCount") if isinstance(clients, dict) else None,
                    "types": dict(Counter(str(client.get("type", "unknown")) for client in client_rows)),
                    "available_fields": sorted({key for client in client_rows for key in client})},
        "networks": [{key: network.get(key) for key in ("name", "vlanId", "management", "enabled")}
                     for network in networks],
        "device_details": [],
    }
    if client_rows:
        client_id = str(uuid.UUID(client_rows[0]["id"]))
        detail = api.get(base + "/clients/" + client_id)
        result["clients"]["detail_fields"] = sorted(detail)
        result["clients"]["detail_object_fields"] = {key: sorted(value) for key, value in detail.items() if isinstance(value, dict)}
    for device in devices[:10]:
        device_id = str(uuid.UUID(device["id"]))
        detail = api.get(base + "/devices/" + device_id)
        result["device_details"].append({
            "name": detail.get("name"), "firmware": detail.get("firmwareVersion"),
            "features": detail.get("features"), "uplink": detail.get("uplink"),
            "interfaces": detail.get("interfaces"), "available_fields": sorted(detail),
        })
        try:
            statistics = api.get(base + "/devices/" + device_id + "/statistics/latest")
            result["device_details"][-1]["statistics_fields"] = sorted(statistics)
            result["device_details"][-1]["statistics_object_fields"] = {key: sorted(value) for key, value in statistics.items() if isinstance(value, dict)}
        except ValueError as exc:
            result["device_details"][-1]["statistics_error"] = str(exc)
    try:
        settings = rows(api.get("/proxy/network/api/s/default/rest/setting"))
        result["logging_settings"] = []
        safe = {"key", "enabled", "ip", "port", "debug", "remote_server", "remote_port",
                "remotelog_enabled", "remotelog_server", "remotelog_port", "netconsole_enabled",
                "netconsole_host", "netconsole_port", "syslog_enabled", "syslog_ip", "syslog_port",
                "this_controller", "this_controller_encrypted_only", "log_all_contents"}
        for setting in settings:
            if "syslog" in str(setting.get("key", "")) or any("remotelog" in key for key in setting):
                result["logging_settings"].append({"fields": {key: setting[key] for key in safe & setting.keys()},
                                                   "available_fields": sorted(setting)})
    except ValueError as exc:
        result["logging_settings_error"] = str(exc)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert-sha256", required=True, help="Public TLS certificate fingerprint verified through SSH")
    args = parser.parse_args()
    try:
        print(json.dumps(probe(ReadOnlyApi(args.cert_sha256)), indent=2, sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException) as exc:
        # Do not print response bodies, credentials, or transport exception text.
        print(f"UniFi inspection failed ({type(exc).__name__}); details suppressed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
