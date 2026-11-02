import { RefreshCw } from "lucide-react";
import type { Destinations as DestinationsView } from "./types";

const count = (value: number | null | undefined) =>
  value == null ? "—" : new Intl.NumberFormat().format(value);
const when = (value: string | null) => {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export function Destinations({
  data,
  window,
  host,
  loading,
  error,
  onWindow,
  onHost,
  onRefresh,
}: {
  data: DestinationsView | null;
  window: string;
  host: string;
  loading: boolean;
  error: string;
  onWindow: (value: string) => void;
  onHost: (value: string) => void;
  onRefresh: () => void;
}) {
  const scope = data?.window.label || "Last 24 hours";
  const inventory = data?.inventory ?? [];
  return (
    <div className="ops-home dest-home">
      <div className="toolbar">
        <div>
          <span className="eyebrow">IOT AND STREAMING</span>
          <h1>DNS destinations</h1>
        </div>
        <div className="tools">
          {data?.illustrative && <span className="demo-badge">DEMO DATA</span>}
          <label className="sr-only" htmlFor="dest-host">
            Allowlisted host
          </label>
          <select
            id="dest-host"
            value={host}
            onChange={(event) => onHost(event.target.value)}
          >
            <option value="all">All allowlisted hosts</option>
            {inventory.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.ip}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="dest-time-window">
            DNS time window
          </label>
          <select
            id="dest-time-window"
            value={window}
            onChange={(event) => onWindow(event.target.value)}
          >
            <option value="1h">Last hour</option>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
          </select>
          <button
            className="icon-button"
            aria-label="Refresh DNS destinations"
            onClick={onRefresh}
          >
            <RefreshCw size={17} className={loading ? "spinning" : ""} />
          </button>
        </div>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          {error}
          <button onClick={onRefresh}>Retry</button>
        </div>
      )}
      {!data ? (
        <div className="loading-panel">
          {loading
            ? "Getting DNS destinations…"
            : "No DNS destinations yet. Retry to reconnect."}
        </div>
      ) : (
        <>
          {data.illustrative && (
            <p className="ops-illustrative">
              Illustrative domain counts. The host list is the checked-in
              allowlist, not live telemetry.
            </p>
          )}
          <p className="dest-scope">
            {scope}
            {data.deduped
              ? " · event id deduplicated"
              : " · stored receipts"} · {data.hosts.length} shown
          </p>
          <div className="dest-list">
            {data.hosts.map((item) => (
              <section
                className="ops-panel"
                key={item.id}
                aria-label={`${item.name} DNS destinations`}
              >
                <div className="ops-section-heading">
                  <h2>
                    {item.name} <span className="dest-class">{item.class}</span>
                  </h2>
                  <p>
                    {count(item.queries)} queries
                    {item.state === "partial" ? " · Partial" : ""}
                    {item.state === "unavailable" ? " · Unavailable" : ""}
                  </p>
                </div>
                <p className="dest-host-meta">
                  {item.ip} · {item.mac}
                  <br />
                  Matches {item.ip}
                  {item.dns_names.length
                    ? `, ${[item.name, ...item.dns_names.filter((name) => name !== item.name)].join(", ")}`
                    : ""}
                  <br />
                  First seen {when(item.first_seen)} · Last seen{" "}
                  {when(item.last_seen)}
                </p>
                {item.notes && <p className="dest-host-meta">{item.notes}</p>}
                {item.state === "unavailable" ? (
                  <p className="muted">{item.note}</p>
                ) : (
                  <div className="dest-split">
                    <div>
                      <h3>Sites</h3>
                      {item.sites.length ? (
                        <table aria-label={`${item.name} sites`}>
                          <thead>
                            <tr>
                              <th>Site</th>
                              <th>Queries</th>
                            </tr>
                          </thead>
                          <tbody>
                            {item.sites.map((row) => (
                              <tr key={row.name}>
                                <td>{row.name}</td>
                                <td>{count(row.queries)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <p className="muted">No sites in this window.</p>
                      )}
                    </div>
                    <div>
                      <h3>Domains</h3>
                      {item.domains.length ? (
                        <table aria-label={`${item.name} domains`}>
                          <thead>
                            <tr>
                              <th>Domain</th>
                              <th>Queries</th>
                            </tr>
                          </thead>
                          <tbody>
                            {item.domains.map((row) => (
                              <tr key={row.name}>
                                <td>{row.name}</td>
                                <td>{count(row.queries)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <p className="muted">No domains in this window.</p>
                      )}
                    </div>
                  </div>
                )}
                {item.state !== "unavailable" && (
                  <p className="muted">{item.note}</p>
                )}
              </section>
            ))}
          </div>
          <ul className="ops-notes">
            {data.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
