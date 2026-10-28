"""Pi-hole destinations for the IoT and streaming allowlist.

Reads go through the existing VictoriaLogs client. The one-hour window
deduplicates ``event_id`` before counting domains. Longer windows aggregate
``domain`` only: a multi-day ``stats by (event_id)`` can exhaust VictoriaLogs
memory, which is the same limit Ops Home already keeps for its rankings.
"""
import concurrent.futures
import ipaddress
import time
from datetime import datetime, timedelta, timezone

from .alerts import parse_time
from .client import QueryError
from .models import DestinationsView
from .service import number, stamp

UTC = timezone.utc
DOMAIN_FETCH = 80
DOMAIN_LIMIT = 12
SITE_LIMIT = 8
WINDOWS = {3600: "Last hour", 86400: "Last 24 hours", 604800: "Last 7 days"}
# One label beyond these public suffixes. Ordinary com/net/org names use two labels.
_MULTI_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "net.uk",
    "com.au", "net.au", "org.au", "edu.au",
    "co.nz", "org.nz", "net.nz",
    "co.jp", "ne.jp", "or.jp",
    "com.br", "com.mx", "co.za", "com.sg", "com.tr",
    "com.tw", "co.in", "com.hk", "com.cn", "com.ar",
    "co.kr", "com.co",
})
_DEMO = {
    "roku-premiere": (
        ("scribe.logs.roku.com", 40),
        ("www.roku.com", 12),
        ("roku.com", 8),
        ("manifest.googlevideo.com", 30),
        ("googlevideo.com", 5),
    ),
    "living-room": (
        ("peacocktv.com", 20),
        ("init.itunes.apple.com", 9),
        ("apple.com", 4),
    ),
    "ring-113237": (
        ("fw.ring.com", 15),
        ("ring.com", 6),
    ),
    "sonos-zp": (
        ("msmetrics.ws.sonos.com", 11),
        ("sonos.com", 3),
    ),
    "google-nest-mini": (
        ("google.com", 6),
        ("nest.com", 2),
    ),
    "samsung-bedroom-tv": (
        ("samsung.com", 5),
        ("samsungcloudsolution.com", 3),
    ),
    "esp-ca34f5": (("mq.gw.tuyaus.com", 4),),
    "esp-ca2ced": (("mq.gw.tuyaus.com", 3),),
    "honeywell-thermostat": (("resideo.com", 2),),
}


def client_filter(host):
    parts = [f'client_ip:="{host.ip}"']
    parts.extend(f'client_name:="{name}"' for name in host.match_names())
    return "(" + " OR ".join(parts) + ")"


def _span(start, end):
    return f"_time:[{stamp(start)},{stamp(end)})"


def _base(start, end, host):
    return f"{_span(start, end)} app_name:=pihole-dns {client_filter(host)}"


def domain_query(start, end, host, dedupe):
    base = _base(start, end, host)
    if dedupe:
        return (
            f"{base} | stats by (event_id, domain) count() rows "
            "| stats by (domain) count() queries "
            f"| sort by (queries) desc | limit {DOMAIN_FETCH}"
        )
    return (
        f"{base} | stats by (domain) count() queries "
        f"| sort by (queries) desc | limit {DOMAIN_FETCH}"
    )


def span_query(start, end, host):
    return (
        f"{_base(start, end, host)} | stats min(_time) first_seen, "
        "max(_time) last_seen, count() queries"
    )


def destination_queries(start, end, hosts, dedupe):
    queries = {}
    for host in hosts:
        queries[f"domains:{host.id}"] = domain_query(start, end, host, dedupe)
        queries[f"span:{host.id}"] = span_query(start, end, host)
    return queries


def site_name(domain):
    """Registrable-domain style group (eTLD+1) for a displayed DNS name."""
    name = domain.strip().rstrip(".").lower()
    if not name:
        return ""
    try:
        return str(ipaddress.ip_address(name))
    except ValueError:
        pass
    labels = name.split(".")
    if len(labels) <= 2 or any(not label or len(label) > 63 for label in labels):
        return name
    if ".".join(labels[-2:]) in _MULTI_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _clean_domain(value):
    if not isinstance(value, str):
        value = str(value or "")
    name = "".join(ch for ch in value.strip() if ch.isprintable()).rstrip(".")
    if not name or len(name) > 253 or any(ch.isspace() for ch in name):
        return ""
    return name


def _rows(items, limit):
    ranked = sorted(items, key=lambda item: (-item["queries"], item["name"]))
    return ranked[:limit]


def _fetched_domains(domain_rows):
    fetched = []
    if domain_rows is None:
        return fetched
    for row in domain_rows:
        if not isinstance(row, dict):
            continue
        name = _clean_domain(row.get("domain"))
        if not name:
            continue
        try:
            queries = number(row.get("queries"))
        except (ValueError, TypeError):
            continue
        fetched.append({"name": name, "queries": queries})
    return fetched


def _stamp_field(row, key):
    if not isinstance(row, dict):
        return None
    seen = parse_time(row.get(key))
    return stamp(seen) if seen else None


