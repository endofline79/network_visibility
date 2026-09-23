# Intake validation — 2026-09-19 (America/New_York)

## Approved controller syslog rule — 2026-09-20 21:54–21:58 (America/New_York)

- User explicitly approved adding the prepared exception. Added UUID
  `bf764198-b6ed-4696-a5a9-598e2b5a6ab5`, sequence 350: IPv4 UDP from
  `10.10.20.50` to `192.168.5.230:514`, inbound on INFRA, logging enabled.
- Verified API readback and the active PF rule immediately before the original
  sequence-400 INFRA-to-LAN block. A full protected-configuration fingerprint
  matched before/after, excluding only the new rule and normal save metadata.
- Private encrypted checkpoint was created before the change and validated by
  authenticated decryption and byte equality. Both checkpoint and operation
  state are mode 0600. Backup:
  `state/opnsense-20260921T015451Z-before-unifi-syslog.xml.gpg`.
- The first runtime check rejected PF's service-name rendering (`syslog` rather
  than numeric `514`). The rule itself was correct. Corrected the verifier to
  accept only those exact equivalents and added a regression check; all **five
  rule-guard tests passed**. Final state is `applied_verified`.
- One synthetic RFC5424 UDP record from the controller host was received at
  `2026-09-21T01:56:58.833387Z`, source `10.10.20.50`, hostname `visibility-test`,
  application `visibility-path`. Its token is
  `visibility-unifi-a4b879f019f24b338e94f1bf9ab81906`. The new firewall rule
  logged PASS at `01:56:59Z`. The test is excluded from normal dashboard views.
- At `01:57:58Z`, no ordinary UniFi exporter events had arrived yet. Network-path
  acceptance is complete; real application export/event-format acceptance is
  still pending a natural event. No AP reboot or client disconnect was used.
- Collector ID/start are unchanged, with zero restarts. OPNsense intake remained
  active (1,936 records in a five-minute check), and dashboard health remains
  `ok`, version 0.4.0. No dashboard deployment, controller setting, or Jev request
  was part of this change.
- Reusable helper and rollback: `scripts/unifi_syslog_rule.py`; verify/disable
  commands are documented in [UniFi operations](docs/unifi-integration.md).

## UniFi controller export diagnosis — 2026-09-20 21:48 (America/New_York)

User reports UniFi export configured. At `2026-09-21T01:48:03Z`, filterlog
recorded BLOCK for `10.10.20.50:51196 -> 192.168.5.230:514/UDP`, inbound on
`bridge0`. Read-only configuration inspection identified rule
`ac8317c3-b436-4b15-80f8-0f4863c30974`, sequence 400, description
`INFRA block initiation to LAN`. No matching allow rule exists on INFRA.
The collector is running, has zero restarts, and publishes TCP/UDP 514 on
`192.168.5.230`. No UniFi records arrived in the inspected 15-minute window.

Prepared the exact single-rule proposal at
`state/unifi-syslog-rule-proposal.json`: IPv4 UDP, INFRA inbound, sequence 350,
source `10.10.20.50`, destination `192.168.5.230`, destination port `514`, logged.
No firewall or controller changes were applied. Approval is required by the
user's AGENTS.md. Rollback disables only the new rule and preserves all logs.

## UniFi syslog follow-up — 2026-09-20 21:40 (America/New_York)

The user reported clearing the AP syslog blocker. Read-only collector checks
at `2026-09-21T01:40:42Z` confirmed recent `bridge0` PASS records for
`10.10.20.11 -> 10.10.20.50:5514/UDP` (01:39:24Z) and
`10.10.20.12 -> 10.10.20.50:5514/UDP` (01:40:00Z). Earlier blocks in the
five-minute window predate those passes. This confirms the firewall permits
these observed packets; receiver-side delivery was not inspected.

AI-02 still had no source records from `.50`, `.10`, `.11`, or `.12` in the
prior hour, and its 15-minute source inventory contained only OPNsense. UniFi
forwarding to `192.168.5.230:514` remains the next integration step. No firewall
or controller settings were changed by this follow-up.

## UniFi inventory — deployed 2026-09-20 (America/New_York)

- Dashboard `visibility-dashboard:0.4.0` is healthy; image ID:
  `sha256:88038e43375a7ac619fffb7fdc63e7b74c3e1480e226c988ffa6ac211d5d98a4`.
  Started at `2026-09-20T23:59:43.961761737Z`.
