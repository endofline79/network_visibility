import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Home,
  Map as MapIcon,
  ShieldCheck,
  Monitor,
  Activity,
  Radio,
  ArrowUpRight,
  ChevronRight,
  Wifi,
  X,
  RefreshCw,
  Eye,
  Clock,
  Router,
  Search,
  Menu,
  Database,
  AlertTriangle,
  Bell,
  Gauge,
} from "lucide-react";
import { Destinations } from "./Destinations";
import { OpsHome } from "./OpsHome";
import { WorldView } from "./WorldView";
import type {
  Alerts,
  Destinations as DestinationsView,
  OpsHome as OpsView,
  Overview,
} from "./types";
import "./style.css";
import "./dashboard.css";
const count = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat().format(v);
const bytes = (v: number | null | undefined) =>
  v == null
    ? "Unavailable"
    : v >= 1e9
      ? `${(v / 1e9).toFixed(2)} GB`
      : v >= 1e6
        ? `${(v / 1e6).toFixed(1)} MB`
        : `${(v / 1e3).toFixed(1)} kB`;
const age = (t: string | null) => {
  if (!t) return "No observation";
  const s = Math.max(0, Math.floor((Date.now() - Date.parse(t)) / 1000));
  return s < 60
    ? "Just now"
    : s < 3600
      ? `${Math.floor(s / 60)} min ago`
      : `${Math.floor(s / 3600)} hr ago`;
};
const duration = (seconds: number) =>
  seconds < 60
    ? "Just now"
    : seconds < 3600
      ? `${Math.floor(seconds / 60)} min`
      : seconds < 86400
        ? `${Math.floor(seconds / 3600)} hr`
        : `${Math.floor(seconds / 86400)} d`;
const flag = (code: string) =>
  /^[A-Z]{2}$/.test(code)
    ? String.fromCodePoint(...[...code].map((x) => x.charCodeAt(0) + 127397))
    : "◌";
