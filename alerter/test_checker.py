import json
import logging
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard" / "backend"))

from checker import refresh_rules, run_dry, stream_record
from config import load
from der import not_after
from evaluate import Observation, evaluate
from install_inserter import install
from machine import apply, blank_state, fingerprint
from times import iso
from transport import (
    InsertError,
    WebhookError,
    classify_gateway,
    docker_containers,
    file_cert_days,
    insert_rows,
    parse_metrics,
    post_webhook,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
RULES = Path(__file__).with_name("rules.json")
WAN = "5,,,rule-uuid,igc0,match,pass,in,4,0x0,,64,12345,0,DF,6,tcp,60,198.51.100.20,192.168.5.50,443,22,0,S,123456,,64240,,mss"


def config():
    data = load(RULES)
    data["state_dir"] = "/tmp"
    data["webhook_url_file"] = "/no/such/url"
    data["webhook_key_file"] = "/no/such/key"
    return data


def obs(**kwargs):
    base = config()
    kwargs.setdefault("sources", {source["id"]: iso(NOW - timedelta(seconds=10)) for source in base["sources"]})
    return Observation(NOW, **kwargs)


def names(conditions, rule=None):
    return [(c["severity"], c["subject"]) for c in conditions if rule is None or c["rule"] == rule]


class RulesFile(unittest.TestCase):
    def test_shipped_thresholds_match_the_tiers(self):
        data = load(RULES)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["staleness"], {"warning_seconds": 900, "critical_seconds": 1800})
        self.assertEqual(data["cert_thresholds_days"], {"info": 60, "warning": 30, "critical": 7})
        self.assertEqual(data["disk"]["warning_percent"], 80)
        self.assertEqual(data["disk"]["critical_percent"], 90)
        self.assertEqual(data["warning_notify_after_seconds"], 1800)
        self.assertEqual(data["webhook_header"], "Authorization")
        self.assertEqual(data["webhook_max_per_hour"], 30)
        self.assertIn("igc0", data["wan_ingress"]["interfaces"])
        self.assertEqual(data["rules"]["new-entity"]["notify"], "never")
        self.assertEqual(data["rules"]["webhook-rate"]["notify"], "immediate")
        self.assertTrue(data["insert_url"].startswith("https://api:8427/insert/"))
        self.assertNotIn("bearer_token", json.dumps(data))


