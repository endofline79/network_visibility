"""Firing/resolved state, dedupe, hysteresis, and notify decisions.

Fingerprint is SHA-256 of `rule + newline + subject`, first 20 hex characters.
The same inputs always produce the same id, so a restart does not open a second alert.
"""

import hashlib
import copy

from times import iso, parse_time

OUTBOX_CAP = 200


def fingerprint(rule, subject):
    return hashlib.sha256(f"{rule}\n{subject}".encode()).hexdigest()[:20]


def blank_state():
    return {
        "version": 1,
        "alerts": {},
        "pending": {},
        "seen_entities": {},
        "entities_seeded": False,
        "metric_counters": {},
        "webhook_sends": [],
        "outbox": [],
        "notify_seq": 0,
        "stream_outbox": [],
        "rate_limited": False,
        "suppressed": 0,
    }


def _rule(config, rule_id):
    rules = config.get("rules") or {}
    return rules.get(rule_id) or {}


def _payload(alert, config):
    return {
        "fingerprint": alert["fingerprint"],
        "rule": alert["rule"],
        "severity": alert["severity"],
        "state": alert["state"],
        "subject": alert["subject"],
        "summary": alert["summary"],
        "first_seen": alert["first_seen"],
        "last_seen": alert["last_seen"],
        "evidence_query": alert["evidence_query"],
        "console_url": config.get("console_url", ""),
        "details": copy.deepcopy(alert.get("details") or {}),
    }


def _enqueue(state, alert, now, config):
    if len(state["outbox"]) >= OUTBOX_CAP:
        return False
    state["notify_seq"] = int(state.get("notify_seq", 0)) + 1
    state["outbox"].append({
        "id": f"{alert['fingerprint']}:{alert['state']}:{alert['severity']}:{state['notify_seq']}",
        "payload": _payload(alert, config),
        "attempts": 0,
        "next_attempt": iso(now),
    })
    return True


def _notify_due(alert, now, config, rule):
    if alert.get("notify_queued"):
        return False
    mode = rule.get("notify", "default")
    if alert["severity"] == "info" or mode == "never":
        return False
    renotify = float(rule.get("renotify_seconds", config["renotify_seconds"]))
    warning_after = float(rule.get(
        "warning_notify_after_seconds", config["warning_notify_after_seconds"]))
    last = alert.get("last_notified")
    since_notify = None if not last else (now - parse_time(last)).total_seconds()
    if mode == "immediate" or alert["severity"] == "critical" or alert.get("escalate"):
        if not alert.get("notified") or alert.get("escalate"):
            return True
        return since_notify is not None and since_notify >= renotify
    if alert["severity"] == "warning":
        open_for = (now - parse_time(alert["severity_since"])).total_seconds()
        if open_for < warning_after:
            return False
        if not alert.get("notified"):
            return True
        return since_notify is not None and since_notify >= renotify
    return False


def _maybe_notify(state, alert, now, config):
    if config.get("webhook_enabled") is False:
        return
    rule = _rule(config, alert["rule"])
    if not _notify_due(alert, now, config, rule):
        return
    if _enqueue(state, alert, now, config):
        alert["notify_queued"] = True
        alert["escalate"] = False


def _new_alert(fp, cond, now):
    return {
        "fingerprint": fp,
        "rule": cond["rule"],
        "subject": cond["subject"],
        "severity": cond["severity"],
        "state": "firing",
        "summary": cond["summary"],
        "evidence_query": cond["evidence_query"],
        "details": copy.deepcopy(cond.get("details") or {}),
        "first_seen": iso(now),
        "last_seen": iso(now),
        "severity_since": iso(now),
        "clear_since": None,
        "notified": False,
        "resolve_notified": False,
        "resolve_queued": False,
        "last_notified": None,
        "notify_queued": False,
        "notify_count": 0,
        "escalate": False,
    }


