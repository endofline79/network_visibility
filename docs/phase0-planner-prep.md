# Phase 0 planner prep

Repo changes that line up with the 2026-11-01 AI-02 host work. Nothing in this
document repoints OPNsense, restarts llama-swap, or rebuilds the running
console image.

## Compose

Tracked `compose.yaml` now matches the live VictoriaLogs budget:

| Setting | Value |
| --- | --- |
| `-memory.allowedBytes` | `3GiB` |
| `mem_limit` / `memswap_limit` | `4g` / `4g` |

`allowedBytes` stays under the container limit so ingest and the Go runtime
still have about a gibibyte.

`compose.yaml` also includes the live `alerter` service (image
`visibility-alerter:0.1.0`) and a new `filterlog-relay` service.
`alerter/Dockerfile` and `alerter/rules.json` are **not in this git repo**.
They already exist on the AI-02 checkout that is not a git working tree.
Copying this `compose.yaml` onto that host keeps the running alerter build
context. A fresh clone cannot `docker compose build alerter` until that source
is added. Webhook URL and insert token stay in `*_FILE` mounts under
`${VISIBILITY_SECRETS_DIR}`.

## Live console overlay

AI-02 deploys the presentation console with:

```bash
docker compose -f deploy/compose.live.yaml up -d
```

That file is the sanitized live overlay: `visibility-console:0.4.2`,
`pull_policy: never`, `PRESENTATION_MODE=live`, `PRESENTATION_AUTH=required`,
TLS material and tokens from `/home/klab/.local/share/visibility/presentation`
mounted at `/run/visibility`. No secret values are in git.

`compose.presentation.yaml` stays the loopback **demo** (`visibility-console:0.1.0`,
`PRESENTATION_MODE=demo`). It names the same planner variables so the two files
do not drift apart, and it does not call a model.

Planner environment, on the live overlay and in the console code:

| Variable | Value |
| --- | --- |
| `PLANNER_TOKEN_FILE` | `/run/visibility/planner-token` |
| Host file | `~/.local/share/visibility/presentation/planner-token` (mode `0600`, not in git) |
| `PLANNER_MODEL` | `visibility-planner` |
| `LLM_BASE_URL` | `http://172.17.0.1:8081/v1` |

`visibility-planner` is the llama-swap alias of `qwen38-27b-ud-q8-k-xl-llama`.
That process uses `--parallel 1`. `presentation/backend/planner.py` queues
callers on one in-process slot (`planner_call`). Keep the console's uvicorn
command single-process. `GET /api/planner` reports the pin and whether the
token file is non-empty. It does not return the token and it refuses to
advertise a non-local base URL. Cloud LLM fallback is off. There is no ask UI
in this change.

The running `visibility-console:0.4.2` image does not contain the host cache or
`/api/planner` until that image is rebuilt from this source.

## Filterlog relay

Today OPNsense syslog-ng sends TCP/IPv4 RFC5424 to `192.168.5.230:514`, which
Docker publishes straight to VictoriaLogs' built-in syslog listener. There is
no mid-parse. The stream is `{hostname="OPNsense.internal", app_name="filterlog"}`
and the CSV stays in `_msg`. VictoriaLogs 1.52 cannot extract those CSV fields.

`filterlog-relay` listens on `192.168.5.230:1515/tcp` (override with
`FILTERLOG_RELAY_PORT`). Port 1515 is deliberately not 514 and not 1514 (the
old disabled `telemetry-alloy` destination). The relay parses RFC5424, calls
`presentation/backend/filterlog.py`, and POSTs JSON lines to
`http://logs:9428/insert/jsonline` with `_stream_fields=hostname,app_name`,
`_time_field=_time`, and `_msg_field=_msg`. Parsed fields are `action`, `iface`,
`dir`, `proto`, `src`, `dst`, `sport`, `dport`, `rule`, `reason`, `ip_version`,
`packet_bytes`, `src_local`, `dst_local`, and `parse_error` when parsing fails.
`_msg` stays the raw CSV. `src` and `dst` are not stream labels.

