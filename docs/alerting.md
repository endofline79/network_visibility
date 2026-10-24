# Tiered alerting

The alert checker is a separate Compose service. It reads VictoriaLogs and
Docker health, writes state changes to the `app_name:=visibility-alert` stream,
and posts a webhook when a notify condition is met. The presentation console
only reads that stream. This note is the deploy and rollback procedure. It does
not start the service by itself.

Current surfaces stay the console at **https://192.168.5.230:8096/** and the
telemetry API at **https://192.168.5.230:9429**. The stopped `:8095` dashboard
is not part of alerting.

## What restarts

| Step | Containers |
| --- | --- |
| Install the insert-only vmauth user | None, if vmauth reloads `auth.yaml`. Recreate **only** `api` if the new user is still rejected. |
| Start the checker | **New** `alerter` container only. `logs`, `flows`, `telemetry`, and `api` stay up. |
| Show alerts on the console | Recreate **only** `visibility-presentation-console-1`. `:8096` drops while that container restarts. Collectors and the API stay up. |
| Synthetic dry-run | Stop and start **only** `alerter`. |

Do not use `docker compose down --volumes`. Do not rotate the operator token.
Do not change firewall rules, switch ports, or retention.

## Rules

Thresholds live in `alerter/rules.json`. The checker reloads that file every
cycle (about 60 seconds). A full-line `//` comment is allowed. Do not put
secrets in the file.

| Tier | Dashboard | Webhook |
| --- | --- | --- |
| info | Yes | Never. Includes a source lagging less than 15 minutes past its cadence, a new UniFi or DNS client after the first inventory seed, and a certificate inside 60 days. |
| warning | Yes | After the alert has stayed warning for 30 minutes (`warning_notify_after_seconds`). Includes a source stale at least 15 minutes, disk above 80 percent, VictoriaLogs query or memory-limit errors, a certificate inside 30 days, and a firewall block-rate spike. |
| critical | Yes | On the transition to critical. Includes VictoriaLogs read-only or dropped rows, a stack container down or unhealthy, a source stale at least 30 minutes, a WAN gateway down when OPNsense logs `dpinger`, disk above 90 percent, a certificate inside 7 days, and an accepted WAN (`igc0`) filterlog pass to an RFC1918 host that is not on `wan_ingress.allow`. |

One fingerprint is the first 20 hex characters of SHA-256 over `rule`, a
newline, and `subject`. The same condition keeps one alert across restarts.
Source freshness uses a single rule id so a source does not become a second
alert when it moves from info to warning to critical. Firing waits for
`fire_after_seconds`. Resolving waits for `resolve_after_seconds`. Disk also
clears only below 75 and 85 percent. A notified alert is repeated only after
`renotify_seconds`. Resolving sends a webhook only when that alert was
notified, was queued to notify, or still has an outbox item. Info never
notifies. A severity drop is written to the stream and is not a webhook.

The webhook body is JSON: `fingerprint`, `rule`, `severity`, `state`,
`subject`, `summary`, `first_seen`, `last_seen`, `evidence_query`,
`console_url`, `details`. `evidence_query` is LogsQL that reproduces the
evidence. Delivery is at-least-once, with the backoff list in the rules file,
an 8 second timeout, and an on-disk outbox under the state directory. Successful
sends are limited to `webhook_max_per_hour` (30). Further sends stay queued and
a `webhook-rate` warning is raised. The header name and prefix
(`webhook_header`, `webhook_header_prefix`) are set in the rules file because
the receiver's scheme is a deploy choice. The URL and key are files, not
environment variables.

Each cycle also writes `kind:=heartbeat`. If that heartbeat is missing or older
than 180 seconds, the console shows a synthetic critical `checker-silent`
alert. If the heartbeat query itself fails, the console reports the checker as
unknown and does not invent that alert. The container healthcheck reads
`/state/status.json` and fails when `updated_at` is older than 150 seconds.

## Secrets

Create directories as `klab` before Compose starts. Never commit these paths.

```bash
install -d -m 0700 -o klab -g klab /home/klab/.local/share/visibility/alerter
install -d -m 0755 -o klab -g klab /home/klab/.local/share/visibility/certs
install -d -m 0700 -o klab -g klab /home/klab/.local/share/visibility/secrets
touch /home/klab/.local/share/visibility/secrets/alert_insert_token
touch /home/klab/.local/share/visibility/secrets/alert_webhook_url
touch /home/klab/.local/share/visibility/secrets/alert_webhook_key
chmod 0600 /home/klab/.local/share/visibility/secrets/alert_insert_token \
  /home/klab/.local/share/visibility/secrets/alert_webhook_url \
  /home/klab/.local/share/visibility/secrets/alert_webhook_key
chown klab:klab /home/klab/.local/share/visibility/secrets/alert_insert_token \
  /home/klab/.local/share/visibility/secrets/alert_webhook_url \
  /home/klab/.local/share/visibility/secrets/alert_webhook_key
```

Generate an insert token that is not the operator token. Pass it on stdin.
`install_inserter.py` adds `alert-inserter` with only `/insert/jsonline` and
`/insert/*`, strips `Authorization`, and refuses to change the operator user or
to reuse an existing token. It does not print the token.

```bash
TOKEN="$(openssl rand -base64 32)"
printf '%s' "$TOKEN" | tee /home/klab/.local/share/visibility/secrets/alert_insert_token \
  | python3 alerter/install_inserter.py
unset TOKEN
```

vmauth reloads `auth.yaml` on its config check interval. Confirm an insert with
the new token. Recreate only `api` if the reload does not pick the user up:

```bash
docker compose up -d --no-deps --force-recreate api
```