class Machine(unittest.TestCase):
    def setUp(self):
        self.config = config()

    def condition(self, severity="warning", subject="filterlog", rule="source-freshness"):
        return {
            "rule": rule, "subject": subject, "severity": severity,
            "summary": f"{severity} {subject}", "evidence_query": "app_name:=filterlog",
            "details": {"n": 1},
        }

    def test_fingerprint_is_stable(self):
        self.assertEqual(fingerprint("wan-ingress", "igc0:192.168.5.50:22/tcp"),
                         fingerprint("wan-ingress", "igc0:192.168.5.50:22/tcp"))
        self.assertNotEqual(fingerprint("a", "b"), fingerprint("a", "c"))

    def test_info_never_webhooks_and_warning_waits(self):
        state = blank_state()
        state, _ = apply(state, [self.condition("info", rule="new-entity")], NOW, self.config)
        self.assertEqual(state["outbox"], [])
        state, _ = apply(state, [self.condition("warning")], NOW, self.config)
        self.assertEqual(state["outbox"], [])
        later = NOW + timedelta(minutes=31)
        state, _ = apply(state, [self.condition("warning")], later, self.config)
        self.assertEqual(len(state["outbox"]), 1)
        self.assertEqual(state["outbox"][0]["payload"]["severity"], "warning")
        self.assertNotIn("webhook", state["outbox"][0]["payload"])

    def test_critical_webhooks_immediately_and_resolve_notifies_once(self):
        state = blank_state()
        state, transitions = apply(state, [self.condition("critical", rule="gateway-down")], NOW, self.config)
        self.assertEqual(transitions[0]["state"], "firing")
        self.assertEqual(len(state["outbox"]), 1)
        state["alerts"][transitions[0]["fingerprint"]]["notified"] = True
        state["alerts"][transitions[0]["fingerprint"]]["notify_queued"] = False
        state["outbox"].clear()
        state, started = apply(state, [], NOW + timedelta(minutes=1), self.config)
        self.assertEqual(started, [])
        state, transitions = apply(state, [], NOW + timedelta(minutes=5), self.config)
        self.assertEqual(transitions[0]["state"], "resolved")
        self.assertEqual(len(state["outbox"]), 1)
        self.assertEqual(state["outbox"][0]["payload"]["state"], "resolved")
        state["outbox"].clear()
        state["alerts"][transitions[0]["fingerprint"]]["resolve_queued"] = True
        state, again = apply(state, [], NOW + timedelta(minutes=6), self.config)
        self.assertEqual(again, [])
        self.assertEqual(state["outbox"], [])

    def test_hysteresis_and_renotify_cooldown(self):
        state = blank_state()
        cfg = config()
        cfg["rules"]["disk-usage"]["fire_after_seconds"] = 60
        cond = self.condition("warning", "data-volume", "disk-usage")
        state, opened = apply(state, [cond], NOW, cfg)
        self.assertEqual(opened, [])
        self.assertIn(fingerprint("disk-usage", "data-volume"), state["pending"])
        state, opened = apply(state, [], NOW + timedelta(seconds=30), cfg)
        self.assertEqual(state["pending"], {})
        state, opened = apply(state, [cond], NOW + timedelta(seconds=40), cfg)
        state, opened = apply(state, [cond], NOW + timedelta(seconds=100), cfg)
        self.assertEqual(opened[0]["state"], "firing")
        cfg["rules"]["gateway-down"]["renotify_seconds"] = 600
        state = blank_state()
        state, _ = apply(state, [self.condition("critical", rule="gateway-down")], NOW, cfg)
        from machine import mark_sent
        mark_sent(state, state["outbox"][0], NOW)
        state, _ = apply(state, [self.condition("critical", rule="gateway-down")], NOW + timedelta(seconds=30), cfg)
        self.assertEqual(state["outbox"], [])
        state, _ = apply(state, [self.condition("critical", rule="gateway-down")], NOW + timedelta(seconds=601), cfg)
        self.assertEqual(len(state["outbox"]), 1)

    def test_escalation_to_critical_notifies_immediately(self):
        state = blank_state()
        state, _ = apply(state, [self.condition("warning")], NOW, self.config)
        state["alerts"][fingerprint("source-freshness", "filterlog")]["notified"] = True
        state["alerts"][fingerprint("source-freshness", "filterlog")]["last_notified"] = iso(NOW)
        state, transitions = apply(state, [self.condition("critical")], NOW + timedelta(minutes=5), self.config)
        self.assertEqual(transitions[0]["severity"], "critical")
        self.assertEqual(state["outbox"][0]["payload"]["severity"], "critical")

    def test_disabled_webhook_does_not_queue(self):
        state = blank_state()
        cfg = config()
        cfg["webhook_enabled"] = False
        state, _ = apply(state, [self.condition("critical", rule="gateway-down")], NOW, cfg)
        self.assertEqual(state["outbox"], [])


