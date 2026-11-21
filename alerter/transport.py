"""Network and host I/O. Secrets are read from files and are never logged."""

import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from der import CertParseError, not_after
from evaluate import QUERY_ERROR, Observation, median_baseline
from times import parse_time

log = __import__("logging").getLogger("visibility.alerter")

PRIVATE_KEY_MARK = "PRIVATE KEY"
_GATEWAY_DOWN = re.compile(r"(?i)alarm|loss\s*100\s*%|gateway down")
_GATEWAY_UP = re.compile(r"(?i)\bclear\b|gateway up|loss\s*0\s*%")
_DHCP = re.compile(
    r"(?i)DHCPACK(?:\s+\S+){0,4}\s+(?P<ip>(?:\d{1,3}\.){3}\d{1,3}).*?(?P<mac>[0-9a-f]{2}(?::[0-9a-f]{2}){5})")


class InsertError(Exception):
    pass


class WebhookError(Exception):
    pass


def _memory_text(body):
    text = body.lower()
    return "memory" in text and "limit" in text


def query_logs(base, logsql, timeout):
    url = base.rstrip("/") + "/select/logsql/query"
    data = urllib.parse.urlencode({"query": logsql, "limit": "2000"}).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise InsertError("status")
            raw = response.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        snippet = exc.read(500).decode("utf-8", "replace")
        err = InsertError("memory" if _memory_text(snippet) else "status")
        raise err from None
    except (OSError, TimeoutError) as exc:
        raise InsertError("unreachable") from exc
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def parse_metrics(text):
    totals = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        try:
            body, raw_value = line.rsplit(" ", 1)
            value = float(raw_value)
        except ValueError:
            continue
        name = body.split("{", 1)[0]
        totals[name] = totals.get(name, 0.0) + value
    return totals


