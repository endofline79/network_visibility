import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Cable,
  Check,
  ChevronRight,
  Clock3,
  Network,
  Search,
  Server,
  Wifi,
} from "lucide-react";

type Device = {
  id: string;
  name: string | null;
  model: string | null;
  ip: string | null;
  mac: string | null;
  kind: "switch" | "ap" | "device";
  state: string | null;
  firmware: string | null;
  uplink_id: string | null;
  cpu_pct: number | null;
  memory_pct: number | null;
  uptime_seconds: number | null;
  last_heartbeat: string | null;
  errors: string[];
  ports: {
    index: number | null;
    state: string | null;
    speed_mbps: number | null;
    max_speed_mbps: number | null;
    poe_state: string | null;
  }[];
  radios: {
    band: string | number | null;
    channel: number | null;
    width_mhz: number | null;
    standard: string | null;
  }[];
};
type Client = {
  id: string;
  name: string | null;
  ip: string | null;
  mac: string | null;
  type: string | null;
  uplink_id: string | null;
  connected_at: string | null;
};
type InventoryResponse = {
  state:
    "fresh" | "partial" | "stale" | "starting" | "unavailable" | "disabled";
  stale: boolean;
  age_seconds: number | null;
  controller: string;
  poll_seconds: number;
  stale_seconds: number;
  last_attempt: string | null;
  next_poll: string | null;
  polling: boolean;
  error: string | null;
  snapshot: {
    observed_from: string;
    observed_at: string;
    site: { id: string; name: string | null };
    partial: boolean;
    devices: Device[];
    clients: Client[];
    networks: {
      id: string;
      name: string | null;
      vlan: number | null;
      enabled: boolean | null;
    }[];
  } | null;
};
const known = (value: string | number | null | undefined) => value ?? "Unknown";
const name = (device: Device) =>
  device.name || device.model || device.ip || "Unnamed device";
const duration = (seconds: number | null) =>
  seconds === null
    ? "Unknown"
    : seconds < 60
      ? `${Math.floor(seconds)}s`
      : seconds < 3600
        ? `${Math.floor(seconds / 60)}m`
        : seconds < 86400
          ? `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
          : `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
const age = (value: string | null, now: number) =>
  value
    ? `${duration(Math.max(0, (now - Date.parse(value)) / 1000))} ago`
    : "Unknown";
const speed = (value: number | null) =>
  value === null
    ? "Unknown"
    : value >= 1000
      ? `${value / 1000} Gbps`
      : `${value} Mbps`;
const title = (value: string | null) =>
  value
    ? value
        .toLowerCase()
        .replaceAll("_", " ")
        .replace(/^./, (c) => c.toUpperCase())
    : "Unknown";

