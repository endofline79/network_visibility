# Pi-hole DNS source

Pi-hole `ns0` at `192.168.5.238` is read through its v6 HTTPS API. Open
[Activity / DNS](http://192.168.5.230:8095/#activity/dns). This adds local polling
to the existing dashboard container, with no new service on Pi-hole.

## Data and boundaries

- Recent 24-hour summary, 10-minute activity buckets, busiest clients, and
  frequently blocked domains come from Pi-hole. These are source totals, not
  counts from the bounded query table. Pi-hole's privacy settings are respected.
- New DNS query records are forwarded to VictoriaLogs for its existing 30-day
  retention. The initial checkpoint starts 15 minutes before first collection;
  this is not a backfill of Pi-hole's entire historical database.
- Each poll reads at most a five-minute interval and 5,000 queries in pages of
  500. It uses Pi-hole's fixed cursor plus advancing `start` offset, checks
  completeness, and advances a half-open time checkpoint only after forwarding.
- Polls run once a minute after completion, with a 60-second settling delay and
  a 22-second poll budget. Typical visible archive lag is about one to two
  minutes. Initial catch-up takes several polls. Source freshness and archive
  lag/errors are independent and visible; no browser tab is required.
- The exact pending batch is saved before forwarding. A timeout after the
  collector accepted it can cause a repeated receipt. DNS query views collapse
  identical event IDs within the loaded records; **All logs** and source intake
  counts describe stored receipts. This is not an exactly-once delivery claim.
- Query search scans the selected range on the server, then returns the newest
  1,000 intake records with a cap notice. Loaded rows are paginated in the browser.
- A gap beyond Pi-hole's in-memory history, an oversized interval, or an
  inconsistent page stops checkpoint advancement and displays an error. There
  is no silent gap skip or automatic import of its multi-million-row disk DB.
  An operator can investigate a recovery/backfill before changing the checkpoint.
- Original Pi-hole statuses are retained, including `IN_PROGRESS` and unknown
  statuses. The view groups them as blocked, cached, forwarded, or other. It
  does not infer threats. Query replies can remain unresolved in the source.
- DNS queries include background work and do not prove a website visit.
  Alternate/encrypted resolvers and connections without a new lookup are outside
  this source. DNS observations are not automatically joined to historical
  firewall traffic or UniFi clients by their current IP address.

No DNS/blocking/privacy configuration, firewall policy, or Jev controls are
changed. DNS identifiers stay on AI-02; there are no model calls.

## Authentication and storage

The existing Phase secret `agents / Production /pi-hole / PI-HOLE_APP_PASS`
is installed as `/home/klab/.local/share/visibility/secrets/pihole_app_password`,
mode 0600, owned by UID/GID 1000. It is exposed only through the existing
read-only secret-directory mount. Never place its value in Compose, source,
browser responses, build context, or shell arguments.

The TLS SHA256 pin was independently verified through trusted SSH as `klab`:
`340389c84066e34b861bdbc1df06d3ec1e978aa3debe955593f4eec6d6bdaec1`.
Every request checks the certificate before sending a credential or session ID.
Redirects are refused. The API client permits only specific GET endpoints plus
POST `/api/auth` and DELETE `/api/auth` for its own session. It reuses one session,
clears an expired SID on HTTP 401, and logs out during graceful worker shutdown.
It has no DNS control endpoint. Failed responses never expose upstream bodies.

`/home/klab/.local/share/visibility/dashboard/pihole-state.json` contains the
normalized latest snapshot, checkpoint, and any unsent batch. Writes replace it
atomically as mode 0600. It has no authentication material. A corrupt saved
checkpoint stops collection instead of resetting progress. Do not delete it to
troubleshoot: preserve a copy and inspect the failure first.

The LAN dashboard's existing access scope now includes DNS query names and
client names. Browser **Paused** freezes display updates; collection continues.
Set `PIHOLE_ENABLED=false` and recreate only `dashboard` to stop DNS collection;
saved snapshots and archived logs remain.

## Verify and rollback

```bash
curl --fail http://192.168.5.230:8095/api/dns
curl --fail 'http://192.168.5.230:8095/api/dns/queries?window=15m'
```

These responses contain private network observations. Do not publish raw output.
Check `state`, `snapshot.observed_at`, `archive.through`, `archive.lag_seconds`,
and both error fields. Verify `app_name=pihole-dns` receipts in Collection and
All logs. The process-only `/api/health` endpoint is not a data-path check.

Release 0.5.0 changes only the dashboard container. Retain image
`visibility-dashboard:0.4.0` and the pre-deployment source/configuration backup.
Rollback by restoring that Compose/source checkpoint and recreating **only**
`dashboard` with `--no-deps --no-build`. Do not run `compose down` or remove
data/credentials. Version 0.4.0 ignores the new state and existing DNS logs remain
in VictoriaLogs. The pre-deployment checkpoint on AI-02 is
`/home/klab/codex/Visibility/state/pihole-20260922T002709Z-before/`.
The release receipts under `state/` record image and archive identities.

Source references: [Pi-hole authentication](https://docs.pi-hole.net/api/auth/),
[installed API documentation](https://192.168.5.238/api/docs/),
[FTL v6.7.1 query pagination](https://github.com/pi-hole/FTL/blob/v6.7.1/src/api/queries.c),
[VictoriaLogs JSON ingestion](https://docs.victoriametrics.com/victorialogs/data-ingestion/#json-stream-api).
