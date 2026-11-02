"""Bounded read model for the daily Ops Home page.

Queries go through the existing authenticated VictoriaLogs client. Windows for
flow and DNS rankings stay at 15 minutes or one hour: a multi-day
``stats by (event_id)`` can exhaust VictoriaLogs memory. Freshness thresholds
match the alert checker (warning at 15 minutes, critical at 30 minutes). The
alert heartbeat uses the checker's 3-minute silence limit instead. LAN ranges
come from the presentation network list, not from the browser.
"""
import concurrent.futures
import ipaddress
import re
import time
from datetime import datetime, timedelta, timezone

from .alerts import parse_time
from .client import QueryError
from .filterlog import parse_filterlog
from .models import OpsHome
from .service import NETWORKS, number, stamp

UTC = timezone.utc
LOOKBACK = timedelta(hours=6)
WARNING_SECONDS = 900
CRITICAL_SECONDS = 1800
HEARTBEAT_LIMIT_SECONDS = 180
BLOCK_CAP = 800
TALKER_FETCH = 24
DNS_FETCH = 16
LIST_LIMIT = 8
TALKER_LIMIT = 10
WINDOWS = {900: "Last 15 minutes", 3600: "Last hour"}
_CIDR = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}")
_GATEWAY_DOWN = re.compile(r"(?i)alarm|loss\s*100\s*%|gateway down")
_GATEWAY_UP = re.compile(r"(?i)\bclear\b|gateway up|loss\s*0\s*%")

SOURCES = (
    {
        "id": "filterlog",
        "title": "OPNsense firewall",
        "query": "app_name:=filterlog",
        "cadence_seconds": 120,
        "warning_seconds": WARNING_SECONDS,
        "critical_seconds": CRITICAL_SECONDS,
    },
    {
        "id": "opnsense-flow",
        "title": "NetFlow",
        "query": "app_name:=opnsense-flow schema:=2",
        "cadence_seconds": 300,
        "warning_seconds": WARNING_SECONDS,
        "critical_seconds": CRITICAL_SECONDS,
    },
    {
        "id": "unifi-snapshot",
        "title": "UniFi inventory",
        "query": "app_name:=unifi-snapshot entity_kind:=snapshot",
        "cadence_seconds": 90,
        "warning_seconds": WARNING_SECONDS,
        "critical_seconds": CRITICAL_SECONDS,
    },
    {
        "id": "pihole-dns",
        "title": "Pi-hole DNS",
        "query": "app_name:=pihole-dns",
        "cadence_seconds": 180,
        "warning_seconds": WARNING_SECONDS,
        "critical_seconds": CRITICAL_SECONDS,
    },
    {
        "id": "pihole-snapshot",
        "title": "Pi-hole summary",
        "query": "app_name:=pihole-snapshot entity_kind:=snapshot",
        "cadence_seconds": 90,
        "warning_seconds": WARNING_SECONDS,
        "critical_seconds": CRITICAL_SECONDS,
    },
    {
        "id": "opnsense-syslog",
        "title": "OPNsense syslog",
        "query": "hostname:=OPNsense.internal",
        "cadence_seconds": 120,
        "warning_seconds": WARNING_SECONDS,
        "critical_seconds": CRITICAL_SECONDS,
    },
    {
        "id": "visibility-alert",
        "title": "Alert heartbeat",
        "query": "app_name:=visibility-alert kind:=heartbeat",
        "cadence_seconds": 60,
        "warning_seconds": HEARTBEAT_LIMIT_SECONDS,
        "critical_seconds": HEARTBEAT_LIMIT_SECONDS,
    },
)


def _cidr(network):
    if getattr(network, "version", None) != 4:
        raise ValueError("LAN filter is IPv4 only")
    text = str(network)
    if not _CIDR.fullmatch(text):
        raise ValueError("LAN filter")
    return text


def lan_filter(field, networks=NETWORKS):
    parts = [f'ipv4_range("{_cidr(network)}")' for network in networks]
    return f"{field}:(" + " OR ".join(parts) + ")"


