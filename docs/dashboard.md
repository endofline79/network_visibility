# Visibility dashboard

Live on AI-02: **http://192.168.5.230:8095**. Compose service: `dashboard`;
container: `visibility-dashboard-1`; image: `visibility-dashboard:0.5.0`.

The compiled React/TypeScript frontend and FastAPI backend share one container.
The browser loads scripts, icons, styles, and geographic geometry from AI-02.
The backend queries `http://logs:9428` over the existing Compose network. It does
not hold firewall administration credentials or Docker socket access.

## Views

- **Overview:** world map or draggable globe, Rochester city anchor, country
  selection, activity histogram, and linked firewall event table. Click an IP
  address to filter the table. New observations briefly highlight map points;
  reduced-motion preferences are respected.
- **Activity:** parsed firewall records or **All logs**. All logs searches stored
  message text on the server and can filter by application. Row details retain
  the original message. All log text is rendered as text, not markup.
- **Devices:** local UniFi device/client lists, attachment map, switch ports, AP
  radios, and device health. A server poll runs about once a minute, independently
  of browser tabs or Jev. See [inventory operations](unifi-integration.md).
- **DNS** within Activity: Pi-hole 24-hour summaries, activity chart, client/domain
  rankings, and a searchable DNS archive. See [DNS collection operations](pihole-integration.md).
- **Collection:** last successful query, latest firewall event, source/application
  counts over five minutes, parser failures, and location-database coverage/age.
- **Jev experiment:** continuous classification, off by default. Switch on for
  automatic batches of up to three fresh activity groups each minute, a live
  category feed, saved probabilities, original evidence, and usage. Manual
  sampling remains available. Both modes share a ten-request daily limit and
  15-minute expiry. See [experiment controls](jev-trial.md).
- **Live / Paused:** refresh every ten seconds, or freeze the current result.
  Manual refresh remains available while paused. Time changes request a new
  result. Light/dark preference is saved in the browser.

The firewall view loads the newest **5,000** records in the chosen range. It shows
a notice and a separate matching-record count when capped. Its map, country
breakdown, local filters, and histogram describe the loaded records. All logs
loads the newest **1,000** matching messages; both tables paginate 50 rows at a
time. Narrow the time range or use the All logs server search for specific older
events. Source reporting shows at most 40 source/application pairs.

Time ranges extend to 30 days, subject to records actually collected and retained.
Queries have an eight-second collector timeout, a ten-second HTTP timeout, a
response-size bound, and a short shared cache. Failures are shown explicitly;
the UI retains the previous result with an error instead of replacing it with
a false empty result. Snapshot count queries share fixed time bounds.

See [organization notes](organization.md) for the view hierarchy and planned
cross-source device detail. Existing inventory and Jev bookmarks still work.

## Access and data scope

This initial dashboard uses **HTTP without a login**, bound to AI-02's intended
trusted LAN address. Reachable LAN clients can read its logs and inventory, including client names and addresses. Do not forward this
port from the Internet; use authenticated HTTPS access before expanding its
audience. The raw VictoriaLogs API remains on host loopback. Browser same-origin
policy, host validation, a restrictive content security policy, and read-only
log endpoints are enabled; these are not substitutes for user authentication.
Jev mutation endpoints enforce same-origin browser requests and a shared daily
request limit. Reachable LAN clients can use the trial; it has no separate login.

The map shows approximate public endpoint locations. Lookups use a local MMDB;
observed IPs are never submitted to a geolocation API. Nonpublic, multicast,
locally owned, and unlocated addresses remain in the log table. Explicit local
networks are `192.168.5.0/24`, `10.10.10.0/24`, and `10.10.20.0/24`, verified against OPNsense.
The city-level lab anchor is Rochester, NY (43.1566, -77.6088); it is not a
street address. At most 80 geographic/action groups are drawn, with any map
limit shown. Selecting a country before mapping narrows the points.

These are logged events, **not total bandwidth, active sessions, or all traffic**.
Firewall `in`/`out` refers to the logging interface. Lines are illustrative
connections, not actual routes. No additional rule logging or NetFlow export was
enabled by this deployment. Wider flow coverage needs its own collection work.

## Build, update, and verify

On AI-02, after reviewing changes:

```bash
cd /home/klab/codex/Visibility
docker compose config --quiet
docker compose build dashboard
docker compose up -d --no-deps --no-build --wait --wait-timeout 60 dashboard
docker compose ps
curl --fail http://192.168.5.230:8095/api/health
docker compose logs --tail 50 dashboard
```

The multi-stage image build type-checks and compiles the frontend, then runs the
Python parser/API/collection tests before producing the runtime image. Base images are
pinned by digest, npm uses `package-lock.json`, and Python dependencies are pinned.
Runtime is UID/GID 1000, read-only root filesystem, capabilities dropped,
no-new-privileges, one CPU, 768 MiB memory, no additional swap, and 96 PIDs.
The location directory is mounted read-only. Application access logging is
disabled to avoid storing search terms in container access logs.

The health endpoint verifies the app process. Verify source freshness and
parsing/location counts on Collection to check the data path itself.

For frontend changes without Docker:

```bash
cd dashboard/frontend
npm ci --ignore-scripts
npm run format:check
npm run build
```

## Update location data manually

Data directory: `/home/klab/.local/share/visibility/geoip`. The active
`dbip-city-lite.mmdb` symlink points at a versioned release. Prior releases are
preserved. The backend reloads an updated active database on its next uncached
snapshot. No scheduler is installed.

Read the release month and SHA1 checksum from
[DB-IP's official MMDB download](https://db-ip.com/db/download/ip-to-city-lite).
The initially installed September 2026 release was downloaded with:

```bash
python3 scripts/update_geoip.py \
  --directory /home/klab/.local/share/visibility/geoip \
  --month 2026-09 \
  --sha1 6ea870a637b5460023643fc18fdea84dcea14b9c
```

For a newer release, replace both the month and checksum with values from that
page. The helper validates the release checksum and MMDB marker before switching
the active link. Collection displays database age and recommends an update after
45 days. DB-IP attribution is included in the app footer.

## Rollback

Stop only the dashboard; collected logs and their intake remain intact:

```bash
cd /home/klab/codex/Visibility
docker compose stop dashboard
```

Resume using `docker compose start dashboard`. The pre-dashboard Compose file
is preserved on AI-02 at
`state/dashboard-before-20260920T025328Z/compose.yaml`. If reverting the project
configuration too, stop the dashboard first, then review and restore that file.
Do not use `docker compose down`, remove the data directories, or stop `logs` to
roll back the dashboard.
