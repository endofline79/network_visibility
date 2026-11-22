"""Named read models for the home network console.

The browser never sends LogsQL. Windows are 1h, 24h, or 7d.

Flow and DNS totals deduplicate ``event_id`` only on the one-hour window.
A multi-day ``stats by (event_id)`` can exhaust VictoriaLogs, so 24h and 7d
sum stored receipts and say so. A retried export can then be counted twice.

Per-host site bytes are that host's measured NetFlow, shared across the
registrable domains it queried. Pi-hole archives the question, not the
answer address, so this is not a per-flow join.
"""
import concurrent.futures
import ipaddress
import math
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from .alerts import parse_time
from .client import QueryError
from .destinations import site_name
from .filterlog import parse_filterlog
from .hosts import normalize_ip
from .ops import lan_filter, not_lan_filter
from .service import NETWORKS, number, stamp

UTC = timezone.utc
HOST_FETCH = 64
BLOCK_SAMPLE = 800
DOMAIN_FETCH = 40
BLOCKED_FETCH = 12
DNS_TOP = 8
FRESH_SECONDS = 900
RANGES = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}
LABELS = {3600: "last hour", 86400: "last 24h", 604800: "last 7 days"}
STEPS = {3600: 300, 86400: 900, 604800: 3600}
STEP_TOKEN = {300: "5m", 900: "15m", 3600: "1h"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DNS_SAFE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?")
FIREWALL_LABEL = "OPNsense 192.168.5.1"
DNS_LABEL = "Pi-hole ns0 192.168.5.238"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Longest suffix wins. Display categories only; not a threat classification.
CATEGORIES = (
    ("music.youtube.com", "Music"),
    ("youtube.com", "Streaming"),
    ("googlevideo.com", "Streaming"),
    ("ytimg.com", "Streaming"),
    ("netflix.com", "Streaming"),
    ("nflxvideo.net", "Streaming"),
    ("disneyplus.com", "Streaming"),
    ("bamgrid.com", "Streaming"),
    ("hulu.com", "Streaming"),
    ("primevideo.com", "Streaming"),
    ("aiv-cdn.net", "Streaming"),
    ("peacocktv.com", "Streaming"),
    ("pbs.org", "Streaming"),
    ("spotify.com", "Music"),
    ("scdn.co", "Music"),
    ("pandora.com", "Music"),
    ("icloud.com", "Apple services"),
    ("mzstatic.com", "Apple services"),
    ("cdn-apple.com", "Apple services"),
    ("apple.com", "Apple services"),
    ("akamaized.net", "CDN"),
    ("akamai.net", "CDN"),
    ("akamaihd.net", "CDN"),
    ("fastly.net", "CDN"),
    ("cloudfront.net", "CDN"),
    ("gstatic.com", "CDN"),
    ("googleapis.com", "Cloud storage"),
    ("gvt1.com", "Cloud storage"),
    ("sharepoint.com", "Cloud storage"),
    ("onedrive.com", "Cloud storage"),
    ("dropbox.com", "Cloud storage"),
    ("githubusercontent.com", "Blocklists"),
    ("github.com", "Dev"),
    ("gitlab.com", "Dev"),
    ("cursor.com", "Dev"),
    ("pypi.org", "Dev"),
    ("docker.io", "Containers"),
    ("ghcr.io", "Containers"),
    ("ubuntu.com", "Updates"),
    ("debian.org", "Updates"),
    ("opnsense.org", "Updates"),
    ("ubnt.com", "Updates"),
    ("stun.l.google.com", "STUN"),
    ("huggingface.co", "AI models"),
    ("tailscale.com", "Remote access"),
    ("quickconnect.to", "Remote access"),
    ("teams.microsoft.com", "Work"),
    ("office.com", "Work"),
    ("office365.com", "Work"),
    ("microsoft.com", "Work"),
    ("samsungcloudsolution.com", "Vendor cloud"),
    ("samsungcloudsolution.net", "Vendor cloud"),
    ("samsung.com", "Vendor cloud"),
    ("roku.com", "Vendor cloud"),
    ("sonos.com", "Vendor cloud"),
    ("ring.com", "Vendor cloud"),
    ("ui.com", "Vendor cloud"),
    ("nest.com", "Vendor cloud"),
    ("amazonaws.com", "Vendor cloud"),
    ("google.com", "Vendor cloud"),
    ("cloudflare-dns.com", "DNS upstream"),
    ("emergingthreats.net", "Security feeds"),
    ("mytotalconnectcomfort.com", "Vendor cloud"),
    ("synology.com", "Updates"),
)
SITE_NOTE = (
    "Bytes are this host's measured NetFlow, shared across the sites it queried. "
    "Pi-hole does not store answer addresses, so this is not a per-flow join. "
    "Categories come from a small domain map."
)
DEDUPE_NOTE = (
    "24h and 7d totals sum stored receipts without grouping event id, "
    "because that aggregation can exhaust VictoriaLogs."
)


def deduped(seconds):
    return seconds <= 3600


def category_for(domain):
    name = str(domain or "").strip().rstrip(".").lower()
    best = None
    best_len = -1
    for suffix, label in CATEGORIES:
        if name == suffix or name.endswith("." + suffix):
            if len(suffix) > best_len:
                best = label
                best_len = len(suffix)
    return best or "Other"


def _blob(*parts):
    return " ".join(str(part or "") for part in parts).lower().replace("-", " ").replace("_", " ")


def presentation(name, kind, notes):
    """Icon id and a short type line for a named host."""
    text = _blob(name, kind, notes)
    if "apple tv" in text:
        return "tv", "Apple TV"
    if "roku" in text:
        return "tv", "Roku"
    if "samsung" in text and "tv" in text:
        return "tv", "Samsung TV"
    if kind == "nas" or "synology" in text or " nas" in text or text.startswith("nas"):
        return "nas", "NAS"
    if kind == "switch" or "usw " in text:
        return "router", "Switch"
    if kind == "ap" or "u7 pro" in text:
        return "wifi", "Access point"
    if kind == "controller" or "unifi" in text:
        return "wifi", "UniFi controller"
    if "sonos" in text:
        return "speaker", "Sonos"
    if "ring" in text or "doorbell" in text:
        return "bellring", "Ring doorbell"
    if "nest" in text:
        return "mic", "Smart speaker"
    if "thermostat" in text or "honeywell" in text:
        return "thermo", "Thermostat"
    if kind == "dns" or "pi-hole" in text or "pihole" in text:
        return "dns", "DNS filter"
    if kind == "router" or "opnsense" in text or "firewall" in text:
        return "router", "Firewall"
    if kind == "vm":
        return "server", "Virtual machine"
    if kind == "server" or "server" in text or "ubuntu" in text or "ai-02" in text or "ai 02" in text:
        return "server", "Server"
    if kind == "phone" or "iphone" in text:
        return "devices", "Phone"
    if kind == "tablet" or "ipad" in text:
        return "devices", "Tablet"
    if kind == "printer" or "printer" in text:
        return "monitor", "Printer"
    if kind == "laptop":
        return "monitor", "Laptop"
    if "tv" in text or kind == "streaming":
        return "tv", "Streaming device"
    if kind == "iot":
        return "mic", "IoT device"
    if kind == "workstation" or "workstation" in text:
        return "monitor", "Workstation"
    return "monitor", "Host"


def location_from(notes):
    if not isinstance(notes, str):
        return ""
    first = notes.split(".")[0].strip()
    if not first or len(first) > 48:
        return ""
    return first


def _is_lan(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in network for network in NETWORKS)


def _synthetic(ip):
    return {
        "id": "h-" + ip.replace(".", "-"),
        "name": ip,
        "ip": ip,
        "type": "Observed host",
        "location": "",
        "icon": "monitor",
        "class": "",
        "dns_names": [],
        "notes": "",
    }


class Directory:
    def __init__(self, by_id, by_ip):
        self.by_id = by_id
        self.by_ip = by_ip

    @classmethod
    def build(cls, inventory, cached):
        by_id, by_ip = {}, {}

        def put(record):
            raw_ips = []
            primary = normalize_ip(record.get("ip"))
            if primary:
                raw_ips.append(primary)
            for item in record.get("ips") or ():
                addr = normalize_ip(item)
                if addr and addr not in raw_ips:
                    raw_ips.append(addr)
            available = [addr for addr in raw_ips if addr not in by_ip]
            if not available:
                return
            ip = available[0]
            ident = record.get("id") or ""
            if not ID_RE.fullmatch(ident) or ident in by_id:
                ident = "h-" + ip.replace(".", "-")
            record = {**record, "id": ident, "ip": ip, "ips": available}
            by_id[ident] = record
            for addr in available:
                by_ip[addr] = record

        for host in inventory or ():
            icon, kind = presentation(host.name, host.device_class, host.notes)
            put({
                "id": host.id,
                "name": host.name,
                "ip": host.ip,
                "ips": [host.ip] if host.ip else [],
                "type": kind,
                "location": location_from(host.notes),
                "icon": icon,
                "class": host.device_class,
                "dns_names": list(host.dns_names),
                "notes": host.notes or "",
            })
        for host in cached or ():
            if not isinstance(host, dict):
                continue
            name = host.get("name") or host.get("ip") or ""
            kind = host.get("class") or ""
            notes = host.get("notes") or ""
            icon, type_name = presentation(name, kind, notes)
            names = []
            for item in host.get("dns_names") or []:
                if isinstance(item, str) and DNS_SAFE.fullmatch(item):
                    names.append(item)
            put({
                "id": host.get("id") or "",
                "name": name,
                "ip": host.get("ip"),
                "ips": list(host.get("ips") or ()),
                "type": type_name,
                "location": location_from(notes),
                "icon": icon,
                "class": kind,
                "dns_names": names,
                "notes": notes,
                "match_name": host.get("source") != "pihole",
            })
        name_counts = Counter(
            record["name"].casefold()
            for record in by_ip.values()
            if isinstance(record.get("name"), str) and record["name"]
        )
        for record in by_ip.values():
            if name_counts.get((record.get("name") or "").casefold(), 0) > 1:
                record["match_name"] = False
        return cls(by_id, by_ip)

    @classmethod
    def from_sources(cls, cache):
        cached = []
        try:
            cached = cache.snapshot().get("hosts") or []
        except Exception:
            cached = []
        inventory = ()
        try:
            from .inventory import load_inventory
            inventory = load_inventory().hosts
        except Exception:
            inventory = ()
        return cls.build(inventory, cached)

    def resolve(self, host_id):
        if host_id in self.by_id:
            return self.by_id[host_id]
        if host_id.startswith("h-") and ID_RE.fullmatch(host_id):
            ip = normalize_ip(host_id[2:].replace("-", "."))
            if ip and _is_lan(ip):
                return self.by_ip.get(ip) or _synthetic(ip)
        return None

    def known(self, ip):
        return self.by_ip.get(ip)


def client_expr(record):
    """IP(s) plus inventory-safe names. Untrusted labels are not interpolated."""
    ips = list(record.get("ips") or ([record["ip"]] if record.get("ip") else []))
    parts = [f'client_ip:="{addr}"' for addr in ips]
    seen = set(ips)
    candidates = list(record.get("dns_names") or [])
    if record.get("match_name", True):
        candidates.insert(0, record.get("name"))
    for name in candidates:
        if not isinstance(name, str) or name in seen or not DNS_SAFE.fullmatch(name):
            continue
        seen.add(name)
        parts.append(f'client_name:="{name}"')
    return "(" + " OR ".join(parts) + ")"


def _span(start, end):
    return f"_time:[{stamp(start)},{stamp(end)})"


def _flow(start, end):
    return f"{_span(start, end)} app_name:=opnsense-flow schema:=2"


def _step(seconds):
    return STEP_TOKEN[STEPS[seconds]]


def overview_queries(start, end, seconds):
    flow = _flow(start, end)
    step = _step(seconds)
    look = _span(end - timedelta(hours=6), end)
    queries = {
        "fresh_flow": f"{look} app_name:=opnsense-flow schema:=2 | sort by (_time) desc | limit 1 | fields _time",
        "fresh_dns": f"{look} app_name:=pihole-dns | sort by (_time) desc | limit 1 | fields _time",
        "fresh_fw": f"{look} app_name:=filterlog | sort by (_time) desc | limit 1 | fields _time",
        "blocks": f"{_span(start, end)} app_name:=filterlog action:=block | stats count() blocks",
    }
    if deduped(seconds):
        queries["upload"] = (
            f"{flow} {lan_filter('src_addr')} "
            "| stats by (event_id, src_addr) max(bytes) bytes "
            "| stats by (src_addr) sum(bytes) bytes "
            f"| sort by (bytes) desc | limit {HOST_FETCH}"
        )
        queries["download"] = (
            f"{flow} {lan_filter('dst_addr')} {not_lan_filter('src_addr')} "
            "| stats by (event_id, dst_addr) max(bytes) bytes "
            "| stats by (dst_addr) sum(bytes) bytes "
            f"| sort by (bytes) desc | limit {HOST_FETCH}"
        )
        queries["series"] = (
            f"{flow} | stats by (event_id, _time:{step}) max(bytes) bytes "
            "| stats by (_time) sum(bytes) bytes | sort by (_time)"
        )
        queries["total"] = (
            f"{flow} | stats by (event_id) max(bytes) bytes | stats sum(bytes) bytes"
        )
        queries["dns_blocked"] = (
            f"{_span(start, end)} app_name:=pihole-dns outcome:=blocked "
            "| stats by (event_id) count() rows | stats count() queries"
        )
    else:
        queries["upload"] = (
            f"{flow} {lan_filter('src_addr')} "
            "| stats by (src_addr) sum(bytes) bytes "
            f"| sort by (bytes) desc | limit {HOST_FETCH}"
        )
        queries["download"] = (
            f"{flow} {lan_filter('dst_addr')} {not_lan_filter('src_addr')} "
            "| stats by (dst_addr) sum(bytes) bytes "
            f"| sort by (bytes) desc | limit {HOST_FETCH}"
        )
        queries["series"] = (
            f"{flow} | stats by (_time:{step}) sum(bytes) bytes | sort by (_time)"
        )
        queries["total"] = f"{flow} | stats sum(bytes) bytes"
        queries["dns_blocked"] = (
            f"{_span(start, end)} app_name:=pihole-dns outcome:=blocked | stats count() queries"
        )
    return queries


def _addr_expr(field, ips):
    if len(ips) == 1:
        return f'{field}:="{ips[0]}"'
    return "(" + " OR ".join(f'{field}:="{addr}"' for addr in ips) + ")"


def host_queries(start, end, seconds, ip, expr):
    flow = _flow(start, end)
    step = _step(seconds)
    span = _span(start, end)
    ips = [ip] if isinstance(ip, str) else list(ip)
    src_match = _addr_expr("src_addr", ips)
    dst_match = _addr_expr("dst_addr", ips)
    fw_src = _addr_expr("src", ips)
    dns = f"{span} app_name:=pihole-dns {expr}"
    series_match = f"({src_match} OR ({dst_match} {not_lan_filter('src_addr')}))"
    queries = {
        "fw_blocks": f"{span} app_name:=filterlog action:=block {fw_src} | stats count() blocks",
    }
    if deduped(seconds):
        queries["upload"] = (
            f"{flow} {src_match} | stats by (event_id) max(bytes) bytes | stats sum(bytes) bytes"
        )
        queries["download"] = (
            f"{flow} {dst_match} {not_lan_filter('src_addr')} "
            "| stats by (event_id) max(bytes) bytes | stats sum(bytes) bytes"
        )
        queries["series"] = (
            f"{flow} {series_match} "
            f"| stats by (event_id, _time:{step}) max(bytes) bytes "
            "| stats by (_time) sum(bytes) bytes | sort by (_time)"
        )
        queries["sites"] = (
            f"{dns} NOT outcome:=blocked "
            "| stats by (event_id, domain) count() rows "
            "| stats by (domain) count() queries "
            f"| sort by (queries) desc | limit {DOMAIN_FETCH}"
        )
        queries["blocked_dns"] = (
            f"{dns} outcome:=blocked "
            "| stats by (event_id, domain) count() rows "
            "| stats by (domain) count() queries "
            f"| sort by (queries) desc | limit {BLOCKED_FETCH}"
        )
        queries["blocked_dns_total"] = (
            f"{dns} outcome:=blocked | stats by (event_id) count() rows | stats count() queries"
        )
    else:
        queries["upload"] = f"{flow} {src_match} | stats sum(bytes) bytes"
        queries["download"] = (
            f"{flow} {dst_match} {not_lan_filter('src_addr')} | stats sum(bytes) bytes"
        )
        queries["series"] = (
            f"{flow} {series_match} "
            f"| stats by (_time:{step}) sum(bytes) bytes | sort by (_time)"
        )
        queries["sites"] = (
            f"{dns} NOT outcome:=blocked | stats by (domain) count() queries "
            f"| sort by (queries) desc | limit {DOMAIN_FETCH}"
        )
        queries["blocked_dns"] = (
            f"{dns} outcome:=blocked | stats by (domain) count() queries "
            f"| sort by (queries) desc | limit {BLOCKED_FETCH}"
        )
        queries["blocked_dns_total"] = f"{dns} outcome:=blocked | stats count() queries"
    return queries


def firewall_queries(start, end, seconds):
    span = _span(start, end)
    step = _step(seconds)
    look = _span(end - timedelta(hours=6), end)
    return {
        "fresh": f"{look} app_name:=filterlog | sort by (_time) desc | limit 1 | fields _time",
        "series": (
            f"{span} app_name:=filterlog action:=block | stats by (_time:{step}) count() blocks | sort by (_time)"
        ),
        "blocked": f"{span} app_name:=filterlog action:=block | stats count() blocks",
        "allowed": f"{span} app_name:=filterlog action:=pass | stats count() blocks",
        "sample": (
            f"{span} app_name:=filterlog action:=block | sort by (_time) desc "
            f"| limit {BLOCK_SAMPLE} | fields _time, _msg"
        ),
    }


def dns_queries(start, end, seconds, expr=None):
    span = f"{_span(start, end)} app_name:=pihole-dns" + (f" {expr}" if expr else "")
    step = _step(seconds)
    look = _span(end - timedelta(hours=6), end)
    queries = {
        "fresh": f"{look} app_name:=pihole-dns | sort by (_time) desc | limit 1 | fields _time",
    }
    if deduped(seconds):
        queries["series"] = (
            f"{span} | stats by (event_id, outcome, _time:{step}) count() rows "
            "| stats by (outcome, _time) count() queries | sort by (_time)"
        )
        queries["domains"] = (
            f"{span} | stats by (event_id, domain) count() rows "
            "| stats by (domain) count() queries | sort by (queries) desc | limit 12"
        )
        queries["clients"] = (
            f"{span} | stats by (event_id, client_ip) max(client_name) client_name "
            "| stats by (client_ip) count() queries, max(client_name) client_name "
            "| sort by (queries) desc | limit 12"
        )
        queries["blocked_clients"] = (
            f"{span} outcome:=blocked | stats by (event_id, client_ip) count() rows "
            "| stats by (client_ip) count() queries | sort by (queries) desc | limit 24"
        )
        queries["unique"] = (
            f"{span} | stats by (event_id, domain) count() rows "
            "| stats by (domain) count() rows | stats count() domains"
        )
        queries["totals"] = (
            f"{span} | stats by (event_id, outcome) count() rows | stats by (outcome) count() queries"
        )
    else:
        queries["series"] = (
            f"{span} | stats by (outcome, _time:{step}) count() queries | sort by (_time)"
        )
        queries["domains"] = (
            f"{span} | stats by (domain) count() queries | sort by (queries) desc | limit 12"
        )
        queries["clients"] = (
            f"{span} | stats by (client_ip) count() queries, max(client_name) client_name "
            "| sort by (queries) desc | limit 12"
        )
        queries["blocked_clients"] = (
            f"{span} outcome:=blocked | stats by (client_ip) count() queries "
            "| sort by (queries) desc | limit 24"
        )
        queries["unique"] = f"{span} | stats by (domain) count() queries | stats count() domains"
        queries["totals"] = f"{span} | stats by (outcome) count() queries"
    return queries


def run_all(client, queries, budget=22):
    deadline = time.monotonic() + budget
    results = {}

    def run(query):
        try:
            return client.query(query, deadline)
        except QueryError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(run, query): name for name, query in queries.items()}
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()
    if results and all(value is None for value in results.values()):
        raise QueryError("network")
    return results