def not_lan_filter(field, networks=NETWORKS):
    return " ".join(f'NOT {field}:ipv4_range("{_cidr(network)}")' for network in networks)


def _span(start, end):
    return f"_time:[{stamp(start)},{stamp(end)})"


def ops_queries(start, end, now, networks=NETWORKS):
    """Named LogsQL reads. Flow and DNS spans are the caller's short window."""
    lookback = now - LOOKBACK
    gateway_start = now - timedelta(minutes=30)
    queries = {}
    for spec in SOURCES:
        queries[f"fresh:{spec['id']}"] = (
            f"{_span(lookback, now)} {spec['query']} | sort by (_time) desc | limit 1 | fields _time"
        )
    flow = f"{_span(start, end)} app_name:=opnsense-flow schema:=2"
    queries["talkers_src"] = (
        f"{flow} {lan_filter('src_addr', networks)} "
        "| stats by (event_id, src_addr) max(bytes) bytes "
        "| stats by (src_addr) sum(bytes) bytes "
        f"| sort by (bytes) desc limit {TALKER_FETCH}"
    )
    queries["talkers_dst"] = (
        f"{flow} {lan_filter('dst_addr', networks)} {not_lan_filter('src_addr', networks)} "
        "| stats by (event_id, dst_addr) max(bytes) bytes "
        "| stats by (dst_addr) sum(bytes) bytes "
        f"| sort by (bytes) desc limit {TALKER_FETCH}"
    )
    queries["blocks"] = (
        f'{_span(start, end)} app_name:=filterlog "block" '
        f"| sort by (_time) desc | limit {BLOCK_CAP} | fields _time, _msg"
    )
    dns = f"{_span(start, end)} app_name:=pihole-dns"
    queries["dns_domains"] = (
        f"{dns} | stats by (event_id, domain) count() rows "
        "| stats by (domain) count() queries "
        f"| sort by (queries) desc limit {DNS_FETCH}"
    )
    queries["dns_clients"] = (
        f"{dns} | stats by (event_id, client_ip, client_name) count() rows "
        "| stats by (client_ip, client_name) count() queries "
        f"| sort by (queries) desc limit {DNS_FETCH}"
    )
    queries["gateway"] = (
        f'{_span(gateway_start, now)} hostname:=OPNsense.internal "dpinger" '
        "| sort by (_time) desc | limit 5 | fields _time, _msg"
    )
    return queries


def _window(start, end, seconds):
    return {
        "start": stamp(start),
        "end": stamp(end),
        "seconds": seconds,
        "label": WINDOWS[seconds],
    }


def _age_note(spec, state):
    if spec["id"] == "visibility-alert":
        notes = {
            "fresh": "Heartbeat is inside the checker cadence.",
            "info": "Heartbeat is behind its cadence and under the 3 minute silence limit.",
            "warning": "Heartbeat is at the 3 minute silence limit.",
            "critical": "Heartbeat is older than 3 minutes, the same limit as checker silence.",
        }
    else:
        notes = {
            "fresh": "Inside its expected cadence.",
            "info": "Behind its cadence and under the 15 minute warning.",
            "warning": "At least 15 minutes old.",
            "critical": "At least 30 minutes old.",
        }
    return notes[state]


def reduce_freshness(observations, now, sources=SOURCES):
    items = []
    lookback_seconds = int(LOOKBACK.total_seconds())
    for spec in sources:
        rows = observations.get(spec["id"])
        if rows is None:
            items.append({
                "id": spec["id"],
                "title": spec["title"],
                "state": "unavailable",
                "observed_at": None,
                "age_seconds": None,
                "note": "The freshness query is unavailable.",
            })
            continue
        observed = parse_time(rows[0].get("_time")) if rows else None
        if rows and observed is None:
            items.append({
                "id": spec["id"],
                "title": spec["title"],
                "state": "unavailable",
                "observed_at": None,
                "age_seconds": None,
                "note": "The last-seen time could not be read.",
            })
            continue
        if observed is None:
            items.append({
                "id": spec["id"],
                "title": spec["title"],
                "state": "critical",
                "observed_at": None,
                "age_seconds": lookback_seconds,
                "note": "No records in the 6 hour lookback.",
            })
            continue
        age = max(0, int((now - observed).total_seconds()))
        if age <= spec["cadence_seconds"]:
            state = "fresh"
        elif age >= spec["critical_seconds"]:
            state = "critical"
        elif age >= spec["warning_seconds"]:
            state = "warning"
        else:
            state = "info"
        items.append({
            "id": spec["id"],
            "title": spec["title"],
            "state": state,
            "observed_at": stamp(observed),
            "age_seconds": age,
            "note": _age_note(spec, state),
        })
    return items