- Production Python 3.12 Docker build passed **47 tests**, including ten new
  inventory/route tests. Frontend formatting, TypeScript, and Vite build passed.
  Local Python 3.14 lacks FastAPI; the full authoritative suite ran in Docker.
  The standalone nine-test inventory suite also passed locally.
- The credential is a server-only 0600 file in the existing read-only secret
  mount. It was neither displayed nor placed in the image, browser, or Compose
  environment. Pin validation happens before sending the credential. A separate
  isolated container successfully collected inventory before promotion.
- Compared rendered Compose before/after: collector service is identical;
  dashboard bindings, mounts, limits, and unrelated settings are identical.
  Added only inventory settings, the image version, and INFRA to local networks.
- Live API returned **three ONLINE devices, 19 clients (14 wireless / 5 wired)**,
  with 14 client IPs supplied and five unknown. Both APs link to the Flex switch.
  Per-device client counts were Kitchen 3, Upstairs 11, and Flex 5.
- Verified automatic polling without a browser trigger: persisted observations
  advanced from `23:59:45Z` to `00:00:45Z` and `00:01:45Z`. The saved snapshot
  matches the API and has mode 0600. Unit tests cover failed-poll preservation,
  restart loading, age-based staleness, and recovery without clearing inventory.
- Browser verified direct `#inventory` loading, attachment filters, combined
  filters/empty results, clearing filters, search by attachment name, switch
  port speeds/PoE, and AP channel/width details. No browser errors or warnings;
  page and viewport widths both 1061 px, with no page overflow. No viewport
  override was used. Flex port 1 reports 100 Mbps, as already observed.
- Original collector ID remains
  `9907619866c244f55024965265182fcbfebf48bf12c4458cd88ff4debf678d56`, with its
  original `2026-09-20T02:01:20.569305852Z` start time and zero restarts.
  A live five-minute snapshot had 3,099 firewall records, zero parse errors,
  and a latest event at `2026-09-21T00:00:02Z`.
- Jev remains OFF. Inventory collection makes no model requests and does not
  add client identifiers to Jev prompts. Firewall/controller settings and UniFi
  syslog export were not changed. Existing trial and log storage are preserved.
- Pre-change source, Compose, rendered configuration, and container identities
  are on AI-02 at `state/unifi-inventory-20260920T235801Z-before/`. Previous
  image `visibility-dashboard:0.3.0` is retained. See
  [inventory operation and rollback](docs/unifi-integration.md).

## Jev trial — deployed 2026-09-20

- Deployed `visibility-dashboard:0.2.0` to AI-02. Final image ID:
  `sha256:5b87f941d26f44469b9818d11ac8a7b1a1c3bf294624e2c9a2331f2074353b08`.
- Frontend build/type-check passed. The Docker build passed **26** parser, API,
  and metering-control tests with a fake provider; automated tests made no paid
  calls. Covered server-side off/expiry, persistent daily budget, duplicate
  suppression, concurrency, interrupted/failed attempts, missing storage,
  outgoing-field privacy, local reviews, and browser mutation boundaries.
- Installed the existing Phase TypeSafe key as a server-only 0600 file. The
  dashboard sees its directory read-only; the key is not in the repository,
  Compose environment, frontend, image, or logs.
- Browser verified free sample capture, three-group selection limit, exact
  outgoing-request preview, disabled Run while off, enabling without inference,
  one manual run, usage display, probability cards, and original-record details.
- **One real API request** classified three groups from a capped five-minute
  sample (5,000 of 5,329 logged events). No device roles or context were invented.
  The request omitted addresses, names, raw messages, and exact timestamps.
  Provider usage: **2,318 input tokens, 409 output tokens**. Estimated cost at the
  published input-token rate: **$0.000097356**; this is not an invoice.
- Observed classifications: UDP/53 -> network housekeeping (choice confidence
  0.99); TCP/443 -> tentative web/communication (0.46); UDP/2144 -> unknown (0.95).
  These are recorded model judgments, not verified application identities.
- With Jev OFF, replaying the same trial reused its result without a new call;
  a new request with changed context returned HTTP 409. Attempt count remained 1.
