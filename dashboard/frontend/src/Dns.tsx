import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  Pause,
  Play,
  RefreshCw,
  Search,
  Shield,
  Users,
} from "lucide-react";

type Summary = {
  observed_at: string;
  queries: {
    total: number;
    blocked: number;
    cached: number;
    forwarded: number;
    percent_blocked: number | null;
    unique_domains: number | null;
  };
  clients: number | null;
  blocking: string;
  privacy_level: number | null;
  history: {
    timestamp: number;
    total: number;
    blocked: number;
    cached: number;
    forwarded: number;
  }[];
  top_domains: {
    permitted: { domain: string; count: number }[];
    blocked: { domain: string; count: number }[];
  };
  top_clients: { ip: string; name: string; count: number }[];
};
type Status = {
  state: string;
  stale: boolean;
  age_seconds: number | null;
  host: string;
  name: string;
  error: string | null;
  snapshot: Summary | null;
  archive: {
    since: string | null;
    through: string | null;
    lag_seconds: number | null;
    error: string | null;
    pending_records: number;
    retention_days: number;
  };
};
type QueryRow = {
  event_id: string;
  query_id: string;
  time: string;
  domain: string;
  client_ip: string;
  client_name: string;
  query_type: string;
  outcome: string;
  status: string;
  reply_type: string;
  upstream: string;
  dnssec: string;
};
type Queries = {
  queries: QueryRow[];
  capped: boolean;
  limit: number;
  as_of: string;
  window: string;
};
const count = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString();
const when = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "Waiting for collection";
async function get<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok)
    throw new Error(`Could not read DNS data (${response.status}).`);
  return response.json();
}
function useDnsStatus(live = true, refresh = 0) {
  const [data, setData] = useState<Status | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    const update = async () => {
      try {
        const result = await get<Status>("/api/dns", abort.signal);
        if (active) {
          setData(result);
          setError("");
        }
      } catch (e) {
        if (active && (e as Error).name !== "AbortError")
          setError((e as Error).message);
      } finally {
        if (active && live) timer = setTimeout(update, 15000);
      }
    };
    update();
    return () => {
      active = false;
      abort.abort();
      clearTimeout(timer);
    };
  }, [live, refresh]);
  return { data, error };
}

export function DnsHealth() {
  const { data, error } = useDnsStatus();
  return (
    <section className="health-card wide">
      <Database />
      <h2>DNS collection · Pi-hole</h2>
      {(error || data?.error || data?.archive.error) && (
        <p className="dns-warning" role="alert">
          {error || data?.error || data?.archive.error}
        </p>
      )}
      <dl>
        <dt>Source</dt>
        <dd>ns0 · 192.168.5.238 · local API</dd>
        <dt>Source status</dt>
        <dd>{data?.state || "Connecting"}</dd>
        <dt>Summary observed</dt>
        <dd>{when(data?.snapshot?.observed_at || null)}</dd>
        <dt>Archive begins</dt>
        <dd>{when(data?.archive.since || null)}</dd>
        <dt>Processed through</dt>
        <dd>{when(data?.archive.through || null)}</dd>
        <dt>Collection lag</dt>
        <dd>
          {data?.archive.lag_seconds == null
            ? "—"
            : `${data.archive.lag_seconds}s`}
        </dd>
      </dl>
      <p>
        Polls once a minute. Query collection trails the source by about one to
        two minutes. DNS records share the 30-day log retention.
      </p>
    </section>
  );
}

