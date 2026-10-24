# Data catalog

Single-node VictoriaLogs v1.52.0 on AI-02, 30-day retention. Raw backend HTTP is bound to AI-02 loopback port 9428; clients use HTTPS port 9429 and the Phase bearer token. Most stored scalar fields are returned as strings. Inspect native field discovery before assuming a schema.

## Sources and semantics

| Filter | Content | Important limits |
| --- | --- | --- |
| `app_name:=filterlog` | OPNsense firewall decisions, raw CSV in `_msg` | Only logged rules; not a complete traffic meter. Use the bundled `--parse-firewall` helper for structured decisions. `direction` is relative to the interface. |
| `app_name:=opnsense-flow schema:=2` | NetFlow v9 routed traffic, structured IPs/ports/protocol/counters | Deduplicate `event_id`; schema 1 bootstrap counters were invalid. Records are not sessions. |
| `app_name:=pihole-dns` | DNS events: domain, query_type, status, outcome, client_ip, client_name, upstream, reply_type | Deduplicate `event_id`. Queries only seen by Pi-hole. Polling is 60s with 60s settling; not live packet capture. |
| `app_name:=unifi-snapshot` | Periodic inventory, devices, clients, networks; starts with headless deployment | `entity_kind` is snapshot/device/client/network. Samples, not a complete change audit. |
| `app_name:=pihole-snapshot` | Periodic Pi-hole summary in `snapshot_json` | Rolling source counters; do not sum snapshots as event totals. |
| `app_name:=visibility-alert` | Alert checker transitions and heartbeats: fingerprint, rule, severity, state, subject, summary, first_seen, last_seen, evidence_query, details | Written by the insert-only `alert-inserter` user. `kind:=transition` is a state change; `kind:=heartbeat` is the checker cycle. Deduplicate by fingerprint and keep the newest `_time`. See [alerting](../../../docs/alerting.md). |
| Other app_name values | Raw OPNsense / UniFi syslog | Discover actual sources; messages vary by firmware and logging configuration. |

System-wide `app_name` discovery also includes records that are not network traffic. Do not sum all sources together as one traffic total.

### NetFlow

Fields include `_time` (flow end, NOT ingest time), `event_id`, `src_addr`, `dst_addr`, `src_port`, `dst_port`, `proto`, `bytes`, `packets`, `in_if`, `out_if`, `flow_start_ns`, `flow_end_ns`, `sampling_rate`, `schema`.

Egress-only hooks on OPNsense LAN/LAB/INFRA/WAN avoid counting each routed packet twice. The switch is not mirrored: same-LAN traffic bypassing OPNsense is absent. WAN upload records are post-NAT; per-client upload attribution cannot be inferred. Download destinations can identify internal clients. Bytes are IP-layer bytes, not Ethernet wire bytes or application payload. Low-volume exports can lag several minutes. LAB and IPv6 coverage were configured but not yet validated with live canaries.

### Inventory and joins

UniFi records share `observed_at`, `site_id`, and `partial`. Each snapshot includes a full `snapshot_json` record (`entity_kind:=snapshot`), plus flat entity rows. `ports` and `radios` on device rows are JSON strings. Missing optional API statistics stay missing; inspect `partial` and each device's `errors`.

Within one observed_at: device `id` matches client `uplink_id`; inventory IP can correlate with DNS `client_ip` and flow addresses. Do not use today's IP-to-device mapping for old events without a time-valid observation: DHCP reuse and roaming can change it. An absent client is not proof the device powered off. To obtain current inventory, select the newest complete snapshot, not each entity's independent last-ever row (which would retain departed clients).

Snapshots use durable pending batches and at-least-once retry. Deduplicate `event_id`. During archive outages an outstanding sample is retained; intermediate samples may be skipped before the newest one is archived. Source timestamps expose gaps. No historical UniFi inventory was reconstructed.

## Native API examples

The helper passes native parameters through, without an endpoint allowlist. Query results and live tail are NDJSON; discovery and stats-range responses are native JSON.

```bash
# Source counts, narrow time window.
python3 /home/klab/.codex/skills/homelab-telemetry/scripts/telemetry.py --query '_time:5m | stats by (app_name) count() rows'

# Discover flow fields.
python3 /home/klab/.codex/skills/homelab-telemetry/scripts/telemetry.py --path /select/logsql/field_names --query '_time:1h app_name:=opnsense-flow schema:=2'

# Valid, deduplicated flow totals.
python3 /home/klab/.codex/skills/homelab-telemetry/scripts/telemetry.py --query '_time:1h app_name:=opnsense-flow schema:=2 | stats by (event_id) max(bytes) bytes, max(packets) packets | stats sum(bytes) bytes, sum(packets) packets'

# Latest full inventory, including empty collections and partial status.
python3 /home/klab/.codex/skills/homelab-telemetry/scripts/telemetry.py --query '_time:1h app_name:=unifi-snapshot entity_kind:=snapshot | sort by (_time) desc | limit 1'

# Firewall decoding preserves unsupported messages and parse_error.
python3 /home/klab/.codex/skills/homelab-telemetry/scripts/telemetry.py --query '_time:5m app_name:=filterlog | limit 10' --parse-firewall

# Event stream. It is not SSE, a durable queue, or gap-free replay.
python3 /home/klab/.codex/skills/homelab-telemetry/scripts/telemetry.py --tail --query 'app_name:=pihole-dns' --param offset=120s --seconds 30
```

Native `/select/logsql/stats_query_range` with `query`, `start`, `end`, and `step` supports chart polling. Use an absolute time range for reproducible comparisons. `/select/logsql/field_values` accepts `field`; `/select/logsql/hits` supports histograms. Consult [native query documentation](https://docs.victoriametrics.com/victorialogs/querying/) for endpoint-specific syntax.

Tail doesn't support aggregate, sort, limit, or offset pipes. The native `offset` URL parameter is a time-delay window, not pagination. Its default short delay can miss late flow/DNS records. For reliable totals, periodically re-query a historical overlap and deduplicate; no fixed short window guarantees complete NetFlow delivery. Stop streams when the consumer closes. Keep the bearer token server-side for dashboards, using fetch/NDJSON from the server instead of exposing credentials via browser EventSource.