def _window(start, end, seconds):
    return {
        "start": stamp(start),
        "end": stamp(end),
        "seconds": seconds,
        "label": LABELS[seconds],
    }


def _range_name(seconds):
    return {value: key for key, value in RANGES.items()}[seconds]


def scalar_int(rows, *keys):
    if not rows or not isinstance(rows[0], dict):
        return None
    for key in keys:
        if key in rows[0] and rows[0][key] not in (None, ""):
            try:
                return number(rows[0][key])
            except (ValueError, TypeError):
                return None
    return None


def bytes_by_addr(rows, field):
    if rows is None:
        return None
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ip = normalize_ip(str(row.get(field) or ""))
        if not ip:
            continue
        try:
            found[ip] = found.get(ip, 0) + number(row.get("bytes"))
        except (ValueError, TypeError):
            continue
    return found


def bucket_starts(start, end, step):
    start_s = int((start - EPOCH).total_seconds())
    end_s = int((end - EPOCH).total_seconds())
    if end_s <= start_s or step <= 0:
        return []
    cursor = start_s - (start_s % step)
    starts = []
    while cursor < end_s:
        if cursor + step > start_s:
            starts.append(EPOCH + timedelta(seconds=cursor))
        cursor += step
    return starts


def floor_bucket(moment, step):
    seconds = int((moment - EPOCH).total_seconds())
    return EPOCH + timedelta(seconds=seconds - (seconds % step))