def fetch_metrics(base, timeout):
    request = urllib.request.Request(base.rstrip("/") + "/metrics", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise InsertError("status")
            return parse_metrics(response.read(2 * 1024 * 1024).decode("utf-8", "replace"))
    except InsertError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise InsertError("unreachable") from exc


def _expected_pin(cert_file):
    pem = Path(cert_file).read_text(encoding="utf-8")
    if PRIVATE_KEY_MARK in pem:
        raise InsertError("pin")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def pinned_http(host, port, method, path, body, headers, cert_file, timeout):
    """Send one HTTPS request after the peer certificate matches the mounted PEM.

    The caller must not include a credential until this returns a connection that
    already passed the pin check. This function sends the request itself so the
    token never leaves the process before the pin matches.
    """
    expected = _expected_pin(cert_file)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(host, port, context=context, timeout=timeout)
    try:
        conn.connect()
        peer = conn.sock.getpeercert(binary_form=True)
        actual = hashlib.sha256(peer).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise InsertError("pin")
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        payload = response.read(65536)
        return response.status, payload, peer
    finally:
        conn.close()


def insert_rows(rows, config):
    if not rows:
        return
    token_path = Path(config["insert_token_file"])
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise InsertError("token") from exc
    if not token or len(token) > 8192 or any(ch.isspace() for ch in token):
        raise InsertError("token")
    parts = urllib.parse.urlsplit(config["insert_url"])
    if parts.scheme != "https" or not parts.hostname:
        raise InsertError("url")
    path = parts.path or "/"
    if parts.query:
        path = path + "?" + parts.query
    body = "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows).encode()
    if token.encode() in body:
        raise InsertError("payload")
    try:
        status, _, _ = pinned_http(
            parts.hostname, parts.port or 443, "POST", path, body,
            {"Content-Type": "application/stream+json", "Authorization": "Bearer " + token},
            config["insert_cert_file"], float(config.get("webhook_timeout_seconds", 8)))
    except InsertError:
        log.warning("alert stream insert failed")
        raise
    except (OSError, ssl.SSLError, TimeoutError, http.client.HTTPException):
        log.warning("alert stream insert failed")
        raise InsertError("unreachable") from None
    if status != 200:
        log.warning("alert stream insert failed")
        raise InsertError("status")


def probe_pinned_cert(host, port, pin, timeout):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(host, port, context=context, timeout=timeout)
    try:
        conn.connect()
        peer = conn.sock.getpeercert(binary_form=True)
        actual = hashlib.sha256(peer).hexdigest()
        if not hmac.compare_digest(actual, str(pin).lower()):
            return "pin-mismatch", actual
        try:
            expiry = not_after(peer)
        except CertParseError:
            return "unreadable", actual
        days = (expiry - datetime.now(timezone.utc)).total_seconds() / 86400
        return days, actual
    except (OSError, ssl.SSLError, TimeoutError, http.client.HTTPException):
        return "unreachable", None
    finally:
        conn.close()


def file_cert_days(path):
    file = Path(path)
    if not file.is_file():
        return "missing"
    try:
        pem = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unreadable"
    if PRIVATE_KEY_MARK in pem:
        return "private-key"
    try:
        expiry = not_after(ssl.PEM_cert_to_DER_cert(pem))
    except (CertParseError, ValueError, ssl.SSLError):
        return "unreadable"
    return (expiry - datetime.now(timezone.utc)).total_seconds() / 86400


def scan_cert_dir(directory):
    found = {}
    root = Path(directory)
    if not root.is_dir():
        return found
    for file in sorted(root.iterdir()):
        if not file.is_file() or file.suffix.lower() not in (".crt", ".pem"):
            continue
        found[file.stem] = file_cert_days(file)
    return found


def disk_percent(path):
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    if usage.total <= 0:
        return None
    return (usage.used / usage.total) * 100


def _http_ok(url, timeout):
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(256)
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        return exc.code in (200, 401)
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def _pinned_probe(url, cert_file, timeout):
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    try:
        status, _, _ = pinned_http(
            parts.hostname, parts.port or 443, "GET", path, None, {"Accept": "text/plain"},
            cert_file, timeout)
    except (InsertError, OSError, ssl.SSLError, TimeoutError, http.client.HTTPException):
        return False
    return status in (200, 401) or 200 <= status < 300


def docker_containers(socket_path, projects):
    if not socket_path or not os.path.exists(socket_path):
        raise OSError("socket missing")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect(socket_path)
        target = "/v1.41/containers/json?all=1"
        sock.sendall(
            f"GET {target} HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
        chunks = []
        total = 0
        while total < 2_000_000:
            piece = sock.recv(65536)
            if not piece:
                break
            chunks.append(piece)
            total += len(piece)
    finally:
        sock.close()
    raw = b"".join(chunks)
    _, _, body = raw.partition(b"\r\n\r\n")
    # HTTP/1.0 with Connection: close puts the full body after the headers.
    start, end = body.find(b"["), body.rfind(b"]")
    if start < 0 or end <= start:
        raise OSError("docker response")
    try:
        items = json.loads(body[start:end + 1].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OSError("docker response") from exc
    wanted = set(projects or [])
    found = []
    for item in items:
        labels = item.get("Labels") or {}
        project = labels.get("com.docker.compose.project", "")
        if wanted and project not in wanted:
            continue
        names = item.get("Names") or [""]
        found.append({
            "name": str(names[0]).lstrip("/"),
            "state": item.get("State") or "",
            "status": item.get("Status") or "",
            "project": project,
        })
    return found


def classify_gateway(rows):
    if not rows:
        return "unknown"
    message = str(rows[0].get("_msg") or "")
    down = _GATEWAY_DOWN.search(message)
    up = _GATEWAY_UP.search(message)
    if down and not up:
        return "down"
    if up and not down:
        return "up"
    if down:
        return "down"
    return "unknown"


def _stat_count(row):
    if not isinstance(row, dict):
        return None
    for key in ("rows", "count", "count(*)"):
        if key in row:
            try:
                return float(row[key])
            except (TypeError, ValueError):
                return None
    for key, value in row.items():
        if key == "_time":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def block_counts(recent_rows, bucket_rows):
    recent = 0.0 if not recent_rows else (_stat_count(recent_rows[0]) or 0.0)
    buckets = []
    for row in bucket_rows or []:
        count = _stat_count(row)
        if count is None:
            continue
        stamp = row.get("_time")
        buckets.append((parse_time(stamp) if stamp else None, count))
    if buckets and buckets[-1][0] is not None:
        # The newest bucket overlaps the recent window; keep it out of the baseline.
        ordered = sorted(buckets, key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc))
        baseline_counts = [count for _, count in ordered[:-1]]
    else:
        baseline_counts = [count for _, count in buckets]
    return recent, median_baseline(baseline_counts)


def _load_parser():
    try:
        from filterlog import parse_filterlog
        return parse_filterlog
    except ImportError:
        import sys
        root = Path(__file__).resolve().parents[1]
        bundled = Path(__file__).resolve().parent
        for candidate in (bundled, root / "dashboard" / "backend"):
            if (candidate / "filterlog.py").exists():
                sys.path.insert(0, str(candidate))
                break
        from filterlog import parse_filterlog
        return parse_filterlog


def _entities_from_snapshot(row):
    found = {}
    raw = row.get("snapshot_json")
    if not raw:
        return found
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError:
        return found
    for kind, group in (("device", "devices"), ("client", "clients")):
        for item in snapshot.get(group) or []:
            identity = str(item.get("id") or "")
            if not identity:
                continue
            found[f"unifi-{kind}:{identity}"] = {
                "kind": f"UniFi {kind}",
                "name": str(item.get("name") or identity)[:120],
                "ip": str(item.get("ip") or "")[:64],
                "evidence_query": f'_time:2h app_name:=unifi-snapshot "{identity}" | limit 5',
            }
    return found


def _safe_query(base, logsql, timeout, errors):
    try:
        return query_logs(base, logsql, timeout)
    except InsertError as exc:
        errors.append(str(exc))
        return None


def collect(config, now):
    base = config.get("victorialogs_url", "http://logs:9428")
    timeout = float(config.get("query_timeout_seconds", 8))
    errors = []
    sources = {}
    for source in config["sources"]:
        rows = _safe_query(
            base, f"_time:{source.get('lookback', '6h')} {source['query']} | sort by (_time) desc | limit 1",
            timeout, errors)
        if rows is None:
            sources[source["id"]] = QUERY_ERROR
        elif not rows or not rows[0].get("_time"):
            sources[source["id"]] = None
        else:
            sources[source["id"]] = rows[0]["_time"]
    certs = {}
    for item in config.get("certificates") or []:
        certs[item["name"]] = file_cert_days(item["path"])
    for name, result in scan_cert_dir(config.get("cert_dir", "")).items():
        certs.setdefault(name, result)
    for item in config.get("remote_certs") or []:
        result, _ = probe_pinned_cert(item["host"], int(item["port"]), item["sha256"], timeout)
        certs[item["name"]] = result
    metrics = None
    try:
        metrics = fetch_metrics(base, timeout)
    except InsertError as exc:
        errors.append(str(exc))
    query_error_rows = 0
    query_memory = any(item == "memory" for item in errors)
    error_query = config.get("query_error_query")
    if error_query:
        rows = _safe_query(base, error_query, timeout, errors)
        if rows is not None:
            query_error_rows = len(rows)
    query_memory = query_memory or any(item == "memory" for item in errors)
    containers = None
    docker_error = None
    socket_path = (config.get("containers") or {}).get("socket")
    if socket_path:
        try:
            containers = docker_containers(socket_path, (config.get("containers") or {}).get("projects"))
        except OSError:
            docker_error = "unavailable"
    probes = {}
    for probe in config.get("probes") or []:
        if probe.get("tls"):
            probes[probe["id"]] = _pinned_probe(probe["url"], probe.get("cert_file") or config["insert_cert_file"], timeout)
        else:
            probes[probe["id"]] = _http_ok(probe["url"], timeout)
    gateway_state = "unknown"
    gateway_query = config.get("gateway_query")
    if gateway_query:
        rows = _safe_query(base, gateway_query, timeout, errors)
        if rows is not None:
            gateway_state = classify_gateway(rows)
    wan_events = []
    wan = config.get("wan_ingress") or {}
    if wan.get("query"):
        rows = _safe_query(base, wan["query"], timeout, errors)
        if rows:
            parse_filterlog = _load_parser()
            wan_events = [parse_filterlog(row) for row in rows[:2000]]
    block_recent = block_baseline = None
    spike = config.get("block_spike") or {}
    if spike.get("recent_query") and spike.get("baseline_query"):
        recent_rows = _safe_query(base, spike["recent_query"], timeout, errors)
        base_rows = _safe_query(base, spike["baseline_query"], timeout, errors)
        if recent_rows is not None and base_rows is not None:
            block_recent, block_baseline = block_counts(recent_rows, base_rows)
    entities = None
    entity_rows = _safe_query(
        base,
        '_time:2h app_name:=unifi-snapshot entity_kind:=snapshot | sort by (_time) desc | limit 1',
        timeout, errors)
    dns_rows = _safe_query(
        base,
        '_time:1h app_name:=pihole-dns | stats by (client_ip) count() rows | limit 500',
        timeout, errors)
    dhcp_rows = _safe_query(
        base, '_time:15m "DHCPACK" | limit 200', timeout, errors)
    if entity_rows:
        entities = _entities_from_snapshot(entity_rows[0])
        for row in dns_rows or []:
            ip = str(row.get("client_ip") or "")
            if not ip:
                continue
            entities[f"dns-client:{ip}"] = {
                "kind": "DNS client", "name": ip, "ip": ip,
                "evidence_query": f'_time:1h app_name:=pihole-dns client_ip:="{ip}" | limit 5',
            }
        for row in dhcp_rows or []:
            match = _DHCP.search(str(row.get("_msg") or ""))
            if not match:
                continue
            mac = match.group("mac").lower()
            entities[f"dhcp:{mac}"] = {
                "kind": "DHCP client", "name": mac, "ip": match.group("ip"),
                "evidence_query": f'_time:24h "{mac}" | limit 5',
            }
    private_key = any(value == "private-key" for value in certs.values())
    return Observation(
        now,
        sources=sources,
        certs=certs,
        disk_percent=disk_percent(config.get("disk", {}).get("path", "/data")),
        metrics=metrics,
        query_error_rows=query_error_rows,
        query_memory=query_memory,
        containers=containers,
        docker_error=docker_error,
        probes=probes,
        gateway=gateway_state,
        wan_events=wan_events,
        block_recent=block_recent,
        block_baseline=block_baseline,
        entities=entities,
    ), {"query_errors": len(errors), "private_key_mounted": private_key}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WebhookError("redirect")


def _read_secret(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def webhook_configured(config):
    url = _read_secret(config.get("webhook_url_file", ""))
    key = _read_secret(config.get("webhook_key_file", ""))
    return bool(url) and bool(key)


def post_webhook(payload, config):
    url = _read_secret(config["webhook_url_file"])
    key = _read_secret(config["webhook_key_file"])
    if not url or not key:
        raise WebhookError("unconfigured")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or parts.username or parts.password or not parts.hostname:
        raise WebhookError("url")
    if any(ch in url or ch in key for ch in "\r\n"):
        raise WebhookError("url")
    body = json.dumps(payload, sort_keys=True).encode()
    if key.encode() in body or url.encode() in body:
        raise WebhookError("payload")
    header = str(config["webhook_header"])
    value = str(config.get("webhook_header_prefix", "")) + key
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header(header, value)
    opener = urllib.request.build_opener(_NoRedirect)
    timeout = float(config.get("webhook_timeout_seconds", 8))
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(256)
            if not 200 <= response.status < 300:
                raise WebhookError("status")
    except WebhookError:
        log.warning("webhook delivery failed")
        raise
    except urllib.error.HTTPError:
        log.warning("webhook delivery failed")
        raise WebhookError("status") from None
    except (OSError, urllib.error.URLError, TimeoutError):
        log.warning("webhook delivery failed")
        raise WebhookError("unreachable") from None


def backoff_seconds(attempts, config):
    schedule = list(config.get("webhook_backoff_seconds") or [2, 5, 15, 30, 60])
    index = min(max(attempts, 1), len(schedule)) - 1
    return float(schedule[index])


def drain_webhooks(state, now, config, deliver):
    from datetime import timedelta
    from times import iso

    window = []
    for stamp in state.get("webhook_sends") or []:
        if (now - parse_time(stamp)).total_seconds() < 3600:
            window.append(stamp)
    state["webhook_sends"] = window
    maximum = int(config["webhook_max_per_hour"])
    sent = 0
    suppressed = 0
    ordered = sorted(
        list(state.get("outbox") or []),
        key=lambda item: (0 if item["payload"].get("rule") == "webhook-rate" else 1, item.get("next_attempt") or ""),
    )
    for item in ordered:
        if parse_time(item["next_attempt"]) > now:
            continue
        if len(state["webhook_sends"]) >= maximum:
            suppressed += 1
            continue
        try:
            deliver(item["payload"])
        except WebhookError:
            item["attempts"] = int(item.get("attempts", 0)) + 1
            delay = backoff_seconds(item["attempts"], config)
            item["next_attempt"] = iso(now + timedelta(seconds=delay))
            continue
        from machine import mark_sent
        mark_sent(state, item, now)
        sent += 1
    state["suppressed"] = int(state.get("suppressed") or 0) + suppressed
    return sent, suppressed
