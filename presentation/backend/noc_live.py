"""Real-time NOC front-page payload: world map arcs (flows vs firewall blocks),
live throughput wave, and per-host sparklines with ACTIVE/IDLE status.

Uses bounded 15-minute VictoriaLogs aggregates (1-minute buckets) and local
DB-IP Lite geolocation (0.5-degree grid). Demo mode is strictly illustrative
and never used as a fallback in live mode.
"""

from datetime import datetime, timedelta, timezone
import ipaddress
import math

from .filterlog import public_endpoint
from .locations import aggregate
from .network import (
    _fresh,
    _is_lan,
    _span,
    _synthetic,
    accumulate,
    bucket_starts,
    floor_bucket,
    health_block,
    lan_filter,
    not_lan_filter,
    number,
    parse_time,
    run_all,
    stamp,
)
from .network_demo import HOSTS as DEMO_HOSTS
from .service import NETWORKS

LIVE_WINDOW_SECONDS = 900
MAP_FLOW_SECONDS = 300
ACTIVE_BUCKETS = 5
STEP_SECONDS = 60
REFRESH_SECONDS = 15
HOST_LIMIT = 24
PAIR_LIMIT = 2000

HOME = {"lat": 43.1566, "lon": -77.6088, "label": "Rochester, NY"}
MAP_NOTE = (
    "Cyan arcs show active NetFlow public endpoints (last 5 min); amber arcs show "
    "OPNsense firewall-blocked public IPs (last 15 min). Coordinates use a local "
    "DB-IP Lite 0.5° grid and represent approximate areas, not exact servers or packet routes."
)


def live_queries(start, end, flow_map_start):
    span_15m = _span(start, end)
    span_5m = _span(flow_map_start, end)
    look = _span(end - timedelta(hours=6), end)
    flow_15m = f"{span_15m} app_name:=opnsense-flow schema:=2"
    flow_5m = f"{span_5m} app_name:=opnsense-flow schema:=2 remote_ip:=192.168.5.1"
    return {
        "fresh_flow": f"{look} app_name:=opnsense-flow schema:=2 | sort by (_time) desc | limit 1 | fields _time",
        "fresh_dns": f"{look} app_name:=pihole-dns | sort by (_time) desc | limit 1 | fields _time",
        "fresh_fw": f"{look} app_name:=filterlog | sort by (_time) desc | limit 1 | fields _time",
        "upload_buckets": (
            f"{flow_15m} {lan_filter('src_addr')} "
            "| stats by (src_addr, _time:1m) sum(bytes) bytes | limit 4000"
        ),
        "download_buckets": (
            f"{flow_15m} {lan_filter('dst_addr')} {not_lan_filter('src_addr')} "
            "| stats by (dst_addr, _time:1m) sum(bytes) bytes | limit 4000"
        ),
        "total_series": (
            f"{flow_15m} | stats by (_time:1m) sum(bytes) bytes | sort by (_time)"
        ),
        "block_series": (
            f"{span_15m} app_name:=filterlog action:=block "
            "| stats by (_time:1m) count() blocks | sort by (_time)"
        ),
        "host_blocks": (
            f"{span_15m} app_name:=filterlog action:=block "
            "| stats by (src) count() blocks | sort by (blocks) desc | limit 200"
        ),
        "flow_pairs": (
            f"{flow_5m} | stats by (src_addr, dst_addr) max(_time) last_seen | limit {PAIR_LIMIT + 1}"
        ),
        "block_pairs": (
            f"{span_15m} app_name:=filterlog action:=block "
            f"| stats by (src, dst) count() hits, max(_time) last_seen | sort by (hits) desc | limit {PAIR_LIMIT + 1}"
        ),
    }


def _safe_ip(value):
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        return None


def _geolocate_endpoints(ips_with_seen, geo):
    endpoints = {}
    for ip, seen in ips_with_seen.items():
        loc = geo.lookup(ip) if geo is not None else None
        endpoints[ip] = (loc, stamp(seen) if isinstance(seen, datetime) else seen)
    return aggregate(endpoints, near_live=True)


def _extract_public_ips(rows, fields, start, end):
    if rows is None or len(rows) > PAIR_LIMIT:
        return None, 0
    ips = {}
    events = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = parse_time(row.get("last_seen"))
        if when is None or not (start <= when <= end + timedelta(seconds=60)):
            when = end
        try:
            hits = number(row.get("hits")) if "hits" in row else 1
        except (ValueError, TypeError):
            hits = 1
        events += hits
        for field in fields:
            ip = _safe_ip(row.get(field))
            if ip and public_endpoint(ip, NETWORKS):
                prev = ips.get(ip)
                if prev is None or when > prev:
                    ips[ip] = when
    return ips, events


