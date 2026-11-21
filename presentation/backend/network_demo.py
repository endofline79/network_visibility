"""Labelled example console. These figures are not live telemetry.

The household labels follow the approved mockup so the preview has the same
shape as the design. Live mode never substitutes this payload for a failed read.
"""
from datetime import timedelta

from .network import (
    DNS_LABEL,
    FIREWALL_LABEL,
    LABELS,
    STEPS,
    category_for,
    spike_payload,
    split_weighted,
    stamp,
    weighted_points,
)

BYTES = {3600: 0.052, 86400: 1.0, 604800: 6.62}
DNSQ = {3600: 0.049, 86400: 1.0, 604800: 7.08}
SITE_SCALE = {3600: 0.42, 86400: 1.0, 604800: 1.9}
ACTIVE = {3600: 29, 86400: 38, 604800: 46}
UNIQUE = {3600: 1104, 86400: 3912, 604800: 9860}
FW_BLOCKED = {3600: 690, 86400: 18400, 604800: 112300}
FW_ALLOWED = {3600: 92400, 86400: 2100000, 604800: 14600000}
TOTAL_GB = 142.0
GB = 1_000_000_000

# id, name, ip, location, type, icon, gb, upload fraction, sites contacted,
# ((domain, share, upload fraction), ...), ((blocked domain, queries), ...)
HOSTS = (
    ("ai-02", "AI-02", "192.168.5.230", "Main LAN", "Home server · Ubuntu", "server", 48.2, 0.21, 212,
     (("huggingface.co", 0.40, 0.01), ("googleapis.com", 0.14, 0.78), ("registry-1.docker.io", 0.13, 0.02),
      ("ghcr.io", 0.07, 0.02), ("archive.ubuntu.com", 0.06, 0.01), ("pypi.org", 0.05, 0.02),
      ("github.com", 0.04, 0.15), ("derp.tailscale.com", 0.03, 0.50), ("other", 0.08, 0.20)),
     (("telemetry.ubuntu.com", 118), ("metrics.data.hicloud.com", 61), ("api.segment.io", 48), ("other (6)", 38))),
    ("deneb", "deneb", "192.168.5.139", "Office", "Workstation", "monitor", 31.5, 0.21, 388,
     (("googleapis.com", 0.27, 0.62), ("youtube.com", 0.22, 0.02), ("sharepoint.com", 0.13, 0.20),
      ("teams.microsoft.com", 0.10, 0.35), ("github.com", 0.06, 0.12), ("cursor.com", 0.05, 0.10),
      ("fastly.net", 0.06, 0.01), ("other", 0.11, 0.10)),
     (("doubleclick.net", 214), ("vortex.data.microsoft.com", 188), ("googlesyndication.com", 152),
      ("scorecardresearch.com", 96), ("hotjar.com", 71), ("other (19)", 103))),
    ("apple-tv", "Living-Room Apple TV", "192.168.5.142", "Living room", "Apple TV 4K", "tv", 22.1, 0.077, 47,
     (("netflix.com", 0.43, 0.03), ("youtube.com", 0.28, 0.03), ("apple.com", 0.12, 0.12),
      ("disneyplus.com", 0.09, 0.03), ("icloud.com", 0.04, 0.30), ("akamai.net", 0.02, 0.02),
      ("other", 0.02, 0.10)),
     (("doubleclick.net", 248), ("app-measurement.com", 171), ("iadsdk.apple.com", 139),
      ("ads.youtube.com", 98), ("other (8)", 45))),
    ("samsung-tv", "Samsung Bedroom TV", "192.168.5.134", "Bedroom", "Samsung smart TV", "tv", 9.8, 0.07, 63,
     (("netflix.com", 0.38, 0.02), ("youtube.com", 0.30, 0.02), ("primevideo.com", 0.18, 0.02),
      ("samsungcloudsolution.com", 0.06, 0.40), ("akamai.net", 0.05, 0.01), ("other", 0.03, 0.20)),
     (("log-config.samsungacr.com", 1184), ("samsungads.com", 802), ("lcprd1.samsungcloudsolution.net", 511),
      ("config.samsungads.com", 344), ("other (14)", 236))),
    ("roku", "RokuPremiere", "192.168.5.145", "Yoga room", "Roku Premiere", "tv", 6.4, 0.06, 41,
     (("youtube.com", 0.35, 0.02), ("hulu.com", 0.30, 0.02), ("pbs.org", 0.17, 0.02),
      ("roku.com", 0.08, 0.30), ("akamai.net", 0.07, 0.01), ("other", 0.03, 0.20)),
     (("scribe.logs.roku.com", 742), ("ads.roku.com", 466), ("amoeba.web.roku.com", 281), ("other (9)", 208))),
    ("synology", "Synology", "192.168.5.236", "Main LAN", "NAS · DSM", "nas", 4.2, 0.74, 19,
     (("googleapis.com", 0.70, 0.95), ("quickconnect.to", 0.12, 0.50), ("synology.com", 0.10, 0.02),
      ("other", 0.08, 0.30)),
     (("other (2)", 9),)),
    ("unifi-os", "unifi-os", "10.10.20.50", "INFRA VLAN 20", "UniFi controller VM", "wifi", 3.1, 0.39, 24,
     (("ui.com", 0.45, 0.55), ("fw-download.ubnt.com", 0.25, 0.02), ("amazonaws.com", 0.18, 0.50),
      ("stun.l.google.com", 0.05, 0.50), ("other", 0.07, 0.30)),
     (("trace.svc.ui.com", 33), ("other (3)", 18))),
    ("sonos", "Sonos sound bar", "192.168.5.150", "Living room", "Sonos Beam", "speaker", 1.2, 0.08, 22,
     (("spotify.com", 0.55, 0.02), ("sonos.com", 0.20, 0.30), ("pandora.com", 0.15, 0.02), ("other", 0.10, 0.20)),
     (("msmetrics.ws.sonos.com", 81), ("other (2)", 33))),
    ("ring", "Ring front door", "192.168.5.160", "Front porch", "Ring doorbell", "bellring", 0.9, 0.83, 9,
     (("ring.com", 0.62, 0.90), ("amazonaws.com", 0.30, 0.85), ("other", 0.08, 0.40)),
     (("other (2)", 74),)),
    ("nest-mini", "Google Nest Mini", "192.168.5.155", "Kitchen", "Smart speaker", "mic", 0.6, 0.17, 28,
     (("music.youtube.com", 0.35, 0.02), ("google.com", 0.40, 0.30), ("gstatic.com", 0.15, 0.05),
      ("other", 0.10, 0.20)),
     (("clientlog.google.com", 278), ("app-measurement.com", 141), ("other (4)", 81))),
    ("pihole", "Pi-hole ns0", "192.168.5.238", "Main LAN", "DNS filter", "dns", 0.4, 0.38, 14,
     (("cloudflare-dns.com", 0.55, 0.45), ("raw.githubusercontent.com", 0.25, 0.02),
      ("deb.debian.org", 0.12, 0.02), ("other", 0.08, 0.30)),
     ()),
    ("opnsense", "OPNsense", "192.168.5.1", "Gateway", "Firewall · router", "router", 0.3, 0.33, 16,
     (("pkg.opnsense.org", 0.45, 0.02), ("rules.emergingthreats.net", 0.25, 0.02),
      ("dpinger probes", 0.15, 0.50), ("other", 0.15, 0.30)),
     ()),
    ("honeywell", "Honeywell thermostat", "192.168.5.133", "Hallway", "Wi-Fi thermostat", "thermo", 0.02, 0.40, 3,
     (("mytotalconnectcomfort.com", 0.85, 0.45), ("other", 0.15, 0.30)),
     ()),
)
BY_ID = {row[0]: row for row in HOSTS}
# Firewall source share of blocks: (id, share outside 1h, share during 1h).
FW_SOURCES = (
    ("unifi-os", 0.495, 0.21),
    ("samsung-tv", 0.125, 0.22),
    ("roku", 0.06, 0.12),
    ("nest-mini", 0.035, 0.07),
    ("ring", 0.026, 0.05),
)
FW_DESTINATIONS = (
    ("8.47.100.35", "UDP", "2066–2289", "UniFi cloud relay", 0.228),
    ("255.255.255.255", "UDP", "10001", "UniFi discovery", 0.196),
    ("239.255.255.250", "UDP", "1900", "SSDP", 0.147),
    ("stun.l.google.com", "UDP", "3478", "STUN", 0.103),
    ("224.0.0.251", "UDP", "5353", "mDNS", 0.076),
)
DNS_DOMAINS = (
    ("apple.com", 12400),
    ("icloud.com", 8921),
    ("netflix.com", 6352),
    ("googleapis.com", 4987),
    ("ui.com", 3621),
    ("amazonaws.com", 3154),
)
DNS_CLIENTS = (
    ("deneb", 14200),
    ("ai-02", 12600),
    ("samsung-tv", 9800),
    ("apple-tv", 9600),
    ("roku", 6900),
    ("nest-mini", 4100),
)
EXAMPLE = "Example data for this preview. Live mode does not fill gaps with these figures."


