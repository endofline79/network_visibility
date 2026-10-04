# Headless telemetry — deployed 2026-09-24

AI-02 now exposes native VictoriaLogs APIs at **https://192.168.5.230:9429**.
The custom Visibility UI and Jev process are stopped. Their source, image,
analysis history, and state remain available for rollback; no data was deleted.

## Running components

- `logs`: VictoriaLogs v1.52.0, unchanged 30-day retention and syslog TCP/UDP 514.
  Raw HTTP remains bound to AI-02 loopback port 9428.
- `flows`: existing NetFlow v9 collector, unchanged UDP 2056 source-gated to
  OPNsense. No switch mirroring, firewall, routing, or VLAN changes were made.
- `telemetry`: Python 3.12 standalone UniFi/Pi-hole pollers, no UI or AI runtime.
  Reuses the existing `/analysis/unifi-inventory.json` and `pihole-state.json`.
  Only the UniFi and Pi-hole credential files are mounted, not the Jev key.
- `api`: vmauth v1.152.0 pinned by image digest, HTTPS and one bearer token.
  Full backend path access, **no endpoint allowlist and no additional concurrency
  limits**. Vendor defaults and existing database resource limits still apply.
  Proxy-internal administration/metrics listen only on container loopback;
  authenticated `/metrics` and `/health` on port 9429 reach VictoriaLogs.
- `dashboard`: profile `legacy-ui`, stopped. Never run it concurrently with
  `telemetry`: both would own the same Pi-hole checkpoint and inventory cache.

The DNS archive checkpoint continues from September 22. New `unifi-snapshot`
and `pihole-snapshot` streams begin at this deployment; no inventory history
was reconstructed. Snapshots are sampled state, not a guaranteed event audit.
During archive outages one pending sample is retained, then the newest sample
is sent; intermediate samples can be skipped. Retry duplicates use stable IDs.
The existing firewall CSV parser is packaged with the client; raw firewall
records are not rewritten or duplicated into a second database stream.

## Credentials and TLS

Authority: Phase app **agents**, environment **Production**, path **/**,
key **TELEMETRY_API_TOKEN**. The token permits administrative database APIs.
Keep it server-side in any dashboard; do not ship it to browser JavaScript.
Having the token does not authorize a task to perform unrequested mutations.

The deployment copy is in
`/home/klab/.local/share/visibility/telemetry-api/auth.yaml` on AI-02 (0600,
parent 0700), alongside `server.key` and `server.crt`. The private key never
leaves AI-02. The token was transferred from Phase over encrypted SSH stdin,
not argv or console output. Existing secrets were not rotated.

HTTPS uses a private self-signed certificate for IP `192.168.5.230` and DNS
`ai-02`, trusted explicitly by the client. No system-wide CA changes or
certificate verification bypasses. Public SHA-256 fingerprint:
`3C:02:A4:BF:72:BC:14:C5:96:E2:02:F8:64:46:33:81:54:24:87:10:CA:C4:91:09:09:57:BD:5F:10:ED:53:BF`.
Valid through **2027-09-25 00:32:52 UTC**. Renewal is manual: replace certificate
and key together under operator approval, update the public trust file, restart
only `api`, and rerun verified HTTPS tests. No renewal automation is installed.

## Using it from another task on this host

Global skill: `/home/klab/.codex/skills/homelab-telemetry`, linked to the maintained
source `telemetry/skill` in this repository. It includes the public certificate,
native Python HTTPS client, source catalog, and existing firewall parser.
Invoke `$homelab-telemetry` in a new task, or give it the absolute SKILL.md path
if its loaded skill catalog has not refreshed. No MCP is required.

```bash
python3 /home/klab/.codex/skills/homelab-telemetry/scripts/telemetry.py \
  --query '_time:5m | stats by (app_name) count() rows'

python3 /home/klab/.codex/skills/homelab-telemetry/scripts/telemetry.py \
  --tail --query 'app_name:=filterlog' --seconds 30
```

The helper retrieves only the named Phase secret into memory. Any HTTPS client
can also send an Authorization Bearer header with the same certificate trust.
Native queries, field discovery, stats-range charts, and live NDJSON work;
there is no bespoke query DSL. The API is documented at
https://docs.victoriametrics.com/victorialogs/querying/ and auth configuration at
https://docs.victoriametrics.com/victoriametrics/vmauth/.

Read `telemetry/skill/references/catalog.md` before interpreting counters or
joining data. In particular, deduplicate flows by event_id and filter schema 2;
same-LAN traffic is absent and WAN uploads are post-NAT. Native tail is not SSE
or a durable stream; periodically reconcile historical windows for late data.
Use the same absolute UTC windows/source definitions for A/B comparisons.

## Health and rollback

Run on AI-02:

```bash
cd /home/klab/codex/Visibility
docker compose ps -a
docker exec visibility-telemetry-1 python -m json.tool /analysis/telemetry-status.json
```

Check source freshness, DNS `archive.through` advancing, empty pending batches,
and null source/archive errors. Snapshot and DNS forwarding use the same
VictoriaLogs ingest endpoint; query after its normal visibility delay.

Rollback to the retained UI without rewinding checkpoints:

```bash
cd /home/klab/codex/Visibility
docker compose stop telemetry
docker compose --profile legacy-ui up -d --no-deps dashboard
```

The HTTPS query API can remain available. Stop `api` explicitly if it also
needs rollback. Never use `down --volumes` or restore old poller checkpoints
as an ordinary rollback; rewinding them risks duplicate ingestion. To resume
headless operation, stop `dashboard` first, then `up -d --no-deps telemetry`.

Private AI-02 recovery artifacts (0600):

- `/home/klab/.local/share/visibility/pre-headless-20260924.tar.gz`: source/config
  before cutover (excludes secrets, .env, live database, and generated state).
- `/home/klab/.local/share/visibility/pre-headless-poller-state-20260924.tar.gz`:
  stopped, consistent Pi-hole/UniFi checkpoints; recovery evidence, not a normal
  rollback input.
- Retained local Docker image `visibility-dashboard:0.6.0` and stopped container.

The log and flow containers were not restarted during this deployment.
No database upgrade, firmware change, switch-port change, or A/B experiment
was performed.
