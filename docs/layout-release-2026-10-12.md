# Layout release — 2026-10-12

The user-approved three-pane dashboard is live at **https://192.168.5.230:8096/**.
The presentation container started at **21:29:55 EDT** on October 12, 2026.

## Changes

- Viewport-sized workspace with narrow left/right sidebars and a collapsible right pane.
- Near-live/Summary controls and Observed areas/Recent activity tabs in the right sidebar.
- Map selection and location-method notes in Observed areas; bottom activity cards retained.
- One country selector in Where activity is going, following the map time window.
  All countries remain reachable; unknown locations stay visible when present.
- Removed the duplicate country strip and the map-header Hide details button.

## Release identity

- Frozen source SHA256: `19604db9bdbf26ac16749f328428067a4231160f5cb4f1ba89975fce18d40485`
- Live tag: `visibility-console:layout-19604db9bdbf`
- Live image: `sha256:f26a79743bbfeb49a3282a6f0ea3dbea53c3b72391faf76e9c3b68b5c480e70d`
- Prior tag: `visibility-console:map-reviewed-4a4edbcd3945`
- Retained rollback tag: `visibility-console:rollback-before-layout-19604db9bdbf`
- Live Compose SHA256: `d2e92197e789192353aafcab728b8e0b9c46f3d9b0b6a7857f7d1f272c000086`
- Evidence and frozen source: `state/layout-deployment-20261012/`

This layout was accepted by the user in the local demo before deployment. The
original map's independent review is recorded in [the prior release](map-release-2026-10-12.md).
No Git commit or push was performed for this release.

## Validation

- 56 dashboard, map, quality and refresh browser checks passed on the accepted preview,
  including mobile/tablet layouts, keyboard tabs, filtering, unknown locations,
  selection/camera persistence, and country counts across Near-live/Summary and expiry.
- Pinned Docker build reran all 70 Python tests successfully; TypeScript/build passed.
- Image static assets match the accepted preview byte-for-byte. Backend source is
  unchanged from the prior release. Deployed backend/static hashes match the image.
- HTTPS verified with the existing explicit CA. Health returns 200 in live mode;
  unauthenticated map and overview requests return 401. All served static hashes match.
- After deployment, server-side read-only queries returned fresh map observations
  (118 endpoints across 5 countries at 2026-10-13T01:31:11.074363Z) and current
  summary data. Inventory, router, DNS and firewall sources were fresh.
- Container remains healthy with zero restarts. Collector identities, uptimes and
  restart counts were preserved. Only the console image reference changed;
  runtime settings, mounts, environment and credential-file metadata were preserved.
- Rollback image identity and private backup were verified.

## Existing limitations

Brave showed a certificate privacy warning on a fresh load **before** rollout.
The older tab had stale data and failed refreshes. TLS validates against the
existing explicit CA; browser trust was not changed during rollout and the
warning was not bypassed. The local accepted UI and deployed assets are identical.

The subsequent [certificate review](dashboard-certificate-review-2026-10-12.md)
confirmed a valid certificate and missing workstation CA trust, and records a
user-approved CA import into the workstation's user NSS database. After the
user relaunched the app, signed-in browser verification passed at approximately
21:46 EDT: live dashboard loaded without a certificate warning or Demo label,
manual refresh completed, and near-live map counts updated with current flow
timestamps. The accepted layout was visible. Server certificates and services
were not changed.

Kitchen capture still reports incomplete intervals/connection batches; its
traffic totals and device ranking remain withheld. This was verified before
and after rollout and is unrelated to the layout change. No collector, network,
firewall, retention or credential configuration was changed.

## Rollback

Private AI-02 backup: `/home/klab/.local/share/visibility/backups/layout-20261013T012954Z-19604db9bdbf/`.
It contains the previous Compose file, baseline metadata and rollout result.

After checking for intervening changes, edit **only** the console image reference
in `/home/klab/.local/share/visibility/presentation-deploy/compose.live.yaml` to
`visibility-console:rollback-before-layout-19604db9bdbf`, then run on AI-02:

```bash
docker compose -p visibility-presentation \
  -f /home/klab/.local/share/visibility/presentation-deploy/compose.live.yaml \
  up -d --no-deps --pull never console
```

Verify healthy status and image `sha256:6564507fe7ab267dd21cc04cab45c1268f53d0d6b577f3632ff842b26e477271`.
Recheck HTTPS, live queries and collector identities. Do not restore the whole
Compose file if unrelated settings have changed since the backup.