export function Dns({ onHealth }: { onHealth: (healthy: boolean) => void }) {
  const [live, setLive] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const { data, error } = useDnsStatus(live, refresh);
  const [windowValue, setWindow] = useState("15m");
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [outcome, setOutcome] = useState("");
  const [records, setRecords] = useState<Queries | null>(null);
  const [queryError, setQueryError] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => {
    onHealth(
      !!data &&
        !error &&
        data.state === "fresh" &&
        !data.archive.error &&
        (data.archive.lag_seconds || 0) < 180,
    );
  }, [data, error, onHealth]);
  useEffect(() => {
    setRecords(null);
    setQueryError("");
    setPage(0);
  }, [windowValue, term, outcome]);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    const update = async () => {
      try {
        const params = new URLSearchParams({
          window: windowValue,
          search: term,
          outcome,
        });
        const result = await get<Queries>(
          `/api/dns/queries?${params}`,
          abort.signal,
        );
        if (active) {
          setRecords(result);
          setQueryError("");
        }
      } catch (e) {
        if (active && (e as Error).name !== "AbortError")
          setQueryError((e as Error).message);
      } finally {
        if (active && live) timer = setTimeout(update, 15000);
      }
    };
    update();
    return () => {
      active = false;
      abort.abort();
      clearTimeout(timer);
    };
  }, [windowValue, term, outcome, live, refresh]);
  const snapshot = data?.snapshot;
  const pages = Math.max(1, Math.ceil((records?.queries.length || 0) / 50));
  const currentPage = Math.min(page, pages - 1);
  const chart = useMemo(() => {
    const rows = snapshot?.history || [];
    const max = Math.max(1, ...rows.map((r) => r.total || 0));
    return { rows, max };
  }, [snapshot]);
  const filter = (value: string) => {
    setSearch(value);
    setTerm(value);
  };
  return (
    <div className="dns-view">
      <section className="dns-source-bar" aria-label="DNS source status">
        <div>
          <span
            className={`status-dot ${data?.state === "fresh" && !error ? "good" : "quiet"}`}
          />
          <strong>Pi-hole</strong>
          <span>ns0 · 192.168.5.238</span>
          <span className="dns-source-state">
            {data?.state || "Connecting"}
            {!live ? " · display paused" : ""}
          </span>
        </div>
        <div className="toolbar">
          <button
            className={`live-button ${live ? "is-live" : ""}`}
            aria-pressed={live}
            onClick={() => setLive(!live)}
          >
            {live ? <Pause size={15} /> : <Play size={15} />}
            {live ? "Live" : "Paused"}
          </button>
          <button
            className="icon-button"
            aria-label="Refresh DNS now"
            onClick={() => setRefresh((n) => n + 1)}
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </section>
      {(error || data?.error) && (
        <div className="notice error" role="alert">
          {error || data?.error}{" "}
          {snapshot ? "The last successful snapshot is shown." : ""}
        </div>
      )}
      {data?.stale && snapshot && (
        <div className="notice">
          This DNS summary is stale. Last observed {when(snapshot.observed_at)}.
        </div>
      )}
      {data?.state === "disabled" && (
        <div className="notice">
          Pi-hole collection is disabled. Previously archived queries remain
          searchable.
        </div>
      )}
      {!snapshot && !error && !data?.error && (
        <div className="notice">Waiting for the first Pi-hole summary…</div>
      )}
      {snapshot && (
        <>
          <div className="dns-section-title">
            <h2>The last 24 hours</h2>
            <span>Pi-hole summary · observed {when(snapshot.observed_at)}</span>
          </div>
          <section
            className="metrics"
            aria-label="Pi-hole recent 24-hour summary"
          >
            <div className="metric">
              <span className="metric-label">
                <Activity size={16} />
                DNS queries
              </span>
              <strong>{count(snapshot.queries.total)}</strong>
              <small>
                {count(snapshot.queries.unique_domains)} distinct domains
              </small>
            </div>
            <div className="metric">
              <span className="metric-label">
                <Shield size={16} />
                Blocked queries
              </span>
              <strong>{count(snapshot.queries.blocked)}</strong>
              <small>
                {snapshot.queries.percent_blocked?.toFixed(1) || "0"}% · DNS
                filtering decisions
              </small>
            </div>
            <div className="metric">
              <span className="metric-label">
                <Users size={16} />
                Active clients
              </span>
              <strong>{count(snapshot.clients)}</strong>
              <small>As identified by Pi-hole</small>
            </div>
            <div className="metric">
              <span className="metric-label">
                <Database size={16} />
                From cache / local
              </span>
              <strong>{count(snapshot.queries.cached)}</strong>
              <small>
                {count(snapshot.queries.forwarded)} forwarded upstream
              </small>
            </div>
          </section>
          <section className="dns-chart-card">
            <div className="section-heading">
              <div>
                <h2>DNS activity</h2>
                <p>
                  Queries per 10-minute bucket · filtering {snapshot.blocking}
                </p>
              </div>
              <div className="dns-legend">
                <span>
                  <i />
                  Not reported blocked
                </span>
                <span>
                  <i className="blocked" />
                  Blocked
                </span>
              </div>
            </div>
            <svg
              className="dns-chart"
              viewBox="0 0 1000 165"
              role="img"
              aria-label="DNS query volume and blocked queries across the last 24 hours"
            >
              {[0, 1, 2].map((i) => (
                <line
                  key={i}
                  x1="0"
                  x2="1000"
                  y1={15 + i * 65}
                  y2={15 + i * 65}
                  className="dns-gridline"
                />
              ))}
              {chart.rows.map((r, i) => {
                const step = 1000 / chart.rows.length,
                  height = ((r.total || 0) / chart.max) * 140;
                const blockedHeight =
                  (Math.min(r.total || 0, r.blocked || 0) / chart.max) * 140;
                return (
                  <g key={r.timestamp}>
                    <title>
                      {new Date(r.timestamp * 1000).toLocaleString()} ·{" "}
                      {count(r.total)} queries · {count(r.blocked)} blocked
                    </title>
                    <rect
                      x={i * step + 1}
                      y={155 - height}
                      width={Math.max(1, step - 2)}
                      height={height}
                      fill="var(--allowed)"
                      opacity=".65"
                    />
                    <rect
                      x={i * step + 1}
                      y={155 - blockedHeight}
                      width={Math.max(1, step - 2)}
                      height={blockedHeight}
                      fill="var(--blocked)"
                    />
                  </g>
                );
              })}
            </svg>
            <div className="dns-chart-axis">
              <span>
                {chart.rows[0]
                  ? new Date(chart.rows[0].timestamp * 1000).toLocaleString(
                      [],
                      { weekday: "short", hour: "numeric", minute: "2-digit" },
                    )
                  : "No history"}
              </span>
              <span>Peak {count(chart.max)} queries / bucket</span>
              <span>
                {chart.rows.length
                  ? new Date(
                      chart.rows[chart.rows.length - 1].timestamp * 1000,
                    ).toLocaleTimeString([], {
                      hour: "numeric",
                      minute: "2-digit",
                    })
                  : ""}
              </span>
            </div>
          </section>
          <div className="dns-rankings">
            <Ranking
              title="Frequently blocked domains"
              items={snapshot.top_domains.blocked.map((r) => ({
                label: r.domain,
                value: r.domain,
                count: r.count,
              }))}
              blocked
              onChoose={(v) => {
                filter(v);
                setOutcome("blocked");
                setWindow("24h");
              }}
            />
            <Ranking
              title="Busiest clients"
              items={snapshot.top_clients.map((r) => ({
                label: r.name || r.ip,
                detail: r.name ? r.ip : undefined,
                value: r.ip,
                count: r.count,
              }))}
              onChoose={(v) => {
                filter(v);
                setOutcome("");
                setWindow("24h");
              }}
            />
          </div>
        </>
      )}
      <section className="events-panel dns-queries">
        <div className="section-heading">
          <div>
            <h2>
              DNS query archive{" "}
              <span className="count-badge">
                {count(records?.queries.length)}
              </span>
            </h2>
            <p>
              Recorded on AI-02 · 30-day retention · starts{" "}
              {when(data?.archive.since || null)}
            </p>
          </div>
          <label className="range-picker">
            <Clock3 size={16} />
            <select
              aria-label="DNS query time range"
              value={windowValue}
              onChange={(e) => setWindow(e.target.value)}
            >
              {[
                ["15m", "15 minutes"],
                ["1h", "1 hour"],
                ["6h", "6 hours"],
                ["24h", "24 hours"],
                ["7d", "7 days"],
                ["30d", "30 days"],
              ].map(([v, label]) => (
                <option key={v} value={v}>
                  Last {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {data?.archive.error && (
          <div className="notice error" role="alert">
            {data.archive.error} Archived data below remains available.
          </div>
        )}
        <p className="subnote">
          Processed through {when(data?.archive.through || null)}.{" "}
          {data?.archive.lag_seconds != null
            ? `${data.archive.lag_seconds}s behind the source clock. `
            : ""}
          Normally about one to two minutes behind. The cards above cover
          Pi-hole’s own recent history.
        </p>
        <form
          className="filters"
          onSubmit={(e) => {
            e.preventDefault();
            setTerm(search);
            setRefresh((n) => n + 1);
          }}
        >
          <label className="search-box">
            <Search size={16} />
            <input
              aria-label="Search DNS queries"
              placeholder="Domain, client name, or IP…"
              maxLength={160}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <select
            aria-label="DNS result"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
          >
            <option value="">All results</option>
            <option value="blocked">Blocked</option>
            <option value="cached">Cached</option>
            <option value="forwarded">Forwarded</option>
            <option value="other">Other / unresolved</option>
          </select>
          <button type="submit">Search queries</button>
          {(term || outcome) && (
            <button
              type="button"
              onClick={() => {
                filter("");
                setOutcome("");
              }}
            >
              Clear filters
            </button>
          )}
        </form>
        {queryError && (
          <div className="notice error" role="alert">
            {queryError}{" "}
            {records ? "Showing the previous successful result." : ""}
          </div>
        )}
        {records?.capped && (
          <p className="subnote">
            Newest {records.limit} intake records loaded; repeated receipts are
            collapsed. Narrow the range or search for older queries.
          </p>
        )}
        <div className="table-wrap">
          <table className="dns-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Client</th>
                <th>Domain</th>
                <th>Type</th>
                <th>Result</th>
                <th>Reply</th>
              </tr>
            </thead>
            <tbody>
              {records?.queries
                .slice(currentPage * 50, (currentPage + 1) * 50)
                .map((r) => (
                  <tr key={r.event_id}>
                    <td className="time-cell" title={when(r.time)}>
                      {new Date(r.time).toLocaleTimeString()}
                      <small>{new Date(r.time).toLocaleDateString()}</small>
                    </td>
                    <td>
                      <button
                        className="dns-text-button"
                        onClick={() => filter(r.client_ip)}
                      >
                        {r.client_name || r.client_ip || "Hidden"}
                      </button>
                      {r.client_name && <small>{r.client_ip}</small>}
                    </td>
                    <td className="dns-domain">
                      <button
                        className="dns-text-button"
                        onClick={() => filter(r.domain)}
                      >
                        {r.domain || "Hidden"}
                      </button>
                    </td>
                    <td>{r.query_type}</td>
                    <td>
                      <span className={`dns-result ${r.outcome}`}>
                        {r.outcome === "other" ? "Other" : r.outcome}
                      </span>
                      <small>{r.status}</small>
                    </td>
                    <td
                      title={`Upstream: ${r.upstream || "none reported"} · DNSSEC: ${r.dnssec || "unknown"} · Query ${r.query_id}`}
                    >
                      {r.reply_type || "—"}
                    </td>
                  </tr>
                ))}
              {!records?.queries.length && (
                <tr>
                  <td colSpan={6} className="empty">
                    {queryError
                      ? "DNS query search is unavailable."
                      : records
                        ? "No archived queries match this range and filter."
                        : "Reading the DNS archive…"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="pagination">
          <span>
            {count(records?.queries.length)} loaded queries
            {!live ? " · display paused" : ""}
          </span>
          <div>
            <button
              aria-label="Previous DNS page"
              disabled={currentPage === 0}
              onClick={() => setPage(currentPage - 1)}
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {" "}
              {currentPage + 1} / {pages}{" "}
            </span>
            <button
              aria-label="Next DNS page"
              disabled={currentPage >= pages - 1}
              onClick={() => setPage(currentPage + 1)}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </section>
      <p className="dns-scope">
        DNS queries show name lookups, including background activity. They do
        not prove a website visit or show every connection. Blocking is a
        Pi-hole or upstream DNS decision. Queries using other resolvers are
        outside this source. No DNS data is sent to Jev.
      </p>
    </div>
  );
}

function Ranking({
  title,
  items,
  blocked = false,
  onChoose,
}: {
  title: string;
  items: { label: string; detail?: string; value: string; count: number }[];
  blocked?: boolean;
  onChoose: (value: string) => void;
}) {
  const max = Math.max(1, ...items.map((r) => r.count || 0));
  return (
    <section className="dns-ranking">
      <h2>{title}</h2>
      <p>Pi-hole’s recent 24 hours · click to search the archive</p>
      <div>
        {items.map((r, i) => (
          <button
            key={`${r.value}-${i}`}
            onClick={() => onChoose(r.value)}
            className="dns-rank-row"
          >
            <span className="dns-rank-label">
              {r.label}
              {r.detail && <small>{r.detail}</small>}
            </span>
            <strong>{count(r.count)}</strong>
            <i
              className={blocked ? "blocked" : ""}
              style={{ width: `${((r.count || 0) / max) * 100}%` }}
            />
          </button>
        ))}
        {!items.length && <p className="empty">No entries reported.</p>}
      </div>
    </section>
  );
}