def reduce_host(host, domain_rows, span_rows, dedupe, fetch_cap=DOMAIN_FETCH):
    listing = {
        "id": host.id,
        "class": host.device_class,
        "name": host.name,
        "dns_names": list(host.dns_names),
        "ip": host.ip,
        "mac": host.mac,
        "notes": host.notes,
    }
    if domain_rows is None and span_rows is None:
        return {
            **listing,
            "state": "unavailable",
            "queries": None,
            "first_seen": None,
            "last_seen": None,
            "domains": [],
            "sites": [],
            "note": "Pi-hole DNS for this host could not be read.",
        }
    capped = domain_rows is not None and len(domain_rows) >= fetch_cap
    partial = domain_rows is None or span_rows is None or capped
    fetched = _fetched_domains(domain_rows)
    domains = _rows(fetched, DOMAIN_LIMIT)
    sites = {}
    for item in fetched:
        site = site_name(item["name"])
        if site:
            sites[site] = sites.get(site, 0) + item["queries"]
    site_rows = _rows(
        ({"name": name, "queries": queries} for name, queries in sites.items()),
        SITE_LIMIT,
    )
    span = span_rows[0] if span_rows else None
    first_seen = _stamp_field(span, "first_seen")
    last_seen = _stamp_field(span, "last_seen")
    fetched_total = sum(item["queries"] for item in fetched) if domain_rows is not None else None
    queries = None
    if not dedupe and isinstance(span, dict) and "queries" in span:
        try:
            queries = number(span.get("queries"))
        except (ValueError, TypeError):
            queries = None
    if queries is None:
        queries = fetched_total
    if dedupe:
        basis = "Counts for this hour are deduplicated by event id."
    else:
        basis = (
            "Counts are stored Pi-hole receipts. A retried insert can be counted twice. "
            "Event id is not aggregated on this window."
        )
    if domain_rows is None or span_rows is None:
        note = "Part of the DNS read failed. " + basis
    elif len(domain_rows) >= fetch_cap:
        note = "Domain list hit its fetch cap and may be incomplete. " + basis
    elif queries == 0:
        note = "No Pi-hole queries from this host in the window. " + basis
    else:
        note = basis
    if partial and domain_rows is not None and len(domain_rows) >= fetch_cap:
        note = "Site totals cover the fetched domains only. " + note
    return {
        **listing,
        "state": "partial" if partial else "available",
        "queries": queries,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "domains": domains,
        "sites": site_rows,
        "note": note,
    }


def _selected(inventory, host_id):
    if host_id == "all":
        return inventory.hosts
    host = inventory.by_id(host_id)
    if host is None:
        raise KeyError(host_id)
    return (host,)


def _window(start, end, seconds):
    return {"start": stamp(start), "end": stamp(end), "seconds": seconds, "label": WINDOWS[seconds]}


def _notes(dedupe, illustrative):
    notes = [
        "Scope is the checked-in allowlist in presentation/config/iot-hosts.yaml. The LAN CIDR is not a filter.",
        "One-hour domain counts deduplicate event id. The 24 hour and 7 day views count stored receipts, because a multi-day event_id aggregation can exhaust VictoriaLogs.",
        "Names are what these clients asked Pi-hole to resolve, including blocked lookups. Other resolvers and direct connections are outside this view.",
        "A site row groups names by registrable domain (eTLD+1) inside the fetched domain list.",
    ]
    if not dedupe:
        notes[1] = (
            "This window counts stored Pi-hole receipts and does not aggregate event id. "
            "The one-hour view is the one that deduplicates."
        )
    if illustrative:
        notes.insert(0, "Demo domain counts are illustrative. The host list is the checked-in allowlist.")
    return notes


def assemble(inventory, host_views, end, seconds, now, mode):
    dedupe = seconds == 3600
    payload = {
        "mode": mode,
        "illustrative": mode == "demo",
        "as_of": stamp(now),
        "window": _window(end - timedelta(seconds=seconds), end, seconds),
        "deduped": dedupe,
        "inventory": [
            {
                "id": host.id,
                "class": host.device_class,
                "name": host.name,
                "dns_names": list(host.dns_names),
                "ip": host.ip,
                "mac": host.mac,
                "notes": host.notes,
            }
            for host in inventory.hosts
        ],
        "hosts": host_views,
        "notes": _notes(dedupe, mode == "demo"),
    }
    return DestinationsView.model_validate(payload).model_dump(by_alias=True)


def live_destinations(client, inventory, end, seconds, host_id, now=None):
    if seconds not in WINDOWS:
        raise ValueError("DNS destination windows are 1 hour, 24 hours, or 7 days")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    end = end.astimezone(UTC)
    start = end - timedelta(seconds=seconds)
    hosts = _selected(inventory, host_id)
    dedupe = seconds == 3600
    queries = destination_queries(start, end, hosts, dedupe)
    deadline = time.monotonic() + 18
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
        raise QueryError("destinations")
    views = [
        reduce_host(host, results.get(f"domains:{host.id}"), results.get(f"span:{host.id}"), dedupe)
        for host in hosts
    ]
    return assemble(inventory, views, end, seconds, now, "live")


def _demo_rows(host, start, end):
    sample = _DEMO.get(host.id, (("example.com", 1),))
    domains = [{"domain": name, "queries": str(count)} for name, count in sample]
    total = sum(count for _, count in sample)
    span = [{
        "first_seen": stamp(start + timedelta(minutes=2)),
        "last_seen": stamp(end - timedelta(minutes=1)),
        "queries": str(total),
    }]
    return domains, span


def demo_destinations(inventory, end, seconds, host_id, scenario="normal", now=None):
    if seconds not in WINDOWS:
        raise ValueError("DNS destination windows are 1 hour, 24 hours, or 7 days")
    now = (now or end).astimezone(UTC)
    end = end.astimezone(UTC)
    start = end - timedelta(seconds=seconds)
    hosts = _selected(inventory, host_id)
    dedupe = seconds == 3600
    views = []
    for host in hosts:
        if scenario == "unavailable":
            views.append(reduce_host(host, None, None, dedupe))
            continue
        domains, span = _demo_rows(host, start, end)
        view = reduce_host(host, domains, span, dedupe)
        view["note"] = "Illustrative sample, not live queries. " + view["note"]
        views.append(view)
    return assemble(inventory, views, end, seconds, now, "demo")