def _range_name(seconds):
    return {3600: "1h", 86400: "24h", 604800: "7d"}[seconds]


def _base(end, seconds, now):
    start = end - timedelta(seconds=seconds)
    return {
        "mode": "demo",
        "illustrative": True,
        "as_of": stamp(now),
        "range": _range_name(seconds),
        "window": {
            "start": stamp(start),
            "end": stamp(end),
            "seconds": seconds,
            "label": LABELS[seconds],
        },
        "deduped": seconds <= 3600,
        "footnote": "",
    }


def _healthy(text, detail=None, emphasis="healthy"):
    return {"state": "healthy", "text": text, "emphasis": emphasis, "detail": detail}


def _host_bytes(row, seconds):
    total = round(row[6] * BYTES[seconds] * GB)
    upload = round(total * row[7])
    return total - upload, upload


def _host_public(row, seconds):
    down, up = _host_bytes(row, seconds)
    return {
        "id": row[0], "name": row[1], "ip": row[2], "location": row[3], "type": row[4],
        "icon": row[5], "download_bytes": down, "upload_bytes": up,
    }


def _points(end, seconds, total, spike=False):
    start = end - timedelta(seconds=seconds)
    target = end - timedelta(seconds=100 * 60) if spike else None
    points, index = weighted_points(start, end, STEPS[seconds], total, target)
    return points, index


