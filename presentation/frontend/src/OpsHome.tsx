import { ChevronRight, RefreshCw } from "lucide-react";
import type { Alerts, FreshnessState, OpsHome as OpsView } from "./types";

const count = (value: number | null | undefined) =>
  value == null ? "—" : new Intl.NumberFormat().format(value);
const formatBytes = (value: number) =>
  value >= 1e9
    ? `${(value / 1e9).toFixed(2)} GB`
    : value >= 1e6
      ? `${(value / 1e6).toFixed(1)} MB`
      : `${(value / 1e3).toFixed(1)} kB`;
const duration = (seconds: number) =>
  seconds < 60
    ? "Just now"
    : seconds < 3600
      ? `${Math.floor(seconds / 60)} min`
      : seconds < 86400
        ? `${Math.floor(seconds / 3600)} hr`
        : `${Math.floor(seconds / 86400)} d`;
const ageLabel = (seconds: number | null) => {
  if (seconds == null) return "No observation";
  if (seconds < 60) return "Just now";
  return `${duration(seconds)} old`;
};
const text = (value: string) => value || "—";
const port = (value: number | null) => (value == null ? "—" : String(value));

const FRESH_LABEL: Record<FreshnessState, string> = {
  fresh: "Fresh",
  info: "Lagging",
  warning: "Warning",
  critical: "Critical",
  unavailable: "Unavailable",
};
const GATEWAY_LABEL = {
  up: "Up",
  down: "Down",
  unknown: "Unknown",
  unavailable: "Unavailable",
};