def accumulate(start, end, step, rows, reader):
    if rows is None:
        return None
    starts = bucket_starts(start, end, step)
    totals = {stamp(bucket): 0 for bucket in starts}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        seen = parse_time(row.get("_time"))
        if seen is None:
            continue
        key = stamp(floor_bucket(seen, step))
        if key not in totals:
            continue
        try:
            totals[key] += reader(row)
        except (ValueError, TypeError):
            continue
    return [{"time": stamp(bucket), "value": totals[stamp(bucket)]} for bucket in starts]


def split_weighted(total, weights):
    total = int(total)
    if total < 0:
        total = 0
    if not weights:
        return []
    whole = sum(weights)
    if whole <= 0 or total == 0:
        return [0 for _ in weights]
    raw = [int(total * weight / whole) for weight in weights]
    raw[-1] += total - sum(raw)
    if raw[-1] < 0:
        raw[-1] = 0
    return raw


def _diurnal(moment):
    """Rough Eastern-time daily shape. Fixed UTC−5, no zone database."""
    shifted = moment.astimezone(UTC) + timedelta(hours=-5)
    hour = shifted.hour + shifted.minute / 60.0

    def gauss(center, width):
        delta = ((hour - center + 36) % 24) - 12
        return math.exp(-(delta * delta) / (2 * width * width))

    return 0.30 + 0.45 * gauss(13, 3.5) + 0.75 * gauss(20.5, 2.2)


