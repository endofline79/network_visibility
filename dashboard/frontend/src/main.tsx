import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownLeft,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  Globe2,
  Layers,
  Pause,
  Play,
  Radar,
  RefreshCw,
  Search,
  Server,
  Shield,
  Sun,
  Moon,
  X,
  AlertCircle,
  ExternalLink,
  Sparkles,
  Network,
} from "lucide-react";
import { WorldMap } from "./WorldMap";
import { JevTrial } from "./JevTrial";
import { Inventory } from "./Inventory";
import { Dns, DnsHealth } from "./Dns";
import type { FirewallEvent, LogResponse, LogRow, Snapshot } from "./types";
import "./style.css";

const WINDOWS = [
  ["5m", "5 minutes"],
  ["15m", "15 minutes"],
  ["1h", "1 hour"],
  ["6h", "6 hours"],
  ["24h", "24 hours"],
  ["7d", "7 days"],
  ["30d", "30 days"],
];
const number = (n: number) => n.toLocaleString();
const stamp = (s: string) =>
  new Date(s).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
const clock = (s: string) => new Date(s).toLocaleTimeString();
const age = (s: string | null, now: number) => {
  if (!s) return "No events";
  const seconds = Math.max(0, Math.floor((now - Date.parse(s)) / 1000));
  return seconds < 60
    ? `${seconds}s ago`
    : seconds < 3600
      ? `${Math.floor(seconds / 60)}m ago`
      : `${Math.floor(seconds / 3600)}h ago`;
};
async function getJSON<T>(url: string, signal: AbortSignal): Promise<T> {
  const r = await fetch(url, { signal, cache: "no-store" });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(
      typeof e.detail === "string" ? e.detail : `Request failed (${r.status})`,
    );
  }
  return r.json();
}

