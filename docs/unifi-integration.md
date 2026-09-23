# UniFi inventory and integration

Status: **inventory deployed and verified on AI-02**, dashboard `0.4.0`. The user approved
starting with inventory on 2026-09-20. The integration uses the local API only;
controller settings, firewall rules, and syslog forwarding remain unchanged.

Context: the Codex task **Compare Unified Controller AI-02**
(`01a0bffe-a4fc-7222-9ca2-ba5e871a9bbb`, host `local`) and the deployment record
at `/home/klab/codex/hom-network/changes/2026-09-20-unifi-os-controller.md`.
The findings below were refreshed against the live systems.

## What is available now

Controller: **https://10.10.20.50:11443/**, VM `unifi-os` on AI-02's INFRA
bridge. The deployment record identifies UniFi OS Server 5.1.42 and Network
10.5.67. The service is active and its local Integration API responds.

| Device | Management IP | Observed status |
| --- | --- | --- |
| USW Flex 2.5G 8 PoE | 10.10.20.10 | ONLINE, firmware 2.1.8 |
| U7-Pro-Wall-Kitchen | 10.10.20.11 | ONLINE, firmware 8.7.11 |
| U7-Pro-Wall-Upstarirs | 10.10.20.12 | ONLINE, firmware 8.7.11 |

- The API returned **19 connected clients: 14 wireless and 5 wired** at the
  inspection point. Counts change as clients connect and disconnect.
- Client lists expose IP/MAC, name, wired/wireless type, connected-at time, and
  `uplinkDeviceId`. Missing fields must remain unknown; one inspected client
  detail response omitted IP even though the list supports it.
- AP details expose radio bands/channels/channel widths and upstream device.
  Switch details expose port link speed/state and PoE state.
- Device statistics expose CPU/memory utilization, uptime, heartbeat times,
  aggregate uplink RX/TX rates, and radio statistics where available. This is
  device telemetry, not per-application or per-flow traffic accounting.
- Port 1 on the Flex still negotiates at 100 Mbps; port 2 and the uplink on
  port 9 are at 2.5 Gbps. This matches the existing upstairs-AP link issue in
  the deployment record; no diagnosis or repair was performed here.

The existing secret is `UOS_API_KEY` in Phase application `agents`, environment
`Production`, path `/UOS-server`. The dashboard uses a server-only copy in
`/home/klab/.local/share/visibility/secrets/unifi_api_key` (0600), through its
existing read-only secrets mount. It is never included in images, Compose
environment values, API responses, browser code, or model requests. The
application implements only fixed GET endpoints; this does not assert that
the underlying API credential itself lacks write privileges.

## Inventory operation

Open **http://192.168.5.230:8095/#inventory**. The attachment map filters the
client list by the selected switch or AP. Search by name, IP, MAC, or attached
device; filter by connection type. Expand hardware details for CPU/memory,
uptime/heartbeat, firmware, switch link speeds/PoE, and Wi-Fi channels/widths.
Missing values are unknown. Device names are displayed as received.

- One background worker polls about every 60 seconds after each completed poll.
  The browser reads the saved result every 15 seconds; opening more tabs does
  not increase controller polling. No cloud service or metered model is called.
- API reads use `X-API-Key` only after matching the controller certificate pin
  below. No redirects or immediate retries. Connection timeouts are at most
  five seconds; a poll has a 20-second request budget (an in-progress socket
  operation may take up to five additional seconds). Each response is capped
  at 4 MiB. Each poll pages sites/devices/clients/networks and then reads device
  details and latest statistics; the current three-device setup uses ten GETs.
- Page counts and unique IDs are checked. Limits are 50 sites, 32 devices,
  2,000 clients, and 100 networks. A bound, changed page count, duplicate, or
  incomplete page fails the poll explicitly rather than dropping clients.
  UniFi's paginated API does not promise a transactional point-in-time snapshot.
- An optional device detail/statistics failure marks that device and the snapshot
  partial. Authentication or pin failures abort the poll. Missing IP addresses,
  unknown attachments, and unavailable metrics are not inferred.
- The latest successful normalized snapshot is written atomically as a 0600 file
  at `/home/klab/.local/share/visibility/dashboard/unifi-inventory.json` using the
  existing `/analysis` mount. This is current state, not a history archive.
  Failures preserve it; stale status appears on a failed poll or after 150 seconds.
  Device online/offline labels on stale data reflect that saved observation.
- Client attachments and IPs are **not** joined to historical firewall records:
  addresses can be reassigned. No client data is added to Jev prompts by this step.
- `GET /api/inventory` returns normalized inventory and freshness metadata.
  There are no inventory mutation/refresh-proxy endpoints. App health and
  controller availability are separate; inspect inventory freshness too.