def build_live(end, results, directory, geo=None):
    start = end - timedelta(seconds=LIVE_WINDOW_SECONDS)
    flow_map_start = end - timedelta(seconds=MAP_FLOW_SECONDS)
    starts = bucket_starts(start, end, STEP_SECONDS)
    bucket_index = {stamp(bucket): idx for idx, bucket in enumerate(starts)}
    n_buckets = len(starts)

    flow_st, flow_seen = _fresh(results.get("fresh_flow"), end)
    dns_st, dns_seen = _fresh(results.get("fresh_dns"), end)
    fw_st, fw_seen = _fresh(results.get("fresh_fw"), end)
    health = health_block(
        "Real-time",
        [flow_st, dns_st, fw_st],
        {"flow": flow_seen, "dns": dns_seen, "firewall": fw_seen},
    )

    flow_series_raw = accumulate(
        start, end, STEP_SECONDS, results.get("total_series"), lambda row: number(row.get("bytes"))
    )
    block_series_raw = accumulate(
        start, end, STEP_SECONDS, results.get("block_series"), lambda row: number(row.get("blocks"))
    )
    throughput_points = []
    total_bytes = 0
    total_blocks = 0
    for idx, bucket in enumerate(starts):
        b_val = flow_series_raw[idx]["value"] if flow_series_raw else 0
        blk_val = block_series_raw[idx]["value"] if block_series_raw else 0
        total_bytes += b_val
        total_blocks += blk_val
        throughput_points.append({"time": stamp(bucket), "bytes": b_val, "blocks": blk_val})

    # Per-host bucketed traffic (merged via Directory for multi-IP hosts).
    host_upload = {}
    host_download = {}
    host_sparks = {}
    host_records = {}

    def _bucket_for(row):
        seen = parse_time(row.get("_time"))
        if seen is None:
            return None
        return bucket_index.get(stamp(floor_bucket(seen, STEP_SECONDS)))

    def _credit(rows, field, target_map):
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ip = _safe_ip(row.get(field))
            if not ip or not _is_lan(ip):
                continue
            idx = _bucket_for(row)
            if idx is None:
                continue
            try:
                val = number(row.get("bytes"))
            except (ValueError, TypeError):
                continue
            if val <= 0:
                continue
            rec = directory.known(ip) or _synthetic(ip)
            hid = rec["id"]
            host_records.setdefault(hid, rec)
            target_map[hid] = target_map.get(hid, 0) + val
            spark = host_sparks.setdefault(hid, [0] * n_buckets)
            spark[idx] += val

    _credit(results.get("upload_buckets"), "src_addr", host_upload)
    _credit(results.get("download_buckets"), "dst_addr", host_download)

    host_block_counts = {}
    for row in results.get("host_blocks") or []:
        if not isinstance(row, dict):
            continue
        ip = _safe_ip(row.get("src"))
        if not ip or not _is_lan(ip):
            continue
        try:
            cnt = number(row.get("blocks"))
        except (ValueError, TypeError):
            continue
        rec = directory.known(ip) or _synthetic(ip)
        hid = rec["id"]
        host_records.setdefault(hid, rec)
        host_block_counts[hid] = host_block_counts.get(hid, 0) + cnt

    hosts = []
    active_count = 0
    for hid, rec in host_records.items():
        up = host_upload.get(hid, 0)
        down = host_download.get(hid, 0)
        total = up + down
        blocked = host_block_counts.get(hid, 0)
        if total <= 0 and blocked <= 0:
            continue
        spark = host_sparks.get(hid) or [0] * n_buckets
        recent_bytes = sum(spark[-ACTIVE_BUCKETS:]) if n_buckets else 0
        status = "active" if recent_bytes > 0 else "idle"
        if status == "active":
            active_count += 1
        hosts.append(
            {
                "id": rec["id"],
                "name": rec["name"],
                "ip": rec["ip"],
                "icon": rec.get("icon") or "monitor",
                "type": rec.get("type") or "",
                "location": rec.get("location") or "",
                "status": status,
                "download_bytes": down,
                "upload_bytes": up,
                "bytes": total,
                "blocked": blocked,
                "spark": spark,
            }
        )
    hosts.sort(key=lambda item: (item["status"] != "active", -item["bytes"], -item["blocked"], item["name"].lower()))
    listed_hosts = hosts[:HOST_LIMIT]

    flow_ips, _ = _extract_public_ips(results.get("flow_pairs"), ("src_addr", "dst_addr"), flow_map_start, end)
    block_ips, block_pair_events = _extract_public_ips(results.get("block_pairs"), ("src", "dst"), start, end)

    flow_countries, flow_locations = _geolocate_endpoints(flow_ips or {}, geo) if flow_ips is not None else ([], [])
    block_countries, block_locations = _geolocate_endpoints(block_ips or {}, geo) if block_ips is not None else ([], [])

    peak_bytes = max((p["bytes"] for p in throughput_points), default=0)
    avg_mbps = round((total_bytes * 8) / LIVE_WINDOW_SECONDS / 1e6, 2) if LIVE_WINDOW_SECONDS else 0.0
    peak_mbps = round((peak_bytes * 8) / STEP_SECONDS / 1e6, 2) if STEP_SECONDS else 0.0

    return {
        "mode": "live",
        "illustrative": False,
        "as_of": stamp(end),
        "refresh_seconds": REFRESH_SECONDS,
        "window": {
            "start": stamp(start),
            "end": stamp(end),
            "seconds": LIVE_WINDOW_SECONDS,
            "label": "Last 15 minutes",
        },
        "health": health,
        "totals": {
            "bytes": total_bytes if flow_series_raw is not None else None,
            "avg_mbps": avg_mbps if flow_series_raw is not None else None,
            "peak_mbps": peak_mbps if flow_series_raw is not None else None,
            "active_hosts": active_count,
            "listed_hosts": len(hosts),
            "flow_endpoints": len(flow_ips) if flow_ips is not None else None,
            "block_endpoints": len(block_ips) if block_ips is not None else None,
            "firewall_blocks": total_blocks if block_series_raw is not None else block_pair_events,
        },
        "throughput": {
            "step_seconds": STEP_SECONDS,
            "points": throughput_points,
        },
        "map": {
            "home": HOME,
            "flows": [loc for loc in flow_locations if loc.get("precision") == "area"],
            "blocks": [loc for loc in block_locations if loc.get("precision") == "area"],
            "flow_countries": flow_countries,
            "block_countries": block_countries,
            "geo": geo.status() if geo is not None else {"available": False},
            "note": MAP_NOTE,
        },
        "hosts": listed_hosts,
    }