export function Inventory({
  onHealth,
}: {
  onHealth: (healthy: boolean) => void;
}) {
  const [data, setData] = useState<InventoryResponse | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const [search, setSearch] = useState("");
  const [attachment, setAttachment] = useState("");
  const [connection, setConnection] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    async function update() {
      try {
        const response = await fetch("/api/inventory", {
          signal: abort.signal,
          cache: "no-store",
        });
        if (!response.ok)
          throw new Error(
            "Inventory display is unavailable. Retaining the last result.",
          );
        const result = await response.json();
        if (active) {
          setData(result);
          setError("");
        }
      } catch (e) {
        if (active && (e as Error).name !== "AbortError")
          setError(
            "Inventory display is unavailable. Retaining the last result.",
          );
      } finally {
        if (active) timer = setTimeout(update, 15000);
      }
    }
    update();
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      active = false;
      abort.abort();
      clearTimeout(timer);
      clearInterval(tick);
    };
  }, []);
  useEffect(() => setPage(0), [search, attachment, connection]);
  const snapshot = data?.snapshot;
  const devices = snapshot?.devices || [];
  const clients = snapshot?.clients || [];
  const devicesById = useMemo(
    () => new Map(devices.map((d) => [d.id, d])),
    [devices],
  );
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return clients
      .filter(
        (c) =>
          (!attachment ||
            (attachment === "unknown"
              ? !c.uplink_id || !devicesById.has(c.uplink_id)
              : c.uplink_id === attachment)) &&
          (!connection || (c.type || "UNKNOWN") === connection) &&
          (!query ||
            [
              c.name,
              c.ip,
              c.mac,
              c.uplink_id && devicesById.get(c.uplink_id)?.name,
            ]
              .join(" ")
              .toLowerCase()
              .includes(query)),
      )
      .sort((a, b) =>
        (a.name || a.mac || a.id).localeCompare(b.name || b.mac || b.id),
      );
  }, [clients, search, attachment, connection, devicesById]);
  const safePage = Math.min(
    page,
    Math.max(0, Math.ceil(filtered.length / 50) - 1),
  );
  const stale = !!(
    error ||
    data?.stale ||
    (snapshot &&
      now - Date.parse(snapshot.observed_at) >
        (data?.stale_seconds || 150) * 1000)
  );
  useEffect(
    () => onHealth(!!snapshot && !stale),
    [!!snapshot, stale, onHealth],
  );
  const label =
    data?.state === "disabled"
      ? "Polling disabled"
      : stale && snapshot
        ? "Saved inventory · stale"
        : data?.state === "unavailable"
          ? "Controller unavailable"
          : !snapshot
            ? "Connecting to controller"
            : snapshot.partial
              ? "Inventory synced · some details unavailable"
              : "Inventory synced";
  const selectDevice = (id: string) => {
    setAttachment(attachment === id ? "" : id);
    setSearch("");
    setConnection("");
  };
  const roots = devices.filter(
    (d) => !d.uplink_id || !devicesById.has(d.uplink_id),
  );
  // Keep every device visible, including incomplete or cyclic controller relationships.
  const reachable = new Set<string>();
  const visit = (id: string) => {
    if (reachable.has(id)) return;
    reachable.add(id);
    devices.filter((d) => d.uplink_id === id).forEach((d) => visit(d.id));
  };
  roots.forEach((d) => visit(d.id));
  const detached = devices.filter((d) => !reachable.has(d.id));
  return (
    <div className="inventory-view">
      <section
        className={`inventory-sync ${stale || data?.state === "partial" ? "needs-attention" : ""}`}
        aria-label="Inventory freshness"
      >
        <div className="inventory-sync-icon">
          {stale ? (
            <Clock3 size={21} />
          ) : snapshot ? (
            <Check size={21} />
          ) : (
            <Network size={21} />
          )}
        </div>
        <div>
          <strong>{label}</strong>
          <p>
            {snapshot ? (
              <>
                Observed {age(snapshot.observed_at, now)} ·{" "}
                {new Date(snapshot.observed_at).toLocaleString()}
              </>
            ) : (
              "Waiting for the first complete device and client inventory."
            )}
          </p>
        </div>
        <div className="inventory-sync-meta">
          <span>UniFi · 10.10.20.50</span>
          <small>Local API · every ~60s · no AI calls</small>
        </div>
      </section>
      {(error || data?.error) && (
        <div className="notice error" role="alert">
          <AlertCircle size={18} />
          <span>
            {error || data?.error}{" "}
            {snapshot
              ? "Device states below reflect the last successful poll."
              : "The collector will try again on its next interval."}
          </span>
        </div>
      )}
      {snapshot && (
        <>
          <section className="inventory-metrics" aria-label="Inventory summary">
            <div>
              <Server size={20} />
              <span>Network devices</span>
              <strong>{devices.length}</strong>
              <small>
                {devices.filter((d) => d.state === "ONLINE").length} reported
                online{stale ? " at last poll" : ""}
              </small>
            </div>
            <div>
              <Network size={20} />
              <span>Connected clients</span>
              <strong>{clients.length}</strong>
              <small>Reported by UniFi{stale ? " at last poll" : ""}</small>
            </div>
            <div>
              <Wifi size={20} />
              <span>Wireless clients</span>
              <strong>
                {clients.filter((c) => c.type === "WIRELESS").length}
              </strong>
              <small>
                Across {devices.filter((d) => d.kind === "ap").length} access
                points
              </small>
            </div>
            <div>
              <Cable size={20} />
              <span>Wired clients</span>
              <strong>
                {clients.filter((c) => c.type === "WIRED").length}
              </strong>
              <small>
                Across {devices.filter((d) => d.kind === "switch").length}{" "}
                switches
              </small>
            </div>
          </section>
          <section
            className="inventory-panel"
            aria-labelledby="attachment-title"
          >
            <div className="inventory-section-title">
              <div>
                <div className="eyebrow">HOW THINGS CONNECT</div>
                <h2 id="attachment-title">UniFi attachment map</h2>
              </div>
              <small>Select a device to filter its clients</small>
            </div>
            <div className="inventory-topology">
              {roots.map((d) => (
                <DeviceBranch
                  key={d.id}
                  device={d}
                  devices={devices}
                  clients={clients}
                  selected={attachment}
                  onSelect={selectDevice}
                  ancestors={new Set()}
                />
              ))}
              {detached.map((d) => (
                <DeviceNode
                  key={d.id}
                  device={d}
                  count={clients.filter((c) => c.uplink_id === d.id).length}
                  selected={attachment === d.id}
                  onSelect={selectDevice}
                />
              ))}
              {!devices.length && (
                <p className="muted">
                  No adopted devices reported for this site.
                </p>
              )}
            </div>
            <p className="inventory-footnote">
              Links show UniFi-reported attachments. Client counts belong
              directly to each device. OPNsense remains the source for routed
              traffic; unmanaged devices and unknown attachments may be absent.
            </p>
          </section>
          <section className="inventory-panel" aria-labelledby="clients-title">
            <div className="inventory-section-title">
              <div>
                <div className="eyebrow">THE DEVICES USING YOUR NETWORK</div>
                <h2 id="clients-title">
                  Connected clients{" "}
                  <span className="muted">
                    {filtered.length} of {clients.length}
                  </span>
                </h2>
              </div>
              {(search || attachment || connection) && (
                <button
                  onClick={() => {
                    setSearch("");
                    setAttachment("");
                    setConnection("");
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>
            <div className="inventory-filters">
              <label className="inventory-search">
                <Search size={16} />
                <input
                  aria-label="Search inventory clients"
                  placeholder="Name, IP, MAC, or attached device"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
              <select
                aria-label="Filter clients by attached device"
                value={attachment}
                onChange={(e) => setAttachment(e.target.value)}
              >
                <option value="">All attachments</option>
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {name(d)}
                  </option>
                ))}
                <option value="unknown">Unknown attachment</option>
              </select>
              <select
                aria-label="Filter clients by connection"
                value={connection}
                onChange={(e) => setConnection(e.target.value)}
              >
                <option value="">All connections</option>
                {Array.from(new Set(clients.map((c) => c.type || "UNKNOWN")))
                  .sort()
                  .map((t) => (
                    <option key={t} value={t}>
                      {title(t)}
                    </option>
                  ))}
              </select>
            </div>
            <div className="inventory-table-wrap">
              <table className="inventory-table">
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>IP address</th>
                    <th>Connection</th>
                    <th>Attached to</th>
                    <th>Connected since</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered
                    .slice(safePage * 50, safePage * 50 + 50)
                    .map((c) => (
                      <tr key={c.id}>
                        <td>
                          <strong>{c.name || "Unnamed client"}</strong>
                          <code>{known(c.mac)}</code>
                        </td>
                        <td>
                          <code>{known(c.ip)}</code>
                        </td>
                        <td>
                          <span className="inventory-connection">
                            {c.type === "WIRELESS" ? (
                              <Wifi size={14} />
                            ) : (
                              <Cable size={14} />
                            )}
                            {title(c.type)}
                          </span>
                        </td>
                        <td>
                          {c.uplink_id && devicesById.has(c.uplink_id)
                            ? name(devicesById.get(c.uplink_id)!)
                            : "Unknown"}
                        </td>
                        <td title={c.connected_at || undefined}>
                          {c.connected_at
                            ? new Date(c.connected_at).toLocaleString(
                                undefined,
                                {
                                  month: "short",
                                  day: "numeric",
                                  hour: "numeric",
                                  minute: "2-digit",
                                },
                              )
                            : "Unknown"}
                        </td>
                      </tr>
                    ))}
                  {!filtered.length && (
                    <tr>
                      <td colSpan={5} className="inventory-empty">
                        {clients.length
                          ? "No clients match these filters."
                          : "No connected clients reported for this site."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {filtered.length > 50 && (
              <div className="inventory-pagination">
                <button
                  disabled={!safePage}
                  onClick={() => setPage(safePage - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {safePage + 1} of {Math.ceil(filtered.length / 50)}
                </span>
                <button
                  disabled={(safePage + 1) * 50 >= filtered.length}
                  onClick={() => setPage(safePage + 1)}
                >
                  Next
                </button>
              </div>
            )}
            <p className="inventory-footnote">
              Current attachments only. An IP address may change owners; this
              snapshot is not historical attribution. Missing addresses are
              shown as unknown.
            </p>
          </section>
          <section aria-labelledby="hardware-title">
            <div className="inventory-section-title">
              <div>
                <div className="eyebrow">SWITCHES & ACCESS POINTS</div>
                <h2 id="hardware-title">Hardware details</h2>
              </div>
              <small>Open a device for ports or radios</small>
            </div>
            <div className="inventory-hardware">
              {devices.map((d) => (
                <details className="inventory-device" key={d.id}>
                  <summary>
                    <span className="inventory-device-icon">
                      {d.kind === "ap" ? (
                        <Wifi size={20} />
                      ) : (
                        <Server size={20} />
                      )}
                    </span>
                    <span>
                      <strong>{name(d)}</strong>
                      <small>
                        {known(d.ip)} · {known(d.model)}
                      </small>
                    </span>
                    <span
                      className={`inventory-state ${d.state === "ONLINE" ? "allowed" : "blocked"}`}
                    >
                      {title(d.state)}
                    </span>
                    <ChevronRight size={16} />
                  </summary>
                  <div className="inventory-device-body">
                    {d.errors.length > 0 && (
                      <p className="inventory-inline-warning">
                        {d.errors.join(" ")}
                      </p>
                    )}
                    <dl className="inventory-telemetry">
                      <div>
                        <dt>CPU</dt>
                        <dd>
                          {d.cpu_pct === null ? "Unknown" : `${d.cpu_pct}%`}
                        </dd>
                      </div>
                      <div>
                        <dt>Memory</dt>
                        <dd>
                          {d.memory_pct === null
                            ? "Unknown"
                            : `${d.memory_pct}%`}
                        </dd>
                      </div>
                      <div>
                        <dt>Uptime</dt>
                        <dd>{duration(d.uptime_seconds)}</dd>
                      </div>
                      <div>
                        <dt>Heartbeat</dt>
                        <dd>{age(d.last_heartbeat, now)}</dd>
                      </div>
                      <div>
                        <dt>Firmware</dt>
                        <dd>{known(d.firmware)}</dd>
                      </div>
                      <div>
                        <dt>MAC</dt>
                        <dd>{known(d.mac)}</dd>
                      </div>
                    </dl>
                    {d.ports.length > 0 && (
                      <>
                        <h3>Switch ports</h3>
                        <div className="inventory-ports">
                          {d.ports.map((p, i) => (
                            <div
                              className={`inventory-port ${p.state === "UP" ? "port-up" : ""}`}
                              key={i}
                            >
                              <span>Port {known(p.index)}</span>
                              <strong>
                                {p.state === "UP"
                                  ? speed(p.speed_mbps)
                                  : title(p.state)}
                              </strong>
                              <small>PoE {title(p.poe_state)}</small>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                    {d.radios.length > 0 && (
                      <>
                        <h3>Wi-Fi radios</h3>
                        <div className="inventory-radios">
                          {d.radios.map((r, i) => (
                            <div key={i}>
                              <Wifi size={18} />
                              <strong>{known(r.band)} GHz</strong>
                              <span>Channel {known(r.channel)}</span>
                              <small>
                                {known(r.width_mhz)} MHz · {known(r.standard)}
                              </small>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </section>
          <div className="inventory-network-note">
            <Network size={16} />
            <span>
              Networks configured in UniFi:{" "}
              {snapshot.networks.length
                ? snapshot.networks
                    .map(
                      (n) =>
                        `${n.name || "Unnamed"} · VLAN ${known(n.vlan)}${n.enabled === false ? " (disabled)" : ""}`,
                    )
                    .join(" / ")
                : "None reported"}
              . This list covers the controller's configuration.
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function DeviceNode({
  device,
  count,
  selected,
  onSelect,
}: {
  device: Device;
  count: number;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      className={`inventory-node ${selected ? "selected" : ""}`}
      onClick={() => onSelect(device.id)}
      aria-pressed={selected}
      aria-label={`Show clients attached to ${name(device)}`}
    >
      <span className="inventory-node-icon">
        {device.kind === "ap" ? <Wifi size={23} /> : <Server size={23} />}
      </span>
      <span className="inventory-node-content">
        <strong>{name(device)}</strong>
        <small>{known(device.ip)}</small>
        <span>
          <i
            className={`status-dot ${device.state === "ONLINE" ? "good" : "quiet"}`}
          />
          {title(device.state)} <span className="muted">·</span> {count}{" "}
          {count === 1 ? "client" : "clients"}
        </span>
      </span>
    </button>
  );
}

function DeviceBranch({
  device,
  devices,
  clients,
  selected,
  onSelect,
  ancestors,
}: {
  device: Device;
  devices: Device[];
  clients: Client[];
  selected: string;
  onSelect: (id: string) => void;
  ancestors: Set<string>;
}) {
  const visited = new Set([...ancestors, device.id]);
  const children = devices.filter(
    (d) => d.uplink_id === device.id && !visited.has(d.id),
  );
  return (
    <div className="inventory-branch">
      <DeviceNode
        device={device}
        count={clients.filter((c) => c.uplink_id === device.id).length}
        selected={selected === device.id}
        onSelect={onSelect}
      />
      {children.length > 0 && (
        <div className="inventory-children">
          {children.map((d) => (
            <DeviceBranch
              key={d.id}
              device={d}
              devices={devices}
              clients={clients}
              selected={selected}
              onSelect={onSelect}
              ancestors={visited}
            />
          ))}
        </div>
      )}
    </div>
  );
}