def _lan(address, networks):
    try:
        ip = ipaddress.ip_address(str(address))
    except ValueError:
        return False
    return any(ip in network for network in networks)


def _add_bytes(totals, rows, field, networks):
    if not rows:
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        ip = str(row.get(field) or "")
        if not _lan(ip, networks):
            continue
        try:
            amount = number(row.get("bytes"))
        except (ValueError, TypeError):
            continue
        current = totals.get(ip, 0)
        if amount > (2**63 - 1) - current:
            continue
        totals[ip] = current + amount


def reduce_talkers(src_rows, dst_rows, networks=NETWORKS, fetch_cap=TALKER_FETCH, limit=TALKER_LIMIT):
    if src_rows is None and dst_rows is None:
        return {
            "state": "unavailable",
            "rows": [],
            "note": "LAN talkers could not be read.",
        }
    partial = src_rows is None or dst_rows is None
    if src_rows is not None and len(src_rows) >= fetch_cap:
        partial = True
    if dst_rows is not None and len(dst_rows) >= fetch_cap:
        partial = True
    totals = {}
    _add_bytes(totals, src_rows, "src_addr", networks)
    _add_bytes(totals, dst_rows, "dst_addr", networks)
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]
    note = (
        "Egress-only schema 2 bytes after event_id deduplication. "
        "A configured LAN source is credited; otherwise a LAN destination is. "
        "Post-NAT WAN uploads are not assigned to a client."
    )
    if src_rows is None or dst_rows is None:
        note = "Part of the talker ranking could not be read. " + note
    elif partial:
        note = "Ranking may be incomplete. " + note
    elif not ranked:
        note = "No configured LAN endpoints in this window. " + note
    return {
        "state": "partial" if partial else "available",
        "rows": [{"ip": ip, "bytes": amount} for ip, amount in ranked],
        "note": note,
    }


def reduce_blocks(rows, networks=NETWORKS, cap=BLOCK_CAP, limit=LIST_LIMIT):
    if rows is None:
        return {
            "state": "unavailable",
            "rows": [],
            "unparsed": 0,
            "note": "Firewall logs could not be read.",
        }
    counts = {}
    unparsed = 0
    for row in rows[:cap]:
        if not isinstance(row, dict):
            unparsed += 1
            continue
        event = parse_filterlog(row, networks)
        if event.get("parse_error"):
            unparsed += 1
            continue
        if str(event.get("action") or "").lower() != "block":
            continue
        port = event.get("destination_port")
        key = (
            str(event.get("interface") or "")[:40],
            str(event.get("source") or "")[:80],
            str(event.get("destination") or "")[:80],
            port if isinstance(port, int) else None,
            str(event.get("protocol") or "")[:20],
        )
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(
        counts.items(),
        key=lambda item: (
            -item[1],
            item[0][0],
            item[0][1],
            item[0][2],
            item[0][3] is None,
            item[0][3] or 0,
            item[0][4],
        ),
    )[:limit]
    partial = len(rows) >= cap
    note = "Newest logged block lines in this window."
    if partial:
        note = f"Ranking uses the newest {cap} matching lines, not every block in the window."
    if unparsed:
        note += f" {unparsed} lines could not be parsed."
    return {
        "state": "partial" if partial else "available",
        "rows": [
            {
                "interface": key[0],
                "source": key[1],
                "destination": key[2],
                "destination_port": key[3],
                "protocol": key[4],
                "count": count,
            }
            for key, count in ranked
        ],
        "unparsed": unparsed,
        "note": note,
    }