- `UNIFI_INVENTORY_ENABLED=false` followed by recreating only `dashboard` stops
  polling. The snapshot remains. The controller host is fixed at `10.10.20.50:11443`;
  `UNIFI_SITE_ID`, `UNIFI_CERT_SHA256`, and `UNIFI_API_KEY_FILE` are server settings.
  Update a certificate pin only after independently verifying its replacement.

The existing dashboard is LAN HTTP without a login. Its current audience can
read the new inventory. INFRA `10.10.20.0/24` is included in the app's explicit
local-network defaults; this does not change routing or firewall policy.

### Verification and rollback

The image build runs the parser/API/Jev/inventory test suite and the frontend
TypeScript build. Inventory tests cover paging bounds, relationships, missing
telemetry, durable last-good state, stale/recovery behavior, disabled polling,
credential-safe errors, pin-before-auth, and rejected redirects. Verification
uses normal API reads; no AP reboots or client disconnects are needed.

On AI-02:

```bash
cd /home/klab/codex/Visibility
curl --fail --silent http://192.168.5.230:8095/api/health
# The following returns client identifiers; inspect locally, do not publish it.
curl --fail --silent http://192.168.5.230:8095/api/inventory
```

To roll back, use the release's saved Compose configuration (recorded in
`VALIDATION.md`) and its retained `visibility-dashboard:0.3.0` image. Recreate
only `dashboard` with `--no-deps --no-build`; keep the log collector and data
files intact:

```bash
cd /home/klab/codex/Visibility
docker compose --project-directory "$PWD" \
  -f state/unifi-inventory-20260920T235801Z-before/compose.yaml \
  up -d --no-deps --no-build --wait --wait-timeout 60 dashboard
```

Before the next normal update, reconcile the source and primary Compose file
with the selected release. The backup preserves both; the `.env` was not changed.
Dashboard restarts reset the metered Jev switch to OFF by design.
No controller or firewall rollback is required for this inventory addition.

## Verified collection paths and gaps

| Path | Current result | Integration implication |
| --- | --- | --- |
| Dashboard container -> controller TCP 11443 | Authenticated inventory polls succeed with the pinned certificate. | Deployed local inventory feed uses the existing routed path. |
| Controller -> VictoriaLogs | Real exporter events are now arriving. A check at 2026-09-22 00:29 UTC found 91 `CEF` application records from `.50` over the preceding 12 hours, excluding the labelled test host; latest timestamp 2026-09-21 23:31:30 UTC. | Natural event delivery is verified. Activity / All logs can search these records; a structured CEF view remains future work. |
| APs `.11`/`.12` -> controller UDP 5514 | User cleared the blocker. Fresh OPNsense records show PASS for `.12` at 01:40:00 UTC and `.11` at 01:39:24 UTC on 2026-09-21, interface `bridge0`. | Firewall now permits the observed AP-to-controller logging traffic. This check did not inspect receiver-side delivery. |
| Controller's internal log receiver | UDP 5514 is listening. `rsyslogd.enabled=true`, `this_controller=true`, `this_controller_encrypted_only=true`, `log_all_contents=true`. | Internal logging is configured, but reconcile the encrypted-only setting with actual device log transport before changing it. |
| Controller -> AI-02 syslog port 514 | After explicit approval, added IPv4 UDP allowance `bf764198-b6ed-4696-a5a9-598e2b5a6ab5`, sequence 350, from `.50` to `192.168.5.230:514` on INFRA inbound. Active PF ordering was verified before the existing sequence-400 LAN block. | Approved path is open; all pre-existing configuration is unchanged apart from normal save metadata. No TCP or broader subnet allowance was added. |

The legacy Network logging settings inspected above do not establish the current
UniFi OS SIEM exporter configuration. No external SIEM destination was changed.

The visibility app now includes **10.10.20.0/24** in its explicit local-network
defaults, alongside LAN and LAB. The live snapshot API confirmed all three.
This is an app classification setting, not a routing change.

## Integration sequence

1. **API inventory and health — complete.** The local polling feed and inventory
   view described above are live. Future traffic-to-device enrichment needs
   fresh, unambiguous evidence; historical attribution needs its own history.
2. **Controller event export — natural arrivals verified.** The user configured
   export, and the approved UDP exception is active. In addition to the initial
   labelled path test, ordinary CEF records have now arrived from the controller.
   Activity / All logs can filter application `CEF`. Events are episodic, so a
   quiet five-minute window does not by itself indicate a failed exporter.
3. **Structured UniFi event parsing.** Retain original syslog messages and parse
   CEF fields into a separate UniFi event view: event kind, severity, client,
   AP/switch, Wi-Fi/network, and available event-specific measurements. The
   existing All logs view can show arrivals before a dedicated view is built.