def live_noc(client, end, directory, geo=None):
    start = end - timedelta(seconds=LIVE_WINDOW_SECONDS)
    flow_map_start = end - timedelta(seconds=MAP_FLOW_SECONDS)
    results = run_all(client, live_queries(start, end, flow_map_start))
    if all(
        results.get(key) is None
        for key in ("total_series", "upload_buckets", "download_buckets", "flow_pairs", "block_pairs")
    ):
        raise RuntimeError("Live NOC queries failed")
    return build_live(end, results, directory, geo=geo)


def _demo_wave(seed, scale, active=True, spike_idx=None):
    pts = []
    for i in range(15):
        phase = (i + seed * 1.7) * 0.65
        base = 0.45 + 0.35 * math.sin(phase) + 0.18 * math.cos(phase * 1.9)
        if not active and i >= 10:
            val = 0
        else:
            val = int(max(0.05, base) * scale)
        if spike_idx is not None and i == spike_idx:
            val = int(scale * 2.1)
        pts.append(val)
    return pts


def demo_live(end):
    start = end - timedelta(seconds=LIVE_WINDOW_SECONDS)
    starts = bucket_starts(start, end, STEP_SECONDS)
    n = len(starts)

    # Illustrative host rows aligned with existing household demo inventory.
    demo_specs = [
        # id, active, mb_scale_per_min, blocked_count, spike_idx
        ("ai-02", True, 28_000_000, 0, 12),
        ("deneb", True, 16_500_000, 0, 9),
        ("apple-tv", True, 14_200_000, 0, None),
        ("samsung-tv", True, 6_400_000, 14, 11),
        ("roku", True, 4_100_000, 6, None),
        ("synology", False, 3_600_000, 0, 6),
        ("unifi-os", True, 2_200_000, 29, 13),
        ("sonos", True, 1_150_000, 0, None),
        ("ring", False, 850_000, 2, 4),
        ("nest-mini", True, 620_000, 0, None),
        ("pihole", True, 410_000, 0, None),
        ("opnsense", True, 320_000, 0, None),
    ]
    by_id = {row[0]: row for row in DEMO_HOSTS}
    hosts = []
    agg_bytes = [0] * n
    for idx, (hid, active, scale, blocked, spike_idx) in enumerate(demo_specs):
        row = by_id[hid]
        spark = _demo_wave(idx + 1, scale, active=active, spike_idx=spike_idx)[:n]
        total = sum(spark)
        up = int(total * row[7])
        down = total - up
        for i, val in enumerate(spark):
            agg_bytes[i] += val
        hosts.append(
            {
                "id": row[0],
                "name": row[1],
                "ip": row[2],
                "location": row[3],
                "type": row[4],
                "icon": row[5],
                "status": "active" if active else "idle",
                "download_bytes": down,
                "upload_bytes": up,
                "bytes": total,
                "blocked": blocked,
                "spark": spark,
            }
        )

    agg_blocks = [4, 6, 5, 9, 7, 5, 11, 8, 6, 14, 9, 7, 12, 8, 6][:n]
    throughput_points = [
        {"time": stamp(bucket), "bytes": agg_bytes[i], "blocks": agg_blocks[i]}
        for i, bucket in enumerate(starts)
    ]
    total_bytes = sum(agg_bytes)
    peak_bytes = max(agg_bytes) if agg_bytes else 0

    flow_places = [
        ("US", "United States", "Virginia", "Ashburn", 39.04, -77.49, 28),
        ("US", "United States", "California", "San Jose", 37.34, -121.89, 19),
        ("US", "United States", "Washington", "Seattle", 47.61, -122.33, 12),
        ("CA", "Canada", "Ontario", "Toronto", 43.65, -79.38, 9),
        ("GB", "United Kingdom", "England", "London", 51.51, -0.13, 14),
        ("DE", "Germany", "Hesse", "Frankfurt", 50.11, 8.68, 11),
        ("JP", "Japan", "Tokyo", "Tokyo", 35.68, 139.69, 8),
        ("AU", "Australia", "New South Wales", "Sydney", -33.87, 151.21, 5),
    ]
    block_places = [
        ("NL", "Netherlands", "North Holland", "Amsterdam", 52.37, 4.90, 11),
        ("CN", "China", "Guangdong", "Shenzhen", 22.54, 114.06, 9),
        ("BR", "Brazil", "São Paulo", "São Paulo", -23.55, -46.63, 6),
        ("SG", "Singapore", "Central", "Singapore", 1.35, 103.82, 7),
        ("MX", "Mexico", "Mexico City", "Mexico City", 19.43, -99.13, 4),
        ("AE", "United Arab Emirates", "Dubai", "Dubai", 25.20, 55.27, 5),
    ]

    def _agg_demo(places, tag):
        endpoints = {
            f"demo:{tag}:{code}:{city}:{i}": (
                {"code": code, "name": cname, "region": region, "city": city, "latitude": lat, "longitude": lon},
                stamp(end - timedelta(seconds=20 + i * 3)),
            )
            for code, cname, region, city, lat, lon, cnt in places
            for i in range(cnt)
        }
        return aggregate(endpoints, near_live=True)

    flow_countries, flow_locs = _agg_demo(flow_places, "flow")
    block_countries, block_locs = _agg_demo(block_places, "block")

    return {
        "mode": "demo",
        "illustrative": True,
        "as_of": stamp(end),
        "refresh_seconds": REFRESH_SECONDS,
        "window": {
            "start": stamp(start),
            "end": stamp(end),
            "seconds": LIVE_WINDOW_SECONDS,
            "label": "Last 15 minutes",
        },
        "health": {
            "state": "healthy",
            "text": "Real-time",
            "emphasis": None,
            "detail": None,
            "sources": {
                "flow": stamp(end - timedelta(seconds=18)),
                "dns": stamp(end - timedelta(seconds=12)),
                "firewall": stamp(end - timedelta(seconds=9)),
            },
        },
        "totals": {
            "bytes": total_bytes,
            "avg_mbps": round((total_bytes * 8) / LIVE_WINDOW_SECONDS / 1e6, 2),
            "peak_mbps": round((peak_bytes * 8) / STEP_SECONDS / 1e6, 2),
            "active_hosts": sum(1 for h in hosts if h["status"] == "active"),
            "listed_hosts": len(hosts),
            "flow_endpoints": sum(p[6] for p in flow_places),
            "block_endpoints": sum(p[6] for p in block_places),
            "firewall_blocks": sum(agg_blocks),
        },
        "throughput": {
            "step_seconds": STEP_SECONDS,
            "points": throughput_points,
        },
        "map": {
            "home": HOME,
            "flows": [loc for loc in flow_locs if loc.get("precision") == "area"],
            "blocks": [loc for loc in block_locs if loc.get("precision") == "area"],
            "flow_countries": flow_countries,
            "block_countries": block_countries,
            "geo": {"available": True, "provider": "DB-IP Lite (demo locations)", "age_days": 4},
            "note": "Illustrative demo data. " + MAP_NOTE,
        },
        "hosts": hosts,
    }