function App() {
  const [view, setView] = useState<
    "overview" | "events" | "health" | "jev" | "inventory"
  >(
    ["#inventory", "#devices"].includes(window.location.hash)
      ? "inventory"
      : window.location.hash === "#jev"
        ? "jev"
        : window.location.hash.startsWith("#activity") ||
            window.location.hash === "#dns"
          ? "events"
          : window.location.hash === "#collection"
            ? "health"
            : "overview",
  );
  const [inventoryHealthy, setInventoryHealthy] = useState(false);
  const [dnsHealthy, setDnsHealthy] = useState(false);
  const [windowValue, setWindow] = useState("15m");
  const [data, setData] = useState<Snapshot | null>(null);
  const [rawData, setRawData] = useState<LogResponse | null>(null);
  const [error, setError] = useState("");
  const [rawError, setRawError] = useState("");
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [country, setCountry] = useState("");
  const [action, setAction] = useState("all");
  const [search, setSearch] = useState("");
  const [iface, setIface] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<FirewallEvent | LogRow | null>(null);
  const [eventMode, setEventMode] = useState<"firewall" | "system" | "dns">(
    ["#dns", "#activity/dns"].includes(window.location.hash)
      ? "dns"
      : window.location.hash === "#activity/logs"
        ? "system"
        : "firewall",
  );
  const dnsView = view === "events" && eventMode === "dns";
  const [rawSearch, setRawSearch] = useState("");
  const [rawQuery, setRawQuery] = useState("");
  const [application, setApplication] = useState("");
  const [rawPage, setRawPage] = useState(0);
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("visibility-theme") || "dark";
    } catch {
      return "dark";
    }
  });
  const detail = useRef<HTMLDialogElement>(null);
  const lastSnapshotRequest = useRef("");
  const lastRawRequest = useRef("");
  const lastRawScope = useRef("");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("visibility-theme", theme);
    } catch {}
  }, [theme]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (view === "jev" || view === "inventory" || dnsView) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    const key = `${windowValue}:${refresh}`;
    if (!live && lastSnapshotRequest.current === key && data) {
      setLoading(false);
      return;
    }
    lastSnapshotRequest.current = key;
    async function update() {
      setLoading(true);
      try {
        const d = await getJSON<Snapshot>(
          `/api/snapshot?window=${windowValue}`,
          controller.signal,
        );
        if (active) {
          setData(d);
          setError("");
        }
      } catch (e) {
        if (active && (e as Error).name !== "AbortError")
          setError((e as Error).message);
      } finally {
        if (active) {
          setLoading(false);
          if (live) timer = setTimeout(update, 10000);
        }
      }
    }
    update();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [windowValue, live, refresh, view, dnsView]);
  useEffect(() => {
    if (view !== "events" || eventMode !== "system") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    const scope = `${windowValue}:${rawQuery}:${application}`,
      key = `${scope}:${refresh}`;
    if (!live && lastRawRequest.current === key && rawData) return;
    lastRawRequest.current = key;
    async function update() {
      try {
        const query = new URLSearchParams({
          window: windowValue,
          search: rawQuery,
          application,
        });
        const d = await getJSON<LogResponse>(
          `/api/logs?${query}`,
          controller.signal,
        );
        if (active) {
          setRawData(d);
          setRawError("");
        }
      } catch (e) {
        if (active && (e as Error).name !== "AbortError")
          setRawError((e as Error).message);
      } finally {
        if (active && live) timer = setTimeout(update, 10000);
      }
    }
    if (lastRawScope.current !== scope) setRawData(null);
    lastRawScope.current = scope;
    update();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [view, eventMode, windowValue, rawQuery, application, live, refresh]);
  useEffect(() => {
    setPage(0);
  }, [country, action, search, iface, windowValue]);
  useEffect(() => {
    setRawPage(0);
  }, [rawQuery, application, windowValue]);
  useEffect(() => {
    if (selected && !detail.current?.open) detail.current?.showModal();
  }, [selected]);
  const events = data?.events || [];
  const locations = data?.locations || {};
  const filtered = useMemo(() => {
    const text = search.trim().toLowerCase();
    return events.filter(
      (e) =>
        (!country ||
          [e.source, e.destination].some(
            (ip) => locations[ip]?.country_code === country,
          )) &&
        (action === "all" || e.action === action) &&
        (!iface || e.interface === iface) &&
        (!text ||
          [
            e.source,
            e.destination,
            e.source_port,
            e.destination_port,
            e.protocol,
            e.rule,
            e.raw,
          ]
            .join(" ")
            .toLowerCase()
            .includes(text)),
    );
  }, [events, locations, country, action, search, iface]);
  const countries = useMemo(() => {
    const values = new Map<
      string,
      { code: string; name: string; count: number }
    >();
    for (const e of events) {
      const seen = new Set<string>();
      for (const ip of [e.source, e.destination]) {
        const g = locations[ip];
        if (!g || seen.has(g.country_code)) continue;
        seen.add(g.country_code);
        const c = values.get(g.country_code) || {
          code: g.country_code,
          name: g.country,
          count: 0,
        };
        c.count++;
        values.set(g.country_code, c);
      }
    }
    return [...values.values()].sort((a, b) => b.count - a.count);
  }, [events, locations]);
  const interfaces = [
    ...new Set(events.map((e) => e.interface).filter(Boolean)),
  ].sort();
  const pages = Math.max(1, Math.ceil(filtered.length / 50));
  const currentPage = Math.min(page, pages - 1);
  const currentRows = filtered.slice(currentPage * 50, (currentPage + 1) * 50);
  const rawCurrentPage = Math.min(
    rawPage,
    Math.max(0, Math.ceil((rawData?.logs.length || 0) / 50) - 1),
  );
  const applications = [
    ...new Set((data?.sources || []).map((s) => s.app_name)),
  ].sort();
  const healthy =
    !error &&
    !!data &&
    !!data.last_event &&
    now - Date.parse(data.last_event) < 120000;
  const coverage = data?.public_ips
    ? Math.round((Object.keys(locations).length / data.public_ips) * 100)
    : null;
  const selectedName =
    countries.find((c) => c.code === country)?.name || country;
  const closeDetail = () => {
    detail.current?.close();
    setSelected(null);
  };
  const resetFilters = () => {
    setCountry("");
    setAction("all");
    setSearch("");
    setIface("");
  };
  const pickIP = (ip: string) => {
    setSearch(ip);
    setCountry("");
  };
  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Visibility home">
          <span className="brand-mark">
            <Radar size={21} />
          </span>
          VISIBILITY<span className="brand-sub">HOMELAB</span>
        </a>
        <nav aria-label="Main navigation">
          {(["overview", "events", "inventory", "health", "jev"] as const).map(
            (v) => (
              <button
                key={v}
                className={view === v ? "active" : ""}
                onClick={() => {
                  setView(v);
                  history.replaceState(
                    null,
                    "",
                    v === "events"
                      ? `#activity/${eventMode === "system" ? "logs" : eventMode}`
                      : v === "inventory"
                        ? "#devices"
                        : v === "health"
                          ? "#collection"
                          : v === "jev"
                            ? "#jev"
                            : window.location.pathname,
                  );
                }}
                aria-current={view === v ? "page" : undefined}
              >
                {v === "overview" ? (
                  <Globe2 size={17} />
                ) : v === "events" ? (
                  <Layers size={17} />
                ) : v === "inventory" ? (
                  <Network size={17} />
                ) : v === "jev" ? (
                  <Sparkles size={17} />
                ) : (
                  <Activity size={17} />
                )}
                <span>
                  {v === "jev"
                    ? "Jev trial"
                    : v === "health"
                      ? "Collection"
                      : v === "events"
                        ? "Activity"
                        : v === "inventory"
                          ? "Devices"
                          : v[0].toUpperCase() + v.slice(1)}
                </span>
              </button>
            ),
          )}
        </nav>
        <div className="top-end">
          <span
            className={`status-dot ${(dnsView ? dnsHealthy : view === "inventory" ? inventoryHealthy : healthy) ? "good" : "quiet"}`}
          />
          <span className="host-name">AI-02</span>
          <button
            className="icon-button"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>
      <main>
        <div className="page-heading">
          <div>
            <div className="eyebrow">YOUR NETWORK, IN VIEW</div>
            <h1>
              {view === "overview"
                ? "Network activity"
                : view === "events"
                  ? "Explore network activity"
                  : view === "inventory"
                    ? "Meet your network"
                    : view === "jev"
                      ? "Understand your activity"
                      : "Collection health"}
            </h1>
            <p>
              {view === "inventory"
                ? "UniFi devices, connected clients, and the links between them"
                : view === "jev"
                  ? "Watch Jev classify fresh activity · bounded, metered experiments"
                  : view === "health"
                    ? "Source freshness, location coverage, and query status."
                    : view === "events"
                      ? "Firewall decisions, DNS queries, and device events"
                      : "OPNsense firewall logs · 30-day retention"}
            </p>
          </div>
          {!dnsView && view !== "jev" && view !== "inventory" && (
            <div className="toolbar">
              <label className="range-picker">
                <Clock3 size={16} />
                <select
                  aria-label="Time range"
                  value={windowValue}
                  onChange={(e) => {
                    setWindow(e.target.value);
                    setData(null);
                    setSelected(null);
                  }}
                >
                  {WINDOWS.map(([v, label]) => (
                    <option key={v} value={v}>
                      Last {label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className={`live-button ${live ? "is-live" : ""}`}
                onClick={() => setLive(!live)}
                aria-pressed={live}
              >
                {live ? <Pause size={15} /> : <Play size={15} />}{" "}
                {live ? "Live" : "Paused"}
              </button>
              <button
                className="icon-button"
                aria-label="Refresh now"
                onClick={() => setRefresh((n) => n + 1)}
                disabled={loading}
              >
                <RefreshCw size={16} className={loading ? "spinning" : ""} />
              </button>
            </div>
          )}
        </div>
        {view === "events" && (
          <div className="activity-tabs segmented" aria-label="Activity type">
            {(
              [
                ["firewall", "Firewall"],
                ["dns", "DNS"],
                ["system", "All logs"],
              ] as const
            ).map(([mode, label]) => (
              <button
                key={mode}
                aria-pressed={eventMode === mode}
                onClick={() => {
                  setEventMode(mode);
                  history.replaceState(
                    null,
                    "",
                    `#activity/${mode === "system" ? "logs" : mode}`,
                  );
                }}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        {dnsView && <Dns onHealth={setDnsHealthy} />}
        {view === "jev" && <JevTrial onInspect={setSelected} />}
        {view === "inventory" && <Inventory onHealth={setInventoryHealthy} />}
        {!dnsView && view !== "jev" && view !== "inventory" && error && (
          <div className="notice error" role="alert">
            <AlertCircle size={18} />
            <span>
              {error} {data ? "Showing the last successful result." : ""}
            </span>
          </div>
        )}
        {!dnsView &&
          view !== "jev" &&
          view !== "inventory" &&
          data &&
          data.capped && (
            <div className="notice">
              <Layers size={17} />
              <span>
                Showing the newest <strong>{number(events.length)}</strong> of{" "}
                {number(data.total)} firewall events in this window. Map,
                filters, and breakdowns use these loaded events. Narrow the time
                range for fuller detail.
              </span>
            </div>
          )}
        {!dnsView &&
          view !== "jev" &&
          view !== "inventory" &&
          data &&
          data.parse_errors > 0 && (
            <div className="notice">
              <AlertCircle size={17} />
              {data.parse_errors} records could not be parsed. Their original
              messages remain available in the event table.
            </div>
          )}
        {!dnsView &&
          view !== "jev" &&
          view !== "inventory" &&
          !data &&
          !error && (
            <div className="loading-state">
              <Radar className="spinning" size={32} />
              <h2>Reading your network logs…</h2>
              <p>Connecting to the collector on AI-02</p>
            </div>
          )}
        {!dnsView && view !== "jev" && view !== "inventory" && data && (
          <>
            {view === "overview" && (
              <>
                <section className="metrics" aria-label="Loaded event summary">
                  <Metric
                    icon={<Layers />}
                    label="Loaded events"
                    value={number(events.length)}
                    note={`${number(data.total)} in selected window`}
                  />
                  <Metric
                    icon={<Shield />}
                    label="Allowed / blocked"
                    value={`${number(events.filter((e) => e.action === "pass").length)} / ${number(events.filter((e) => e.action === "block").length)}`}
                    note="Logged firewall decisions"
                  />
                  <Metric
                    icon={<Globe2 />}
                    label="Countries observed"
                    value={number(countries.length)}
                    note={
                      coverage === null
                        ? "No public endpoints"
                        : `${coverage}% of public IPs located`
                    }
                  />
                  <Metric
                    icon={<Activity />}
                    label="Latest firewall event"
                    value={age(data.last_event, now)}
                    note={
                      live
                        ? "Refreshing every 10 seconds"
                        : "Display updates paused"
                    }
                  />
                </section>
                <WorldMap
                  events={filtered}
                  locations={locations}
                  lab={data.lab}
                  selectedCountry={country}
                  onCountry={setCountry}
                  asOf={data.as_of}
                />
                <div className="country-strip">
                  <button
                    className={!country ? "selected" : ""}
                    onClick={() => setCountry("")}
                  >
                    All countries <span>{countries.length}</span>
                  </button>
                  {countries.slice(0, 7).map((c) => (
                    <button
                      key={c.code}
                      className={country === c.code ? "selected" : ""}
                      onClick={() => setCountry(c.code)}
                    >
                      {c.name}
                      <span>{number(c.count)}</span>
                    </button>
                  ))}
                  {countries.length > 7 && (
                    <label className="country-more">
                      <select
                        aria-label="All observed countries"
                        value={country}
                        onChange={(e) => setCountry(e.target.value)}
                      >
                        <option value="">More countries…</option>
                        {countries.map((c) => (
                          <option value={c.code} key={c.code}>
                            {c.name} ({number(c.count)})
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
                {!data.geoip.available && (
                  <div className="notice">
                    The local location database is unavailable. Logs are still
                    searchable; geographic points will appear when it is
                    restored.
                  </div>
                )}
                <ActivityStrip
                  events={filtered}
                  from={data.oldest_event}
                  to={data.as_of}
                />
              </>
            )}
            {view !== "health" && (
              <section className="event-section">
                <div className="section-heading">
                  <div>
                    <h2>
                      {view === "events"
                        ? "Collected events"
                        : "Firewall events"}{" "}
                      <span className="muted">
                        /{" "}
                        {number(
                          view === "events" && eventMode === "system"
                            ? rawData?.logs.length || 0
                            : filtered.length,
                        )}
                      </span>
                    </h2>
                    <p>
                      {view === "events" && eventMode === "system"
                        ? "All collected applications · server-side message search"
                        : `${country ? selectedName : "All countries"} · ${action === "all" ? "All actions" : action === "pass" ? "Allowed" : "Blocked"} · ${number(filtered.length)} matching loaded events`}
                    </p>
                  </div>
                </div>
                {!(view === "events" && eventMode === "system") ? (
                  <>
                    <div className="filters">
                      <label className="search-box">
                        <Search size={16} />
                        <input
                          aria-label="Filter loaded firewall events"
                          placeholder="Search IP, port, protocol, rule…"
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                        {search && (
                          <button
                            className="input-clear"
                            aria-label="Clear search"
                            onClick={() => setSearch("")}
                          >
                            <X size={14} />
                          </button>
                        )}
                      </label>
                      <select
                        aria-label="Firewall action"
                        value={action}
                        onChange={(e) => setAction(e.target.value)}
                      >
                        <option value="all">All actions</option>
                        <option value="pass">Allowed</option>
                        <option value="block">Blocked</option>
                      </select>
                      <select
                        aria-label="Interface"
                        value={iface}
                        onChange={(e) => setIface(e.target.value)}
                      >
                        <option value="">All interfaces</option>
                        {interfaces.map((i) => (
                          <option key={i}>{i}</option>
                        ))}
                      </select>
                      {view === "events" && (
                        <select
                          aria-label="Country"
                          value={country}
                          onChange={(e) => setCountry(e.target.value)}
                        >
                          <option value="">All countries</option>
                          {countries.map((c) => (
                            <option value={c.code} key={c.code}>
                              {c.name}
                            </option>
                          ))}
                        </select>
                      )}
                      {(country || action !== "all" || search || iface) && (
                        <button className="text-button" onClick={resetFilters}>
                          Clear filters
                        </button>
                      )}
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Time</th>
                            <th>Action</th>
                            <th>Source</th>
                            <th>Destination</th>
                            <th>Protocol / port</th>
                            <th>Interface</th>
                            <th>
                              <span className="sr-only">Details</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {currentRows.map((e, i) => (
                            <tr key={`${e.id}-${i}`}>
                              <td className="time-cell" title={stamp(e.time)}>
                                {clock(e.time)}
                              </td>
                              <td>
                                <Action
                                  action={e.action}
                                  error={!!e.parse_error}
                                />
                              </td>
                              <td>
                                <Address
                                  ip={e.source}
                                  local={e.source_local}
                                  location={locations[e.source]}
                                  onClick={pickIP}
                                />
                              </td>
                              <td>
                                <Address
                                  ip={e.destination}
                                  local={e.destination_local}
                                  location={locations[e.destination]}
                                  onClick={pickIP}
                                />
                              </td>
                              <td>
                                <span className="protocol">
                                  {e.protocol || "—"}
                                </span>
                                {e.destination_port !== null && (
                                  <span className="port">
                                    {" "}
                                    :{e.destination_port}
                                  </span>
                                )}
                              </td>
                              <td>
                                <span className="interface">
                                  {e.interface || "—"}
                                </span>
                              </td>
                              <td>
                                <button
                                  className="row-detail"
                                  aria-label={`Inspect event ${i + 1}`}
                                  onClick={() => setSelected(e)}
                                >
                                  <ChevronRight size={17} />
                                </button>
                              </td>
                            </tr>
                          ))}
                          {!currentRows.length && (
                            <tr>
                              <td colSpan={7} className="empty">
                                No events match these filters. Try another time
                                range or clear the filters.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    <Pagination
                      page={currentPage}
                      pages={pages}
                      total={filtered.length}
                      onPage={setPage}
                    />
                  </>
                ) : (
                  <>
                    <form
                      className="filters"
                      onSubmit={(e) => {
                        e.preventDefault();
                        setRawQuery(rawSearch);
                        setRefresh((n) => n + 1);
                      }}
                    >
                      <label className="search-box">
                        <Search size={16} />
                        <input
                          aria-label="Search all log messages"
                          placeholder="Search message text…"
                          maxLength={160}
                          value={rawSearch}
                          onChange={(e) => setRawSearch(e.target.value)}
                        />
                      </label>
                      <select
                        aria-label="Application"
                        value={application}
                        onChange={(e) => setApplication(e.target.value)}
                      >
                        <option value="">All applications</option>
                        {applications.map((a) => (
                          <option key={a}>{a}</option>
                        ))}
                      </select>
                      <button type="submit">Search logs</button>
                    </form>
                    {rawError && (
                      <div className="notice error" role="alert">
                        {rawError}
                      </div>
                    )}
                    {rawData?.capped && (
                      <p className="subnote">
                        Newest {rawData.limit} matching records shown. Narrow
                        the range or search to see more specific events.
                      </p>
                    )}
                    <div className="table-wrap">
                      <table className="raw-table">
                        <thead>
                          <tr>
                            <th>Time</th>
                            <th>Source / application</th>
                            <th>Message</th>
                            <th>
                              <span className="sr-only">Details</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {rawData?.logs
                            .slice(
                              rawCurrentPage * 50,
                              (rawCurrentPage + 1) * 50,
                            )
                            .map((e, i) => (
                              <tr key={`${e.time}-${i}`}>
                                <td className="time-cell">{clock(e.time)}</td>
                                <td>
                                  {e.application || "syslog"}
                                  <small>{e.hostname || e.source}</small>
                                </td>
                                <td className="message-cell">
                                  <span>{e.message}</span>
                                </td>
                                <td>
                                  <button
                                    className="row-detail"
                                    aria-label={`Inspect log ${i + 1}`}
                                    onClick={() => setSelected(e)}
                                  >
                                    <ChevronRight size={17} />
                                  </button>
                                </td>
                              </tr>
                            ))}
                          {!rawData?.logs.length && (
                            <tr>
                              <td colSpan={4} className="empty">
                                {rawData
                                  ? "No log messages matched."
                                  : rawError
                                    ? "Could not load logs."
                                    : "Loading collected logs…"}
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    <Pagination
                      page={rawCurrentPage}
                      pages={Math.max(
                        1,
                        Math.ceil((rawData?.logs.length || 0) / 50),
                      )}
                      total={rawData?.logs.length || 0}
                      onPage={setRawPage}
                    />
                  </>
                )}
              </section>
            )}
            {view === "health" && (
              <div className="health-grid">
                <DnsHealth />
                <section className="health-card">
                  <Database />
                  <h2>Collector connection</h2>
                  <dl>
                    <dt>Last successful query</dt>
                    <dd>{stamp(data.as_of)}</dd>
                    <dt>Query duration</dt>
                    <dd>{data.query_ms} ms</dd>
                    <dt>Latest firewall event</dt>
                    <dd>
                      {data.last_event
                        ? stamp(data.last_event)
                        : "None in this window"}
                    </dd>
                    <dt>Loaded / matching events</dt>
                    <dd>
                      {number(events.length)} / {number(data.total)}
                    </dd>
                    <dt>Parsing failures</dt>
                    <dd>{number(data.parse_errors)}</dd>
                    <dt>Retention</dt>
                    <dd>30 days</dd>
                  </dl>
                </section>
                <section className="health-card">
                  <Globe2 />
                  <h2>Local location database</h2>
                  <dl>
                    <dt>Provider</dt>
                    <dd>
                      <a
                        href="https://db-ip.com"
                        target="_blank"
                        rel="noreferrer"
                      >
                        DB-IP Lite
                      </a>
                    </dd>
                    <dt>Status</dt>
                    <dd>
                      {data.geoip.available ? "Available" : "Unavailable"}
                    </dd>
                    <dt>Database built</dt>
                    <dd>
                      {data.geoip.build_time
                        ? new Date(data.geoip.build_time).toLocaleDateString()
                        : "—"}
                    </dd>
                    <dt>Age</dt>
                    <dd>
                      {data.geoip.age_days === undefined
                        ? "—"
                        : `${data.geoip.age_days} days`}
                      {(data.geoip.age_days || 0) > 45
                        ? " · update recommended"
                        : ""}
                    </dd>
                    <dt>Public IPs located</dt>
                    <dd>
                      {number(Object.keys(locations).length)} /{" "}
                      {number(data.public_ips)}
                    </dd>
                    <dt>Unlocated public IPs</dt>
                    <dd>{number(data.unlocated_public_ips)}</dd>
                    <dt>Lab anchor</dt>
                    <dd>{data.lab?.label || "Not configured"}</dd>
                  </dl>
                  <p>
                    Lookups happen on AI-02. Observed IP addresses are not sent
                    to a location service.
                  </p>
                </section>
                <section className="health-card wide">
                  <Server />
                  <h2>Sources reporting in the last 5 minutes</h2>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Hostname</th>
                          <th>Application</th>
                          <th>Events</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.sources.map((s) => (
                          <tr key={`${s.hostname}:${s.app_name}`}>
                            <td>{s.hostname || "Unknown"}</td>
                            <td>{s.app_name || "syslog"}</td>
                            <td>{number(Number(s.events))}</td>
                          </tr>
                        ))}
                        {!data.sources.length && (
                          <tr>
                            <td colSpan={3}>
                              No sources reported in the last 5 minutes.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
                <section className="health-card wide">
                  <h2>What this view observes</h2>
                  <p>
                    Existing OPNsense logging decisions. Counts describe log
                    records, not bytes or active connections. Unlogged traffic
                    and traffic that stays within a switched LAN are outside
                    this view. Locations are approximate; connection lines do
                    not describe packet routes.
                  </p>
                  <p>
                    Local networks:{" "}
                    <code>{data.local_networks.join(", ")}</code>. Firewall
                    directions are relative to the interface that logged the
                    event.
                  </p>
                </section>
              </div>
            )}
          </>
        )}
        <footer className="footer">
          <span>
            <span
              className={`status-dot ${(dnsView ? dnsHealthy : view === "inventory" ? inventoryHealthy : healthy) ? "good" : "quiet"}`}
            />
            {dnsView
              ? "Local DNS activity · Pi-hole"
              : view === "inventory"
                ? "Local UniFi inventory · read-only collection"
                : view === "jev"
                  ? "Jev experiment · automatic and manual batches"
                  : data
                    ? `Updated ${age(data.as_of, now)}${live ? "" : " · paused"}`
                    : error
                      ? "Collector unavailable"
                      : "Connecting"}
            {!dnsView &&
            view !== "inventory" &&
            view !== "jev" &&
            loading &&
            data
              ? " · refreshing"
              : ""}
          </span>
          {dnsView ? (
            <span>Local collection · No AI requests</span>
          ) : view === "inventory" ? (
            <span>Current inventory · Identifiers remain on AI-02</span>
          ) : (
            <span>
              Logged activity · Approximate locations ·{" "}
              <a href="https://db-ip.com" target="_blank" rel="noreferrer">
                IP Geolocation by DB-IP
              </a>{" "}
              ·{" "}
              <a
                href="https://www.naturalearthdata.com"
                target="_blank"
                rel="noreferrer"
              >
                Natural Earth
              </a>
            </span>
          )}
        </footer>
      </main>
      <dialog
        ref={detail}
        className="detail-dialog"
        onCancel={() => setSelected(null)}
        onClick={(e) => {
          if (e.target === detail.current) closeDetail();
        }}
      >
        {selected && (
          <>
            <div className="section-heading">
              <div>
                <div className="eyebrow">EVENT DETAILS</div>
                <h2>
                  {"raw" in selected
                    ? "Firewall decision"
                    : selected.application || "System log"}
                </h2>
                <p>{stamp(selected.time)}</p>
              </div>
              <button
                className="icon-button"
                onClick={closeDetail}
                aria-label="Close event details"
              >
                <X size={20} />
              </button>
            </div>
            {"raw" in selected ? (
              <>
                <dl className="detail-fields">
                  {Object.entries({
                    Action: selected.action,
                    Source: `${selected.source}${selected.source_port !== null ? " :" + selected.source_port : ""}`,
                    Destination: `${selected.destination}${selected.destination_port !== null ? " :" + selected.destination_port : ""}`,
                    Protocol: selected.protocol,
                    Interface: selected.interface,
                    "Interface direction": selected.direction,
                    Rule: selected.rule,
                    Reason: selected.reason,
                    "Logged packet bytes": selected.packet_bytes,
                    Host: selected.hostname,
                  }).map(([k, v]) => (
                    <React.Fragment key={k}>
                      <dt>{k}</dt>
                      <dd>{String(v ?? "—")}</dd>
                    </React.Fragment>
                  ))}
                </dl>
                {selected.parse_error && (
                  <div className="notice">{selected.parse_error}</div>
                )}
                <h3>Original message</h3>
                <pre>{selected.raw}</pre>
              </>
            ) : (
              <>
                <p>
                  {selected.hostname} · {selected.source}
                </p>
                <h3>Original message</h3>
                <pre>{selected.message}</pre>
              </>
            )}
          </>
        )}
      </dialog>
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  note,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="metric">
      <div className="metric-label">
        {icon}
        {label}
      </div>
      <div className="metric-value">{value}</div>
      <p>{note}</p>
    </div>
  );
}
function Action({ action, error }: { action: string; error: boolean }) {
  return (
    <span
      className={`action ${action === "pass" ? "allowed" : action === "block" ? "blocked" : ""}`}
    >
      {error ? (
        <AlertCircle size={13} />
      ) : action === "pass" ? (
        <Check size={13} />
      ) : action === "block" ? (
        <Shield size={13} />
      ) : null}
      {error
        ? "Unparsed"
        : action === "pass"
          ? "Allowed"
          : action === "block"
            ? "Blocked"
            : action}
    </span>
  );
}
function Address({
  ip,
  local,
  location,
  onClick,
}: {
  ip: string;
  local: boolean;
  location?: Snapshot["locations"][string];
  onClick: (ip: string) => void;
}) {
  return (
    <div className="address">
      <button onClick={() => onClick(ip)} disabled={!ip}>
        {ip || "—"}
      </button>
      <small>
        {local
          ? "Local device"
          : location
            ? `${location.city ? location.city + ", " : ""}${location.country}`
            : "Non-public / unlocated"}
      </small>
    </div>
  );
}
function Pagination({
  page,
  pages,
  total,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  onPage: (n: number) => void;
}) {
  const current = Math.min(page, pages - 1);
  return (
    <div className="pagination">
      <span>
        {total
          ? `${number(current * 50 + 1)}–${number(Math.min((current + 1) * 50, total))} of ${number(total)}`
          : "0 events"}
      </span>
      <div>
        <button
          aria-label="Previous page"
          disabled={current === 0}
          onClick={() => onPage(current - 1)}
        >
          <ChevronLeft size={16} />
        </button>
        <span>
          {current + 1} / {pages}
        </span>
        <button
          aria-label="Next page"
          disabled={current >= pages - 1}
          onClick={() => onPage(current + 1)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
function ActivityStrip({
  events,
  from,
  to,
}: {
  events: FirewallEvent[];
  from: string | null;
  to: string;
}) {
  const end = Date.parse(to),
    start = from ? Date.parse(from) : end - 900000,
    span = Math.max(end - start, 1000),
    bins = Array.from({ length: 60 }, () => ({ pass: 0, block: 0, other: 0 }));
  for (const e of events) {
    const index = Math.max(
      0,
      Math.min(59, Math.floor(((Date.parse(e.time) - start) / span) * 60)),
    );
    if (!Number.isFinite(index)) continue;
    const k =
      e.action === "pass" ? "pass" : e.action === "block" ? "block" : "other";
    bins[index][k]++;
  }
  const max = Math.max(1, ...bins.map((b) => b.pass + b.block + b.other));
  return (
    <section
      className="activity-strip"
      aria-label="Loaded event activity over time"
    >
      <div className="activity-heading">
        <span>
          <Activity size={15} />
          Loaded event activity
        </span>
        <small>
          {from ? clock(from) : "—"} — {clock(to)} · peak {max} events / bucket
        </small>
      </div>
      <div
        className="activity-bars"
        role="img"
        aria-label={`${events.length} loaded firewall records, peak ${max} per time bucket`}
      >
        {bins.map((b, i) => (
          <div
            key={i}
            className="activity-bin"
            title={`${b.pass} allowed, ${b.block} blocked, ${b.other} other`}
          >
            <i
              className="bar-other"
              style={{ height: `${(b.other / max) * 100}%` }}
            />
            <i
              className="bar-blocked"
              style={{ height: `${(b.block / max) * 100}%` }}
            />
            <i
              className="bar-allowed"
              style={{ height: `${(b.pass / max) * 100}%` }}
            />
          </div>
        ))}
      </div>
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