def _count(row):
    for key in ("queries", "rows", "count"):
        if key in row:
            return number(row[key])
    raise ValueError("missing count")


def reduce_dns(domain_rows, client_rows, fetch_cap=DNS_FETCH, limit=LIST_LIMIT):
    if domain_rows is None and client_rows is None:
        return {
            "state": "unavailable",
            "domains": [],
            "clients": [],
            "note": "DNS events could not be read.",
        }
    partial = domain_rows is None or client_rows is None
    domains = []
    if domain_rows is not None:
        if len(domain_rows) >= fetch_cap:
            partial = True
        for row in domain_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("domain") or "").strip()[:253]
            if not name:
                continue
            try:
                queries = _count(row)
            except (ValueError, TypeError):
                continue
            domains.append({"name": name, "queries": queries})
        domains.sort(key=lambda item: (-item["queries"], item["name"]))
        domains = domains[:limit]
    clients = []
    if client_rows is not None:
        if len(client_rows) >= fetch_cap:
            partial = True
        for row in client_rows:
            if not isinstance(row, dict):
                continue
            ip = str(row.get("client_ip") or "").strip()
            try:
                ipaddress.ip_address(ip)
                queries = _count(row)
            except (ValueError, TypeError):
                continue
            clients.append({
                "ip": ip,
                "name": str(row.get("client_name") or "").strip()[:80],
                "queries": queries,
            })
        clients.sort(key=lambda item: (-item["queries"], item["ip"]))
        clients = clients[:limit]
    note = "Pi-hole events deduplicated by event id. Other resolvers are outside this view."
    if domain_rows is None or client_rows is None:
        note = "Part of the DNS ranking could not be read. " + note
    elif partial:
        note = "Ranking may be incomplete. " + note
    return {
        "state": "partial" if partial else "available",
        "domains": domains,
        "clients": clients,
        "note": note,
    }


def reduce_gateway(rows):
    if rows is None:
        return {
            "state": "unavailable",
            "observed_at": None,
            "summary": "Gateway logs could not be read.",
            "sample": "",
        }
    if not rows or not isinstance(rows[0], dict):
        return {
            "state": "unknown",
            "observed_at": None,
            "summary": "No dpinger lines in the last 30 minutes. Absence is not treated as down.",
            "sample": "",
        }
    row = rows[0]
    message = "".join(ch for ch in str(row.get("_msg") or "") if ch.isprintable())[:240]
    seen = parse_time(row.get("_time"))
    down = _GATEWAY_DOWN.search(message)
    up = _GATEWAY_UP.search(message)
    # Same reading as the alert checker: a line that matches both is down.
    if down and not up:
        state = "down"
    elif up and not down:
        state = "up"
    elif down:
        state = "down"
    else:
        state = "unknown"
    if state == "down":
        summary = "The newest dpinger line reports the WAN gateway down."
    elif state == "up":
        summary = "The newest dpinger line reports the WAN gateway up."
    else:
        summary = "A dpinger line was seen, but it does not say whether the gateway is up."
    return {
        "state": state,
        "observed_at": stamp(seen) if seen else None,
        "summary": summary,
        "sample": message,
    }


def _notes(illustrative):
    notes = [
        "Flow and DNS rankings use the selected 15 minute or 1 hour window. A longer event_id aggregation is not queried.",
        "Open alerts are the existing alert list. Gateway lines are read from OPNsense dpinger logs; this page does not send a probe.",
    ]
    if illustrative:
        notes.insert(0, "Demo values are illustrative and are never substituted for live telemetry.")
    return notes


def assemble(results, end, seconds, now, mode="live"):
    observations = {spec["id"]: results.get(f"fresh:{spec['id']}") for spec in SOURCES}
    talkers = reduce_talkers(results.get("talkers_src"), results.get("talkers_dst"))
    if talkers["state"] != "unavailable":
        ranges = ", ".join(_cidr(network) for network in NETWORKS)
        talkers["note"] = f"Configured LAN ranges: {ranges}. {talkers['note']}"
    payload = {
        "mode": mode,
        "illustrative": False,
        "as_of": stamp(now),
        "window": _window(end - timedelta(seconds=seconds), end, seconds),
        "freshness": reduce_freshness(observations, now),
        "talkers": talkers,
        "blocks": reduce_blocks(results.get("blocks")),
        "dns": reduce_dns(results.get("dns_domains"), results.get("dns_clients")),
        "gateway": reduce_gateway(results.get("gateway")),
        "notes": _notes(False),
    }
    return OpsHome.model_validate(payload).model_dump()