class Evaluation(unittest.TestCase):
    def test_source_tiers(self):
        cfg = config()
        fresh = iso(NOW - timedelta(seconds=30))
        lagging = iso(NOW - timedelta(minutes=8))
        warning = iso(NOW - timedelta(minutes=16))
        critical = iso(NOW - timedelta(minutes=31))
        state = blank_state()
        conditions = evaluate(cfg, obs(sources={
            "filterlog": fresh, "opnsense-flow": lagging, "unifi-snapshot": warning,
            "pihole-dns": critical, "pihole-snapshot": None, "opnsense-syslog": fresh,
        }), state)
        tiers = {subject: severity for severity, subject in names(conditions, "source-freshness")}
        self.assertNotIn("filterlog", tiers)
        self.assertEqual(tiers["opnsense-flow"], "info")
        self.assertEqual(tiers["unifi-snapshot"], "warning")
        self.assertEqual(tiers["pihole-dns"], "critical")
        self.assertEqual(tiers["pihole-snapshot"], "critical")

    def test_certificate_tiers_and_private_key(self):
        cfg = config()
        conditions = evaluate(cfg, obs(certs={
            "telemetry-api": 50, "soon": 20, "urgent": 3, "ok": 90,
            "leaked": "private-key", "rotated": "pin-mismatch",
        }), blank_state())
        tiers = {c["subject"]: c["severity"] for c in conditions if c["rule"] in ("cert-expiry", "cert-pin")}
        self.assertEqual(tiers["telemetry-api"], "info")
        self.assertEqual(tiers["soon"], "warning")
        self.assertEqual(tiers["urgent"], "critical")
        self.assertNotIn("ok", tiers)
        self.assertEqual(tiers["leaked"], "warning")
        self.assertEqual(tiers["rotated"], "critical")
        self.assertNotIn("PRIVATE KEY", json.dumps(conditions))

    def test_disk_hysteresis(self):
        cfg = config()
        state = blank_state()
        first = evaluate(cfg, obs(disk_percent=91), state)
        self.assertEqual(names(first, "disk-usage"), [("critical", "data-volume")])
        state, _ = apply(state, first, NOW, cfg)
        held = evaluate(cfg, obs(disk_percent=86), state)
        self.assertEqual(names(held, "disk-usage"), [("warning", "data-volume")])
        state, _ = apply(state, held, NOW, cfg)
        cleared = evaluate(cfg, obs(disk_percent=70), state)
        self.assertEqual(names(cleared, "disk-usage"), [])

    def test_dropped_rows_are_a_delta_and_read_only_is_a_gauge(self):
        cfg = config()
        state = blank_state()
        first = evaluate(cfg, obs(metrics={"vl_rows_dropped_total": 5, "vl_storage_is_read_only": 0}), state)
        self.assertEqual(names(first, "rows-dropped"), [])
        second = evaluate(cfg, obs(metrics={"vl_rows_dropped_total": 7, "vl_storage_is_read_only": 1}), state)
        self.assertEqual(names(second, "rows-dropped"), [("critical", "victorialogs")])
        self.assertEqual(names(second, "storage-readonly"), [("critical", "victorialogs")])

    def test_wan_pass_to_rfc1918_respects_allowlist(self):
        from filterlog import parse_filterlog
        event = parse_filterlog({"_time": iso(NOW), "_msg": WAN})
        cfg = config()
        hit = [item for item in evaluate(cfg, obs(wan_events=[event]), blank_state()) if item["rule"] == "wan-ingress"]
        self.assertEqual(len(hit), 1)
        self.assertIn("192.168.5.50", hit[0]["subject"])
        cfg["wan_ingress"]["allow"] = [{"destination": "192.168.5.50", "destination_port": 22, "protocol": "tcp"}]
        self.assertEqual(evaluate(cfg, obs(wan_events=[event]), blank_state()), [])
        blocked = dict(event, action="block")
        self.assertEqual(evaluate(cfg, obs(wan_events=[blocked]), blank_state()), [])

    def test_block_spike_and_gateway(self):
        cfg = config()
        quiet = evaluate(cfg, obs(block_recent=10, block_baseline=4), blank_state())
        self.assertEqual(names(quiet, "block-spike"), [])
        spike = evaluate(cfg, obs(block_recent=80, block_baseline=10), blank_state())
        self.assertEqual(names(spike, "block-spike"), [("warning", "filterlog")])
        down = evaluate(cfg, obs(gateway="down"), blank_state())
        self.assertEqual(names(down, "gateway-down"), [("critical", "wan")])
        self.assertEqual(classify_gateway([{"_msg": "dpinger: WAN_DHCP 203.0.113.1: Alarm latency 0us loss 100%"}]), "down")
        self.assertEqual(classify_gateway([{"_msg": "dpinger: WAN_DHCP 203.0.113.1: Clear latency 1ms loss 0%"}]), "up")
        self.assertEqual(classify_gateway([]), "unknown")

    def test_new_entity_seeds_once(self):
        cfg = config()
        state = blank_state()
        current = {"unifi-client:a": {"kind": "UniFi client", "name": "Phone", "ip": "192.168.5.10"}}
        self.assertEqual(evaluate(cfg, obs(entities=current), state), [])
        self.assertTrue(state["entities_seeded"])
        current["unifi-client:b"] = {"kind": "UniFi client", "name": "Tablet", "ip": "192.168.5.11"}
        opened = evaluate(cfg, obs(entities=current), state)
        self.assertEqual(names(opened, "new-entity"), [("info", "unifi-client:b")])
        self.assertIn("Tablet", opened[0]["summary"])

    def test_container_down_and_probe_fallback(self):
        cfg = config()
        running = [{"name": name, "state": "running", "status": "Up (healthy)"} for name in cfg["containers"]["expect"]]
        self.assertEqual(names(evaluate(cfg, obs(containers=running, probes={"logs": True}), state=blank_state()), "container-health"), [])
        broken = [dict(item) for item in running]
        broken[0] = dict(broken[0], state="exited", status="Exited")
        hit = evaluate(cfg, obs(containers=broken), blank_state())
        self.assertIn(("critical", "visibility-logs-1"), names(hit, "container-health"))
        missing_socket = evaluate(cfg, obs(containers=None, docker_error="unavailable", probes={"logs": False}), blank_state())
        subjects = [c["subject"] for c in missing_socket if c["rule"] == "container-health"]
        self.assertIn("docker-socket", subjects)
        self.assertIn("visibility-logs-1", subjects)


