"""Pure alert conditions. Thresholds come from the rules file, not from code."""

import ipaddress
import statistics

from times import iso, parse_time

RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
QUERY_ERROR = "error"


class Observation:
    def __init__(self, now, **kwargs):
        self.now = now
        self.sources = kwargs.get("sources", {})
        self.certs = kwargs.get("certs", {})
        self.disk_percent = kwargs.get("disk_percent", "skip")
        self.metrics = kwargs.get("metrics")
        self.query_error_rows = kwargs.get("query_error_rows", 0)
        self.query_memory = kwargs.get("query_memory", False)
        self.containers = kwargs.get("containers")
        self.docker_error = kwargs.get("docker_error")
        self.probes = kwargs.get("probes", {})
        self.gateway = kwargs.get("gateway", "unknown")
        self.wan_events = kwargs.get("wan_events", [])
        self.block_recent = kwargs.get("block_recent")
        self.block_baseline = kwargs.get("block_baseline")
        self.entities = kwargs.get("entities")


def _cond(rule, subject, severity, summary, evidence, details=None):
    return {
        "rule": rule,
        "subject": str(subject)[:180],
        "severity": severity,
        "summary": summary[:500],
        "evidence_query": evidence,
        "details": details or {},
    }


def _firing(state, rule, subject=None):
    found = []
    for alert in state.get("alerts", {}).values():
        if alert.get("state") != "firing" or alert.get("rule") != rule:
            continue
        if subject is not None and alert.get("subject") != subject:
            continue
        found.append(_cond(
            alert["rule"], alert["subject"], alert["severity"], alert["summary"],
            alert["evidence_query"], alert.get("details")))
    return found


def _ip_in(address, spec):
    try:
        ip = ipaddress.ip_address(address)
        network = ipaddress.ip_network(spec, strict=False)
        return ip in network if network.prefixlen < network.max_prefixlen or "/" in str(spec) else ip == network.network_address
    except ValueError:
        return False


def _allowed(event, allow):
    keys = ("protocol", "destination_port", "destination", "source", "interface")
    for rule in allow or []:
        if not any(key in rule and rule[key] not in (None, "") for key in keys):
            continue
        if rule.get("protocol") and str(event.get("protocol", "")).lower() != str(rule["protocol"]).lower():
            continue
        if rule.get("destination_port") not in (None, ""):
            if event.get("destination_port") != int(rule["destination_port"]):
                continue
        if rule.get("destination") and not _ip_in(event.get("destination", ""), rule["destination"]):
            continue
        if rule.get("source") and not _ip_in(event.get("source", ""), rule["source"]):
            continue
        if rule.get("interface") and str(event.get("interface", "")).lower() != str(rule["interface"]).lower():
            continue
        return True
    return False


def _rfc1918(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in RFC1918)