- Recreated the dashboard for the final display/sample-diversity changes. Its
  saved result, token counts, and daily allowance survived; the switch reset OFF.
  Browser reload showed that saved result and no JavaScript console errors.
- Final state: **Jev OFF, 1/10 attempts used today**. No schedules or automatic
  retries were added. User labels remain unreviewed for the user to assess.
- Original collector ID and start time remained unchanged. Pre-trial source and
  Compose backup: `state/jev-before-20260920/` on AI-02. Rollback and usage guide:
  [Jev trial](docs/jev-trial.md).

## Status

**Deployed to AI-02 after explicit user approval.** The `visibility` Compose
project runs `visibility-logs-1`. Configuration is present both in this local
workspace and at `/home/klab/codex/Visibility` on AI-02.

## Read-only AI-02 inspection

- SSH identity confirmed `ai-02` at `192.168.5.230`.
- Ubuntu 24.04.4 LTS; Docker 29.5.3; Compose 5.1.4.
- Approximately 111 GiB memory available at inspection.
- `/home` is a separate approximately 3.2 TiB filesystem with about 2 TiB free.
- TCP/UDP 514 and TCP 9428 were absent from the listening-port inventory.
- Proposed project and data paths did not exist.
- Existing container and Compose inventories were inspected; none were changed.

These values are a snapshot, not a capacity reservation. Recheck ports and paths
before deployment.

## Completed local validation

- Compose configuration rendered successfully with `.env.example`.
- Python intake-check script passed syntax validation.
- Official VictoriaLogs v1.52.0 Linux AMD64 binary matched its release SHA-256:
  `26941a2f987795dbae465089020b0b592b05718c5f93f4b328b32b429862899b`.
- The binary started with the Compose service's flags, substituting temporary
  storage and loopback-only ephemeral listener addresses. Because local `/tmp`
  is a 15 GiB tmpfs, its test free-space threshold was 1 MiB instead of the
  production 20 GiB threshold.
- Four synthetic records were sent and retrieved: TCP newline framing, TCP
  octet-counted framing, UDP RFC3164, and OPNsense-style RFC5424/filterlog.
- The OPNsense CSV message body, application name, and message ID were preserved.
- All four records remained queryable after a graceful process stop and restart.
- The test process was stopped. Temporary test artifacts remain under
  `/tmp/visibility-validation-cns7wpx1` on the operator workstation.

## Completed AI-02 acceptance

- Pulled and ran `victoriametrics/victoria-logs:v1.52.0`; recorded image digest:
  `sha256:47b820890d64c4575a2a0a46415dcd8a4fd59a0f1fcd6a377693d7aea639442e`.
- `/health` returned `OK`; the container was running with no automatic restarts.
- Runtime inspection confirmed UID/GID `1000:1000`, a read-only root filesystem,
  a 2 GiB memory limit with no additional swap, and a 2 CPU quota.
- Data is bind-mounted from `/home/klab/.local/share/visibility/victorialogs`.
- Confirmed published TCP/UDP syslog listeners on `192.168.5.230:514` and the
  query API on `127.0.0.1:9428` only.
- The four synthetic formats passed ingestion and retrieval on AI-02.
- Repeated the four-format test by sending from the operator workstation across
  the actual LAN and querying those specific records through SSH.
- Stopped and started only `visibility-logs-1`, then retrieved all four LAN
  records without resending them. This verified persistent storage across a
  container stop/start.
- A connection to `192.168.5.230:9428` from the workstation was refused, confirming
  that the query API was not exposed on the LAN address.
- Initial idle measurement: approximately 3.8 MiB RAM and 0.10% CPU. This is only
  a startup observation, not a load benchmark or sizing guarantee.

External acceptance token:
`visibility-lan-43006b667ec34012aad98719f3d5bbbd`.

## Remaining work

OPNsense is connected and verified below. Connect additional network devices as
needed. Measure daily growth before relying on 30-day capacity. The dashboard is
deployed (see below). NetFlow, TLS transport, and a sender allowlist remain later work.

## OPNsense forwarding — connected 2026-09-20 UTC

The user authorized connecting OPNsense to the collector. Live inspection
confirmed OPNsense 26.7.1_1 at `192.168.5.1`, working SSH/API access with verified
HTTPS, the existing disabled target, and firewall-to-collector TCP reachability.