def weighted_points(start, end, step, total, spike_at=None):
    starts = bucket_starts(start, end, step)
    if not starts:
        return [], None
    weights = []
    for bucket in starts:
        mid = bucket + timedelta(seconds=step / 2)
        weights.append(max(_diurnal(mid), 0.05))
    index = None
    if spike_at is not None:
        for position, bucket in enumerate(starts):
            if bucket <= spike_at < bucket + timedelta(seconds=step):
                index = position
                break
        if index is not None:
            others = sum(weights) - weights[index]
            weights[index] = max(weights[index], others * 0.22)
    amounts = split_weighted(total, weights)
    points = [{"time": stamp(bucket), "value": amount} for bucket, amount in zip(starts, amounts)]
    return points, index


def find_spike(values):
    if len(values) < 8:
        return None
    peak = max(values)
    if peak < 40:
        return None
    index = values.index(peak)
    ordered = sorted(values)
    median = ordered[len(ordered) // 2]
    if median <= 0:
        if peak < 80:
            return None
    elif peak < median * 4:
        return None
    return index


def spike_payload(points, index, detail):
    if index is None or not points:
        return None
    resolved = None
    peak = points[index]["value"]
    if index + 1 < len(points) and points[index + 1]["value"] < peak * 0.45:
        resolved = points[index + 1]["time"]
    return {
        "index": index,
        "time": points[index]["time"],
        "detail": detail,
        "resolved": resolved,
    }


def _fresh(rows, now):
    if rows is None:
        return "unavailable", None
    if not rows or not isinstance(rows[0], dict):
        return "critical", None
    seen = parse_time(rows[0].get("_time"))
    if seen is None:
        return "unavailable", None
    age = (now - seen).total_seconds()
    if age <= FRESH_SECONDS:
        return "fresh", stamp(seen)
    return "stale", stamp(seen)


def _overall(states):
    if states and all(state == "fresh" for state in states):
        return "healthy"
    if states and all(state in ("unavailable", "critical") for state in states):
        return "unavailable"
    return "degraded"


def health_block(text, states, now_rows):
    overall = _overall(states)
    emphasis = None
    detail = None
    if overall == "degraded":
        detail = "behind"
    elif overall == "unavailable":
        detail = "unavailable"
    return {
        "state": overall,
        "text": text,
        "emphasis": emphasis,
        "detail": detail,
        "sources": now_rows,
    }


def _clean_domain(value):
    if not isinstance(value, str):
        value = str(value or "")
    name = "".join(ch for ch in value.strip() if ch.isprintable()).rstrip(".")
    if not name or len(name) > 253 or any(ch.isspace() for ch in name):
        return ""
    return name


def _domain_rows(rows):
    found = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = _clean_domain(row.get("domain"))
        if not name:
            continue
        try:
            queries = number(row.get("queries"))
        except (ValueError, TypeError):
            continue
        found.append({"name": name, "queries": queries})
    found.sort(key=lambda item: (-item["queries"], item["name"]))
    return found


def attribute_sites(download, upload, domain_rows, fetch_cap=DOMAIN_FETCH):
    grouped = {}
    site_cats = {}
    for item in _domain_rows(domain_rows):
        site = site_name(item["name"]) or item["name"]
        grouped[site] = grouped.get(site, 0) + item["queries"]
        cat = category_for(item["name"])
        if cat != "Other":
            cats = site_cats.setdefault(site, Counter())
            cats[cat] += item["queries"]
    ranked = sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
    capped = domain_rows is not None and len(domain_rows) >= fetch_cap
    if not ranked:
        if download or upload:
            return [{
                "name": "unattributed",
                "category": "Other",
                "download_bytes": int(download or 0),
                "upload_bytes": int(upload or 0),
                "queries": 0,
            }], 0, capped
        return [], 0, capped
    top = ranked[:6]
    rest = ranked[6:]
    if rest:
        top.append(("other", sum(queries for _, queries in rest)))
    weights = [queries for _, queries in top]
    down_parts = split_weighted(download or 0, weights)
    up_parts = split_weighted(upload or 0, weights)
    sites = []
    for (name, queries), down, up in zip(top, down_parts, up_parts):
        if name == "other":
            category = "Other"
        elif site_cats.get(name):
            category = sorted(site_cats[name].items(), key=lambda item: (-item[1], item[0]))[0][0]
        else:
            category = category_for(name)
        sites.append({
            "name": name,
            "category": category,
            "download_bytes": down,
            "upload_bytes": up,
            "queries": queries,
        })
    sites.sort(key=lambda item: (item["name"] == "other", -(item["download_bytes"] + item["upload_bytes"])))
    return sites, len(grouped), capped


def blocked_tags(rows, fetch_cap=BLOCKED_FETCH):
    ranked = _domain_rows(rows)
    if not ranked:
        return []
    shown = ranked[:5]
    rest = ranked[5:]
    tags = [{"name": item["name"], "queries": item["queries"]} for item in shown]
    if rest or (rows is not None and len(rows) >= fetch_cap and len(ranked) >= 5):
        extra = len(rest) if rest else 0
        if extra:
            tags.append({
                "name": f"other ({extra})",
                "queries": sum(item["queries"] for item in rest),
            })
    return tags


def _host_row(ip, download, upload, directory):
    known = directory.known(ip) if directory else None
    if known:
        record = known
    else:
        record = _synthetic(ip)
    return {
        "id": record["id"],
        "name": record["name"],
        "ip": ip,
        "type": record.get("type") or "Host",
        "location": record.get("location") or "",
        "icon": record.get("icon") or "monitor",
        "download_bytes": int(download),
        "upload_bytes": int(upload),
    }


def merge_host_traffic(upload_rows, download_rows, directory, total_bytes):
    upload = bytes_by_addr(upload_rows, "src_addr")
    download = bytes_by_addr(download_rows, "dst_addr")
    partial = upload is None or download is None
    upload = upload or {}
    download = download or {}
    capped = (upload_rows is not None and len(upload_rows) >= HOST_FETCH) or (
        download_rows is not None and len(download_rows) >= HOST_FETCH
    )
    addresses = set(upload) | set(download)
    by_id = {}
    for ip in sorted(addresses):
        if not _is_lan(ip):
            continue
        row = _host_row(ip, download.get(ip, 0), upload.get(ip, 0), directory)
        existing = by_id.get(row["id"])
        if existing is not None:
            existing["download_bytes"] += row["download_bytes"]
            existing["upload_bytes"] += row["upload_bytes"]
            known = directory.known(ip) if directory else None
            if known and known.get("ip"):
                existing["ip"] = known["ip"]
        else:
            known = directory.known(ip) if directory else None
            if known and known.get("ip"):
                row["ip"] = known["ip"]
            by_id[row["id"]] = row
    hosts = list(by_id.values())
    hosts.sort(key=lambda item: (-(item["download_bytes"] + item["upload_bytes"]), item["name"].lower()))
    assigned = sum(item["download_bytes"] + item["upload_bytes"] for item in hosts)
    other_bytes = None
    if total_bytes is not None:
        other_bytes = max(0, int(total_bytes) - assigned)
    other_hosts = None if capped else 0
    state = "partial" if partial or capped else "available"
    if upload_rows is None and download_rows is None and total_bytes is None:
        state = "unavailable"
    return hosts, other_bytes, other_hosts, state, capped


def _envelope(mode, illustrative, end, seconds, now):
    start = end - timedelta(seconds=seconds)
    return {
        "mode": mode,
        "illustrative": illustrative,
        "as_of": stamp(now),
        "range": _range_name(seconds),
        "window": _window(start, end, seconds),
        "deduped": deduped(seconds),
        "footnote": "" if illustrative or deduped(seconds) else DEDUPE_NOTE,
    }


def _series_payload(points, step, field="bytes"):
    rows = [] if points is None else [{"time": point["time"], field: point["value"]} for point in points]
    return {"step_seconds": step, "points": rows}


def reduce_overview(results, directory, end, seconds, now, mode="live"):
    start = end - timedelta(seconds=seconds)
    step = STEPS[seconds]
    total = scalar_int(results.get("total"), "bytes")
    hosts, other_bytes, other_hosts, state, _capped = merge_host_traffic(
        results.get("upload"), results.get("download"), directory, total,
    )
    if total is None and hosts:
        total = sum(item["download_bytes"] + item["upload_bytes"] for item in hosts)
        if other_bytes:
            total += other_bytes
    points = accumulate(start, end, step, results.get("series"), lambda row: number(row.get("bytes")))
    if points is None and state == "available":
        state = "partial"
    flow_state, _flow_at = _fresh(results.get("fresh_flow"), now)
    dns_state, _dns_at = _fresh(results.get("fresh_dns"), now)
    fw_state, _fw_at = _fresh(results.get("fresh_fw"), now)
    health = health_block(
        "All sources healthy · NetFlow, Pi-hole, OPNsense" if _overall([flow_state, dns_state, fw_state]) == "healthy"
        else "A source is behind · NetFlow, Pi-hole, OPNsense" if _overall([flow_state, dns_state, fw_state]) == "degraded"
        else "Source status could not be read",
        [flow_state, dns_state, fw_state],
        [
            {"id": "netflow", "state": flow_state},
            {"id": "pihole", "state": dns_state},
            {"id": "filterlog", "state": fw_state},
        ],
    )
    payload = _envelope(mode, False, end, seconds, now)
    payload.update({
        "state": state,
        "health": health,
        "totals": {
            "bytes": total,
            "active_hosts": len(hosts) if other_hosts == 0 else None,
            "active_hosts_capped": other_hosts is None,
            "firewall_blocks": scalar_int(results.get("blocks"), "blocks"),
            "dns_blocked": scalar_int(results.get("dns_blocked"), "queries"),
        },
        "throughput": _series_payload(points, step),
        "hosts": hosts,
        "other": {"hosts": other_hosts, "bytes": other_bytes},
        "notes": [
            "Upload is LAN-sourced NetFlow. Download is traffic to a LAN host from outside the LAN. Post-NAT WAN uploads stay in Other.",
            SITE_NOTE,
        ],
    })
    if not deduped(seconds):
        payload["notes"].insert(0, DEDUPE_NOTE)
    if hosts and payload["totals"]["active_hosts"] is None:
        payload["totals"]["active_hosts"] = len(hosts)
    return payload


def reduce_host(record, results, end, seconds, now, mode="live"):
    start = end - timedelta(seconds=seconds)
    step = STEPS[seconds]
    download = scalar_int(results.get("download"), "bytes") or 0
    upload = scalar_int(results.get("upload"), "bytes") or 0
    if results.get("download") is None and results.get("upload") is None:
        download = upload = 0
        traffic_state = "unavailable"
    elif results.get("download") is None or results.get("upload") is None:
        traffic_state = "partial"
    else:
        traffic_state = "available"
    sites, contacted, capped = attribute_sites(
        download if results.get("download") is not None else 0,
        upload if results.get("upload") is not None else 0,
        results.get("sites"),
    )
    if results.get("sites") is None:
        sites = []
        contacted = None
        site_state = "unavailable"
    else:
        site_state = "partial" if capped else "available"
    points = accumulate(start, end, step, results.get("series"), lambda row: number(row.get("bytes")))
    if points is None and traffic_state == "available":
        traffic_state = "partial"
    blocked = blocked_tags(results.get("blocked_dns")) if results.get("blocked_dns") is not None else []
    blocked_total = scalar_int(results.get("blocked_dns_total"), "queries")
    if blocked_total is None and results.get("blocked_dns") is not None:
        blocked_total = sum(item["queries"] for item in blocked)
    payload = _envelope(mode, False, end, seconds, now)
    payload.update({
        "state": "unavailable" if traffic_state == "unavailable" and site_state == "unavailable" else (
            "partial" if "partial" in (traffic_state, site_state) or "unavailable" in (traffic_state, site_state) else "available"
        ),
        "host": {
            "id": record["id"],
            "name": record["name"],
            "ip": record["ip"],
            "type": record.get("type") or "Host",
            "location": record.get("location") or "",
            "icon": record.get("icon") or "monitor",
            "download_bytes": download if results.get("download") is not None else None,
            "upload_bytes": upload if results.get("upload") is not None else None,
        },
        "sites_contacted": contacted,
        "sites_capped": capped,
        "sites": sites,
        "blocked": blocked,
        "blocked_total": blocked_total,
        "blocked_state": "unavailable" if results.get("blocked_dns") is None else "available",
        "firewall_blocks": scalar_int(results.get("fw_blocks"), "blocks"),
        "throughput": _series_payload(points, step),
        "attribution": "query-weighted",
        "site_note": SITE_NOTE,
    })
    return payload


def _service_label(ip, proto, port):
    if (ip, proto, port) == ("255.255.255.255", "UDP", 10001):
        return "UniFi discovery"
    if (ip, proto, port) == ("239.255.255.250", "UDP", 1900):
        return "SSDP"
    if (ip, proto, port) == ("224.0.0.251", "UDP", 5353):
        return "mDNS"
    if proto == "UDP" and port == 3478:
        return "STUN"
    if port == 53:
        return "DNS"
    if port == 443:
        return "HTTPS"
    if port == 80:
        return "HTTP"
    if ip.startswith("224.") or ip.startswith("239."):
        return "Multicast"
    if ip == "255.255.255.255":
        return "Broadcast"
    return ""


def _port_text(ports):
    if not ports:
        return "", None
    common, _count = Counter(ports).most_common(1)[0]
    uniq = sorted(set(ports))
    if len(uniq) >= 4 and uniq[-1] - uniq[0] <= 512:
        top_share = Counter(ports)[common] / len(ports)
        if top_share < 0.5:
            return f"{uniq[0]}–{uniq[-1]}", common
    return str(common), common


def reduce_firewall_sample(rows, directory, cap=BLOCK_SAMPLE):
    if rows is None:
        return None
    events = []
    unparsed = 0
    for row in rows:
        if not isinstance(row, dict):
            unparsed += 1
            continue
        event = parse_filterlog(row, NETWORKS)
        if event.get("parse_error"):
            unparsed += 1
            continue
        if event.get("action") != "block":
            continue
        event["_time"] = row.get("_time")
        events.append(event)
    capped = len(rows) >= cap
    sources_counter = Counter(event["source"] for event in events if event.get("source"))
    ranked = sources_counter.most_common(5)
    listed = {ip for ip, _count in ranked}
    sources = []
    for ip, count in ranked:
        known = directory.known(ip) if directory else None
        linkable = bool(known) or _is_lan(ip)
        ident = known["id"] if known else ("h-" + ip.replace(".", "-") if _is_lan(ip) else None)
        sources.append({
            "id": ident,
            "name": known["name"] if known else ip,
            "ip": ip,
            "count": count,
            "link": linkable,
        })
    other_count = sum(count for ip, count in sources_counter.items() if ip not in listed)
    groups = {}
    for event in events:
        key = (event.get("destination") or "", (event.get("protocol") or "").upper())
        groups.setdefault(key, []).append(event)
    destinations = []
    for (ip, proto), items in groups.items():
        ports = [item["destination_port"] for item in items if item.get("destination_port") is not None]
        port_label, sample_port = _port_text(ports) if ports else ("", None)
        destinations.append({
            "name": ip,
            "protocol": proto,
            "port": port_label,
            "label": _service_label(ip, proto, sample_port),
            "count": len(items),
        })
    destinations.sort(key=lambda item: (-item["count"], item["name"]))
    rules = Counter(str(event.get("rule_number") or "") for event in events)
    rules.pop("", None)
    top_rule = None
    if rules and events:
        rule, count = rules.most_common(1)[0]
        top_rule = {
            "id": rule,
            "label": f"#{rule}" if rule.isdigit() else rule,
            "name": None,
            "percent": round(100 * count / len(events)),
        }
    return {
        "sources": sources,
        "other": {
            "count": other_count,
            "hosts": max(0, len(sources_counter) - len(ranked)),
        },
        "destinations": destinations[:5],
        "top_rule": top_rule,
        "unparsed": unparsed,
        "capped": capped,
        "events": events,
        "sample_count": len(events),
    }


def reduce_firewall(results, directory, end, seconds, now, mode="live"):
    start = end - timedelta(seconds=seconds)
    step = STEPS[seconds]
    points = accumulate(start, end, step, results.get("series"), lambda row: number(row.get("blocks"))) or []
    sample = reduce_firewall_sample(results.get("sample"), directory)
    index = find_spike([point["value"] for point in points])
    detail = "spike"
    if index is not None and sample is not None:
        bucket = parse_time(points[index]["time"])
        if bucket is not None:
            counts = Counter()
            for event in sample["events"]:
                seen = parse_time(event.get("_time"))
                if seen and bucket <= seen < bucket + timedelta(seconds=step) and event.get("source"):
                    counts[event["source"]] += 1
            if counts:
                ip, _count = counts.most_common(1)[0]
                known = directory.known(ip) if directory else None
                detail = "spike · " + (known["name"] if known else ip)
    fw_state, _seen = _fresh(results.get("fresh"), now)
    health_state = "healthy" if fw_state == "fresh" else "degraded" if fw_state == "stale" else "unavailable"
    payload = _envelope(mode, False, end, seconds, now)
    payload.update({
        "state": "unavailable" if results.get("blocked") is None and results.get("series") is None else (
            "partial" if sample is None or (sample and sample["capped"]) or results.get("blocked") is None else "available"
        ),
        "health": {
            "state": health_state,
            "text": FIREWALL_LABEL,
            "emphasis": "healthy" if health_state == "healthy" else None,
            "detail": None if health_state == "healthy" else ("behind" if health_state == "degraded" else "unavailable"),
        },
        "blocked": scalar_int(results.get("blocked"), "blocks"),
        "allowed": scalar_int(results.get("allowed"), "blocks"),
        "series": {"step_seconds": step, "points": [{"time": point["time"], "blocks": point["value"]} for point in points]},
        "spike": spike_payload(points, index, detail),
        "sources": sample["sources"] if sample else [],
        "other": sample["other"] if sample else {"count": 0, "hosts": 0},
        "destinations": sample["destinations"] if sample else [],
        "top_rule": sample["top_rule"] if sample else None,
        "rule_scope": "sampled blocks" if sample and sample["capped"] else "blocks",
        "lists_capped": bool(sample and sample["capped"]),
        "note": (
            "Top sources and destinations are the newest 800 logged blocks. "
            "The chart counts every matching receipt. Only logged rules are visible."
            if sample and sample["capped"] else
            "Only logged filterlog decisions are counted."
        ),
    })
    return payload


def _clean_name(value):
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if not text or len(text) > 80 or any(ord(char) < 32 for char in text):
        return ""
    return text


def reduce_dns(results, directory, end, seconds, now, mode="live", record=None):
    start = end - timedelta(seconds=seconds)
    step = STEPS[seconds]
    answered_rows = []
    blocked_rows = []
    for row in results.get("series") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("outcome") or "") == "blocked":
            blocked_rows.append(row)
        else:
            answered_rows.append(row)
    series = []
    if results.get("series") is not None:
        answered = accumulate(start, end, step, answered_rows, lambda row: number(row.get("queries"))) or []
        blocked = accumulate(start, end, step, blocked_rows, lambda row: number(row.get("queries"))) or []
        for left, right in zip(answered, blocked):
            series.append({"time": left["time"], "answered": left["value"], "blocked": right["value"]})
    domains = []
    for item in _domain_rows(results.get("domains"))[:6]:
        domains.append({**item, "category": category_for(item["name"])})
    blocked_by_ip = {}
    for row in results.get("blocked_clients") or []:
        if not isinstance(row, dict):
            continue
        ip = normalize_ip(str(row.get("client_ip") or ""))
        if not ip:
            continue
        try:
            blocked_by_ip[ip] = blocked_by_ip.get(ip, 0) + number(row.get("queries"))
        except (ValueError, TypeError):
            continue
    clients_by_ip = {}
    for row in results.get("clients") or []:
        if not isinstance(row, dict):
            continue
        ip = normalize_ip(str(row.get("client_ip") or ""))
        if not ip:
            continue
        try:
            queries = number(row.get("queries"))
        except (ValueError, TypeError):
            continue
        raw_name = _clean_name(row.get("client_name"))
        existing = clients_by_ip.get(ip)
        if existing is not None:
            existing["queries"] += queries
            if not existing["raw_name"] and raw_name:
                existing["raw_name"] = raw_name
            continue
        clients_by_ip[ip] = {"ip": ip, "queries": queries, "raw_name": raw_name}
    clients_by_key = {}
    for ip, item in clients_by_ip.items():
        known = directory.known(ip) if directory else None
        ident = known["id"] if known else ("h-" + ip.replace(".", "-") if _is_lan(ip) else None)
        key = ident or ip
        existing = clients_by_key.get(key)
        if existing is not None:
            existing["queries"] += item["queries"]
            existing["blocked"] += blocked_by_ip.get(ip, 0)
            continue
        name = known["name"] if known else (item["raw_name"] or ip)
        clients_by_key[key] = {
            "id": ident,
            "name": name,
            "ip": known["ip"] if known and known.get("ip") else ip,
            "icon": known["icon"] if known else "monitor",
            "queries": item["queries"],
            "blocked": blocked_by_ip.get(ip, 0),
            "link": bool(known) or _is_lan(ip),
        }
    clients = list(clients_by_key.values())
    clients.sort(key=lambda item: -item["queries"])
    clients = clients[:DNS_TOP]
    total_queries = 0
    blocked_queries = 0
    totals_ok = results.get("totals") is not None
    for row in results.get("totals") or []:
        if not isinstance(row, dict):
            continue
        try:
            count = number(row.get("queries"))
        except (ValueError, TypeError):
            continue
        total_queries += count
        if str(row.get("outcome") or "") == "blocked":
            blocked_queries += count
    dns_state, _seen = _fresh(results.get("fresh"), now)
    health_state = "healthy" if dns_state == "fresh" else "degraded" if dns_state == "stale" else "unavailable"
    payload = _envelope(mode, False, end, seconds, now)
    failed = results.get("totals") is None and results.get("series") is None
    payload.update({
        "state": "unavailable" if failed else "partial" if not totals_ok or results.get("domains") is None else "available",
        "health": {
            "state": health_state,
            "text": DNS_LABEL,
            "emphasis": "healthy" if health_state == "healthy" else None,
            "detail": None if health_state == "healthy" else ("behind" if health_state == "degraded" else "unavailable"),
        },
        "queries": total_queries if totals_ok else None,
        "blocked": blocked_queries if totals_ok else None,
        "unique_domains": scalar_int(results.get("unique"), "domains"),
        "host": (
            {"id": record["id"], "name": record["name"], "ip": record["ip"]}
            if record
            else None
        ),
        "series": {"step_seconds": step, "points": series},
        "domains": domains,
        "clients": clients,
        "note": "Counts are Pi-hole queries. A blocked lookup is not by itself an intrusion.",
    })
    return payload