def freshness(config, obs, state):
    stale = config["staleness"]
    warning_at = float(stale["warning_seconds"])
    critical_at = float(stale["critical_seconds"])
    conditions = []
    failed = False
    for source in config["sources"]:
        seen = obs.sources.get(source["id"], QUERY_ERROR)
        evidence = f"_time:{source.get('lookback', '6h')} {source['query']} | sort by (_time) desc | limit 5"
        if seen == QUERY_ERROR:
            failed = True
            conditions.extend(_firing(state, "source-freshness", source["id"]))
            continue
        if seen is None:
            age = critical_at
            severity = "critical"
            summary = f"{source['title']} has no records in the lookback window."
        else:
            age = (obs.now - parse_time(seen)).total_seconds()
            cadence = float(source["cadence_seconds"])
            if age <= cadence:
                continue
            if age >= critical_at:
                severity = "critical"
            elif age >= warning_at:
                severity = "warning"
            else:
                severity = "info"
            minutes = max(1, int(age // 60))
            summary = f"{source['title']} is {minutes} min behind its expected cadence."
        conditions.append(_cond(
            "source-freshness", source["id"], severity, summary, evidence,
            {"age_seconds": int(max(0, age)), "cadence_seconds": source["cadence_seconds"]}))
    return conditions, failed


def certificates(config, obs):
    tiers = config.get("cert_thresholds_days", {"info": 60, "warning": 30, "critical": 7})
    conditions = []
    for name, result in obs.certs.items():
        spec = next((item for item in config.get("certificates", []) if item["name"] == name), {})
        evidence = f'app_name:=visibility-alert rule:=cert-expiry subject:="{name}" | sort by (_time) desc | limit 5'
        if result == "pin-mismatch":
            conditions.append(_cond(
                "cert-pin", name, "critical",
                f"Pinned certificate for {name} changed; no credential was sent.",
                evidence, {"name": name}))
            continue
        if result == "private-key":
            conditions.append(_cond(
                "cert-expiry", name, "warning",
                f"A private key was mounted for {name}; remove it. Expiry was not read.",
                evidence, {"name": name}))
            continue
        if result in ("missing", "unreadable"):
            if spec.get("required", True) or result == "unreadable":
                conditions.append(_cond(
                    "cert-expiry", name, "warning",
                    f"Certificate for {name} could not be read.",
                    evidence, {"name": name, "result": result}))
            continue
        if result in ("unreachable", None):
            continue
        days = float(result)
        if days <= float(tiers["critical"]):
            severity = "critical"
        elif days <= float(tiers["warning"]):
            severity = "warning"
        elif days <= float(tiers["info"]):
            severity = "info"
        else:
            continue
        when = "expired" if days < 0 else f"expires in {int(days)} days"
        conditions.append(_cond(
            "cert-expiry", name, severity,
            f"TLS certificate {name} {when}.",
            evidence, {"name": name, "days_remaining": round(days, 2)}))
    return conditions


def disk(config, obs, state):
    percent = obs.disk_percent
    if percent == "skip":
        return []
    cfg = config["disk"]
    previous = next((alert for alert in state.get("alerts", {}).values()
                     if alert.get("rule") == "disk-usage" and alert.get("subject") == "data-volume"
                     and alert.get("state") == "firing"), None)
    evidence = 'app_name:=visibility-alert rule:=disk-usage subject:="data-volume" | sort by (_time) desc | limit 5'
    if percent is None:
        if previous:
            return _firing(state, "disk-usage", "data-volume")
        return [_cond("disk-usage", "data-volume", "warning",
                      "Data volume usage could not be read.", evidence, {})]
    warn = float(cfg["warning_percent"])
    crit = float(cfg["critical_percent"])
    warn_clear = float(cfg.get("warning_clear_percent", warn - 5))
    crit_clear = float(cfg.get("critical_clear_percent", crit - 5))
    severity = None
    if previous and previous["severity"] == "critical" and percent >= crit_clear:
        severity = "critical" if percent >= crit else "warning"
    elif previous and previous["severity"] in ("critical", "warning") and percent >= warn_clear:
        severity = "critical" if percent >= crit else "warning"
    elif percent >= crit:
        severity = "critical"
    elif percent >= warn:
        severity = "warning"
    if not severity:
        return []
    return [_cond(
        "disk-usage", "data-volume", severity,
        f"Data volume is {percent:.0f}% full.",
        evidence, {"percent": round(percent, 1)})]


def storage(config, obs, state):
    metrics_cfg = config.get("metrics") or {}
    if obs.metrics is None:
        held = []
        held.extend(_firing(state, "storage-readonly"))
        held.extend(_firing(state, "rows-dropped"))
        held.extend(_firing(state, "query-errors"))
        return held, {}
    updates = {}
    conditions = []
    read_name = metrics_cfg.get("read_only", "vl_storage_is_read_only")
    read_only = obs.metrics.get(read_name)
    if read_only is not None and float(read_only) >= 1:
        conditions.append(_cond(
            "storage-readonly", "victorialogs", "critical",
            "VictoriaLogs is read-only and is not accepting new rows.",
            "app_name:=visibility-alert rule:=storage-readonly | sort by (_time) desc | limit 5",
            {"metric": read_name, "value": read_only}))
    drop_name = metrics_cfg.get("dropped_rows", "vl_rows_dropped_total")
    current = obs.metrics.get(drop_name)
    previous = (state.get("metric_counters") or {}).get(drop_name)
    if current is not None:
        updates[drop_name] = float(current)
        if previous is not None and float(current) > float(previous):
            conditions.append(_cond(
                "rows-dropped", "victorialogs", "critical",
                "VictoriaLogs dropped rows since the last check.",
                "_time:1h | stats count() rows",
                {"metric": drop_name, "delta": float(current) - float(previous)}))
    error_hit = bool(obs.query_memory) or int(obs.query_error_rows or 0) > 0
    for name in metrics_cfg.get("query_errors") or []:
        value = obs.metrics.get(name)
        if value is None:
            continue
        updates[name] = float(value)
        prior = (state.get("metric_counters") or {}).get(name)
        if prior is not None and float(value) > float(prior):
            error_hit = True
    if error_hit:
        conditions.append(_cond(
            "query-errors", "victorialogs", "warning",
            "VictoriaLogs reported query errors or a memory-limit failure.",
            config.get("query_error_query", '_time:15m "memory limit"'),
            {"memory_limit": bool(obs.query_memory), "matching_rows": int(obs.query_error_rows or 0)}))
    return conditions, updates


def containers(config, obs):
    spec = config.get("containers") or {}
    expected = list(spec.get("expect") or [])
    probes = {item["id"]: item for item in config.get("probes") or []}
    by_name = {}
    if obs.containers is not None:
        for item in obs.containers:
            by_name[item["name"]] = item
    conditions = []
    if obs.docker_error and spec.get("required", True):
        conditions.append(_cond(
            "container-health", "docker-socket", "warning",
            "Container inspection is unavailable; only direct health probes are running.",
            'app_name:=visibility-alert rule:=container-health subject:="docker-socket"',
            {"error": "unavailable"}))
    seen = set()
    for name in expected:
        item = by_name.get(name) if obs.containers is not None else None
        probe_ids = [pid for pid, probe in probes.items() if probe.get("container") == name]
        probe_failed = any(obs.probes.get(pid) is False for pid in probe_ids)
        missing = obs.containers is not None and item is None
        unhealthy = False
        state = ""
        status = ""
        if item:
            state = str(item.get("state") or "")
            status = str(item.get("status") or "")
            unhealthy = state != "running" or "(unhealthy)" in status.lower()
        if missing or unhealthy or (obs.containers is None and probe_failed) or (item and probe_failed):
            reason = "missing" if missing else status or state or "probe failed"
            conditions.append(_cond(
                "container-health", name, "critical",
                f"Stack container {name} is down or unhealthy ({reason}).",
                f'app_name:=visibility-alert rule:=container-health subject:="{name}"',
                {"state": state, "status": status, "probe_failed": probe_failed}))
            seen.add(name)
    if obs.containers is None:
        for pid, ok in obs.probes.items():
            probe = probes.get(pid, {})
            if ok is not False or probe.get("container") in seen:
                continue
            conditions.append(_cond(
                "container-health", f"probe:{pid}", "critical",
                f"Health probe {pid} failed.",
                f'app_name:=visibility-alert rule:=container-health subject:="probe:{pid}"',
                {"probe": pid}))
    return conditions


def gateway(config, obs, state):
    if obs.gateway == "down":
        return [_cond(
            "gateway-down", "wan", "critical",
            "OPNsense reports the WAN gateway is down.",
            config.get("gateway_query", '_time:30m "dpinger" | sort by (_time) desc | limit 5'),
            {})]
    if obs.gateway == "unknown":
        return _firing(state, "gateway-down", "wan")
    return []


def wan_ingress(config, obs):
    spec = config.get("wan_ingress") or {}
    interfaces = {name.lower() for name in spec.get("interfaces") or []}
    grouped = {}
    for event in obs.wan_events:
        if event.get("parse_error"):
            continue
        if str(event.get("action", "")).lower() != "pass":
            continue
        if str(event.get("direction", "")).lower() != "in":
            continue
        interface = str(event.get("interface", "")).lower()
        if interface not in interfaces:
            continue
        if not _rfc1918(event.get("destination", "")):
            continue
        if _rfc1918(event.get("source", "")):
            continue
        if _allowed(event, spec.get("allow")):
            continue
        port = event.get("destination_port")
        key = (interface, event.get("destination"), port, str(event.get("protocol", "")).lower())
        bucket = grouped.setdefault(key, {"count": 0, "sources": []})
        bucket["count"] += 1
        source = event.get("source")
        if source and source not in bucket["sources"] and len(bucket["sources"]) < 5:
            bucket["sources"].append(source)
    conditions = []
    for (interface, destination, port, protocol), bucket in grouped.items():
        subject = f"{interface}:{destination}:{port}/{protocol}"
        conditions.append(_cond(
            "wan-ingress", subject, "critical",
            f"Firewall accepted inbound WAN traffic to internal {destination}:{port}/{protocol}.",
            f'_time:1h app_name:=filterlog "{interface}" "pass" "{destination}" | limit 20',
            {"interface": interface, "destination": destination, "port": port,
             "protocol": protocol, "count": bucket["count"], "sources": bucket["sources"]}))
    return conditions


def block_spike(config, obs, state):
    spec = config.get("block_spike") or {}
    if obs.block_recent is None or obs.block_baseline is None:
        return _firing(state, "block-spike", "filterlog")
    recent = float(obs.block_recent)
    baseline = float(obs.block_baseline)
    minimum = float(spec.get("min_blocks", 50))
    multiplier = float(spec.get("multiplier", 3))
    min_baseline = float(spec.get("min_baseline", 5))
    if baseline < min_baseline and recent < minimum * 2:
        return []
    threshold = max(minimum, multiplier * baseline)
    if recent < threshold:
        return []
    return [_cond(
        "block-spike", "filterlog", "warning",
        f"Firewall blocks rose to {int(recent)} in the recent window versus a baseline of {baseline:.0f}.",
        spec.get("evidence_query", '_time:15m app_name:=filterlog "block" | stats count() rows'),
        {"recent": recent, "baseline": baseline, "threshold": threshold})]


def new_entities(config, obs, state):
    spec = config.get("new_entities") or {}
    dwell = float(spec.get("dwell_seconds", 86400))
    if obs.entities is None:
        held = []
        for alert in _firing(state, "new-entity"):
            first = (state.get("seen_entities") or {}).get(alert["subject"], {}).get("first_seen")
            if first and (obs.now - parse_time(first)).total_seconds() <= dwell:
                held.append(alert)
        return held
    seen = state.setdefault("seen_entities", {})
    if not state.get("entities_seeded"):
        for key, meta in obs.entities.items():
            seen[key] = {"first_seen": iso(obs.now), "seed": True, "name": meta.get("name", "")}
        state["entities_seeded"] = True
        return []
    conditions = []
    for key, meta in obs.entities.items():
        if key not in seen:
            if len(seen) >= int(spec.get("max_tracked", 5000)):
                continue
            seen[key] = {"first_seen": iso(obs.now), "seed": False, "name": meta.get("name", "")}
        rec = seen[key]
        if rec.get("seed"):
            continue
        if (obs.now - parse_time(rec["first_seen"])).total_seconds() > dwell:
            continue
        label = meta.get("name") or key
        kind = meta.get("kind") or "client"
        conditions.append(_cond(
            "new-entity", key, "info",
            f"New {kind} {label} first seen.",
            meta.get("evidence_query") or f'_time:24h "{key.split(":", 1)[-1]}" | limit 5',
            {"kind": kind, "name": meta.get("name"), "ip": meta.get("ip")}))
    return conditions


def rate_limit(config, state):
    if not state.get("rate_limited"):
        return []
    maximum = int(config["webhook_max_per_hour"])
    queued = len(state.get("outbox") or [])
    return [_cond(
        "webhook-rate", "outbound", "warning",
        f"Webhook rate limit reached ({maximum} per hour). Notifications are waiting.",
        'app_name:=visibility-alert rule:=webhook-rate | sort by (_time) desc | limit 5',
        {"max_per_hour": maximum, "queued": queued, "suppressed": int(state.get("suppressed") or 0)})]


def evaluate(config, obs, state):
    conditions = []
    source_conditions, sources_failed = freshness(config, obs, state)
    conditions.extend(source_conditions)
    conditions.extend(certificates(config, obs))
    conditions.extend(disk(config, obs, state))
    stored, updates = storage(config, obs, state)
    conditions.extend(stored)
    if updates:
        counters = state.setdefault("metric_counters", {})
        counters.update(updates)
    conditions.extend(containers(config, obs))
    conditions.extend(gateway(config, obs, state))
    conditions.extend(wan_ingress(config, obs))
    conditions.extend(block_spike(config, obs, state))
    conditions.extend(new_entities(config, obs, state))
    conditions.extend(rate_limit(config, state))
    if sources_failed and not any(item["rule"] == "query-errors" for item in conditions):
        conditions.append(_cond(
            "query-errors", "victorialogs", "warning",
            "VictoriaLogs queries failed during this check.",
            config.get("query_error_query", "_time:15m"),
            {"source_queries": "failed"}))
    return conditions


def median_baseline(counts):
    """Median of completed buckets. Empty history is zero, not a spike."""
    if not counts:
        return 0.0
    return float(statistics.median(counts))
