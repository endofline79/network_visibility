# OPNsense traffic flows (no switch mirroring)

The Traffic page is `http://192.168.5.230:8095/#traffic`.

## Collection

OPNsense exports unsampled NetFlow v9, egress-only on WAN `igc0`, LAN `igc1`,
LAB `vlan01`, and INFRA `bridge0`. Physical trunk `igc2` and bridge members
`vlan02`/`vlan03` are not separately selected. Active timeout is 60 seconds;
inactive timeout is 15 seconds. Local Insight collection stays disabled.

`192.168.5.1 -> 192.168.5.230:2056/UDP -> flows -> logs:9428/insert/jsonline`

The collector gates UDP by source IP and v9 header before forwarding to a
loopback-only GoFlow2 v2.2.6 decoder. Its Docker image is pinned by digest.
HTTP status is internal to the Compose network on 8081; decoder metrics are
loopback-only on 8080. No Docker socket, firewall credentials, external AI calls,
port mirroring, packet payloads, or additional database service are involved.

Normalized records live in the existing VictoriaLogs database with
`app_name=opnsense-flow`, `schema=2`, and existing 30-day retention. A separate
SQLite spool at `/home/klab/.local/share/visibility/flows/pending.sqlite3` holds
up to 100,000 pending records, draining in batches of 500. On overflow, new
records are dropped and counted. Retries are at-least-once; the Traffic API
deduplicates event IDs before summing. All logs retains receipt duplicates.
Container limits: 1 CPU, 512 MiB, read-only root, no capabilities, non-root user.

### Important FreeBSD compatibility mapping

FreeBSD sends IN_BYTES/IN_PKTS followed by zero OUT_BYTES/OUT_PKTS. The decoder's
default shared counter fields are overwritten by OUT. `collector/mapping.yaml`
preserves IN counters as separate fields; zero/missing counters are rejected.
A real-decoder synthetic-packet regression test runs during image build.
Early schema-1 bootstrap records with zero counters were retained, not deleted;
they are excluded from Traffic totals. Valid schema-2 collection began around
2026-09-24 02:27 UTC. There is no historical backfill.

## Interpretation and limits

- Totals are observed IP bytes and packets, not Ethernet wire bytes, payload
  bytes, sessions, unique connections, or billing-quality accounting.
- Egress-only coverage excludes dropped inbound attempts; use firewall logs for
  logged decisions. Traffic originated by OPNsense itself is included.
- Upload sources on WAN are post-NAT (currently the CGNAT WAN address), so this
  source does not provide per-client Internet upload attribution. Download
  destinations and routed internal endpoints retain their local addresses.
- Same-LAN traffic switched without OPNsense remains out of scope. No switch
  setting or mirroring was changed. LAB and IPv6 hooks/formats are configured,
  but their live traffic paths were not exercised (LAB currently has no client).
- Flow-end timestamps place the entire exported chunk in its ending window;
  bytes are not interpolated across time bins. Long connections produce several
  records. The top-100 tuples are bounded, but summary totals cover the full
  selected window. Large windows can time out explicitly instead of returning
  silently partial totals.
- The active timeout is not an end-to-end latency guarantee. Low-volume
  datagrams and kernel cache scanning delayed some canaries several minutes.
- UDP loss is possible before durable buffering. A decoder restart loses its
  in-memory template cache; data before the next template can be lost. OPNsense
  announces templates every 500 export packets or 600 seconds (plus export
  delay). A reviewed exporter reconfigure refreshes them immediately.
- UI counters are since collector start; UDP receive errors are namespace
  counters. Decoder, invalid-record and spool-overflow counts indicate known
  gaps, but zero counters cannot prove complete coverage. Source-IP checking is
  not cryptographic authentication; keep UDP2056 on the trusted LAN.

## Validation / operations

```bash
docker compose ps
curl -fsS 'http://192.168.5.230:8095/api/traffic?window=15m'
docker compose exec -T flows python -c \
  'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8081/status").read().decode())'
phase run --app Operator --env Production --path /opnsense -- \
  python3 scripts/opnsense_netflow.py inspect
```

Exporter settings are managed through the supported diagnostics/netflow API.
`scripts/opnsense_netflow.py` saves only that subtree, refuses an unexpected
baseline, saves an ignored mode-0600 rollback checkpoint, and fingerprints the
rest of the firewall configuration before/after. It does not modify installed
OPNsense scripts. The encrypted full backup is
`/home/klab/codex/hom-network/recovery/opnsense-20260924T022304Z-pre-netflow.xml.gpg`.

## Rollback (requires operator approval)

On the workstation, inspect current state before the guarded rollback:

```bash
phase run --app Operator --env Production --path /opnsense -- \
  python3 /home/klab/codex/Visibility/scripts/opnsense_netflow.py rollback
```

It restores only prior NetFlow settings and reconfigures that service. If
unrelated firewall state changed since deployment, the guard stops for review.
Do not restore a full firewall backup over intervening changes.

On AI-02, stop `flows` with `docker compose stop flows`. Restore the dashboard
image to `visibility-dashboard:0.5.0` in Compose and run
`docker compose up -d --no-deps dashboard`. Before rebuilding old source, inspect
the source backup `/home/klab/.local/share/visibility/pre-netflow-source-20260923.tar.gz`
and selectively restore approved files. Keep the spool and log data; never use
`down --volumes` or delete either bind mount for rollback. Existing syslog/DNS
and UniFi collection do not depend on the flows service.

## Upstream references

- [OPNsense NetFlow](https://docs.opnsense.org/manual/netflow.html)
- [GoFlow2 v2.2.6](https://github.com/netsampler/goflow2/tree/v2.2.6)
- [FreeBSD v9 templates and counters](https://github.com/freebsd/freebsd-src/blob/releng/14.3/sys/netgraph/netflow/netflow_v9.c)
