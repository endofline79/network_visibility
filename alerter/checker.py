"""Alert checker loop. One cycle evaluates rules, then the stream, then webhooks."""

import argparse
import json
import logging
import os
import signal
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import load
from evaluate import evaluate, rate_limit
from machine import apply, blank_state, ensure_open, fingerprint
from times import iso
from transport import (
    InsertError,
    WebhookError,
    collect,
    drain_webhooks,
    insert_rows,
    post_webhook,
    webhook_configured,
)

log = logging.getLogger("visibility.alerter")
STREAM_CAP = 100


def stream_record(alert, hostname, when):
    details = alert.get("details") or {}
    summary = alert["summary"]
    return {
        "_time": iso(when),
        "_msg": summary,
        "hostname": hostname,
        "app_name": "visibility-alert",
        "kind": "transition",
        "fingerprint": alert["fingerprint"],
        "rule": alert["rule"],
        "severity": alert["severity"],
        "state": alert["state"],
        "subject": alert["subject"],
        "summary": summary,
        "first_seen": alert["first_seen"],
        "last_seen": alert["last_seen"],
        "evidence_query": alert["evidence_query"],
        "details": json.dumps(details, sort_keys=True, default=str),
    }


def heartbeat_record(config, now, open_count, extra):
    summary = f"Alert checker completed a cycle with {open_count} open alerts."
    return {
        "_time": iso(now),
        "_msg": summary,
        "hostname": config["hostname"],
        "app_name": "visibility-alert",
        "kind": "heartbeat",
        "fingerprint": fingerprint("checker-heartbeat", "alerter"),
        "rule": "checker-heartbeat",
        "severity": "info",
        "state": "ok",
        "subject": "alerter",
        "summary": summary,
        "first_seen": iso(now),
        "last_seen": iso(now),
        "evidence_query": '_time:1h app_name:=visibility-alert kind:=heartbeat | sort by (_time) desc | limit 5',
        "details": json.dumps(extra, sort_keys=True, default=str),
    }