export function OpsHome({
  data,
  alerts,
  window,
  loading,
  error,
  onWindow,
  onRefresh,
  onOpenAlerts,
}: {
  data: OpsView | null;
  alerts: Alerts | null;
  window: string;
  loading: boolean;
  error: string;
  onWindow: (value: string) => void;
  onRefresh: () => void;
  onOpenAlerts: () => void;
}) {
  const scope = data?.window.label || "Last hour";
  const wanAlerts = (alerts?.open ?? []).filter(
    (item) => item.rule === "gateway-down" || item.rule === "wan-ingress",
  );
  return (
    <div className="ops-home">
      <div className="toolbar">
        <div>
          <span className="eyebrow">DAILY OPERATIONS</span>
          <h1>Ops Home</h1>
        </div>
        <div className="tools">
          {data?.illustrative && <span className="demo-badge">DEMO DATA</span>}
          <label className="sr-only" htmlFor="ops-time-window">
            Operations time window
          </label>
          <select
            id="ops-time-window"
            value={window}
            onChange={(event) => onWindow(event.target.value)}
          >
            <option value="15m">Last 15 minutes</option>
            <option value="1h">Last hour</option>
          </select>
          <button
            className="icon-button"
            aria-label="Refresh operations view"
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
            ? "Getting the operations view…"
            : "No operations view yet. Retry to reconnect."}
        </div>
      ) : (
        <>
          {data.illustrative && (
            <p className="ops-illustrative">
              Illustrative demo data. These panels are not live telemetry.
            </p>
          )}
          <section className="ops-freshness" aria-label="Source freshness">
            <div className="ops-section-heading">
              <h2>Source freshness</h2>
              <p>
                Warning at about 15 minutes and critical at about 30 minutes,
                matching the alert checker. The heartbeat tile uses the 3 minute
                silence limit.
              </p>
            </div>
            <div className="ops-tiles">
              {data.freshness.map((item) => (
                <article
                  className={"ops-tile state-" + item.state}
                  key={item.id}
                  aria-label={`${item.title}: ${FRESH_LABEL[item.state]}`}
                >
                  <span className="ops-state">{FRESH_LABEL[item.state]}</span>
                  <strong>{item.title}</strong>
                  <small>{ageLabel(item.age_seconds)}</small>
                  <p>{item.note}</p>
                </article>
              ))}
            </div>
          </section>
          <section className="alerts-panel ops-alerts" aria-label="Open alerts">
            <div className="alerts-heading">
              <h2>Open alerts</h2>
              {alerts?.illustrative && <span>Illustrative</span>}
              {alerts?.checker === "silent" && <span>Checker silent</span>}
              {alerts?.checker === "unknown" && (
                <span>Checker status unknown</span>
              )}
              <button className="text-button" onClick={onOpenAlerts}>
                All alerts <ChevronRight size={14} />
              </button>
            </div>
            {!alerts ? (
              <p className="muted">Alert status is unavailable.</p>
            ) : alerts.open.length ? (
              alerts.open.slice(0, 3).map((item) => (
                <article className="alerts-row" key={item.fingerprint}>
                  <span className={"sev sev-" + item.severity}>
                    {item.severity}
                  </span>
                  <span className="alerts-rule">{item.rule}</span>
                  <span className="alerts-subject">{item.subject}</span>
                  <span className="alerts-age">
                    {duration(item.age_seconds)}
                  </span>
                  <span className="alerts-summary">{item.summary}</span>
                </article>
              ))
            ) : (
              <p className="muted">No open alerts</p>
            )}
          </section>
          <div className="ops-grid">
            <section className="ops-panel" aria-label="LAN talkers">
              <div className="ops-section-heading">
                <h2>Top LAN talkers</h2>
                <p>
                  {scope}
                  {data.talkers.state === "partial" ? " · Partial" : ""}
                </p>
              </div>
              {data.talkers.state === "unavailable" ||
              !data.talkers.rows.length ? (
                <p className="muted">{data.talkers.note}</p>
              ) : (
                <table aria-label="Top LAN talkers">
                  <thead>
                    <tr>
                      <th>Address</th>
                      <th>Bytes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.talkers.rows.map((row) => (
                      <tr key={row.ip}>
                        <td>{row.ip}</td>
                        <td>{formatBytes(row.bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {!!data.talkers.rows.length && (
                <p className="muted">{data.talkers.note}</p>
              )}
            </section>
            <section className="ops-panel" aria-label="Firewall blocks">
              <div className="ops-section-heading">
                <h2>Top firewall blocks</h2>
                <p>
                  {scope}
                  {data.blocks.state === "partial" ? " · Partial" : ""}
                </p>
              </div>
              {data.blocks.state === "unavailable" ||
              !data.blocks.rows.length ? (
                <p className="muted">{data.blocks.note}</p>
              ) : (
                <table aria-label="Top firewall blocks">
                  <thead>
                    <tr>
                      <th>Iface</th>
                      <th>Source</th>
                      <th>Destination</th>
                      <th>Port</th>
                      <th>Proto</th>
                      <th>Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.blocks.rows.map((row) => (
                      <tr
                        key={`${row.interface}|${row.source}|${row.destination}|${row.destination_port}|${row.protocol}`}
                      >
                        <td>{text(row.interface)}</td>
                        <td>{text(row.source)}</td>
                        <td>{text(row.destination)}</td>
                        <td>{port(row.destination_port)}</td>
                        <td>{text(row.protocol)}</td>
                        <td>{count(row.count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {!!data.blocks.rows.length && (
                <p className="muted">{data.blocks.note}</p>
              )}
            </section>
            <section className="ops-panel" aria-label="DNS activity">
              <div className="ops-section-heading">
                <h2>Top DNS</h2>
                <p>
                  {scope}
                  {data.dns.state === "partial" ? " · Partial" : ""}
                </p>
              </div>
              {data.dns.state === "unavailable" ? (
                <p className="muted">{data.dns.note}</p>
              ) : (
                <>
                  <h3>Domains</h3>
                  {data.dns.domains.length ? (
                    <table aria-label="Top DNS domains">
                      <thead>
                        <tr>
                          <th>Domain</th>
                          <th>Queries</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.dns.domains.map((row) => (
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
                  <h3>Clients</h3>
                  {data.dns.clients.length ? (
                    <table aria-label="Top DNS clients">
                      <thead>
                        <tr>
                          <th>Client</th>
                          <th>Queries</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.dns.clients.map((row) => (
                          <tr key={row.ip + row.name}>
                            <td>
                              {row.name ? `${row.name} · ${row.ip}` : row.ip}
                            </td>
                            <td>{count(row.queries)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="muted">No clients in this window.</p>
                  )}
                  <p className="muted">{data.dns.note}</p>
                </>
              )}
            </section>
            <section className="ops-panel" aria-label="WAN gateway">
              <div className="ops-section-heading">
                <h2>WAN gateway</h2>
                <p className={"ops-state gateway-" + data.gateway.state}>
                  {GATEWAY_LABEL[data.gateway.state]}
                </p>
              </div>
              <p>{data.gateway.summary}</p>
              {data.gateway.sample && (
                <p className="ops-sample">{data.gateway.sample}</p>
              )}
              {wanAlerts.length ? (
                <>
                  <h3>Related open alerts</h3>
                  {wanAlerts.map((item) => (
                    <article className="alerts-row" key={item.fingerprint}>
                      <span className={"sev sev-" + item.severity}>
                        {item.severity}
                      </span>
                      <span className="alerts-rule">{item.rule}</span>
                      <span className="alerts-subject">{item.subject}</span>
                      <span className="alerts-summary">{item.summary}</span>
                    </article>
                  ))}
                </>
              ) : (
                <p className="muted">
                  No open gateway-down or wan-ingress alerts.
                </p>
              )}
              <button className="text-button" onClick={onOpenAlerts}>
                Open alerts <ChevronRight size={14} />
              </button>
            </section>
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
