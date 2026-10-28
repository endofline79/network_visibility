# Visibility presentation

A read-only presentation of existing Visibility telemetry. The map extends presentation read models; it does not start, configure or restart collectors. Live mode requires the existing authenticated viewer and fixed-origin HTTPS query client. Credentials, source gates, retention, query limits and network configuration remain unchanged.

`GET /api/alerts` lists open alerts and alerts resolved in the last day. Demo mode returns labelled illustrative alerts. The desktop workspace shows a short Alerts strip above the map; narrower windows keep that strip out of the fixed layout and open the same list from **Alerts** or **Needs attention**. The console does not write alerts or call the webhook.

## Ops Home

**Ops** in the left navigation opens the daily operations page. The map, the other navigation entries, and the Alerts drawer stay as they are.

The page is one scrollable workspace, including at a narrow phone width:

- **Source freshness** is the last-seen age for firewall logs, NetFlow, UniFi inventory, Pi-hole DNS, the Pi-hole summary, the OPNsense syslog family, and the alert-checker heartbeat. Warning and critical follow the checker, about 15 minutes and about 30 minutes. The heartbeat tile is critical after 3 minutes, the same limit as checker silence.
- **Open alerts** is the existing `/api/alerts` list. **All alerts** opens the same Alerts drawer. There is no second alert model.
- **Top LAN talkers** ranks egress-only NetFlow schema 2 bytes for the selected window. `event_id` is deduplicated before bytes are summed. A configured LAN source is credited; otherwise a LAN destination is. Post-NAT WAN uploads are not assigned to a client. The ranges stay in the backend network list and are not hard-coded in the frontend.
- **Top firewall blocks** groups the newest logged `filterlog` lines by interface, source, destination, destination port, and protocol. The read is capped.
- **Top DNS** ranks Pi-hole domains and clients after `event_id` deduplication.
- **WAN gateway** is the newest OPNsense `dpinger` line from the last 30 minutes, plus any open `gateway-down` or `wan-ingress` alert. The page does not send a probe.

The labelled window is **Last 15 minutes** or **Last hour**. A 24 hour flow ranking is not offered, because a long `stats by (event_id)` can exhaust VictoriaLogs memory. `GET /api/ops` runs the reads on the server through the existing query client. Demo mode labels the panels as illustrative. Live mode does not fill a failed read with demo data. An unauthenticated live request is rejected like the other API routes.

Deploy is a console image rebuild only, the same pattern as the alerting console. From the repository root, `docker compose -f compose.presentation.yaml build console` tags `visibility-console:0.3.0`. Recreate only the presentation console after the image exists. Roll this page back by pointing the host compose file at `visibility-console:0.2.0`. Collectors and VictoriaLogs stay up.

## IoT and streaming DNS destinations

**Destinations** in the left navigation lists Pi-hole names for the hosts in `config/iot-hosts.yaml`. The flat LAN is not a scope. There is no IoT VLAN, so a client is included only when that file lists its `ip` and the `name` / `dns_names` values Pi-hole stores in `client_name`. The page can show one host or every allowlisted host for the last hour, 24 hours, or 7 days.

`GET /api/destinations` reads `app_name:=pihole-dns` through the existing VictoriaLogs client. The one-hour view deduplicates `event_id`, then counts domains. The 24 hour and 7 day views count stored receipts with `stats by (domain)` and do not group by `event_id`, because a multi-day event-id aggregation can exhaust VictoriaLogs. Each host also reports first and last seen time in the window. Domain rows are grouped by registrable domain (eTLD+1) for the site column. Blocked and allowed lookups both stay in the list. Demo mode labels the counts as illustrative and still uses this allowlist for the host names.

To add a host, edit `config/iot-hosts.yaml` only: a new list item needs `id`, `class` (`iot` or `streaming`), `name`, `dns_names`, `ip`, `mac`, and optional `notes`. Rebuild and recreate the console image as above. The file is copied into the image; no collector or alerter change is required. Keep phones, PCs, printers, and INFRA gear out. MYCAR, the household phones, Leslie's watch, iPad, and printer, and Leslie's URMC work laptop BLN4N74 are comments at the bottom of the file and are not queried. Gateway3164F5 is the Honeywell/Resideo thermostat and is on the allowlist. The two Tuya hosts stay in the list without assigning either MAC to the front-door light switch.