def demo_overview(end, seconds, now=None):
    now = now or end
    rows = [_host_public(row, seconds) for row in HOSTS]
    rows.sort(key=lambda item: -(item["download_bytes"] + item["upload_bytes"]))
    named = sum(item["download_bytes"] + item["upload_bytes"] for item in rows)
    total = round(TOTAL_GB * BYTES[seconds] * GB)
    points, _index = _points(end, seconds, total, spike=False)
    payload = _base(end, seconds, now)
    payload.update({
        "state": "available",
        "health": _healthy("All sources healthy · NetFlow, Pi-hole, OPNsense", emphasis=None),
        "totals": {
            "bytes": total,
            "active_hosts": ACTIVE[seconds],
            "active_hosts_capped": False,
            "firewall_blocks": FW_BLOCKED[seconds],
            "dns_blocked": round(round(84200 * DNSQ[seconds]) * 9515 / 84200),
        },
        "throughput": {
            "step_seconds": STEPS[seconds],
            "points": [{"time": point["time"], "bytes": point["value"]} for point in points],
        },
        "hosts": rows,
        "other": {"hosts": ACTIVE[seconds] - len(rows), "bytes": max(0, total - named)},
        "notes": [EXAMPLE],
    })
    return payload


def demo_host(end, seconds, host_id, now=None):
    row = BY_ID.get(host_id)
    if row is None:
        return None
    now = now or end
    host = _host_public(row, seconds)
    total = host["download_bytes"] + host["upload_bytes"]
    sites_raw = row[9]
    parts = split_weighted(total, [item[1] for item in sites_raw])
    sites = []
    for (name, _share, upload_fraction), amount in zip(sites_raw, parts):
        upload = round(amount * upload_fraction)
        sites.append({
            "name": name,
            "category": "Other" if name == "other" else category_for(name),
            "download_bytes": amount - upload,
            "upload_bytes": upload,
            "queries": 0,
        })
    sites.sort(key=lambda item: (item["name"] == "other", -(item["download_bytes"] + item["upload_bytes"])))
    scale = DNSQ[seconds]
    blocked = [{"name": name, "queries": max(1, round(count * scale))} for name, count in row[10]]
    points, _index = _points(end, seconds, total, spike=False)
    payload = _base(end, seconds, now)
    payload.update({
        "state": "available",
        "host": host,
        "sites_contacted": max(len(sites), round(row[8] * SITE_SCALE[seconds])),
        "sites_capped": False,
        "sites": sites,
        "blocked": blocked,
        "blocked_total": sum(item["queries"] for item in blocked),
        "blocked_state": "available",
        "firewall_blocks": _firewall_for(host_id, seconds),
        "throughput": {
            "step_seconds": STEPS[seconds],
            "points": [{"time": point["time"], "bytes": point["value"]} for point in points],
        },
        "attribution": "example",
        "site_note": (
            "Example data. Live mode shares each host's measured NetFlow across the sites it queried. "
            "Pi-hole does not store answer addresses, so that share is not a per-flow join. "
            "Categories come from a small domain map."
        ),
    })
    return payload