def load_state(path):
    file = Path(path)
    if not file.exists():
        return blank_state()
    data = json.loads(file.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("Alert state version is unsupported; refusing to replace it")
    for key, value in blank_state().items():
        data.setdefault(key, value)
    return data


def save_state(path, state):
    file = Path(path)
    file.parent.mkdir(mode=0o700, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", dir=file.parent, delete=False)
    try:
        json.dump(state, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
        os.chmod(handle.name, 0o600)
        os.replace(handle.name, file)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)


def deliver_stream(state, rows, insert):
    pending = list(state.get("stream_outbox") or []) + list(rows)
    transitions = [row for row in pending if row.get("kind") != "heartbeat"]
    heartbeats = [row for row in pending if row.get("kind") == "heartbeat"]
    batch = transitions[-STREAM_CAP:]
    if heartbeats:
        batch.append(heartbeats[-1])
    if not batch:
        state["stream_outbox"] = []
        return True
    try:
        insert(batch)
    except InsertError:
        state["stream_outbox"] = batch
        return False
    state["stream_outbox"] = []
    return True


def open_count(state):
    return sum(1 for alert in state["alerts"].values() if alert.get("state") == "firing")


def run_cycle(config, state, now, obs, insert, deliver, notes=None):
    webhook_on = webhook_configured(config)
    cycle_config = dict(config)
    cycle_config["webhook_enabled"] = webhook_on
    conditions = evaluate(cycle_config, obs, state)
    state, transitions = apply(state, conditions, now, cycle_config)
    sent = suppressed = 0
    if webhook_on:
        sent, suppressed = drain_webhooks(state, now, config, deliver)
    over = suppressed > 0 or (
        webhook_on and len(state.get("webhook_sends") or []) >= int(config["webhook_max_per_hour"])
        and any(True for _ in state.get("outbox") or []))
    state["rate_limited"] = bool(over)
    if state["rate_limited"]:
        for cond in rate_limit(config, state):
            transitions.extend(ensure_open(state, cond, now, cycle_config))
    records = [stream_record(alert, config["hostname"], now) for alert in transitions]
    extra = {
        "open": open_count(state),
        "webhook": "configured" if webhook_on else "not-configured",
        "webhook_sent": sent,
        "webhook_queued": len(state.get("outbox") or []),
        "suppressed": suppressed,
    }
    if notes:
        extra.update(notes)
    records.append(heartbeat_record(config, now, extra["open"], extra))
    wrote = deliver_stream(state, records, insert)
    status = {
        "updated_at": now.timestamp(),
        "open": extra["open"],
        "webhook_queued": extra["webhook_queued"],
        "last_error": None if wrote else "stream-insert",
        "webhook": extra["webhook"],
    }
    return state, records, status


def dry_conditions(now):
    warning_seen = iso(now - timedelta(minutes=31))
    return [
        {
            "rule": "dry-run",
            "subject": "synthetic-warning",
            "severity": "warning",
            "summary": "Synthetic dry-run warning. No network condition is asserted.",
            "evidence_query": 'app_name:=visibility-alert rule:=dry-run subject:="synthetic-warning" | sort by (_time) desc | limit 5',
            "details": {"synthetic": True, "tier": "warning"},
            "backdate": warning_seen,
        },
        {
            "rule": "dry-run",
            "subject": "synthetic-critical",
            "severity": "critical",
            "summary": "Synthetic dry-run critical. No network condition is asserted.",
            "evidence_query": 'app_name:=visibility-alert rule:=dry-run subject:="synthetic-critical" | sort by (_time) desc | limit 5',
            "details": {"synthetic": True, "tier": "critical"},
        },
    ]


def run_dry(config, state, now, insert, deliver):
    """Fire one aged synthetic warning and one critical through the real state machine."""
    warning, critical = dry_conditions(now)
    backdated = now - timedelta(minutes=31)
    state, first = apply(state, [{k: v for k, v in warning.items() if k != "backdate"}], backdated, config)
    # The warning must already have been open for the notify delay. Stamp the
    # episode at the backdated time; apply() did that by being called then.
    state, second = apply(state, [
        {k: v for k, v in warning.items() if k != "backdate"},
        critical,
    ], now, config)
    transitions = first + second
    sent, suppressed = drain_webhooks(state, now, config, deliver)
    records = [stream_record(alert, config["hostname"], parse_alert_time(alert, backdated, now))
               for alert in transitions]
    records.append(heartbeat_record(config, now, open_count(state), {
        "open": open_count(state), "webhook": "configured", "webhook_sent": sent,
        "synthetic": True, "suppressed": suppressed,
    }))
    if not deliver_stream(state, records, insert):
        raise InsertError("status")
    kinds = {(row["severity"], row["state"], row["subject"]) for row in records if row["kind"] == "transition"}
    if ("warning", "firing", "synthetic-warning") not in kinds or ("critical", "firing", "synthetic-critical") not in kinds:
        raise RuntimeError("dry-run did not emit both synthetic alerts")
    return state, records, sent


def parse_alert_time(alert, backdated, now):
    if alert["subject"] == "synthetic-warning" and alert["state"] == "firing" and alert["first_seen"] == iso(backdated):
        return backdated
    return now


def clear_synthetic(config, state, now, insert, deliver):
    from machine import _resolve
    transitions = []
    for alert in list(state["alerts"].values()):
        if alert.get("rule") == "dry-run" and alert.get("state") == "firing":
            transitions.append(_resolve(state, alert, now, config))
    if webhook_configured(config):
        drain_webhooks(state, now, config, deliver)
    records = [stream_record(alert, config["hostname"], now) for alert in transitions]
    records.append(heartbeat_record(config, now, open_count(state), {"synthetic_clear": True}))
    deliver_stream(state, records, insert)
    return state, records


def state_path(config):
    return Path(config["state_dir"]) / "state.json"


def status_path(config):
    return Path(config["state_dir"]) / "status.json"


def write_status(config, status):
    path = status_path(config)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(status), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def apply_env(config):
    mapping = {
        "ALERT_INSERT_URL": "insert_url",
        "ALERT_INSERT_TOKEN_FILE": "insert_token_file",
        "ALERT_API_CERT_FILE": "insert_cert_file",
        "WEBHOOK_URL_FILE": "webhook_url_file",
        "WEBHOOK_KEY_FILE": "webhook_key_file",
        "ALERTER_STATE_DIR": "state_dir",
        "VICTORIALOGS_URL": "victorialogs_url",
    }
    for env_name, key in mapping.items():
        if os.environ.get(env_name):
            config[key] = os.environ[env_name]
    return config


def _insert(config):
    def _send(rows):
        insert_rows(rows, config)
    return _send


def _deliver(config):
    def _send(payload):
        post_webhook(payload, config)
    return _send


def refresh_rules(config):
    """Reload the rules file so threshold edits apply on the next cycle."""
    path = os.environ.get("ALERTER_CONFIG", str(Path(__file__).with_name("rules.json")))
    try:
        fresh = apply_env(load(path))
    except Exception:
        log.warning("rules reload failed; keeping the previous rules")
        return config
    config.clear()
    config.update(fresh)
    return config


def once(config, state_file):
    refresh_rules(config)
    now = datetime.now(timezone.utc)
    state = load_state(state_file)
    obs, notes = collect(config, now)
    if notes.get("private_key_mounted"):
        notes = {**notes, "private_key": True}
    try:
        state, _, status = run_cycle(config, state, now, obs, _insert(config), _deliver(config), notes)
    except Exception:
        log.warning("cycle failed: %s", "checker")
        status = {"updated_at": now.timestamp(), "open": open_count(state), "last_error": "cycle", "webhook_queued": len(state.get("outbox") or [])}
        write_status(config, status)
        raise
    save_state(state_file, state)
    write_status(config, status)
    log.info("cycle open=%s webhook_queued=%s", status["open"], status["webhook_queued"])
    return state


def loop(config, stop, once_only=False):
    file = state_path(config)
    while not stop.is_set():
        started = time.monotonic()
        try:
            once(config, file)
        except Exception:
            log.warning("cycle failed")
        if once_only:
            return
        remaining = float(config["interval_seconds"]) - (time.monotonic() - started)
        if remaining > 0:
            stop.wait(remaining)


def dry_main(config):
    if not webhook_configured(config):
        log.warning("dry-run refused: webhook secrets are not configured")
        return 2
    now = datetime.now(timezone.utc)
    file = state_path(config)
    state = load_state(file)
    try:
        state, records, sent = run_dry(config, state, now, _insert(config), _deliver(config))
    except (InsertError, WebhookError):
        log.warning("dry-run failed")
        return 1
    save_state(file, state)
    write_status(config, {"updated_at": now.timestamp(), "open": open_count(state), "last_error": None, "webhook_queued": len(state.get("outbox") or [])})
    log.info("dry-run wrote %s stream records and delivered %s webhooks", len(records), sent)
    return 0 if sent >= 2 else 1


def clear_main(config):
    now = datetime.now(timezone.utc)
    file = state_path(config)
    state = load_state(file)
    state, _ = clear_synthetic(config, state, now, _insert(config), _deliver(config))
    save_state(file, state)
    log.info("cleared synthetic dry-run alerts")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Visibility alert checker")
    parser.add_argument("--dry-run", action="store_true", help="Emit one synthetic warning and one synthetic critical")
    parser.add_argument("--clear-synthetic", action="store_true", help="Resolve synthetic dry-run alerts")
    parser.add_argument("--once", action="store_true", help="Evaluate one cycle and exit")
    args = parser.parse_args(argv)
    config = apply_env(load(os.environ.get("ALERTER_CONFIG", str(Path(__file__).with_name("rules.json")))))
    if args.dry_run:
        raise SystemExit(dry_main(config))
    if args.clear_synthetic:
        raise SystemExit(clear_main(config))
    stop = __import__("threading").Event()

    def _stop(signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    loop(config, stop, once_only=args.once)


if __name__ == "__main__":
    main()