def live_overview(client, end, seconds, directory, now=None):
    now = (now or datetime.now(UTC)).astimezone(UTC)
    end = end.astimezone(UTC)
    start = end - timedelta(seconds=seconds)
    results = run_all(client, overview_queries(start, end, seconds))
    return reduce_overview(results, directory, end, seconds, now)


def live_host(client, end, seconds, record, now=None):
    now = (now or datetime.now(UTC)).astimezone(UTC)
    end = end.astimezone(UTC)
    start = end - timedelta(seconds=seconds)
    ips = record.get("ips") or [record["ip"]]
    results = run_all(client, host_queries(start, end, seconds, ips, client_expr(record)))
    return reduce_host(record, results, end, seconds, now)


def live_firewall(client, end, seconds, directory, now=None):
    now = (now or datetime.now(UTC)).astimezone(UTC)
    end = end.astimezone(UTC)
    start = end - timedelta(seconds=seconds)
    results = run_all(client, firewall_queries(start, end, seconds))
    view = reduce_firewall(results, directory, end, seconds, now)
    view.pop("events", None)
    return view


def live_dns(client, end, seconds, directory, now=None, record=None):
    now = (now or datetime.now(UTC)).astimezone(UTC)
    end = end.astimezone(UTC)
    start = end - timedelta(seconds=seconds)
    expr = client_expr(record) if record else None
    results = run_all(client, dns_queries(start, end, seconds, expr=expr))
    return reduce_dns(results, directory, end, seconds, now, record=record)