function App() {
  const [needsLogin, setNeedsLogin] = useState(false),
    [loginError, setLoginError] = useState("");
  const [data, setData] = useState<Overview | null>(null),
    [alerts, setAlerts] = useState<Alerts | null>(null),
    [window, setWindow] = useState("1h"),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [selected, setSelected] = useState(""),
    [drawer, setDrawer] = useState(""),
    [search, setSearch] = useState("");
  const [scenario, setScenario] = useState("normal");
  const [view, setView] = useState<"home" | "ops" | "destinations">("home");
  const [ops, setOps] = useState<OpsView | null>(null),
    [opsWindow, setOpsWindow] = useState("1h"),
    [opsError, setOpsError] = useState(""),
    [opsLoading, setOpsLoading] = useState(false);
  const [destinations, setDestinations] = useState<DestinationsView | null>(
      null,
    ),
    [destWindow, setDestWindow] = useState("24h"),
    [destHost, setDestHost] = useState("all"),
    [destError, setDestError] = useState(""),
    [destLoading, setDestLoading] = useState(false);
  const requireLogin = useCallback(() => setNeedsLogin(true), []);
  const abort = useRef<AbortController | null>(null),
    opsAbort = useRef<AbortController | null>(null),
    destAbort = useRef<AbortController | null>(null),
    dialog = useRef<HTMLDialogElement>(null),
    opener = useRef<HTMLElement | null>(null);
  const refresh = useCallback(async () => {
    abort.current?.abort();
    const c = new AbortController();
    abort.current = c;
    const alertsPromise = fetch("/api/alerts", {
      signal: c.signal,
      cache: "no-store",
    })
      .then(async (r) => {
        if (r.status === 401) return { unauthorized: true as const };
        if (!r.ok) return { failed: true as const };
        return { body: (await r.json()) as Alerts };
      })
      .catch(() => ({ failed: true as const }));
    try {
      const r = await fetch(
        `/api/overview?window=${window}&scenario=${scenario}`,
        { signal: c.signal, cache: "no-store" },
      );
      const alertsResult = await alertsPromise;
      if (
        r.status === 401 ||
        ("unauthorized" in alertsResult && alertsResult.unauthorized)
      ) {
        setNeedsLogin(true);
        return;
      }
      if (!r.ok) throw Error();
      setNeedsLogin(false);
      setData(await r.json());
      setError("");
      const nextAlerts = "body" in alertsResult ? alertsResult.body : null;
      setAlerts(nextAlerts ?? null);
    } catch (e) {
      if (!c.signal.aborted)
        setError(
          "Updates are unavailable. Your last view is preserved; its timestamp has not changed.",
        );
    } finally {
      if (!c.signal.aborted) setLoading(false);
    }
  }, [window, scenario]);
  const refreshOps = useCallback(async () => {
    opsAbort.current?.abort();
    const c = new AbortController();
    opsAbort.current = c;
    try {
      const r = await fetch(
        `/api/ops?window=${opsWindow}&scenario=${scenario}`,
        { signal: c.signal, cache: "no-store" },
      );
      if (r.status === 401) {
        setNeedsLogin(true);
        return;
      }
      if (!r.ok) throw Error();
      setNeedsLogin(false);
      setOps((await r.json()) as OpsView);
      setOpsError("");
    } catch {
      if (!c.signal.aborted)
        setOpsError(
          "The operations view is unavailable. Your last view is preserved.",
        );
    } finally {
      if (!c.signal.aborted) setOpsLoading(false);
    }
  }, [opsWindow, scenario]);
  const refreshDestinations = useCallback(async () => {
    destAbort.current?.abort();
    const c = new AbortController();
    destAbort.current = c;
    try {
      const r = await fetch(
        `/api/destinations?window=${destWindow}&host=${encodeURIComponent(destHost)}&scenario=${scenario}`,
        { signal: c.signal, cache: "no-store" },
      );
      if (r.status === 401) {
        setNeedsLogin(true);
        return;
      }
      if (!r.ok) throw Error();
      setNeedsLogin(false);
      setDestinations((await r.json()) as DestinationsView);
      setDestError("");
    } catch {
      if (!c.signal.aborted)
        setDestError(
          "DNS destinations are unavailable. Your last view is preserved.",
        );
    } finally {
      if (!c.signal.aborted) setDestLoading(false);
    }
  }, [destWindow, destHost, scenario]);
  useEffect(() => {
    setLoading(true);
    refresh();
    const id = setInterval(() => {
      if (!document.hidden) refresh();
    }, 30000);
    const show = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", show);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", show);
      abort.current?.abort();
    };
  }, [refresh]);
  useEffect(() => {
    if (view !== "ops") return;
    setOpsLoading(true);
    refreshOps();
    const id = setInterval(() => {
      if (!document.hidden) refreshOps();
    }, 30000);
    const show = () => {
      if (!document.hidden) refreshOps();
    };
    document.addEventListener("visibilitychange", show);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", show);
      opsAbort.current?.abort();
    };
  }, [view, refreshOps]);
  useEffect(() => {
    if (view !== "destinations") return;
    setDestLoading(true);
    refreshDestinations();
    const id = setInterval(() => {
      if (!document.hidden) refreshDestinations();
    }, 30000);
    const show = () => {
      if (!document.hidden) refreshDestinations();
    };
    document.addEventListener("visibilitychange", show);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", show);
      destAbort.current?.abort();
    };
  }, [view, refreshDestinations]);
  useEffect(() => {
    if (drawer) {
      opener.current = document.activeElement as HTMLElement;
      dialog.current?.showModal();
    } else {
      dialog.current?.close();
      opener.current?.focus();
    }
  }, [drawer]);
  const open = (v: string) => {
    setSearch("");
    setDrawer(v);
  };
  const country = data?.countries.find((c) => c.code === selected);
  const coverageProblems = data
    ? ["inventory", "router", "dns", "capture", "firewall"].filter((id) => {
        const source = data.sources.find((s) => s.id === id);
        return (
          !source ||
          (source.state !== "fresh" &&
            !(id !== "router" && source.state === "quiet"))
        );
      })
    : [];
  const fresh = !!data && coverageProblems.length === 0;
  const alertProblems = (alerts?.open ?? []).filter(
    (item) => item.severity !== "info",
  ).length;
  const attention = Math.max(
    data?.metrics.attention ?? 0,
    coverageProblems.length,
    alertProblems,
  );
  const scope = data?.window.label || "Last hour";
  if (needsLogin)
    return (
      <div className="login-screen">
        <form
          className="panel"
          onSubmit={async (e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            try {
              const r = await fetch("/api/session/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  username: f.get("username"),
                  password: f.get("password"),
                }),
              });
              if (!r.ok) throw Error();
              setLoginError("");
              setNeedsLogin(false);
              refresh();
            } catch {
              setLoginError(
                "Sign-in failed. Check your details, or wait a minute before trying again.",
              );
            }
          }}
        >
          <span className="brand-icon">
            <Home />
          </span>
          <h1>Welcome to My Network</h1>
          <p>Your private view of home.</p>
          <label>
            Username
            <input
              name="username"
              autoComplete="username"
              required
              maxLength={80}
            />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={512}
            />
          </label>
          {loginError && <p role="alert">{loginError}</p>}
          <button type="submit">Sign in</button>
        </form>
      </div>
    );
  return (
    <div className="dashboard-shell">
      <header>
        <div className="brand">
          <span className="brand-icon">
            <Home size={23} />
          </span>{" "}
          My Network <span className="brand-sub">VISIBILITY</span>
        </div>
        <div className="header-right">
          <span>A clearer view of home</span>
          <span className="header-clock">
            {new Date().toLocaleDateString(undefined, {
              weekday: "short",
              month: "short",
              day: "numeric",
            })}
          </span>
          <i className={fresh && !error ? "dot" : "dot amber"} />
          {data?.mode === "live" && (
            <button
              onClick={async () => {
                await fetch("/api/session/logout", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: "{}",
                });
                setData(null);
                setNeedsLogin(true);
              }}
            >
              Sign out
            </button>
          )}
        </div>
      </header>
      <aside className="sidebar">
        <nav aria-label="Main navigation">
          <button
            className={view === "home" && !drawer ? "active" : ""}
            onClick={() => {
              setView("home");
              setDrawer("");
            }}
          >
            <Home />
            Home
          </button>
          <button
            className={view === "ops" && !drawer ? "active" : ""}
            onClick={() => {
              setView("ops");
              setDrawer("");
            }}
          >
            <Gauge />
            Ops
          </button>
          <button
            className={view === "destinations" && !drawer ? "active" : ""}
            onClick={() => {
              setView("destinations");
              setDrawer("");
            }}
          >
            <Radio />
            Destinations
          </button>
          <button
            className={drawer === "Devices" ? "active" : ""}
            onClick={() => open("Devices")}
          >
            <Monitor />
            Devices
          </button>
          <button
            className={drawer === "Coverage" ? "active" : ""}
            onClick={() => open("Coverage")}
          >
            <ShieldCheck />
            Coverage
          </button>
          <button
            className={"nav-alerts" + (drawer === "Alerts" ? " active" : "")}
            onClick={() => open("Alerts")}
          >
            <Bell />
            Alerts
          </button>
        </nav>
        <div className="sidebar-bottom">
          <span>
            <i className={fresh && !error ? "dot" : "dot amber"} />
            {data?.mode === "demo"
              ? "Demo preview"
              : fresh && !error
                ? "Receiving data"
                : "Check updates"}
          </span>
          <p>
            {data?.mode === "demo"
              ? "Illustrative data. Explore the design."
              : "A view of what your network reports."}
          </p>
          {data?.mode === "demo" && (
            <div className="demo-controls">
              <label htmlFor="demo-state">Preview state</label>
              <select
                id="demo-state"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                <option value="normal">Normal</option>
                <option value="stale">Delayed data</option>
                <option value="unavailable">Unavailable sources</option>
                <option value="error">API error</option>
              </select>
              <span>
                Demo values are illustrative and never mixed with live
                telemetry.
              </span>
            </div>
          )}
        </div>
      </aside>
      <main>
        {view === "ops" ? (
          <OpsHome
            data={ops}
            alerts={alerts}
            window={opsWindow}
            loading={opsLoading}
            error={opsError}
            onWindow={setOpsWindow}
            onRefresh={() => {
              setOpsLoading(true);
              refresh();
              refreshOps();
            }}
            onOpenAlerts={() => open("Alerts")}
          />
        ) : view === "destinations" ? (
          <Destinations
            data={destinations}
            window={destWindow}
            host={destHost}
            loading={destLoading}
            error={destError}
            onWindow={setDestWindow}
            onHost={setDestHost}
            onRefresh={() => {
              setDestLoading(true);
              refreshDestinations();
            }}
          />
        ) : (
          <>
            <div className="toolbar">
              <div>
                <span className="eyebrow">HOME OVERVIEW</span>
                <h1>Your network, at a glance.</h1>
              </div>
              <div className="tools">
                {data?.mode === "demo" && (
                  <span className="demo-badge">DEMO DATA</span>
                )}
                <label className="sr-only" htmlFor="time-window">
                  Time window
                </label>
                <select
                  id="time-window"
                  value={window}
                  onChange={(e) => setWindow(e.target.value)}
                >
                  <option value="15m">Last 15 minutes</option>
                  <option value="1h">Last hour</option>
                  <option value="24h">Last 24 hours</option>
                </select>
                <button
                  className="icon-button"
                  aria-label="Refresh data"
                  onClick={refresh}
                >
                  <RefreshCw size={17} className={loading ? "spinning" : ""} />
                </button>
              </div>
            </div>
            {error && (
              <div className="error-banner" role="alert">
                <AlertTriangle size={17} />
                {error}
                <button onClick={refresh}>Retry</button>
              </div>
            )}
            {!data ? (
              <div className="loading-panel">
                {loading
                  ? "Getting your network view…"
                  : "No data available. Retry to reconnect."}
              </div>
            ) : (
              <>
                <section className="metrics" aria-label="Network summary">
                  <button
                    className="metric green"
                    onClick={() => open("Devices")}
                  >
                    <span className="metric-icon">
                      <Monitor />
                    </span>
                    <div>
                      <span className="metric-label">Devices seen</span>
                      <strong>{count(data.metrics.devices)}</strong>
                      <small>
                        {count(data.metrics.infrastructure)} network devices ·
                        latest view
                      </small>
                    </div>
                    <ChevronRight className="card-arrow" size={16} />
                  </button>
                  <button
                    className="metric gold"
                    onClick={() => open("Kitchen activity")}
                  >
                    <span className="metric-icon">
                      <Activity />
                    </span>
                    <div>
                      <span className="metric-label">
                        Most active in Kitchen
                      </span>
                      <strong className="device-name">
                        {data.metrics.busiest?.name || "Not available"}
                      </strong>
                      <small>
                        {data.metrics.busiest
                          ? bytes(data.metrics.busiest.bytes) +
                            " · recent sample"
                          : "Waiting for identified traffic"}
                      </small>
                    </div>
                    <ChevronRight className="card-arrow" size={16} />
                  </button>
                  <button
                    className="metric cyan"
                    onClick={() => open("Destinations")}
                  >
                    <span className="metric-icon">
                      <MapIcon />
                    </span>
                    <div>
                      <span className="metric-label">Destinations seen</span>
                      <strong>{count(data.metrics.destinations)}</strong>
                      <small>Public endpoints · {scope.toLowerCase()}</small>
                    </div>
                    <ChevronRight className="card-arrow" size={16} />
                  </button>
                  <button
                    className={"metric " + (attention ? "gold" : "green")}
                    onClick={() => open("Alerts")}
                  >
                    <span className="metric-icon">
                      <ShieldCheck />
                    </span>
                    <div>
                      <span className="metric-label">Needs attention</span>
                      <strong>{attention}</strong>
                      <small>
                        {attention
                          ? "Monitoring updates to review"
                          : "No monitoring alerts"}
                      </small>
                    </div>
                    <ChevronRight className="card-arrow" size={16} />
                  </button>
                </section>
                <section className="alerts-panel" aria-label="Alerts">
                  <div className="alerts-heading">
                    <h2>Alerts</h2>
                    {alerts?.illustrative && <span>Illustrative</span>}
                    {alerts?.checker === "silent" && (
                      <span>Checker silent</span>
                    )}
                    {alerts?.checker === "unknown" && (
                      <span>Checker status unknown</span>
                    )}
                    <button
                      className="text-button"
                      onClick={() => open("Alerts")}
                    >
                      All <ChevronRight size={14} />
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
                  {!!alerts?.resolved.length && (
                    <details className="alerts-resolved">
                      <summary>
                        Recently resolved ({alerts.resolved.length})
                      </summary>
                      {alerts.resolved.slice(0, 3).map((item) => (
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
                      ))}
                    </details>
                  )}
                </section>
                <WorldView
                  data={data}
                  scenario={scenario}
                  onLoginRequired={requireLogin}
                  summarySelected={selected}
                  onSummarySelect={setSelected}
                  onExplore={() => open("Destinations")}
                  activity={
                    <div className="panel happening">
                      <div className="panel-title">
                        <div className="title-with-icon">
                          <span className="small-icon">
                            <Activity />
                          </span>
                          <div>
                            <h2>What's happening</h2>
                            <p>Different views of the same network</p>
                          </div>
                        </div>
                        <button
                          className="text-button"
                          onClick={() => open("Coverage")}
                        >
                          Details <ChevronRight size={16} />
                        </button>
                      </div>
                      <div className="activity-cards">
                        {[
                          {
                            title: "Router traffic",
                            value: bytes(data.metrics.router_bytes),
                            sub: "Observed IP bytes",
                            icon: Router,
                            tone: "green",
                            view: "Router traffic",
                          },
                          {
                            title: "Kitchen traffic",
                            value: bytes(data.metrics.capture_bytes),
                            sub: "Observed frame bytes",
                            icon: Wifi,
                            tone: "cyan",
                            view: "Kitchen activity",
                          },
                          {
                            title: "DNS requests",
                            value: count(data.metrics.dns_queries),
                            sub: "Seen by Pi-hole",
                            icon: Search,
                            tone: "gold",
                            view: "DNS activity",
                          },
                          {
                            title: "Filtered DNS",
                            value: count(data.metrics.dns_blocked),
                            sub: "Requests blocked",
                            icon: ShieldCheck,
                            tone: "purple",
                            view: "DNS activity",
                          },
                        ].map((c) => (
                          <button
                            key={c.title}
                            className={"activity-card " + c.tone}
                            onClick={() => open(c.view)}
                          >
                            <span className="metric-icon">
                              <c.icon size={23} />
                            </span>
                            <span>{c.title}</span>
                            <strong>{c.value}</strong>
                            <small>{c.sub}</small>
                            <span className="accent-line" />
                          </button>
                        ))}
                      </div>
                    </div>
                  }
                >
                  <section
                    className="pane-section feed"
                    aria-labelledby="recent-activity-heading"
                  >
                    <h3 id="recent-activity-heading">Recent activity</h3>
                    <p className="muted">
                      Observed events · {scope.toLowerCase()}
                    </p>
                    {data.recent.length ? (
                      data.recent.map((e) => (
                        <div className="feed-item" key={e.id}>
                          <span className="small-icon">
                            <Radio size={19} />
                          </span>
                          <div>
                            <p>{e.text}</p>
                            <small>
                              {age(e.time)} · {e.source}
                            </small>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="empty">No recent events in this window.</p>
                    )}
                  </section>
                </WorldView>

                <footer>
                  <span>
                    <Clock size={13} />{" "}
                    {data.mode === "demo"
                      ? "Illustrative preview"
                      : `Updated ${age(data.as_of)}`}{" "}
                    · Summary every 30 sec · Near-live map about every 10 sec
                  </span>
                  <button onClick={() => open("Coverage")}>
                    What can Visibility see? <ArrowUpRight size={13} />
                  </button>
                  <span className="credits">
                    Map: Natural Earth · Locations: {data.geo.provider}
                  </span>
                </footer>
              </>
            )}
          </>
        )}
      </main>
      <dialog
        ref={dialog}
        onCancel={() => setDrawer("")}
        onClick={(e) => {
          if (e.target === dialog.current) setDrawer("");
        }}
      >
        <div className="drawer">
          <div className="drawer-heading">
            <div>
              <span className="eyebrow">A CLOSER LOOK</span>
              <h2>{drawer}</h2>
            </div>
            <button
              className="icon-button"
              aria-label="Close details"
              onClick={() => setDrawer("")}
            >
              <X />
            </button>
          </div>
          {data && (
            <>
              {drawer === "Alerts" && (
                <>
                  <p>
                    Open alerts from the checker, plus alerts that resolved in
                    the last day. Info stays on this console. Warning and
                    critical alerts can also notify the configured assistant.
                  </p>
                  {alerts?.illustrative && (
                    <p className="muted">
                      Illustrative demo alerts. They are not live telemetry.
                    </p>
                  )}
                  {alerts?.checker === "silent" && (
                    <p>
                      The alert checker heartbeat is missing or stale, so a
                      silence alert is shown here.
                    </p>
                  )}
                  {alerts?.checker === "unknown" && (
                    <p>
                      The checker heartbeat could not be read. Existing alerts
                      are still listed.
                    </p>
                  )}
                  {!alerts ? (
                    <p>Alert status is unavailable.</p>
                  ) : (
                    <>
                      <h3>Open</h3>
                      {alerts.open.length ? (
                        alerts.open.map((item) => (
                          <div className="detail-card" key={item.fingerprint}>
                            <Bell />
                            <div>
                              <strong>
                                {item.severity} · {item.rule}
                              </strong>
                              <p>
                                {item.subject} · {item.summary}
                              </p>
                              <small>
                                Open {duration(item.age_seconds)} ·{" "}
                                {item.evidence_query}
                              </small>
                            </div>
                          </div>
                        ))
                      ) : (
                        <p>No open alerts</p>
                      )}
                      <h3>Recently resolved</h3>
                      {alerts.resolved.length ? (
                        alerts.resolved.map((item) => (
                          <div className="detail-card" key={item.fingerprint}>
                            <Bell />
                            <div>
                              <strong>
                                {item.severity} · {item.rule}
                              </strong>
                              <p>
                                {item.subject} · {item.summary}
                              </p>
                              <small>
                                Resolved {duration(item.age_seconds)}
                              </small>
                            </div>
                          </div>
                        ))
                      ) : (
                        <p className="muted">None in the last day.</p>
                      )}
                    </>
                  )}
                </>
              )}
              {drawer === "Devices" && (
                <>
                  <p className="muted">
                    Latest UniFi observation. A missing device is not
                    necessarily offline.
                  </p>
                  <input
                    aria-label="Search devices"
                    placeholder="Find a device…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  {data.devices
                    .filter((d) =>
                      (d.name + d.ip)
                        .toLowerCase()
                        .includes(search.toLowerCase()),
                    )
                    .map((d) => (
                      <div className="detail-card" key={d.id}>
                        <Monitor />
                        <div>
                          <strong>{d.name || "Unnamed device"}</strong>
                          <p>
                            {d.attachment || "Attachment unknown"} · {d.type}
                          </p>
                          <small>
                            {d.ip} · {age(d.observed_at)}
                          </small>
                        </div>
                      </div>
                    ))}
                </>
              )}
              {drawer === "Coverage" && (
                <>
                  <p>
                    Visibility reports what its sources observed. It cannot
                    certify that every device, connection or packet was seen.
                  </p>
                  {data.sources.map((s) => (
                    <div className="source-row" key={s.id}>
                      <div>
                        <strong>{s.title}</strong>
                        <p>{s.note}</p>
                        <small>
                          {s.observed_at
                            ? new Date(s.observed_at).toLocaleString()
                            : "No observation available"}
                        </small>
                      </div>
                      <span className={"source-state " + s.state}>
                        {s.state}
                      </span>
                    </div>
                  ))}
                  <h3>What this view covers</h3>
                  <ul>
                    {data.coverage.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                  {data.issues.length > 0 && (
                    <>
                      <h3>Data quality</h3>
                      <ul>
                        {data.issues.map((c) => (
                          <li key={c}>{c}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  <p className="muted">
                    Geography: {data.geo.provider}.{" "}
                    {data.geo.age_days === null
                      ? "Database age unavailable."
                      : `Database age: ${data.geo.age_days} days.`}{" "}
                    Arcs are relationships, not physical routes.
                  </p>
                </>
              )}
              {drawer === "Destinations" && (
                <>
                  <p>
                    Distinct public IP endpoints in routed observations.
                    Approximate geography does not identify a person,
                    application or physical packet route.
                  </p>
                  <p className="muted">
                    {data.window.start} → {data.window.end}
                  </p>
                  {data.countries
                    .filter((c) => !selected || c.code === selected)
                    .map((c) => (
                      <button
                        className="destination-detail"
                        key={c.code}
                        onClick={() => {
                          setSelected(c.code);
                          setDrawer("");
                        }}
                      >
                        <span>
                          {flag(c.code)} {c.name}
                        </span>
                        <strong>
                          {count(c.count)} endpoints · {c.percent.toFixed(1)}%
                        </strong>
                        <ChevronRight size={16} />
                      </button>
                    ))}
                  {selected && (
                    <button
                      className="text-button"
                      onClick={() => setSelected("")}
                    >
                      Show every country
                    </button>
                  )}
                  {!data.countries.length && (
                    <p>No location breakdown is available.</p>
                  )}
                </>
              )}
              {drawer === "Kitchen activity" && (
                <>
                  <p>
                    Traffic observed across the Kitchen access point's switch
                    connection. This is one part of your home network.
                  </p>
                  <div className="big-stat">
                    {bytes(data.metrics.capture_bytes)}
                    <small>
                      Observed Ethernet frame bytes · {scope.toLowerCase()}
                    </small>
                  </div>
                  {data.metrics.busiest && (
                    <div className="detail-card">
                      <Wifi />
                      <div>
                        <strong>{data.metrics.busiest.name}</strong>
                        <p>{bytes(data.metrics.busiest.bytes)} observed</p>
                        <small>{data.metrics.busiest.identity_note}</small>
                      </div>
                    </div>
                  )}
                  <p>
                    Mirror: source port 1 → capture port 4, last verified
                    October 5, 2026. No packet payload is retained.
                  </p>
                  <p className="muted">
                    Kernel drops are unmeasured; the collector has an
                    approximately ten-second hourly restart gap. Router and
                    capture byte totals overlap and use different units.
                  </p>
                </>
              )}
              {drawer === "Router traffic" && (
                <>
                  <p>
                    Traffic reported by your router. Recent totals may grow as
                    delayed exports arrive.
                  </p>
                  <div className="big-stat">
                    {bytes(data.metrics.router_bytes)}
                    <small>Observed IP bytes · {scope.toLowerCase()}</small>
                  </div>
                  <div
                    className="trend"
                    aria-label="Observed routed bytes by time bucket"
                  >
                    {data.trend.map((t) => (
                      <div
                        key={t.time}
                        title={`${new Date(t.time).toLocaleTimeString()} · ${bytes(t.bytes)}`}
                        style={{
                          height:
                            Math.max(
                              2,
                              (t.bytes /
                                Math.max(
                                  ...data.trend.map((t) => t.bytes),
                                  1,
                                )) *
                                100,
                            ) + "%",
                        }}
                      />
                    ))}
                  </div>
                  <p className="muted">
                    NetFlow schema 2, deduplicated by event ID. Records are not
                    sessions. Post-NAT uploads cannot reliably be assigned to
                    individual devices.
                  </p>
                </>
              )}
              {drawer === "DNS activity" && (
                <>
                  <p>Requests to look up network names, handled by Pi-hole.</p>
                  <div className="big-stat">
                    {count(data.metrics.dns_queries)}
                    <small>Requests observed · {scope.toLowerCase()}</small>
                  </div>
                  <div className="detail-card">
                    <ShieldCheck />
                    <div>
                      <strong>
                        {count(data.metrics.dns_blocked)} filtered requests
                      </strong>
                      <p>
                        Blocked by Pi-hole. This does not necessarily mean a
                        website visit was prevented.
                      </p>
                    </div>
                  </div>
                  <p className="muted">
                    DNS archiving normally trails by about one to two minutes.
                    Devices using another resolver are outside this view.
                  </p>
                </>
              )}
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