4. **Jev context.** Keep all experimental activity judgments in Jev. Supply
   separately identified inventory evidence such as "access point contacting
   its controller" or "wireless client attached to the kitchen AP", with
   freshness/provenance. Keep identifying names, MACs, and IPs local under the
   current outgoing-data policy. Distinguish observed metadata from model
   guesses. Preserve the existing metering controls and original saved prompts.
5. **Device-log path — AP firewall blocker cleared by the user.** Both APs now
   have observed PASS records to `.50` on UDP 5514. Receiver-side delivery and
   the switch's device-log path were not checked in this follow-up. Preserve
   the intended INFRA isolation when reviewing any remaining logging gaps.

UniFi documents CEF event export for connectivity, device/admin activity, and
other selected categories. Its full Traffic Flows feature requires a supported
UniFi gateway; this deployment uses OPNsense and has no managed UniFi gateway.
Keep OPNsense as the routed-traffic source. Adding this controller alone will
not produce full application traffic classification or all-flow visibility.

## Applied syslog exception and rollback

The user explicitly approved this single firewall exception. It was added on
2026-09-21 UTC as rule `bf764198-b6ed-4696-a5a9-598e2b5a6ab5`:
IPv4 UDP, INFRA (`opt2` / `bridge0`) inbound, source `10.10.20.50`, destination
`192.168.5.230`, destination port 514, sequence 350, logging enabled.

`scripts/unifi_syslog_rule.py` checks the existing block, free sequence, and
interface; makes and decrypt-verifies an encrypted checkpoint; saves the new
rule; compares the complete configuration excluding only that rule and save
metadata; then reloads and checks the active PF rule/order. The installed
filter API exposes apply but has no older savepoint/cancel-rollback endpoints.
Recovery uses the encrypted checkpoint and the scoped disable operation below.
No controller settings, other rules, routing, or running containers changed.

Run from the operator workstation, where Phase and the private operation state
are available:

```bash
cd /home/klab/codex/Visibility
phase run 'python3 scripts/unifi_syslog_rule.py verify' \
  --app Operator --env Production --path /opnsense --generate-leases=false
# After choosing to roll back this exception, disable only this exact new rule:
phase run 'python3 scripts/unifi_syslog_rule.py disable' \
  --app Operator --env Production --path /opnsense --generate-leases=false
```

Private state: `state/unifi-syslog-rule-applied.json`. Encrypted checkpoint:
`state/opnsense-20260921T015451Z-before-unifi-syslog.xml.gpg`, mode 0600,
using the existing Phase recovery passphrase. Plaintext configuration is never
written to this workspace. Rollback preserves logs and retains the disabled
rule for audit; the helper refuses to overwrite a rule whose scope has drifted.

Verification token: `visibility-unifi-a4b879f019f24b338e94f1bf9ab81906`.
The test used hostname `visibility-test`, so normal dashboard views exclude it.
It proves controller-host-to-collector delivery, not the UniFi application's
export settings or event categories. At 01:57:58 UTC no ordinary UniFi exporter
record had arrived. Capture the next natural event without rebooting APs or
disconnecting clients. Future Jev enrichment must preserve its outgoing-data
policy and metering; this change does not send anything to Jev.

## Repeat the read-only probe

Obtain the controller's public TLS fingerprint through its already trusted SSH
connection. No API key is needed for this step:

```bash
ssh -F /home/klab/.ssh/config -o BatchMode=yes -o StrictHostKeyChecking=yes klab@10.10.20.50 'python3 - <<'"'"'PY'"'"'
import ssl, hashlib
certificate = ssl.get_server_certificate(("127.0.0.1", 11443), timeout=5)
print(hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest())
PY'
```

The fingerprint observed during this inspection was
`d961dfaf1d91c5790388c30a2a4de90d90990ddb15275e33b0aae6630dac3d40`.
Do not silently accept a different certificate from the API connection. Verify
any replacement through the trusted SSH path before updating the pin.

```bash
cd /home/klab/codex/Visibility
phase run --app agents --env production --path /UOS-server -- \
  python3 scripts/inspect_unifi.py \
  --cert-sha256 d961dfaf1d91c5790388c30a2a4de90d90990ddb15275e33b0aae6630dac3d40
```

The script performs bounded GET requests only and does not print client identity
lists, credentials, or raw settings responses. It reports page coverage (the
current client limit is 200); a production poller must paginate when needed.

Sources:

- [UniFi system logs and CEF export](https://help.ui.com/hc/en-us/articles/33349041044119-UniFi-System-Logs-SIEM-Integration)
- [UniFi required ports](https://help.ui.com/hc/en-us/articles/218506997-Required-Ports-Reference)
- [UniFi Traffic Flows requirements](https://help.ui.com/hc/en-us/articles/32201256219799-Traffic-Flows-and-Traffic-Logging-in-UniFi-Network)
- [UniFi local Network API](https://developer.ui.com/network/v10.1.84/getconnectedclientoverviewpage)
