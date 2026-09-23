import { useEffect, useMemo, useState } from "react";
import { ChevronRight, Database, Network, Shield } from "lucide-react";
import { WorldMap } from "./WorldMap";
import type { DnsStatus } from "./Dns";
import type { InventoryResponse } from "./Inventory";
import type { FirewallEvent, Geo, Snapshot } from "./types";
import { devicesHash, dnsHash, firewallHash } from "./routes";

type Trend = {
  as_of: string;
  start: string;
  window: "24h";
  bucket_seconds: number;
  firewall: { time: string; count: number }[];
};
type Country = { code: string; name: string; count: number };
type Bin = { time: number; count: number };

const number = (value: number) => value.toLocaleString();
const age = (value: string | null | undefined, now: number) => {
  if (!value || !Number.isFinite(Date.parse(value))) return "Unknown";
  const seconds = Math.max(0, Math.floor((now - Date.parse(value)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
};
const windowLabel: Record<string, string> = {
  "5m": "5 minutes",
  "15m": "15 minutes",
  "1h": "1 hour",
  "6h": "6 hours",
  "24h": "24 hours",
  "7d": "7 days",
  "30d": "30 days",
};

async function get<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok)
    throw new Error(`Could not read ${url} (${response.status})`);
  return response.json();
}

function dnsBins(data: DnsStatus | null): Bin[] | null {
  const snapshot = data?.snapshot;
  if (!snapshot?.history.length) return null;
  const end = Date.parse(snapshot.observed_at);
  if (!Number.isFinite(end)) return null;
  const start = end - 86400000;
  const first = Math.floor(start / 3600000) * 3600000;
  const counts = new Map<number, number>();
  for (const row of snapshot.history) {
    const time = row.timestamp * 1000;
    if (!Number.isFinite(time) || time < start || time >= end) continue;
    const bucket = Math.floor(time / 3600000) * 3600000;
    counts.set(bucket, (counts.get(bucket) || 0) + (row.total || 0));
  }
  const bins: Bin[] = [];
  for (let time = first; time < end; time += 3600000)
    bins.push({ time, count: counts.get(time) || 0 });
  return bins;
}

function TimelineLane({
  label,
  source,
  bins,
  asOf,
}: {
  label: string;
  source: "firewall" | "dns";
  bins: Bin[] | null;
  asOf: string | null;
}) {
  const max = Math.max(1, ...(bins || []).map((bin) => bin.count));
  const total = bins?.reduce((sum, bin) => sum + bin.count, 0) || 0;
  return (
    <div className="overview-timeline-lane">
      <div className="overview-timeline-label">
        <strong>{label}</strong>
        <small>
          {asOf
            ? `Observed ${new Date(asOf).toLocaleTimeString()}`
            : "Unavailable"}
        </small>
      </div>
      {bins ? (
        <div
          className={`overview-hour-bars ${source}`}
          role="img"
          aria-label={`${number(total)} ${label.toLowerCase()} in hourly buckets over the past 24 hours`}
        >
          {bins.map((bin) => (
            <span
              key={bin.time}
              style={{
                height: `${(bin.count / max) * 100}%`,
                visibility: bin.count ? "visible" : "hidden",
              }}
              title={`${new Date(bin.time).toLocaleString()}: ${number(bin.count)}`}
            />
          ))}
        </div>
      ) : (
        <div className="overview-timeline-unavailable">
          No timeline available
        </div>
      )}
      <strong className="overview-timeline-total">
        {bins ? number(total) : "—"}
      </strong>
    </div>
  );
}

export function Overview({
  snapshot,
  firewallError,
  events,
  locations,
  countries,
  country,
  onCountry,
  windowValue,
  live,
  refresh,
  now,
  onNavigate,
}: {
  snapshot: Snapshot | null;
  firewallError: string;
  events: FirewallEvent[];
  locations: Record<string, Geo>;
  countries: Country[];
  country: string;
  onCountry: (value: string) => void;
  windowValue: string;
  live: boolean;
  refresh: number;
  now: number;
  onNavigate: (hash: string) => void;
}) {
  const [dns, setDns] = useState<DnsStatus | null>(null);
  const [dnsError, setDnsError] = useState(false);
  const [inventory, setInventory] = useState<InventoryResponse | null>(null);
  const [inventoryError, setInventoryError] = useState(false);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [trendError, setTrendError] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    async function update() {
      const [dnsResult, inventoryResult] = await Promise.allSettled([
        get<DnsStatus>("/api/dns", abort.signal),
        get<InventoryResponse>("/api/inventory", abort.signal),
      ]);
      if (!active) return;
      if (dnsResult.status === "fulfilled") {
        setDns(dnsResult.value);
        setDnsError(false);
      } else setDnsError(true);
      if (inventoryResult.status === "fulfilled") {
        setInventory(inventoryResult.value);
        setInventoryError(false);
      } else setInventoryError(true);
      if (live) timer = setTimeout(update, 15000);
    }
    update();
    return () => {
      active = false;
      abort.abort();
      clearTimeout(timer);
    };
  }, [live, refresh]);

  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    async function update() {
      try {
        const result = await get<Trend>("/api/overview/trend", abort.signal);
        if (active) {
          setTrend(result);
          setTrendError(false);
        }
      } catch {
        if (active) setTrendError(true);
      } finally {
        if (active && live) timer = setTimeout(update, 60000);
      }
    }
    update();
    return () => {
      active = false;
      abort.abort();
      clearTimeout(timer);
    };
  }, [live, refresh]);

  const dnsHistory = useMemo(() => dnsBins(dns), [dns]);
  const firewallHistory = useMemo(
    () =>
      trend?.firewall.map((bin) => ({
        time: Date.parse(bin.time),
        count: bin.count,
      })) || null,
    [trend],
  );
  const clients = inventory?.snapshot?.clients || [];
  const devices = inventory?.snapshot?.devices || [];
  const allowed = snapshot?.events.filter(
    (event) => event.action === "pass",
  ).length;
  const blocked = snapshot?.events.filter(
    (event) => event.action === "block",
  ).length;
  const dnsBlocked = dns?.snapshot?.queries.blocked;
  const dnsTotal = dns?.snapshot?.queries.total;
  const dnsPercent = dns?.snapshot?.queries.percent_blocked;
  const wireless = clients.filter(
    (client) => client.type === "WIRELESS",
  ).length;
  const wired = clients.filter((client) => client.type === "WIRED").length;
  const offline = devices.filter((device) => device.state === "OFFLINE").length;
  const dnsProblem =
    dnsError ||
    !dns ||
    dns.stale ||
    !!dns.error ||
    !!dns.archive.error ||
    dns.state !== "fresh";
  const inventoryProblem =
    inventoryError ||
    !inventory ||
    inventory.stale ||
    !!inventory.error ||
    (inventory.state !== "fresh" && inventory.state !== "partial");
  const problems = [
    ...(firewallError
      ? ["Firewall collector query failed; showing the last result."]
      : []),
    ...(dnsProblem && (dns || dnsError)
      ? [
          `Pi-hole collection: ${dnsError ? "status unavailable" : dns?.state}${dns?.archive.error ? " · archive needs review" : ""}.`,
        ]
      : []),
    ...(inventoryProblem && (inventory || inventoryError)
      ? [
          `UniFi inventory: ${inventoryError ? "status unavailable" : inventory?.state}.`,
        ]
      : []),
    ...(offline
      ? [`${offline} UniFi device${offline === 1 ? "" : "s"} reported offline.`]
      : []),
    ...(snapshot?.parse_errors
      ? [
          `${snapshot.parse_errors} loaded firewall record${snapshot.parse_errors === 1 ? "" : "s"} could not be parsed.`,
        ]
      : []),
    ...(snapshot && !snapshot.geoip.available
      ? ["The local location database is unavailable."]
      : []),
  ];

  return (
    <>
      <section className="overview-source-strip" aria-label="Source freshness">
        <div>
          <span className="overview-source-name">
            <Shield size={15} /> OPNsense
          </span>
          <strong>
            {firewallError
              ? "Query failed"
              : snapshot
                ? "Collector queried"
                : "Connecting"}
          </strong>
          <small>
            {snapshot?.last_event
              ? `Query ${age(snapshot.as_of, now)} · latest decision ${age(snapshot.last_event, now)}`
              : snapshot
                ? `Query ${age(snapshot.as_of, now)} · no decisions in this window`
                : "Waiting for firewall logs"}
          </small>
        </div>
        <div>
          <span className="overview-source-name">
            <Database size={15} /> Pi-hole
          </span>
          <strong>
            {dnsError ? "Status unavailable" : dns?.state || "Connecting"}
          </strong>
          <small>
            {dns?.archive.lag_seconds != null
              ? `Archive lag ${Math.round(dns.archive.lag_seconds / 60)}m`
              : dns?.snapshot
                ? `Summary ${age(dns.snapshot.observed_at, now)}`
                : "Waiting for source summary"}
          </small>
        </div>
        <div>
          <span className="overview-source-name">
            <Network size={15} /> UniFi
          </span>
          <strong>
            {inventoryError
              ? "Status unavailable"
              : inventory?.state || "Connecting"}
          </strong>
          <small>
            {inventory?.snapshot
              ? `Inventory ${age(inventory.snapshot.observed_at, now)}`
              : "Waiting for inventory"}
          </small>
        </div>
      </section>

      <section className="overview-summary" aria-label="Network summary">
        <div className="overview-summary-card">
          <button
            className="overview-summary-main"
            onClick={() => onNavigate(firewallHash(windowValue))}
          >
            <span>
              <Shield size={15} /> Firewall decisions <ChevronRight size={15} />
            </span>
            <strong>{snapshot ? number(snapshot.total) : "—"}</strong>
            <small>
              {firewallError
                ? "Last available result"
                : `Last ${windowLabel[windowValue]}`}{" "}
              · logged decisions
            </small>
          </button>
          <div className="overview-summary-links">
            <button
              onClick={() => onNavigate(firewallHash(windowValue, "pass"))}
            >
              {allowed == null ? "View allowed" : `${number(allowed)} allowed`}
            </button>
            <button
              onClick={() => onNavigate(firewallHash(windowValue, "block"))}
            >
              {blocked == null ? "View blocked" : `${number(blocked)} blocked`}
            </button>
          </div>
          {snapshot?.capped && (
            <small className="overview-scope">
              Action counts use the newest {number(snapshot.events.length)}{" "}
              records.
            </small>
          )}
        </div>
        <div className="overview-summary-card">
          <button
            className="overview-summary-main"
            onClick={() => onNavigate(dnsHash("24h"))}
          >
            <span>
              <Database size={15} /> DNS queries <ChevronRight size={15} />
            </span>
            <strong>{dnsTotal == null ? "—" : number(dnsTotal)}</strong>
            <small>
              {dnsError || dns?.stale
                ? "Last available Pi-hole summary"
                : "Pi-hole source summary"}{" "}
              · past 24 hours
            </small>
          </button>
          <div className="overview-summary-links">
            <button onClick={() => onNavigate(dnsHash("24h", "blocked"))}>
              {dnsBlocked == null
                ? "View blocked"
                : `${number(dnsBlocked)} blocked`}
              {dnsPercent != null ? ` · ${dnsPercent.toFixed(1)}%` : ""}
            </button>
          </div>
        </div>
        <div className="overview-summary-card">
          <button
            className="overview-summary-main"
            onClick={() => onNavigate(devicesHash(true))}
          >
            <span>
              <Network size={15} /> Connected clients <ChevronRight size={15} />
            </span>
            <strong>
              {inventory?.snapshot ? number(clients.length) : "—"}
            </strong>
            <small>
              {inventoryError || inventory?.stale
                ? "Last available UniFi inventory"
                : "Current UniFi inventory"}{" "}
              · {devices.filter((device) => device.state === "ONLINE").length}{" "}
              devices online
            </small>
          </button>
          <div className="overview-summary-links">
            <button onClick={() => onNavigate(devicesHash(true, "WIRELESS"))}>
              {number(wireless)} wireless
            </button>
            <button onClick={() => onNavigate(devicesHash(true, "WIRED"))}>
              {number(wired)} wired
            </button>
          </div>
        </div>
      </section>

      <div className="overview-hero">
        {snapshot ? (
          <WorldMap
            events={events}
            locations={locations}
            lab={snapshot.lab}
            selectedCountry={country}
            onCountry={onCountry}
            asOf={snapshot.as_of}
          />
        ) : (
          <div className="overview-map-unavailable" role="status">
            <Shield size={30} />
            <strong>Waiting for firewall activity</strong>
            <span>The globe will appear when the collector responds.</span>
          </div>
        )}
        <aside className="overview-signals" aria-label="Current source signals">
          <div className="overview-signals-heading">
            <h2>Current signals</h2>
            <p>Facts from the latest available snapshots</p>
          </div>
          {problems.length ? (
            <ul className="overview-problems">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          ) : (
            <p className="overview-no-problems">
              {snapshot && dns && inventory
                ? "No collection problems reported by the current snapshots."
                : "Checking the latest source status."}
            </p>
          )}
          <dl className="overview-signal-facts">
            <dt>Latest firewall decision</dt>
            <dd>{age(snapshot?.last_event, now)}</dd>
            <dt>DNS archive</dt>
            <dd>
              {dns?.archive.lag_seconds != null
                ? `${Math.round(dns.archive.lag_seconds / 60)}m behind`
                : "Unknown"}
            </dd>
            <dt>UniFi inventory</dt>
            <dd>{age(inventory?.snapshot?.observed_at, now)}</dd>
          </dl>
          <button
            className="text-button"
            onClick={() => onNavigate("#collection")}
          >
            Inspect collection <ChevronRight size={14} />
          </button>
        </aside>
      </div>

      {!!snapshot && (
        <div className="country-strip">
          <button
            className={!country ? "selected" : ""}
            onClick={() => onCountry("")}
          >
            All countries <span>{countries.length}</span>
          </button>
          {countries.slice(0, 7).map((item) => (
            <button
              key={item.code}
              className={country === item.code ? "selected" : ""}
              onClick={() => onCountry(item.code)}
            >
              {item.name}
              <span>{number(item.count)}</span>
            </button>
          ))}
          {countries.length > 7 && (
            <label className="country-more">
              <select
                aria-label="All observed countries"
                value={country}
                onChange={(event) => onCountry(event.target.value)}
              >
                <option value="">More countries…</option>
                {countries.map((item) => (
                  <option value={item.code} key={item.code}>
                    {item.name} ({number(item.count)})
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      <section
        className="overview-timeline"
        aria-label="Activity through the day"
      >
        <div className="overview-timeline-heading">
          <div>
            <h2>Activity through the day</h2>
            <p>Past 24 hours · hourly buckets · separate scales</p>
          </div>
          {trendError && (
            <span>
              Firewall timeline unavailable; previous result shown if available.
            </span>
          )}
        </div>
        <TimelineLane
          label="Firewall decisions"
          source="firewall"
          bins={firewallHistory}
          asOf={trend?.as_of || null}
        />
        <TimelineLane
          label="DNS queries"
          source="dns"
          bins={dnsHistory}
          asOf={dns?.snapshot?.observed_at || null}
        />
        <div className="overview-timeline-axis">
          <span>24h ago</span>
          <span>12h ago</span>
          <span>Now</span>
        </div>
        <p className="overview-timeline-note">
          Firewall counts cover logged decisions. DNS bars use Pi-hole history;
          source totals and archived query rows may differ.
        </p>
      </section>
    </>
  );
}