def _firewall_for(host_id, seconds):
    blocked = FW_BLOCKED[seconds]
    for ident, share, share_1h in FW_SOURCES:
        if ident == host_id:
            return round(blocked * (share_1h if seconds == 3600 else share))
    return 0


def demo_firewall(end, seconds, now=None):
    now = now or end
    blocked = FW_BLOCKED[seconds]
    points, index = _points(end, seconds, blocked, spike=True)
    sources = []
    listed = 0
    for ident, share, share_1h in FW_SOURCES:
        count = round(blocked * (share_1h if seconds == 3600 else share))
        listed += count
        row = BY_ID[ident]
        sources.append({
            "id": ident, "name": row[1], "ip": row[2], "count": count, "link": True,
        })
    sources.sort(key=lambda item: -item["count"])
    destinations = []
    for name, proto, port, label, share in FW_DESTINATIONS:
        factor = 0.15 if seconds == 3600 and name == "8.47.100.35" else 1
        destinations.append({
            "name": name, "protocol": proto, "port": port, "label": label,
            "count": round(blocked * share * factor),
        })
    detail = "spike · unifi-os" if index is not None else "spike"
    payload = _base(end, seconds, now)
    payload.update({
        "state": "available",
        "health": _healthy(FIREWALL_LABEL, "logged decisions only"),
        "blocked": blocked,
        "allowed": FW_ALLOWED[seconds],
        "series": {
            "step_seconds": STEPS[seconds],
            "points": [{"time": point["time"], "blocks": point["value"]} for point in points],
        },
        "spike": spike_payload(points, index, detail),
        "sources": sources,
        "other": {"count": max(0, blocked - listed), "hosts": max(8, ACTIVE[seconds] - 10)},
        "destinations": destinations,
        "top_rule": {"id": "9", "label": "#9", "name": "default deny", "percent": 86},
        "rule_scope": "blocks",
        "lists_capped": False,
        "note": EXAMPLE,
    })
    return payload


def demo_dns(end, seconds, now=None, host_id=None):
    now = now or end
    scale = DNSQ[seconds]
    selected_host = None
    if host_id is not None:
        row = BY_ID.get(host_id)
        if row is None:
            return None
        selected_host = {"id": row[0], "name": row[1], "ip": row[2]}
        base_q = next((count for ident, count in DNS_CLIENTS if ident == host_id), 1200)
        queries = max(1, round(base_q * scale))
        tag_sum = sum(item[1] for item in row[10])
        blocked = min(queries, max(0, round(tag_sum * scale)))
        unique = max(len(row[9]), round(row[8] * scale * 2))
        domains = [
            {"name": name, "queries": max(1, round(queries * share)), "category": category_for(name)}
            for name, share, _up in row[9]
            if name != "other"
        ][:6]
        clients = [{
            "id": row[0], "name": row[1], "ip": row[2], "icon": row[5],
            "queries": queries, "blocked": blocked, "link": True,
        }]
    else:
        queries = round(84200 * scale)
        blocked = round(queries * 9515 / 84200)
        unique = UNIQUE[seconds]
        domains = [
            {"name": name, "queries": max(1, round(count * scale)), "category": category_for(name)}
            for name, count in DNS_DOMAINS
        ]
        clients = []
        for ident, count in DNS_CLIENTS:
            row = BY_ID[ident]
            scaled = max(1, round(count * scale))
            tag_sum = sum(item[1] for item in row[10])
            clients.append({
                "id": ident,
                "name": row[1],
                "ip": row[2],
                "icon": row[5],
                "queries": scaled,
                "blocked": round(scaled * tag_sum / count) if count else 0,
                "link": True,
            })
    answered_total = max(0, queries - blocked)
    start = end - timedelta(seconds=seconds)
    answered_points, _index = weighted_points(start, end, STEPS[seconds], answered_total, None)
    blocked_points, _index = weighted_points(start, end, STEPS[seconds], blocked, None)
    series = []
    for left, right in zip(answered_points, blocked_points):
        series.append({"time": left["time"], "answered": left["value"], "blocked": right["value"]})
    payload = _base(end, seconds, now)
    payload.update({
        "state": "available",
        "health": _healthy(DNS_LABEL, "query log"),
        "queries": queries,
        "blocked": blocked,
        "unique_domains": unique,
        "host": selected_host,
        "series": {"step_seconds": STEPS[seconds], "points": series},
        "domains": domains,
        "clients": clients,
        "note": EXAMPLE,
    })
    return payload