Updated only destination UUID `ad8bb8eb-1abc-4a3d-9d2c-8f36577da137`:

| Field | Before | After |
| --- | --- | --- |
| enabled | 0 | 1 |
| port | 1514 | 514 |
| rfc5424 | 0 | 1 |
| description | telemetry-alloy | AI-02 Visibility |

The transport remains `tcp4`; destination remains `192.168.5.230`. Empty
application, severity, and facility filters continue to select all generated
logs. The API saved the target and reconfigured syslog; the service remained
running. Local logging remains enabled with its previous retention.

An in-memory comparison against the encrypted checkpoint confirmed that all
configuration outside this target was unchanged except the normal Syslog model
`persisted_at` attribute and revision metadata. Target readback matched all
expected fields. No firewall rules, logging flags, DNS, VPN, users, credentials,
or interfaces were modified. Four of the eight explicit rules had logging before
this change; that count was not changed. This is not a claim of all-flow coverage.

Delivery evidence:

- Real records arrived from `192.168.5.1` as `OPNsense.internal` in RFC5424 format.
- A five-minute sample contained **589 filterlog records**, plus configd, SSH,
  sudo, cron, and syslog-ng events. These are a point-in-time count, not a rate
  guarantee. No log bodies or credentials were printed during verification.
- The destination counters showed 505 written, zero queued, zero dropped, and
  zero truncated messages at one inspection point.
- A unique event sent through OPNsense's native `logger` arrived exactly once;
  its timestamp was within 0.447 seconds of the workstation's send time.
- Collector counters for too many fields, future/old timestamps, and debug drops
  were all zero at inspection.

Probe identifier: `visibility-opnsense-a41089cf2f5b49939fe6c93ade7c772e`.

Verified encrypted recovery checkpoints on the operator workstation:

- `/home/klab/Documents/ChatGPT/home_net_checkup/recovery/opnsense-20260920T021524Z-before-visibility-forwarding.xml.gpg`
- `/home/klab/Documents/ChatGPT/home_net_checkup/recovery/opnsense-20260920T021906Z-after-visibility-forwarding.xml.gpg`

Both passed in-memory decryption, byte equality, and XML parsing checks; files
are mode 0600. The existing recovery passphrase stays in Phase. Checkpoints and
credentials were not copied to AI-02. The rollback helper is prepared but was
not executed against the working forwarding setup.

## Custom dashboard — deployed 2026-09-20 UTC

The user approved the interactive map/log design and requested implementation.
They selected Rochester, NY, USA as the approximate lab location. The app is
running at `http://192.168.5.230:8095` as the additional `dashboard` Compose
service. See [operations and rollback](docs/dashboard.md).

Build and data validation:

- React/TypeScript type checking, Vite production build, and source formatting
  checks passed. All map geometry, icons, scripts, and styles are bundled locally.
- Twelve Python tests passed inside the Python 3.12 image build. Coverage includes
  IPv4/IPv6 layouts, TCP/UDP, ICMP/CARP, fragments, malformed records, private and
  multicast address exclusion, bounded queries, quoted search input, source-host
  validation, read-only API methods, result caps/cache, and upstream failure handling.
- npm's production dependency audit reported zero known vulnerabilities at the
  time of the check. This is not a general security certification.
- Installed September 2026 DB-IP Lite MMDB: 127,339,927 bytes. The release checksum
  matched DB-IP's published SHA1. Uncompressed SHA256:
  `05a10861259c7966cb54d7181ef8c360de8c8829d182098c0e62a9b7d54cd50d`.
- A live 15-minute sample returned **3,764 loaded / 3,764 matching records**,
  **zero parsing failures**, and **276 / 276 public IPs located**. These are
  point-in-time observations, not throughput or future accuracy guarantees.
- A larger one-hour query exercised the 5,000-record cap and its visible notice.
  Fixed time bounds and direct counts for uncapped results resolved a moving-window
  count discrepancy found during browser verification.

Browser checks against the live app passed: map/country filtering, map/globe
switching, action filtering, firewall and system-log raw details, Collection,
pause (no polling), manual refresh while paused, and light/dark rendering.
The app retained previous data during an isolated browser-only 503 simulation
and displayed a proper empty state for an empty response. Those simulations
did not modify the collector. No JavaScript page errors were observed.
The page's network requests went only to AI-02; no external location or CDN
requests were made. Responsive checks passed at 1,440, 390, and 320 pixels,
including all three views at 320 pixels. QA screenshots remain under the ignored
local `state/qa/` directory.