def live_ops(client, end, seconds, now=None):
    if seconds not in WINDOWS:
        raise ValueError("Ops flow rankings are limited to 15 minutes or 1 hour")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    end = end.astimezone(UTC)
    start = end - timedelta(seconds=seconds)
    queries = ops_queries(start, end, now)
    deadline = time.monotonic() + 14
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
        raise QueryError("ops")
    return assemble(results, end, seconds, now)


def _demo_lists():
    return {
        "talkers": {
            "state": "available",
            "rows": [
                {"ip": "192.0.2.10", "bytes": 192000000},
                {"ip": "192.0.2.24", "bytes": 88000000},
                {"ip": "192.0.2.31", "bytes": 12000000},
            ],
            "note": "Illustrative addresses for this preview. Not a live ranking.",
        },
        "blocks": {
            "state": "available",
            "rows": [
                {
                    "interface": "igc1",
                    "source": "192.0.2.20",
                    "destination": "198.51.100.20",
                    "destination_port": 443,
                    "protocol": "TCP",
                    "count": 40,
                },
                {
                    "interface": "igc0",
                    "source": "203.0.113.8",
                    "destination": "192.0.2.50",
                    "destination_port": 22,
                    "protocol": "TCP",
                    "count": 6,
                },
            ],
            "unparsed": 0,
            "note": "Illustrative firewall rows. Not live decisions.",
        },
        "dns": {
            "state": "available",
            "domains": [
                {"name": "example.com", "queries": 120},
                {"name": "blocked.example", "queries": 40},
            ],
            "clients": [
                {"ip": "192.0.2.10", "name": "Living room TV", "queries": 80},
                {"ip": "192.0.2.24", "name": "Workstation", "queries": 36},
            ],
            "note": "Illustrative Pi-hole ranking. Not live queries.",
        },
    }


def demo_ops(end, seconds, scenario="normal", now=None):
    if seconds not in WINDOWS:
        raise ValueError("Ops flow rankings are limited to 15 minutes or 1 hour")
    now = (now or end).astimezone(UTC)
    end = end.astimezone(UTC)
    if scenario == "unavailable":
        observations = {spec["id"]: None for spec in SOURCES}
        panels = {
            "talkers": {"state": "unavailable", "rows": [], "note": "Illustrative preview with no samples."},
            "blocks": {
                "state": "unavailable",
                "rows": [],
                "unparsed": 0,
                "note": "Illustrative preview with no samples.",
            },
            "dns": {
                "state": "unavailable",
                "domains": [],
                "clients": [],
                "note": "Illustrative preview with no samples.",
            },
        }
        gateway = reduce_gateway(None)
    else:
        delayed = scenario == "stale"
        observations = {}
        for spec in SOURCES:
            if delayed:
                age = 40 * 60
            elif spec["id"] == "filterlog":
                age = 18 * 60
            elif spec["id"] == "visibility-alert":
                age = 30
            else:
                age = 40
            observations[spec["id"]] = [{"_time": stamp(now - timedelta(seconds=age))}]
        panels = _demo_lists()
        if delayed:
            gateway = reduce_gateway([])
        else:
            gateway = reduce_gateway([{
                "_time": stamp(now - timedelta(seconds=20)),
                "_msg": "dpinger: WAN_DHCP 203.0.113.1: Clear latency 1200us loss 0%",
            }])
    payload = {
        "mode": "demo",
        "illustrative": True,
        "as_of": stamp(now),
        "window": _window(end - timedelta(seconds=seconds), end, seconds),
        "freshness": reduce_freshness(observations, now),
        "gateway": gateway,
        "notes": _notes(True),
        **panels,
    }
    return OpsHome.model_validate(payload).model_dump()