Write the webhook URL and key the same way, as single lines with no trailing
newline required. The URL may be `http` or `https`. `https` is the expected
choice. Userinfo in the URL is rejected. The URL must not appear inside an
alert body, so it must not equal `console_url`.

```bash
printf '%s' 'https://assistant.example/visibility' \
  > /home/klab/.local/share/visibility/secrets/alert_webhook_url
printf '%s' 'replace-with-the-receiver-key' \
  > /home/klab/.local/share/visibility/secrets/alert_webhook_key
chmod 0600 /home/klab/.local/share/visibility/secrets/alert_webhook_url \
  /home/klab/.local/share/visibility/secrets/alert_webhook_key
```

The checker logs `webhook delivery failed` or `alert stream insert failed`. It
does not log the key, the URL, or a traceback that could contain them.

Copy public certificates only. The telemetry API certificate and the
presentation CA are mounted from their existing files. Extra public PEMs in
`VISIBILITY_CERTS_DIR` are scanned. To watch the console leaf (public
fingerprint documented in the certificate review; valid through 2027-01-04),
export the certificate and add a `certificates` entry. Do not copy
`server.key`. If a private key is mounted into the scan directory, the checker
raises a warning and does not parse the key material.

```bash
# Public PEM only. Run from a host that already trusts the console certificate.
openssl s_client -connect 192.168.5.230:8096 -servername 192.168.5.230 </dev/null \
  | openssl x509 -outform PEM \
  > /home/klab/.local/share/visibility/certs/console.crt
chmod 0644 /home/klab/.local/share/visibility/certs/console.crt
```

Set `DOCKER_GID` in `.env` from the socket's group. The checker process is uid
1000 and only issues `GET /v1.41/containers/json`. The socket is still
root-equivalent if the process is compromised: a writable socket mount is
required for that HTTP request, and `group_add` grants the socket's group.
Setting `containers.required` to `false` and removing the socket mount leaves
HTTP probes for logs, flows, and api. Telemetry and the console then show up
through source staleness and a missing heartbeat.

```bash
stat -c %g /var/run/docker.sock
```

## Deploy

From the checkout on AI-02, after the directories, secret files, public certs,
and `DOCKER_GID` exist:

```bash
cd /home/klab/codex/Visibility
docker compose up -d --build --no-deps alerter
docker compose ps alerter
```

`--no-deps` builds and starts `alerter` without recreating `logs`, `flows`,
`telemetry`, or `api`. The service has no `depends_on`, so it still runs when
those containers are down and reports them.

Rebuild the console and recreate only that container. The live Compose file is
outside Git; point `-f` at it. The image tag in `compose.presentation.yaml` is
`visibility-console:0.2.0`. Health reports version `0.2.0`.

```bash
docker compose -p visibility-presentation \
  -f /home/klab/.local/share/visibility/presentation-deploy/compose.live.yaml \
  up -d --build --no-deps --pull never console
```

`:8096` is briefly unavailable. Confirm `GET /api/health` version `0.2.0` and
`GET /api/alerts` after signing in. The console auth model is unchanged:
live mode still requires the viewer session, and the API remains GET/HEAD except
session login and logout.

## Dry-run

Point `alert_webhook_url` at a local receiver first if the assistant should not
be paged. Then stop only the checker and run one shot. The command fires a
synthetic warning that has already been open for 31 minutes and a synthetic
critical, writes both plus a heartbeat to VictoriaLogs, and posts both webhook
bodies.

```bash
docker compose stop alerter
docker compose run --rm --no-deps alerter python checker.py --dry-run
docker compose start alerter
```

The subjects are `synthetic-warning` and `synthetic-critical`, rule `dry-run`.
Summaries say that no network condition is asserted. Exit 0 means both webhook
deliveries succeeded. Exit 2 means the webhook files are missing. The running
checker does not emit these rules, so they resolve after `resolve_after_seconds`
(120) and a resolve webhook is sent if they were notified. To resolve them on
the next one-shot without waiting:

```bash
docker compose stop alerter
docker compose run --rm --no-deps alerter python checker.py --clear-synthetic
docker compose start alerter
```

`--clear-synthetic` resolves only `dry-run` alerts. The stop and start of
`alerter` are the disruptive steps. Other containers keep running.

Query the stream with the operator token, not the insert token:

```text
_time:1h app_name:=visibility-alert rule:=dry-run
_time:15m app_name:=visibility-alert kind:=heartbeat
```

## Rollback

Stop the checker. State on disk is kept, so a later start continues the same
fingerprints.

```bash
docker compose stop alerter
```

To remove the panel, recreate the console from `visibility-console:0.1.0`.
Only that container restarts. While the new panel is still deployed and the
checker is stopped, the console shows `checker-silent` once the last heartbeat
is older than 180 seconds.

Removing `alert-inserter` from `auth.yaml` is optional. Do not edit the
operator user while doing it. vmauth reloads the file; recreate `api` only if
it does not.

## Limits

Quiet sources can look stale; cadences are the `sources` list in the rules
file. The block spike counts filterlog lines containing `block` and compares
the newest 15 minutes with the median of the older 15-minute buckets. The WAN
rule matches `pass` / `in` on `igc0` to an RFC1918 destination from a
non-RFC1918 source, which is what pf sees after rdr. IPv6 unique-local
addresses are not treated as internal. A gateway alert exists only when
`dpinger` lines are present; absence of those lines is not treated as down.
VictoriaLogs does not ingest its own stderr. Query errors come from `/metrics`
deltas, the checker's own failed query, and an optional LogsQL pattern for
operators who later forward container logs. Dropped-row counters alert on a
delta after the first sample. The stream outbox keeps the newest 100
transitions while VictoriaLogs is down. The first successful non-empty UniFi
snapshot seeds known clients and does not alert the existing inventory. A new
client stays info for `new_entities.dwell_seconds` (24 hours).