Runtime:

- Final image digest:
  `sha256:b89798811578108f72b7f8bc9ce8cf2f0edbd8231b7605083a0c8c9353f75fa7`.
- Healthy, UID/GID 1000, read-only root, one CPU, 768 MiB RAM/no additional swap,
  96 PIDs, dropped capabilities, and read-only location-data mount.
- Only dashboard TCP 8095 was added on `192.168.5.230`. The query API remains
  on AI-02 loopback; syslog bindings and the `logs` service definition are unchanged.
- Collector container `9907619866c244f55024965265182fcbfebf48bf12c4458cd88ff4debf678d56`
  retained start time `2026-09-20T02:01:20.569305852Z` with zero restarts. It was
  not recreated during dashboard builds or deployment.
- Pre-dashboard Compose backup:
  `/home/klab/codex/Visibility/state/dashboard-before-20260920T025328Z/compose.yaml`.

No firewall policy, rule logging, flow export, retention, or other running app
was changed. This initial web interface uses HTTP on the trusted LAN without
login. NetFlow/bandwidth collection and broader access controls remain separate
work. Location updates are manual; no recurring task was installed.

## Continuous Jev experiment — deployed 2026-09-20 UTC

The user requested a continuous experiment to observe Jev's network
classifications directly. Dashboard version **0.3.0** adds a server worker and a
live classification feed. It retains the manual experiment, existing key file,
SQLite history, three-group request bound, ten-attempt UTC-day allowance, and
15-minute expiry. All category judgments come from Jev; no rules classifier or
new network data source was added.

- **37 Python tests passed** in the Docker build, including eleven new worker
  and window tests. They cover automatic execution without browser polling,
  stop during collection/inference, expiry, shared persistent allowance,
  failure without retry, empty input, rotation, caps/gaps, mode/session races,
  shutdown, and matching absolute query/count bounds. Tests use a fake provider.
- Frontend formatting, TypeScript checking, and Vite production build passed.
- The deployed image is
  `sha256:77bc3535658cf833e9e92d401616be4d0b4adb81bbfcaa43730b2bf3dd10539c`,
  tagged `visibility-dashboard:0.3.0`; health reports version 0.3.0.
- On deployment, Jev was OFF and the previous manual result and allowance
  survived: one attempt, 2,318 input tokens. No database migration was required.
- Switching ON in the real browser produced two automatic batches around
  **23:28:41** and **23:29:41 UTC** without manual Run requests. The first
  selected 3 of 81 groups from 261 records; the second selected 3 of 118 groups
  from 367 records. Neither input window was capped or had parse errors.
  Their recorded time boundaries were exactly adjacent.
- These two acceptance batches saved **six classifications**, consumed
  **4,635 input / 815 output tokens**, and had estimated combined input cost
  **$0.00019467** at the documented price. Together with the earlier manual test,
  the allowance read 3/10 at the stop check. These figures describe this check,
  not later sessions or the provider's billing ledger.
- First-batch suggestions were housekeeping for UDP 53, tentative housekeeping
  for UDP 10001, and web/communication for TCP 443. The second batch returned
  unknown for UDP 5514, UDP 9930, and TCP 8080. These are observed model outputs,
  not verified application identifications or a measured accuracy result.
- OFF was tested after the second batch. At a check 89 seconds after its
  completion, the attempt count was still three, with no active request.
  Saved results and free manual capture/request-preview continued to work;
  the manual paid Run button stayed disabled while OFF.
- Real-browser checks passed for category filtering, selecting a saved batch,
  following the newest batch, inspecting the sanitized model request, and
  opening an original firewall record from an automatic result. No browser
  console errors or page-width overflow were observed at the normal 826-pixel
  viewport. No separate mobile viewport check was performed in this update.
- The normal five-minute snapshot still returned live records (1,801 at the
  check). The collector retained ID
  `9907619866c244f55024965265182fcbfebf48bf12c4458cd88ff4debf678d56` and start
  time `2026-09-20T02:01:20.569305852Z`. Its rendered Compose configuration was
  compared before promotion and was identical. Dashboard bindings, environment,
  storage/secret mounts, identity, and security/resource settings were retained;
  shutdown grace increased from 20 to 35 seconds for an in-flight request.