def _touch(alert, cond, now):
    changed = alert["severity"] != cond["severity"]
    alert["last_seen"] = iso(now)
    alert["summary"] = cond["summary"]
    alert["evidence_query"] = cond["evidence_query"]
    alert["details"] = copy.deepcopy(cond.get("details") or {})
    alert["clear_since"] = None
    transition = None
    if changed:
        alert["severity"] = cond["severity"]
        alert["severity_since"] = iso(now)
        alert["escalate"] = cond["severity"] == "critical"
        if alert["escalate"]:
            # A queued warning is not a critical notification.
            alert["notify_queued"] = False
        transition = copy.deepcopy(alert)
    return transition


def _will_notify(state, alert):
    if alert.get("notified") or alert.get("notify_queued"):
        return True
    return any(item["payload"]["fingerprint"] == alert["fingerprint"] for item in state["outbox"])


def _resolve(state, alert, now, config):
    alert["state"] = "resolved"
    alert["last_seen"] = iso(now)
    alert["clear_since"] = None
    if not str(alert["summary"]).startswith("Resolved: "):
        alert["summary"] = "Resolved: " + alert["summary"]
    if _will_notify(state, alert) and not alert.get("resolve_notified") and not alert.get("resolve_queued"):
        if _enqueue(state, alert, now, config):
            alert["resolve_queued"] = True
    return copy.deepcopy(alert)


def apply(state, conditions, now, config):
    """Advance the state machine. Returns (state, transition records)."""
    transitions = []
    active = {}
    for cond in conditions:
        active[fingerprint(cond["rule"], cond["subject"])] = cond
    for fp in list(state["pending"]):
        if fp not in active:
            del state["pending"][fp]
    for fp, cond in active.items():
        rule = _rule(config, cond["rule"])
        fire_after = float(rule.get("fire_after_seconds", 0))
        alert = state["alerts"].get(fp)
        if alert and alert["state"] == "firing":
            transition = _touch(alert, cond, now)
            if transition:
                transitions.append(transition)
            _maybe_notify(state, alert, now, config)
            continue
        pending = state["pending"].get(fp)
        if fire_after > 0 and pending is None:
            state["pending"][fp] = iso(now)
            continue
        if fire_after > 0 and (now - parse_time(pending)).total_seconds() < fire_after:
            continue
        state["pending"].pop(fp, None)
        opened = _new_alert(fp, cond, now)
        state["alerts"][fp] = opened
        transitions.append(copy.deepcopy(opened))
        _maybe_notify(state, opened, now, config)
    for fp, alert in state["alerts"].items():
        if alert["state"] != "firing" or fp in active:
            continue
        resolve_after = float(_rule(config, alert["rule"]).get("resolve_after_seconds", 0))
        if resolve_after > 0:
            if not alert.get("clear_since"):
                alert["clear_since"] = iso(now)
                continue
            if (now - parse_time(alert["clear_since"])).total_seconds() < resolve_after:
                continue
        transitions.append(_resolve(state, alert, now, config))
    return state, transitions


def ensure_open(state, cond, now, config):
    """Open one alert if it is not already firing. Does not touch other alerts."""
    fp = fingerprint(cond["rule"], cond["subject"])
    alert = state["alerts"].get(fp)
    if alert and alert["state"] == "firing":
        alert["last_seen"] = iso(now)
        alert["summary"] = cond["summary"]
        alert["details"] = copy.deepcopy(cond.get("details") or {})
        _maybe_notify(state, alert, now, config)
        return []
    state["pending"].pop(fp, None)
    opened = _new_alert(fp, cond, now)
    state["alerts"][fp] = opened
    _maybe_notify(state, opened, now, config)
    return [copy.deepcopy(opened)]


def mark_sent(state, item, now):
    payload = item["payload"]
    state["outbox"] = [row for row in state["outbox"] if row["id"] != item["id"]]
    state.setdefault("webhook_sends", []).append(iso(now))
    alert = state["alerts"].get(payload["fingerprint"])
    if not alert or alert.get("first_seen") != payload["first_seen"]:
        return
    if payload["state"] == "resolved":
        if alert["state"] == "resolved":
            alert["resolve_notified"] = True
            alert["resolve_queued"] = False
        return
    if alert["state"] == "firing":
        alert["notified"] = True
        alert["last_notified"] = iso(now)
        alert["notify_count"] = int(alert.get("notify_count", 0)) + 1
        alert["notify_queued"] = False
        alert["escalate"] = False