The globe is replaced by a locally bundled vector world map. Drag pans; accessible buttons and arrow keys pan/zoom, Home fits the world, and zoom is bounded from 100% to 800%. Fit selected country/areas uses the current geographic estimates. Ordinary wheel and vertical touch gestures scroll the relevant pane when it has overflow; the document stays fixed. A visible opt-in toggle enables wheel/pinch zoom and two-dimensional touch pan. Movement, multiple pointers, cancellation and held drags consume selection for the entire gesture. Country filters and area details do not reset the camera on refresh. Reduced motion disables observation highlighting. No third-party tiles, geolocation requests, tracking or external browser requests are required.

## Map layout

The desktop workspace fits the browser height. Left navigation and a narrow,
264px **Network details** sidebar run from the shared header to the bottom edge.
The map resizes within the remaining center space. **Where activity is going**
and **What's happening** remain visible along the bottom at desktop sizes.

The right sidebar has **Observed areas** and **Recent activity** tabs. Observed
areas holds map selection, matching areas and location-method notes; Recent
activity holds the event feed supplied as children of `WorldView`. The shared
**Near-live / Summary** map controls sit above both tabs. The feed continues to
use the labelled dashboard time window. Each tab body and the area list scroll
independently; tab changes preserve selection, zoom and each body's scroll
position. Arrow keys, Home and End switch tabs with keyboard focus. Selecting
a country or map area returns to Observed areas. To add a tab, extend
`detailTabs` in `WorldView.tsx` and add its labelled tab panel.
The demo-only scenario selector lives in the left sidebar.

The sidebar's collapse icon gives its width back to the map, leaving a small
edge button to reopen it. The map heading has no sidebar or time-view buttons. The preference is
saved locally as `visibility.details-pane`; the pane starts open on first use.
Collapsing preserves map selection and zoom. A compact summary with **View
selection details** remains below the map navigation while the pane is closed.
Opening from that summary focuses the selection heading; collapsing from the
pane returns keyboard focus to the edge button. Reopening there focuses the
active tab. At widths of 1100px and below the
right pane stacks inside the center workspace. On narrow or short windows the
center pane scrolls internally to keep every control reachable; the outer page,
header and navigation stay fixed. The login page and modal dialogs keep their
own existing scrolling behavior.

**Where activity is going** is the single country selector. It follows the map's
Near-live five-minute window or Summary window, including aging saved observations.
All known countries remain reachable in an internally scrolling list; an
**Unknown locations** row stays visible below it whenever unresolved endpoints
exist. Unknown locations are counted and selectable without inventing map points.
Rows expose endpoint counts and percentages through accessible labels and hover
text. Clicking a row filters the map and the right-hand area list; clicking it
again or choosing **All countries** clears the filter without changing the
camera. Summary destination drill-down remains available through **Details** in
the sidebar or the Destinations metric. The redundant country strip below map
navigation is removed. **What's happening** and Recent activity continue to use
the dashboard's labelled summary window.

Freshness, mapped/unplaced totals, query-limit withholding, expired observations,
refresh failures and unavailable geolocation stay visible above the map. The
longer database metadata, grouping explanation and NetFlow timing notes are in
**About location estimates and timing**, a native keyboard-accessible disclosure
in the right sidebar. The approximate-location warning remains in the map heading.

## Location interpretation

Public endpoint counts remain distinct IP addresses seen in router source/destination fields in the selected flow-end-time window. They are not physical server counts, requests, flows or traffic-byte shares. Private/reserved endpoints stay excluded. The existing local DB-IP Lite MMDB supplies country, region/city labels and coordinates. Build date and age are exposed. No validated accuracy radius is available in the inspected current database sample. Neither a city label nor more map zoom proves a physical server's position; no confidence circles are invented.

The read model groups estimates on a fixed **0.5-degree grid**, scoped by country and region. Points represent grouping-cell centers, not exact hosts. This display coarsening is not a guarantee that the real host lies in the cell or within a particular distance. Named city/region data with valid finite coordinates is required to plot an area. Country-only, missing/unusable position and unknown-country endpoints remain in explicit unplaced buckets instead of inventing country centroids or zero coordinates. Country totals contain no single representative coordinate.

