# Homelab visibility

Receive, retain, and explore network logs on **AI-02 (192.168.5.230)**.

Open the custom dashboard at **[http://192.168.5.230:8095](http://192.168.5.230:8095)**.
It combines an interactive world map/globe, filtered firewall events, raw system
logs, UniFi devices, Pi-hole DNS activity, and collection health. The lab marker uses the requested Rochester, NY
city location. See [dashboard operations](docs/dashboard.md) and the
[design notes](docs/dashboard-design.md). Alerting and NetFlow remain later phases.

The local source tree now includes a broader Overview with source status,
click-through summary cards, and a 24-hour firewall/DNS timeline. This version
has not been deployed to AI-02; the live dashboard remains at its prior version.

The **[Jev experiment](docs/jev-trial.md)** adds continuous activity classification:
switch on to automatically judge up to three fresh groups each minute and watch
the live result feed. It starts off, stops after 15 minutes or ten attempts per
UTC day, and saves probabilities, request evidence, usage, and reviewer labels.
Manual samples remain available. Open it at
**[http://192.168.5.230:8095/#jev](http://192.168.5.230:8095/#jev)**.

The **[UniFi inventory](http://192.168.5.230:8095/#inventory)** adds a live view of
network devices, connected clients, and their attachments, plus switch ports
and AP radios. It polls the controller at `10.10.20.50` locally about once a
minute, preserves the last good snapshot, and makes no Jev calls. See
[inventory operations and later integration steps](docs/unifi-integration.md).

The **[DNS view](http://192.168.5.230:8095/#activity/dns)** adds Pi-hole summaries,
an activity chart, frequently blocked domains, busiest clients, and searchable
query records. Collection runs locally without Jev. See [Pi-hole operations](docs/pihole-integration.md)
and the [navigation and organization plan](docs/organization.md).

## Local source history

This folder has a local Git repository on `main`. Commits provide a rollback
point for source, configuration templates, tests, and documentation. Check the
working tree and recent commits before changing the app:

```bash
git status --short
git log --oneline -5
git diff
```

For a committed change that needs to be undone, review it with `git show`, then
use `git revert COMMIT` to make an explicit rollback commit. Git does not track
`.env`, `state/`, collector data, secrets, or generated build output, and a Git
rollback does not change a running deployment. Follow the service-specific
rollback instructions below when a deployed version must also be restored.

Initially deployed and verified on 2026-09-19 (America/New_York). See
[VALIDATION.md](VALIDATION.md) for the acceptance results. OPNsense now forwards
its currently generated logs to the collector over TCP with RFC5424 framing.

## Platform decision

Use Docker Compose on AI-02. Docker and Compose are already installed, and the
host has ample available memory and a separate, large `/home` filesystem. A VM
would add a guest OS to maintain. A dedicated VM remains an option if stronger
isolation or independent guest snapshots become a requirement; a VM on the same
host would still share AI-02's power, disks, and reboot downtime.

The initial service is VictoriaLogs **v1.52.0**. It accepts RFC3164 and RFC5424
syslog directly and stores searchable records without an additional database.
The syslog envelope is parsed into fields such as hostname, application, and
severity. The message body, including OPNsense's filterlog CSV, stays available
as `_msg`; the dashboard parses firewall fields while retaining that message.
This is not a byte-for-byte archive of the original syslog envelope.

## Deployment settings

| Item | Setting |
| --- | --- |
| Compose project | `visibility` |
| Syslog TCP and UDP | `192.168.5.230:514` |
| Query API and built-in explorer | `127.0.0.1:9428` on AI-02 |
| Custom dashboard | `http://192.168.5.230:8095` on the trusted LAN |
| Data | `/home/klab/.local/share/visibility/victorialogs` |
| Retention | 30 days, as requested; expired records are automatically removed |
| Container limits | 2 CPUs, 2 GiB RAM, no swap |
| Cache budget | 1 GiB within that memory limit |
| Disk protection | Switch to read-only when the data filesystem has less than 20 GiB free |
| Runtime | UID/GID 1000, read-only container filesystem, capabilities dropped |
| Legacy timestamps | Interpret RFC3164 timestamps as `America/New_York` |

The 20 GiB threshold is a free-space safeguard, not a quota or delivery guarantee.
The initial deployment has no maximum dataset size: measure daily growth before
promising that 30 days will fit indefinitely. Logs cannot be recovered if a sender
drops them while the collector is unavailable. UDP provides no acknowledgements;
prefer TCP where the sender supports it. Durable forwarding queues and TLS can be
added after checking the actual senders' capabilities.

These initial listeners accept plaintext, unauthenticated syslog. Any host that
can reach the published address and ports can submit records. Use this only on
the intended trusted network. Binding the LAN address is not a sender allowlist.
Docker-published ports can bypass UFW rules; verify actual reachability rather
than assuming UFW protects them. Do not forward these ports from the Internet.

Starting the stack creates its Docker bridge/network, publishes the ports, and
writes its data directory. It does not require changing existing containers,
OPNsense rules, host mounts, or partitions. Review the bind address and data path
before starting on a different host. Changes to firewall policy, routing, or disk
layout need separate review and authorization.

## Deploy the collector on AI-02

Copy this project to `/home/klab/codex/Visibility` on AI-02 first. Run as `klab`:

```bash
cd /home/klab/codex/Visibility
# Keep any existing .env; .env.example contains no credentials.
if [ ! -e .env ]; then cp .env.example .env; fi
mkdir -p /home/klab/.local/share/visibility/victorialogs
docker compose config --quiet
docker compose pull logs
docker compose up -d logs
docker compose ps
curl --fail http://127.0.0.1:9428/health
python3 scripts/check_intake.py --host 192.168.5.230
```

The bind-mounted data directory must already exist and be writable by UID 1000.
Compose refuses to create it as root. No package installation is needed.
Check available space and port conflicts again immediately before starting:

```bash
df -h /home/klab
ss -lntu
```

To check persistence, save the token printed by the intake check. During the
initial validation window, stop/start only this new service, then query it again:

```bash
docker compose stop logs
docker compose start logs
curl --fail http://127.0.0.1:9428/health
python3 scripts/check_intake.py --verify-only --token REPLACE_WITH_PRINTED_TOKEN
```

The check writes four clearly identified synthetic records using reserved example
IP addresses. It covers TCP newline and octet-counted framing, UDP RFC3164, and
OPNsense-style RFC5424/filterlog messages. They expire under normal retention.

## OPNsense source — connected

Under **System > Settings > Logging**, the remote destination **AI-02 Visibility**
is enabled. It reuses UUID `ad8bb8eb-1abc-4a3d-9d2c-8f36577da137`, previously the
disabled `telemetry-alloy` target on port 1514. Do not add a duplicate destination.

| Setting | Value |
| --- | --- |
| Sender | `192.168.5.1` / `OPNsense.internal` |
| Transport | TCP/IPv4 |
| Destination | `192.168.5.230` |
| Port | `514` |
| Format | RFC5424/IETF |
| Application, severity, facility filters | Empty: forward all currently generated events |
| Local logging | Kept enabled; existing local retention unchanged |

Only events actually generated are forwarded. Allowed traffic needs logging on
the existing matching pass rules. Review those separately: do not add a broad
allow rule just to obtain logs. Standard stateful firewall logging records the
initial packet of a flow, not every packet or total bytes transferred. No firewall
rule logging, DNS query logging, or service verbosity settings were changed.

Synchronize clocks on senders. Logs outside the retention window, malformed
messages, and future timestamps can be rejected. A successful synthetic test
does not prove that a real device is configured or can reach the collector.
For OPNsense, real firewall and system records and a timestamped end-to-end probe
have now been verified. Additional network devices still need separate setup.

NetFlow is a different protocol and needs its own collector later. Traffic that
never traverses OPNsense requires another observation point.

The guarded helper uses the existing Phase-backed API credentials. From the
operator workstation, inspect the current target without printing credentials:

```bash
phase run 'python3 /home/klab/codex/Visibility/scripts/opnsense_forwarding.py inspect' \
  --app Operator --env Production --path /opnsense --generate-leases=false
```

The helper's rollback state is private and ignored by Git at
`/home/klab/codex/Visibility/state/opnsense-forwarding.json` on the operator
workstation. It contains target settings and a configuration fingerprint, not
credentials. To restore the original disabled target after an authorized rollback:

```bash
phase run 'python3 /home/klab/codex/Visibility/scripts/opnsense_forwarding.py rollback' \
  --app Operator --env Production --path /opnsense --generate-leases=false
```

Rollback restores the old description, disabled state, port 1514, and legacy
format, then reconfigures syslog only. It refuses to overwrite a target with newer
settings and verifies the rest of the configuration, excluding normal save and
revision timestamps. It preserves local and already collected logs. The encrypted
before/after checkpoint locations are recorded in [VALIDATION.md](VALIDATION.md).

## Operate and roll back

```bash
cd /home/klab/codex/Visibility
docker compose ps
docker compose logs --tail 50 logs
du -sh /home/klab/.local/share/visibility/victorialogs
df -h /home/klab
curl --fail http://127.0.0.1:9428/metrics
```

Watch `vl_storage_is_read_only`, `vl_rows_dropped_total`, free space, and actual
arrival of records from each sender. `/health` alone does not prove ingestion.
The service's own Docker logs rotate separately from the 30-day collected logs.

For private access from the operator workstation:

```bash
ssh -F /home/klab/.ssh/config -N -L 9428:127.0.0.1:9428 klab@192.168.5.230
```

Then use `http://127.0.0.1:9428/select/vmui/` locally. The intake query API is kept
off the LAN. The custom dashboard provides bounded log reads and explicit Jev
trial controls; its
initial HTTP interface is available without login to clients that can reach the
LAN address. See [access scope](docs/dashboard.md#access-and-data-scope).

Collector rollback stops this service and leaves the collected data intact:

```bash
cd /home/klab/codex/Visibility
docker compose stop logs
```

If stopping intake permanently, first disable or roll back the OPNsense target
so the firewall does not keep attempting delivery to a stopped service.

Do not remove the data directory or use `down --volumes` as routine rollback.
Retention is not a backup. Plan separate backup/export if the records need to
survive loss of AI-02's storage. Keep the pinned version until an upgrade and its
storage compatibility have been reviewed.

## Sources

- [VictoriaLogs syslog ingestion](https://docs.victoriametrics.com/victorialogs/data-ingestion/syslog/)
- [VictoriaLogs storage and retention](https://docs.victoriametrics.com/victorialogs/)
- [VictoriaLogs security](https://docs.victoriametrics.com/victorialogs/security-and-lb/)
- [Docker Compose on a single server](https://docs.docker.com/compose/how-tos/production/)
- [Docker and host firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [OPNsense remote logging](https://docs.opnsense.org/manual/settingsmenu.html#logging)
- [OPNsense firewall logging](https://docs.opnsense.org/manual/logging_firewall.html)