Non-filterlog lines that reach the relay are inserted with hostname, app name,
time, and raw message so a mistaken full-stream cutover does not drop cron or
syslog-ng. The supported cutover is filterlog only.

Bringing the compose service up does **not** change OPNsense. Until the cutover
below, the relay is idle and `:514` ingest is unchanged.

### Cutover (needs Kevin's OK — not done)

1. Deploy `filterlog-relay` and confirm it is listening (`ss -lnt` shows
   `192.168.5.230:1515`, container healthcheck passes). Do not send production
   firewall logs at it until the next steps are approved.
2. Add a **new** OPNsense syslog destination, TCP/IPv4, RFC5424, host
   `192.168.5.230`, port `1515`, program filter `filterlog` only. Leave the
   existing destination UUID `ad8bb8eb-1abc-4a3d-9d2c-8f36577da137`
   ("AI-02 Visibility", all programs, port 514) in place.
3. Confirm new VictoriaLogs rows for `app_name:=filterlog` have `action`, `src`,
   and `dst` populated, with the same `hostname` and `app_name` stream fields.
   Older rows stay raw CSV in `_msg`.
4. While both destinations include filterlog, those rows are stored twice.
   After the relay looks right, stop the original destination from also
   forwarding the `filterlog` program. Do not disable the original destination
   outright; syslog-ng and cron still use `:514`.
5. `scripts/opnsense_forwarding.py` only knows that one all-programs UUID. Do
   not change its port to 1515. Its `rollback` action restores the disabled
   port-1514 target and stops forwarding. It is not the relay rollback.
6. Relay rollback: remove or disable the filterlog-only destination first, then
   `docker compose stop filterlog-relay`. Port 514 keeps ingesting raw filterlog.

Optional `RELAY_ALLOW_FROM` can limit peers. Loopback stays allowed so the
container healthcheck works. Docker's published-port source address is not a
reliable allowlist, so the default is the LAN bind address, same as VictoriaLogs.

## Host cache

`presentation/backend/hosts.py` keeps an in-memory name cache for the later
planner. `HostCache.lookup(ip=..., mac=...)` is the call `/api/ask` should use.
`GET /api/hosts` returns the same snapshot (demo mode skips VictoriaLogs;
live mode requires the existing viewer session).

Merge order:

1. `iot-hosts.yaml` (highest). Packaged file
   `presentation/config/iot-hosts.yaml` is an empty allowlist. On AI-02, put the
   real file at `~/.local/share/visibility/presentation/iot-hosts.yaml` so the
   console sees `/run/visibility/iot-hosts.yaml`. At most 16 hosts. Values are
   checked before they can be reused in LogsQL; the cache queries themselves
   are fixed strings and do not interpolate the file.
2. UniFi `app_name:=unifi-snapshot` clients from the last 15 minutes, keyed by
   MAC. A hand entry with the same MAC keeps its name and also matches the
   UniFi IP.
3. Pi-hole `client_name` over the last hour, by client IP, only when no
   higher-priority source already has that IP.

Refresh default is 300 seconds (`HOST_CACHE_REFRESH_SECONDS`). Live mode tries
the `console-planner` token file first and then the console query token. A
failed poll keeps the previous sample and marks the snapshot stale. Two UniFi
MACs sharing one IP are listed as `ambiguous_ips` and are not given a single
name.

**Wired-client gap:** there is still no OPNsense DHCP lease or ARP feed in
VictoriaLogs. UniFi only sees clients that pass its gear, and Pi-hole names are
partial. Wired clients that appear in neither source stay unresolved until a
later telemetry pull or an `iot-hosts.yaml` row.

## llama-swap alias

The `visibility-planner` alias was applied on AI-02 in the **generated** file
`dual-amd-interface/config/generated/llama-swap.yaml`. `scripts/render_config.py`
and `dual_amd_interface.renderer` are not in this repository (`network_visibility`).
This PR does not teach that renderer about `aliases`. A re-render on the host
will drop `visibility-planner` until that other repo grows alias support, or
until the alias is put back into the generated file by hand.
