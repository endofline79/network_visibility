"""Read-only reduction of the visibility-alert stream.

The checker writes transitions and heartbeats. This module folds the newest
transition per fingerprint into open and recently resolved alerts. A missing
or stale heartbeat becomes a synthetic critical alert so a dead checker is
visible without a second writer. A failed heartbeat query stays unknown and
does not invent that alert.
"""
import hashlib
import time
from datetime import datetime, timedelta, timezone

from .client import QueryError

UTC = timezone.utc
TRANSITIONS = (
    "_time:48h app_name:=visibility-alert kind:=transition | sort by (_time) desc | limit 2000"
)
HEARTBEAT = (
    "_time:15m app_name:=visibility-alert kind:=heartbeat | sort by (_time) desc | limit 1"
)
HEARTBEAT_EVIDENCE = (
    "_time:1h app_name:=visibility-alert kind:=heartbeat | sort by (_time) desc | limit 5"
)


def fingerprint(rule, subject):
    return hashlib.sha256(f"{rule}\n{subject}".encode()).hexdigest()[:20]


def _iso(moment):
    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, tail = text.split(".", 1)
        split = len(tail)
        for index, char in enumerate(tail):
            if not char.isdigit():
                split = index
                break
        text = head + "." + tail[:split][:6] + tail[split:]
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _item(row, now, state):
    first = str(row.get("first_seen") or "")
    last = str(row.get("last_seen") or "")
    anchor = parse_time(first if state == "firing" else last)
    age = 0 if anchor is None else max(0, int((now - anchor).total_seconds()))
    severity = row.get("severity")
    if severity not in ("info", "warning", "critical"):
        severity = "warning"
    return {
        "fingerprint": str(row.get("fingerprint") or "")[:64],
        "rule": str(row.get("rule") or "")[:80],
        "severity": severity,
        "state": "firing" if state == "firing" else "resolved",
        "subject": str(row.get("subject") or "")[:200],
        "summary": str(row.get("summary") or "")[:500],
        "first_seen": first,
        "last_seen": last,
        "age_seconds": age,
        "evidence_query": str(row.get("evidence_query") or "")[:1000],
    }


def _rank(severity):
    return {"critical": 0, "warning": 1, "info": 2}.get(severity, 3)


def reduce_alerts(transitions, heartbeat_row, heartbeat_known, now, stale_seconds=180, resolved_hours=24):
    newest = {}
    for row in transitions or []:
        if not isinstance(row, dict):
            continue
        if row.get("kind") not in (None, "transition"):
            continue
        key = str(row.get("fingerprint") or "")
        if not key or row.get("state") not in ("firing", "resolved"):
            continue
        moment = parse_time(row.get("_time") or row.get("last_seen"))
        previous = newest.get(key)
        if previous is None or moment is None or previous[0] is None or moment >= previous[0]:
            if previous is not None and moment is None:
                continue
            newest[key] = (moment, row)
    open_alerts = []
    resolved = []
    cutoff = now - timedelta(hours=resolved_hours)
    for _key, (moment, row) in newest.items():
        state = row.get("state")
        item = _item(row, now, state)
        if not item["fingerprint"]:
            continue
        if state == "firing":
            open_alerts.append(item)
        else:
            last = parse_time(row.get("last_seen")) or moment
            if last is not None and last >= cutoff:
                resolved.append(item)
    open_alerts.sort(key=lambda item: (_rank(item["severity"]), item["first_seen"]))
    resolved.sort(key=lambda item: item["last_seen"], reverse=True)
    checker = "unknown"
    if heartbeat_known:
        seen = parse_time((heartbeat_row or {}).get("_time") or (heartbeat_row or {}).get("last_seen")) if heartbeat_row else None
        fresh = seen is not None and (now - seen).total_seconds() <= stale_seconds
        checker = "ok" if fresh else "silent"
        if not fresh:
            anchor = seen or now
            open_alerts.insert(0, {
                "fingerprint": fingerprint("checker-silent", "alerter"),
                "rule": "checker-silent",
                "severity": "critical",
                "state": "firing",
                "subject": "alerter",
                "summary": "Alert checker heartbeat is missing or older than its limit.",
                "first_seen": _iso(anchor),
                "last_seen": _iso(anchor),
                "age_seconds": max(0, int((now - anchor).total_seconds())),
                "evidence_query": HEARTBEAT_EVIDENCE,
            })
    return {"checker": checker, "open": open_alerts, "resolved": resolved[:20]}


def _alert(rule, subject, severity, state, summary, first, last, now, evidence):
    anchor = first if state == "firing" else last
    return {
        "fingerprint": fingerprint(rule, subject),
        "rule": rule,
        "severity": severity,
        "state": state,
        "subject": subject,
        "summary": summary,
        "first_seen": _iso(first),
        "last_seen": _iso(last),
        "age_seconds": max(0, int((now - anchor).total_seconds())),
        "evidence_query": evidence,
    }


def demo_alerts(now=None):
    now = now or datetime.now(UTC)
    warning_at = now - timedelta(minutes=12)
    info_at = now - timedelta(minutes=4)
    resolved_at = now - timedelta(hours=2)
    return {
        "mode": "demo",
        "as_of": _iso(now),
        "checker": "ok",
        "illustrative": True,
        "open": [
            _alert(
                "source-freshness", "filterlog", "warning", "firing",
                "Illustrative warning: firewall logs are delayed. Demo data only.",
                warning_at, now, now,
                'app_name:=filterlog | sort by (_time) desc | limit 5',
            ),
            _alert(
                "new-entity", "demo-client", "info", "firing",
                "Illustrative info: a client was first seen. Demo data only.",
                info_at, now, now,
                '_time:2h app_name:=unifi-snapshot entity_kind:=client | limit 5',
            ),
        ],
        "resolved": [
            _alert(
                "disk-usage", "data-volume", "warning", "resolved",
                "Illustrative resolved warning: disk use returned below its clear threshold.",
                now - timedelta(hours=3), resolved_at, now,
                'app_name:=visibility-alert rule:=disk-usage subject:="data-volume" | sort by (_time) desc | limit 5',
            ),
        ],
    }


def live_alerts(client, now=None, stale_seconds=180):
    now = now or datetime.now(UTC)
    deadline = time.monotonic() + 8
    try:
        transitions = client.query(TRANSITIONS, deadline)
    except QueryError:
        raise
    heartbeat_known = True
    heartbeat = None
    try:
        rows = client.query(HEARTBEAT, time.monotonic() + 8)
        heartbeat = rows[0] if rows else None
    except QueryError:
        heartbeat_known = False
    reduced = reduce_alerts(transitions, heartbeat, heartbeat_known, now, stale_seconds)
    return {"mode": "live", "as_of": _iso(now), "illustrative": False, **reduced}
