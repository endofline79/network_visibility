"""Bounded log facade and opt-in Jev trial. No firewall credentials."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import ipaddress
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Literal
import urllib.parse
import urllib.request

import maxminddb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .filterlog import parse_filterlog, public_endpoint
from .jev import JevTrial
from .unifi import Inventory
from .pihole import DnsSource

LOG_URL = os.environ.get("VICTORIALOGS_URL", "http://logs:9428").rstrip("/")
SOURCE_IP = str(ipaddress.ip_address(os.environ.get("FIREWALL_SOURCE_IP", "192.168.5.1")))
LOCAL_NETWORKS = tuple(ipaddress.ip_network(n.strip()) for n in os.environ.get(
    "LOCAL_NETWORKS", "192.168.5.0/24,10.10.10.0/24,10.10.20.0/24").split(",") if n.strip())
MAX_EVENTS = 5000
MAX_LOGS = 1000
GEO_PATH = Path(os.environ.get("GEOIP_DATABASE", "/geoip/dbip-city-lite.mmdb"))
STATIC = Path(os.environ.get("STATIC_DIR", "/app/static"))
Window = Literal["5m", "15m", "1h", "6h", "24h", "7d", "30d"]
WINDOW_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400,
                  "7d": 604800, "30d": 2592000}
log = logging.getLogger("visibility")
cache_lock = threading.Lock()
cache = {}
geo_reader = None
geo_mtime = None
geo_status = {"available": False, "provider": "DB-IP Lite", "build_time": None}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def query_logs(query: str) -> list[dict]:
    request = urllib.request.Request(LOG_URL + "/select/logsql/query", data=urllib.parse.urlencode({
        "query": query, "timeout": "8s",
    }).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Collector response too large")
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def cached(key, build):
    # Serialize cache misses, avoiding duplicate expensive scans from multiple tabs.
    with cache_lock:
        item = cache.get(key)
        if item and time.monotonic() - item[0] < 10:
            return item[1]
        try:
            value = build()
        except Exception as exc:
            # Never log the upstream URL, response body, query or log contents.
            log.warning("Collector request failed (%s)", type(exc).__name__)
            raise HTTPException(503, "Collector query failed. Retry shortly; previous data may be stale.") from None
        if len(cache) >= 32:
            cache.pop(next(iter(cache)))
        cache[key] = (time.monotonic(), value)
        return value


def refresh_geo():
    global geo_reader, geo_mtime, geo_status
    try:
        mtime = GEO_PATH.stat().st_mtime_ns
        if mtime == geo_mtime and geo_reader is not None:
            build = datetime.fromisoformat(geo_status["build_time"])
            geo_status["age_days"] = (datetime.now(timezone.utc) - build).days
            return
        reader = maxminddb.open_database(str(GEO_PATH))
        meta = reader.metadata()
        old = geo_reader
        geo_reader, geo_mtime = reader, mtime
        locate.cache_clear()
        if old:
            old.close()
        build = datetime.fromtimestamp(meta.build_epoch, timezone.utc)
        geo_status = {"available": True, "provider": "DB-IP Lite", "build_time": build.isoformat(),
                      "age_days": (datetime.now(timezone.utc) - build).days}
    except (OSError, ValueError, maxminddb.InvalidDatabaseError):
        geo_status = {"available": False, "provider": "DB-IP Lite", "build_time": None}
        if geo_reader:
            geo_reader.close()
        geo_reader, geo_mtime = None, None
        locate.cache_clear()


@lru_cache(maxsize=20000)
def locate(address):
    if geo_reader is None or not public_endpoint(address, LOCAL_NETWORKS):
        return None
    record = geo_reader.get(address)
    if not record:
        return None
    country = record.get("country", {})
    place = record.get("location", {})
    lat, lon = place.get("latitude"), place.get("longitude")
    if not country.get("iso_code") or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"country_code": country["iso_code"], "country": country.get("names", {}).get("en", country["iso_code"]),
            "city": record.get("city", {}).get("names", {}).get("en", ""), "latitude": lat, "longitude": lon}


def lab_location():
    try:
        lat, lon = float(os.environ["LAB_LATITUDE"]), float(os.environ["LAB_LONGITUDE"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return {"latitude": lat, "longitude": lon, "label": os.environ.get("LAB_LOCATION_LABEL", "Lab")}
    except (KeyError, ValueError):
        return None


def base_filter(window, firewall=True, at=None):
    scope = f'remote_ip:={json.dumps(SOURCE_IP)} AND app_name:="filterlog"' if firewall else 'NOT hostname:="visibility-test"'
    if at is not None:
        start = (at - timedelta(seconds=WINDOW_SECONDS[window])).isoformat().replace("+00:00", "Z")
        end = at.isoformat().replace("+00:00", "Z")
        return f"_time:[{start},{end}) AND {scope}"
    return f"_time:{window} AND {scope}"


def build_snapshot(window):
    started = time.monotonic()
    anchor = datetime.now(timezone.utc)
    base = base_filter(window, at=anchor)
    raw = query_logs(f"{base} | sort by (_time) desc limit {MAX_EVENTS + 1}")
    events = [parse_filterlog(r, LOCAL_NETWORKS) for r in raw[:MAX_EVENTS]]
    capped = len(raw) > MAX_EVENTS
    # Uncapped results already contain the full snapshot. For a capped query,
    # use the same absolute time interval when counting the remaining records.
    total = len(events)
    if capped:
        totals = query_logs(f"{base} | stats count() as total")
        total = max(len(raw), int(totals[0].get("total", 0)) if totals else 0)
    refresh_geo()
    endpoints = {e[k] for e in events for k in ("source", "destination") if public_endpoint(e[k], LOCAL_NETWORKS)}
    locations = {ip: location for ip in endpoints if (location := locate(ip)) is not None}
    sources = query_logs('_time:5m AND NOT hostname:="visibility-test" | stats by (hostname, app_name) count() as events | sort by (events) desc limit 40')
    return {
        "as_of": anchor.isoformat(), "window": window, "window_seconds": WINDOW_SECONDS[window],
        "events": events, "locations": locations, "lab": lab_location(), "geoip": dict(geo_status),
        "limit": MAX_EVENTS, "capped": capped, "total": total,
        "parse_errors": sum(bool(e["parse_error"]) for e in events),
        "unlocated_public_ips": len(endpoints) - len(locations), "public_ips": len(endpoints),
        "last_event": events[0]["time"] if events else None,
        "oldest_event": events[-1]["time"] if events else None,
        "sources": sources, "query_ms": round((time.monotonic() - started) * 1000),
        "local_networks": list(map(str, LOCAL_NETWORKS)),
    }


def build_overview_trend(at=None):
    """Count all logged firewall decisions in hourly buckets over a bounded day."""
    anchor = at or datetime.now(timezone.utc)
    start = anchor - timedelta(hours=24)
    base = base_filter("24h", at=anchor)
    rows = query_logs(f"{base} | stats by (_time:1h) count() events | sort by (_time)")
    if len(rows) > 25:
        raise ValueError("Unexpected number of hourly buckets")
    counts = {}
    for row in rows:
        bucket = datetime.fromisoformat(str(row["_time"]).replace("Z", "+00:00"))
        if bucket.tzinfo is None:
            raise ValueError("Hourly bucket has no timezone")
        bucket = bucket.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        count = int(row["events"])
        if bucket in counts or count < 0:
            raise ValueError("Invalid hourly bucket")
        counts[bucket] = count
    current = start.replace(minute=0, second=0, microsecond=0)
    buckets = []
    while current < anchor:
        buckets.append({"time": current.isoformat(), "count": counts.pop(current, 0)})
        current += timedelta(hours=1)
    if counts:
        raise ValueError("Hourly bucket outside requested range")
    return {"as_of": anchor.isoformat(), "start": start.isoformat(), "window": "24h",
            "bucket_seconds": 3600, "firewall": buckets}


def build_jev_window(start, end):
    """Independent, non-overlapping stream windows; no map enrichment or 5m cache."""
    bounds = [datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
              for value in (start, end)]
    base = f'_time:[{bounds[0]},{bounds[1]}) AND remote_ip:={json.dumps(SOURCE_IP)} AND app_name:="filterlog"'
    raw = query_logs(f"{base} | sort by (_time) desc limit {MAX_EVENTS + 1}")
    events = [parse_filterlog(row, LOCAL_NETWORKS) for row in raw[:MAX_EVENTS]]
    capped, total = len(raw) > MAX_EVENTS, len(events)
    if capped:
        totals = query_logs(f"{base} | stats count() as total")
        total = max(len(raw), int(totals[0].get("total", 0)) if totals else 0)
    return {"as_of": bounds[1], "window_start": bounds[0], "window": "continuous",
            "window_seconds": round(end - start), "events": events, "total": total,
            "capped": capped, "parse_errors": sum(bool(e["parse_error"]) for e in events),
            "local_networks": list(map(str, LOCAL_NETWORKS))}


trial = JevTrial(Path(os.environ.get("JEV_DATA_DIR", "/analysis")) / "trial.sqlite3",
                 snapshot_loader=build_jev_window)
inventory = Inventory(Path(os.environ.get("JEV_DATA_DIR", "/analysis")) / "unifi-inventory.json")
dns = DnsSource(Path(os.environ.get("JEV_DATA_DIR", "/analysis")) / "pihole-state.json")


@asynccontextmanager
async def lifespan(app):
    trial.start_worker()
    inventory.start_worker()
    dns.start_worker()
    try:
        yield
    finally:
        # Signal all before waiting so shutdown does not add their time budgets.
        inventory.stop.set()
        dns.stop.set()
        trial.stop_worker()
        inventory.stop_worker()
        dns.stop_worker()


app = FastAPI(title="Visibility", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.environ.get(
    "ALLOWED_HOSTS", "192.168.5.230,ai-02,localhost,127.0.0.1,testserver").split(","))


class TrialControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    mode: Literal["manual", "continuous"] = "manual"


class TrialSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{16}$")
    role: str = Field(default="unknown", max_length=20)
    context: str = Field(default="", max_length=200)


class TrialRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    groups: list[TrialSelection] = Field(min_length=1, max_length=3)


class TrialReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    category: str = Field(max_length=40)


@app.middleware("http")
async def headers(request, call_next):
    if request.url.path.startswith("/api/jev/") and request.method == "POST" and (
        request.headers.get("x-visibility-trial") != "1" or
        request.headers.get("content-type", "").split(";")[0] != "application/json" or
        request.headers.get("origin", str(request.base_url).rstrip("/")) != str(request.base_url).rstrip("/")
    ):
        response = JSONResponse({"detail": "Trial controls require a same-origin JSON request."}, status_code=403)
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.5.0"}


@app.get("/api/inventory")
def inventory_status():
    return inventory.status()


@app.get("/api/dns")
def dns_status():
    return dns.status()


@app.get("/api/dns/queries")
def dns_queries(window: Window = "15m", search: str = Query("", max_length=160),
                outcome: Literal["", "blocked", "cached", "forwarded", "other"] = ""):
    def build():
        base = f'_time:{window} AND app_name:="pihole-dns" AND remote_ip:="192.168.5.238"'
        if search.strip():
            base += " AND _msg:" + json.dumps(search.strip())
        if outcome:
            base += " AND outcome:=" + json.dumps(outcome)
        rows = query_logs(f"{base} | sort by (_time) desc limit {MAX_LOGS + 1}")
        # A lost insert acknowledgment can retry an identical durable batch.
        # Collapse repeats in this bounded view; All logs retains intake records.
        unique = {r["event_id"]: r for r in rows[:MAX_LOGS] if r.get("event_id")}
        fields = ("event_id", "query_id", "domain", "query_type", "status", "outcome", "client_ip", "client_name",
                  "reply_type", "upstream", "dnssec")
        return {"as_of": utcnow(), "window": window, "queries": [
                {"time": r.get("_time", ""), **{key: r.get(key, "") for key in fields}}
                for r in unique.values()], "capped": len(rows) > MAX_LOGS, "limit": MAX_LOGS}
    return cached(("dns-queries", window, search, outcome), build)


@app.get("/api/jev/status")
def trial_status():
    return trial.status()


@app.post("/api/jev/control")
def trial_control(body: TrialControl):
    return trial.control(body.enabled, body.mode)


@app.post("/api/jev/preview")
def trial_preview():
    return trial.preview(cached(("snapshot", "5m"), lambda: build_snapshot("5m")))


@app.post("/api/jev/request-preview")
def trial_request_preview(body: TrialRun):
    return trial.request_preview(body.preview_id, [g.model_dump() for g in body.groups])


@app.post("/api/jev/run")
def trial_run(body: TrialRun):
    return trial.run(body.preview_id, [g.model_dump() for g in body.groups])


@app.post("/api/jev/runs/{run_id}/review")
def trial_review(run_id: str, body: TrialReview):
    return trial.review(run_id, body.group_id, body.category)


@app.get("/api/snapshot")
def snapshot(window: Window = "15m"):
    return cached(("snapshot", window), lambda: build_snapshot(window))


@app.get("/api/overview/trend")
def overview_trend():
    return cached(("overview-trend",), build_overview_trend)


@app.get("/api/logs")
def logs(window: Window = "15m", search: str = Query("", max_length=160), application: str = Query("", max_length=80)):
    def build():
        base = base_filter(window, firewall=False)
        if search.strip():
            base += " AND _msg:" + json.dumps(search.strip())
        if application:
            base += " AND app_name:=" + json.dumps(application)
        rows = query_logs(f"{base} | sort by (_time) desc limit {MAX_LOGS + 1}")
        return {"as_of": utcnow(), "logs": [{"time": r.get("_time", ""), "hostname": r.get("hostname", ""),
                 "application": r.get("app_name", ""), "message": r.get("_msg", ""),
                 "severity": r.get("severity", ""), "source": r.get("remote_ip", "")} for r in rows[:MAX_LOGS]],
                "capped": len(rows) > MAX_LOGS, "limit": MAX_LOGS}
    return cached(("logs", window, search, application), build)


if STATIC.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")