class WebhookAndInsert(unittest.TestCase):
    def test_webhook_header_is_configurable_and_key_is_not_logged(self):
        canary = "CANARY-WEBHOOK-KEY-DO-NOT-LEAK"
        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                seen["body"] = self.rfile.read(length)
                seen["header"] = self.headers.get("X-Test-Auth")
                self.send_response(204)
                self.end_headers()

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            url = Path(tmp, "url")
            key = Path(tmp, "key")
            url.write_text(f"http://127.0.0.1:{server.server_address[1]}/hook")
            key.write_text(canary)
            cfg = config()
            cfg.update(webhook_url_file=str(url), webhook_key_file=str(key),
                       webhook_header="X-Test-Auth", webhook_header_prefix="Token ")
            records = []

            class Grab(logging.Handler):
                def emit(self, record):
                    records.append(record.getMessage())

            logger = logging.getLogger("visibility.alerter")
            handler = Grab()
            logger.addHandler(handler)
            self.addCleanup(logger.removeHandler, handler)
            payload = {"fingerprint": "abc", "rule": "dry-run", "severity": "critical", "state": "firing",
                       "subject": "synthetic-critical", "summary": "Synthetic", "first_seen": iso(NOW),
                       "last_seen": iso(NOW), "evidence_query": "app_name:=visibility-alert",
                       "console_url": "https://192.168.5.230:8096/", "details": {"synthetic": True}}
            post_webhook(payload, cfg)
            self.assertEqual(seen["header"], "Token " + canary)
            self.assertNotIn(canary.encode(), seen["body"])
            self.assertNotIn(canary, "\n".join(records))
            url.write_text("http://user:secret@127.0.0.1/hook")
            with self.assertRaises(WebhookError):
                post_webhook(payload, cfg)
            self.assertNotIn(canary, "\n".join(records))

    def test_redirect_is_not_followed(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1/stolen")
                self.end_headers()

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            url = Path(tmp, "url")
            key = Path(tmp, "key")
            url.write_text(f"http://127.0.0.1:{server.server_address[1]}/hook")
            key.write_text("k" * 40)
            cfg = config()
            cfg.update(webhook_url_file=str(url), webhook_key_file=str(key), webhook_timeout_seconds=2)
            with self.assertRaises(WebhookError) as caught:
                post_webhook({"fingerprint": "x", "details": {}}, cfg)
            self.assertEqual(str(caught.exception), "redirect")

    def test_rate_limit_keeps_the_rest_and_opens_a_summary(self):
        from transport import drain_webhooks
        cfg = config()
        cfg["webhook_max_per_hour"] = 1
        state = blank_state()
        state, _ = apply(state, [
            {"rule": "gateway-down", "subject": "wan", "severity": "critical", "summary": "down",
             "evidence_query": "x", "details": {}},
            {"rule": "storage-readonly", "subject": "victorialogs", "severity": "critical",
             "summary": "ro", "evidence_query": "y", "details": {}},
        ], NOW, cfg)
        sent = []
        delivered, suppressed = drain_webhooks(state, NOW, cfg, sent.append)
        self.assertEqual(delivered, 1)
        self.assertEqual(suppressed, 1)
        self.assertEqual(len(state["outbox"]), 1)
        state["rate_limited"] = True
        summary = evaluate(cfg, obs(), state)
        self.assertEqual(names(summary, "webhook-rate"), [("warning", "outbound")])
        self.assertNotIn("alert_webhook", json.dumps(state["outbox"]))

    def test_pin_mismatch_does_not_send_the_token(self):
        if subprocess.call(["openssl", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            self.skipTest("openssl is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            good = self._cert(tmp, "good")
            other = self._cert(tmp, "other")
            seen = {}

            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    seen["auth"] = self.headers.get("Authorization")
                    length = int(self.headers.get("Content-Length", "0"))
                    self.rfile.read(length)
                    self.send_response(200)
                    self.end_headers()

                def log_message(self, fmt, *args):
                    return

            httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(good[0], good[1])
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(httpd.shutdown)
            token = "T" * 40
            token_file = Path(tmp, "token")
            token_file.write_text(token)
            cfg = config()
            port = httpd.server_address[1]
            cfg.update(insert_url=f"https://127.0.0.1:{port}/insert/jsonline?_stream_fields=hostname,app_name",
                       insert_token_file=str(token_file), insert_cert_file=other[0])
            with self.assertRaises(InsertError):
                insert_rows([{"_msg": "x", "app_name": "visibility-alert"}], cfg)
            self.assertNotIn("auth", seen)
            cfg["insert_cert_file"] = good[0]
            insert_rows([{"_msg": "synthetic", "app_name": "visibility-alert"}], cfg)
            self.assertEqual(seen["auth"], "Bearer " + token)

    def _cert(self, tmp, name):
        crt = str(Path(tmp, name + ".crt"))
        key = str(Path(tmp, name + ".key"))
        subprocess.check_call([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key, "-out", crt,
            "-days", "40", "-nodes", "-subj", f"/CN={name}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return crt, key

    def test_der_not_after_matches_openssl(self):
        if subprocess.call(["openssl", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            self.skipTest("openssl is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            crt, _ = self._cert(tmp, "dated")
            der = ssl.PEM_cert_to_DER_cert(Path(crt).read_text())
            parsed = not_after(der)
            printed = subprocess.check_output(["openssl", "x509", "-enddate", "-noout", "-in", crt], text=True)
            stamp = printed.split("=", 1)[1].strip()
            expected = datetime.strptime(stamp, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
            self.assertEqual(parsed, expected)
            self.assertLess(file_cert_days(crt), 41)
            key = Path(tmp, "dated.key")
            key.write_text(key.read_text() + "\n")
            mixed = Path(tmp, "mixed.pem")
            mixed.write_text(Path(crt).read_text() + key.read_text())
            self.assertEqual(file_cert_days(mixed), "private-key")


class RulesReload(unittest.TestCase):
    def test_reload_replaces_thresholds_and_keeps_the_previous_file_on_failure(self):
        cfg = config()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "rules.json")
            path.write_text(RULES.read_text().replace(
                '"warning_notify_after_seconds": 1800',
                '"warning_notify_after_seconds": 42',
            ))
            with patch.dict(os.environ, {"ALERTER_CONFIG": str(path)}):
                refresh_rules(cfg)
            self.assertEqual(cfg["warning_notify_after_seconds"], 42)
            path.write_text("{")
            with patch.dict(os.environ, {"ALERTER_CONFIG": str(path)}):
                refresh_rules(cfg)
            self.assertEqual(cfg["warning_notify_after_seconds"], 42)


class DryRun(unittest.TestCase):
    def test_synthetic_warning_and_critical_reach_stream_and_webhook(self):
        cfg = config()
        inserted = []
        posted = []
        state, records, sent = run_dry(cfg, blank_state(), NOW, inserted.append, posted.append)
        self.assertGreaterEqual(sent, 2)
        subjects = {row["subject"] for row in records if row["kind"] == "transition"}
        self.assertEqual(subjects, {"synthetic-warning", "synthetic-critical"})
        self.assertTrue(any(row["kind"] == "heartbeat" for row in records))
        self.assertEqual(inserted[0][-1]["kind"], "heartbeat")
        payload_subjects = {item["subject"] for item in posted}
        self.assertEqual(payload_subjects, {"synthetic-warning", "synthetic-critical"})
        warning = next(item for item in posted if item["subject"] == "synthetic-warning")
        for key in ("fingerprint", "rule", "severity", "state", "subject", "summary",
                    "first_seen", "last_seen", "evidence_query", "console_url", "details"):
            self.assertIn(key, warning)
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(warning["state"], "firing")
        self.assertTrue(warning["details"]["synthetic"])
        self.assertLess(warning["first_seen"], iso(NOW))
        critical = next(row for row in records if row["subject"] == "synthetic-critical")
        rendered = stream_record(state["alerts"][critical["fingerprint"]], "ai-02", NOW)
        self.assertEqual(rendered["app_name"], "visibility-alert")
        self.assertEqual(rendered["state"], "firing")


class DockerSocket(unittest.TestCase):
    def test_lists_only_the_requested_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp, "docker.sock"))
            body = json.dumps([
                {"Names": ["/visibility-logs-1"], "State": "running", "Status": "Up (healthy)",
                 "Labels": {"com.docker.compose.project": "visibility"}},
                {"Names": ["/other-1"], "State": "exited", "Status": "Exited",
                 "Labels": {"com.docker.compose.project": "other"}},
            ]).encode()

            def serve():
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(path)
                server.listen(1)
                conn, _ = server.accept()
                conn.recv(65536)
                header = f"HTTP/1.0 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode()
                conn.sendall(header + body)
                conn.close()
                server.close()

            threading.Thread(target=serve, daemon=True).start()
            import time
            found = None
            deadline = time.time() + 2
            while time.time() < deadline:
                if os.path.exists(path):
                    try:
                        found = docker_containers(path, ["visibility"])
                        break
                    except OSError:
                        time.sleep(0.02)
                else:
                    time.sleep(0.02)
            self.assertIsNotNone(found)
            self.assertEqual([item["name"] for item in found], ["visibility-logs-1"])


class Inserter(unittest.TestCase):
    def test_adds_insert_only_user_without_changing_operator_or_printing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "auth.yaml")
            operator = "O" * 40
            path.write_text(json.dumps({"users": [{
                "name": "operator", "bearer_token": operator,
                "url_prefix": "http://logs:9428/", "headers": ["Authorization:"],
            }]}))
            token = "I" * 48
            self.assertEqual(install(path, token), "installed")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["users"][0]["bearer_token"], operator)
            added = saved["users"][1]
            self.assertEqual(added["name"], "alert-inserter")
            self.assertEqual(added["url_map"][0]["url_prefix"], "http://logs:9428")
            self.assertNotIn("url_prefix", {k: v for k, v in added.items() if k != "url_map"})
            self.assertIn("/insert/", "".join(added["url_map"][0]["src_paths"]))
            self.assertEqual(install(path, token), "matches")
            with self.assertRaises(SystemExit):
                install(path, "N" * 48)
            text = path.read_text()
            self.assertNotIn("printed", text)
            mode = oct(path.stat().st_mode & 0o777)
            self.assertEqual(mode, "0o600")


class Metrics(unittest.TestCase):
    def test_sums_labelled_samples(self):
        text = """
# HELP vl_rows_dropped_total dropped
vl_rows_dropped_total{reason="too_old"} 2
vl_rows_dropped_total{reason="too_big"} 3
vl_storage_is_read_only 0
"""
        parsed = parse_metrics(text)
        self.assertEqual(parsed["vl_rows_dropped_total"], 5)
        self.assertEqual(parsed["vl_storage_is_read_only"], 0)


if __name__ == "__main__":
    unittest.main()