At most **96 mapped areas** are returned. Deterministic hash ordering bounds the payload without ranking points by changing counts or timestamps; remaining areas become country-labelled, unplotted overflow counts. Every public endpoint contributes exactly once to a mapped, country-only, unknown or overflow group. City label lists are bounded to three plus an explicit additional-label count. No endpoint IP addresses are exposed in these location objects. Nearby screen areas combine at wider zoom, and their detail panel retains all canonical member areas; pan does not change membership. Country selection keeps selected/non-selected member groups separate. The location list makes every returned area or remainder reachable.

Near-live remains the five-minute router NetFlow observation window, with the compatibility `/api/globe` route polling about every ten seconds after completion. Summary follows the existing 15-minute/hour/day controls and stays separate. Pair/query/time gates are unchanged. Partial bounds withhold locations and counts; successful unavailable responses clear the view. Failed HTTP refreshes preserve saved observations while they age. Per-area endpoint timestamp buckets let individual endpoints expire correctly inside a still-active area, so counts stay consistent between mapped points, unplaced groups and country totals during failure. A zero remaining saved count is labelled as aged out, not a new measured zero-traffic result.

Observation highlights key off canonical area IDs and newer flow-end timestamps. Zoom/screen grouping/selection do not change those identities. The actual high-water helper holds at most 256 entries for ten minutes across disappearance and Summary re-entry; initial baselines, duplicate/older/out-of-order data and returning observations do not replay highlights. Pulses describe observations, not packets moving along physical routes.

## Preview and verification

Default mode is a clearly labelled synthetic demo; live data is never replaced by demo fixtures. From the repository root, `docker compose -f compose.presentation.yaml build console` builds `visibility-console:0.3.0` using this directory as the Docker context. The live host Compose file does not contain that build. Build the frontend for a local preview with `npm --prefix frontend run build`, serve `backend.app:app` on loopback, and use the existing Python requirements. Map assets come from the already pinned `@d3-maps/atlas`, d3-geo and topojson-client dependencies. See THIRD_PARTY.md and the bundled atlas license.

From the repository root, prepare an isolated local environment (Python 3.12+
and Node.js 22):

```bash
cd presentation
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
npm --prefix frontend ci --ignore-scripts --no-audit --no-fund
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/map_history_unit.cjs
npm --prefix frontend run format:check
npm --prefix frontend run build
PRESENTATION_MODE=demo PRESENTATION_AUTH=preview \
  .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8096
```

In a second terminal, run browser QA from `presentation/`. Use a disposable
Playwright installation, or set `PLAYWRIGHT_MODULE` to an existing installation.
`CHROMIUM_EXECUTABLE` optionally selects an existing test browser; otherwise
Playwright selects its bundled Chromium. The tests launch isolated headless
sessions and do not use the operator's signed-in browser. `PREVIEW_URL` defaults
to `http://127.0.0.1:8096`; point it only at a synthetic demo.

```bash
npm install --prefix .browser-qa --no-save --package-lock=false playwright@1.60.0
node .browser-qa/node_modules/playwright/cli.js install chromium
export PLAYWRIGHT_MODULE="$PWD/.browser-qa/node_modules/playwright"
for suite in browser_qa coverage_qa map_initial_qa map_qa map_refresh_qa \
  map_quality_qa map_marker_press_qa map_performance ops_qa; do
  node "tests/$suite.cjs" || exit 1
done
```

`.venv/`, `.browser-qa/`, build output and generated `artifacts/` stay local and
are excluded from Git and the Docker build context. Browser artifacts can be
regenerated and may contain whatever the preview displayed; review them before
sharing. `tests/live_smoke.py` is a separate, opt-in historical homelab check
with fixed October 5 timestamps and SSH settings. It is not part of this local
suite and requires retained data for that window. Globe-only rendering tests
and the unused raster/component are retired because the globe is no longer shipped.

The original flat map passed independent review and registered-browser acceptance before deployment; its verification is recorded in [the original map release note](../docs/map-release-2026-10-12.md). The October 12 deployment of the user-approved three-pane layout and consolidated country list used source **19604db9bdbf**. Validation, live-check limitations and rollback are recorded in [the layout release note](../docs/layout-release-2026-10-12.md). The later source publication review is recorded in [VALIDATION.md](../VALIDATION.md#presentation-source-publication-review--2026-10-24); publishing source does not update that deployment.
