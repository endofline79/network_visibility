# Map release — 2026-10-12

This reviewed flat-map release was superseded by the [three-pane layout release](layout-release-2026-10-12.md) later on October 12. It remains the retained rollback image.
The presentation container started at **18:13:21 EDT** on October 12, 2026.

## Release identity

- Reviewed source: `4a4edbcd3945622617cec8bc4bbec40b803495202e22513e70d32d82b339e880`
- Live tag: `visibility-console:map-reviewed-4a4edbcd3945`
- Image: `sha256:6564507fe7ab267dd21cc04cab45c1268f53d0d6b577f3632ff842b26e477271`
- Previous globe tag: `visibility-console:home-label-reviewed-64b9b39190a7`
- Retained rollback tag: `visibility-console:rollback-before-map-4a4edbcd3945`
- Live Compose SHA256: `7befc36c85dc8b8eb36457d2b6df927cb4eeb925cee1e6be900cec59ade71c09`

The exact frozen candidate was integrated into `presentation/`. Original and
retired source files were preserved under
`state/map-deployment-20261012-4a4edbcd3945/`; the reviewed bundle was not edited.
No Git commit or push was performed for this release.

## Validation

- Independently reviewed candidate: GO with one non-blocking P3 caption issue;
  the independent review recorded 70 Python tests, six history checks, and 81
  browser test groups passing.
- This rollout reran all 70 Python tests and six history checks against the
  integrated source. Build and formatting passed; output assets matched the
  reviewed image byte-for-byte. The initial sandboxed Python run timed out;
  the same tests passed outside the sandbox in under a second.
- Registered Brave acceptance of the corrected demo verified rendering,
  California area selection, uncertainty text, Fit selected/world, and both
  time modes. Gesture preference remained off during those checks.
- After deployment, the existing signed-in Brave session displayed the map
  with current live telemetry. Area selection, Fit selected/world, clearing
  selection, Summary, and Near-live passed. The tab was returned to Near-live
  at world fit with selection cleared.
- Verified TLS using the existing explicit CA. `/api/health` returned 200;
  unauthenticated `/api/globe` and `/api/overview` returned 401.
- All deployed backend source and static files match the reviewed bundle.
  Generated Python bytecode caches were excluded from source comparison.
- Final container health: healthy, zero restarts. Log, flow, telemetry, and
  API container identities, uptime, and restart counts were unchanged.
- Only the presentation image reference changed in live Compose. Runtime
  settings, mounts, environment, and credential-file metadata were preserved.

## Limits and existing issues

Unusually wide captions can overflow their box at narrow widths (review P3).
Full names remain available in details. Physical-device mobile acceptance was
not performed. The registered browser plugin did not exercise direct SVG drag,
pen, or pinch; independent automated tests cover those gesture regressions.

The live dashboard already reported unavailable Kitchen traffic and a coverage
warning before this deployment. That source issue was not changed by this
release. IP location estimates remain approximate; the displayed DB-IP database
was built September 1 and was 41 days old at deployment.

## Rollback

AI-02 private backup:
`/home/klab/.local/share/visibility/backups/map-20261012T221318Z-4a4edbcd3945/`.
It contains the pre-release Compose file, baseline metadata, and rollout result.
The backup and old image were verified after deployment.

After inspecting any intervening changes, edit only the console image in
`/home/klab/.local/share/visibility/presentation-deploy/compose.live.yaml` to
`visibility-console:rollback-before-map-4a4edbcd3945`, then run on AI-02:

```bash
docker compose -p visibility-presentation \
  -f /home/klab/.local/share/visibility/presentation-deploy/compose.live.yaml \
  up -d --no-deps --pull never console
```

Verify healthy status and old image ID
`sha256:f87e49b3130601bfd946c08f39fb079a6e06f741f19e514937efeee30f158519`.
Recheck HTTPS, authenticated rendering, and collector identities. Do not replace
the whole Compose file if unrelated settings have changed since the backup.
No credential, collector, firewall, or network changes are required.

Detailed local evidence: `state/map-deployment-20261012-4a4edbcd3945/completion.json`.