Pre-update source, Compose configuration, and container identities are saved on
AI-02 in `state/jev-continuous-before-20260920/`. The retained prior image is
`visibility-dashboard:0.2.0`. See [operation and rollback](docs/jev-trial.md).
The automatic worker remains an explicitly enabled, bounded sampler; it does
not guarantee classification of every collected record or recover late logs.

## Pi-hole and navigation release — 2026-09-21 EDT / 2026-09-22 UTC

Version **0.5.0** adds read-only Pi-hole API collection, DNS archival, and the
Activity / DNS view. Navigation is Overview, Activity, Devices, Collection,
and Jev trial. Existing `#inventory` and `#jev` bookmarks are preserved.

- Verified SSH as `klab@192.168.5.238`, hostname `ns0`, active Pi-hole FTL.
  API versions observed: core v6.4.3, web v6.6, FTL v6.7.1. The HTTPS
  certificate matched the independently read SSH-side SHA256 pin.
- Existing Phase `PI-HOLE_APP_PASS` was installed server-side as mode 0600;
  no credentials were printed or placed in source, environment files, images,
  or browser responses. Pi-hole configuration was not changed.
- Live reader check paged through **974 DNS queries in ten minutes** and
  read 145 history buckets. Its session was reused and explicitly logged out.
- **60 backend tests passed** in the image build, including 11 Pi-hole tests
  and two DNS API tests. Coverage includes TLS-before-auth, redirect refusal,
  endpoint scope, session reuse/logout, fixed cursor with advancing offset,
  bounds and incomplete pages, durable retry/checkpoint behavior, unavailable
  history, disabled/corrupt/stale states, quoted search, and duplicate receipts.
- Frontend formatting, TypeScript checking, and production build passed.
- The first restricted-container preflight delivered **524 real DNS records**
  and saved the checkpoint as mode 0600. It exited without replacing services.
- At **2026-09-22 00:31:06 UTC**, the live source was fresh and the archive was
  **84 seconds behind**, processed through `00:29:42 UTC`. There were **1,653
  receipts and 1,653 distinct event IDs**. The first record was at
  `00:13:04.504945 UTC`; there was no attempt to import all pre-existing history.
  No pending records or archive error remained.
- At that check, Pi-hole's recent summary contained **75,637 queries**, **7,560
  blocked**, and **19 clients**. These rolling source totals differ from the
  new archive's accumulated records and are labelled separately in the UI.
- Browser checks verified real charts/rankings, the blocking filter (43 loaded
  rows all blocked at that check), empty search, the 30-day selector, cap notice,
  and pagination (50 rows, page 2 of 20). Collection showed fresh DNS status and
  advancing archive time. Firewall activity still loaded without parse errors.
  At the natural 1,350-pixel viewport, no horizontal page overflow was observed.
- Jev remained **off**, with **zero attempts today**; UniFi inventory was fresh.
  No paid model calls were made for this integration.
- Natural UniFi CEF arrival is now verified: 91 controller-origin records over
  the prior 12 hours at 00:29 UTC, excluding the test host. Latest event was
  2026-09-21 23:31:30 UTC. Structured CEF parsing remains future work.
- Dashboard image:
  `sha256:45f3c3842df40f937a548a401ce8f68ad8712f05b1bd0e5c139bdffcac6000a6`.
  It was healthy with zero restarts after starting at `00:28:39.096691066 UTC`.
- Collector ID remains
  `9907619866c244f55024965265182fcbfebf48bf12c4458cd88ff4debf678d56`, started
  `2026-09-20T02:01:20.569305852Z`. Its complete rendered Compose service was
  identical before/after; dashboard mounts, security, resources, and previous
  environment settings also matched. Only its image and Pi-hole settings changed.

AI-02 rollback checkpoint:
`state/pihole-20260922T002709Z-before/`. Prior dashboard image 0.4.0 is retained.
Release receipts are `state/pihole-release.json` on the workstation and
`state/pihole-deployed.json`, `state/pihole-acceptance.json` on AI-02. See
[Pi-hole operations](docs/pihole-integration.md) for data limits and rollback,
and [organization notes](docs/organization.md) for the next design decisions.
