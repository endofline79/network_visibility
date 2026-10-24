import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { PanelRightClose, PanelRightOpen, X } from "lucide-react";
import { CountryActivity } from "./CountryActivity";
import { DestinationMap } from "./DestinationMap";
import type { Country, GlobeSnapshot, Location, Overview } from "./types";
const detailTabs = [
  { id: "areas", label: "Observed areas" },
  { id: "activity", label: "Recent activity" },
] as const;
type DetailTab = (typeof detailTabs)[number]["id"];

export function WorldView({
  data,
  scenario,
  onLoginRequired,
  summarySelected,
  onSummarySelect,
  onExplore,
  children,
  activity,
}: {
  data: Overview;
  scenario: string;
  onLoginRequired: () => void;
  summarySelected: string;
  onSummarySelect: (value: string) => void;
  onExplore: () => void;
  children: ReactNode;
  activity: ReactNode;
}) {
  const [paneOpen, setPaneOpen] = useState(() => {
    try {
      return localStorage.getItem("visibility.details-pane") !== "false";
    } catch {
      return true;
    }
  });
  const [activeTab, setActiveTab] = useState<DetailTab>("areas");
  const paneToggle = useRef<HTMLButtonElement>(null);
  const tabButtons = useRef<
    Partial<Record<DetailTab, HTMLButtonElement | null>>
  >({});
  const selectionHeading = useRef<HTMLHeadingElement>(null);
  const paneFocus = useRef<"toggle" | "tab" | "selection" | null>(null);
  useEffect(() => {
    try {
      localStorage.setItem("visibility.details-pane", String(paneOpen));
    } catch {}
    if (paneOpen && paneFocus.current === "selection") {
      selectionHeading.current?.focus();
    } else if (paneOpen && paneFocus.current === "tab") {
      tabButtons.current[activeTab]?.focus();
    } else if (!paneOpen && paneFocus.current === "toggle") {
      paneToggle.current?.focus();
    }
    paneFocus.current = null;
  }, [paneOpen, activeTab]);
  const [live, setLive] = useState<GlobeSnapshot | null>(null),
    [error, setError] = useState(false),
    [recent, setRecent] = useState(true),
    [nearSelected, setNearSelected] = useState(""),
    [selectedAreas, setSelectedAreas] = useState<string[]>([]),
    [now, setNow] = useState(Date.now());
  const selected = recent ? nearSelected : summarySelected;
  const setSelected = (value: string) =>
    recent ? setNearSelected(value) : onSummarySelect(value);
  useEffect(() => {
    if (summarySelected) {
      setRecent(false);
      setActiveTab("areas");
    }
  }, [summarySelected]);
  useEffect(() => {
    let active = true,
      busy = false,
      timer: ReturnType<typeof setTimeout> | undefined,
      controller: AbortController | null = null;
    const poll = async () => {
      if (busy || document.hidden || !recent) return;
      clearTimeout(timer);
      busy = true;
      controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 6500);
      try {
        const response = await fetch(`/api/globe?scenario=${scenario}`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (response.status === 401) {
          if (active) onLoginRequired();
          return;
        }
        if (!response.ok) throw Error();
        const snapshot = await response.json();
        if (active) {
          setLive((previous) =>
            previous && Date.parse(previous.as_of) > Date.parse(snapshot.as_of)
              ? previous
              : snapshot,
          );
          setError(false);
        }
      } catch {
        if (active) setError(true);
      } finally {
        clearTimeout(timeout);
        busy = false;
        if (active && !document.hidden) timer = setTimeout(poll, 10000);
      }
    };
    setLive(null);
    setError(false);
    poll();
    const visibility = () => {
      if (document.hidden) {
        clearTimeout(timer);
        controller?.abort();
      } else poll();
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [scenario, recent, onLoginRequired]);
  useEffect(() => {
    const id = setInterval(() => {
      if (!document.hidden) setNow(Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, []);
  const locations: Location[] = useMemo(() => {
    if (!recent) return data.locations || [];
    return (live?.locations || [])
      .map((a) => {
        const buckets = (a.age_buckets || []).filter(
          (b) => now - Date.parse(b.last_seen) < 300000,
        );
        const count = buckets.reduce((n, b) => n + b.count, 0);
        return { ...a, count };
      })
      .filter((a) => a.count > 0);
  }, [recent, data.locations, live, now]);
  const countries: Country[] = useMemo(() => {
    if (!recent) return data.countries;
    const groups = new Map<string, Country>();
    for (const a of locations) {
      let c = groups.get(a.country_code);
      if (!c) {
        c = {
          code: a.country_code,
          name: a.country_name,
          count: 0,
          percent: 0,
          latitude: null,
          longitude: null,
        };
        groups.set(c.code, c);
      }
      c.count += a.count;
    }
    const total = locations.reduce((n, a) => n + a.count, 0);
    return [...groups.values()]
      .map((c) => ({ ...c, percent: total ? (c.count / total) * 100 : 0 }))
      .sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
  }, [recent, data.countries, locations]);
  useEffect(() => {
    if (
      selected &&
      selectedAreas.length &&
      !locations.some(
        (a) => selectedAreas.includes(a.id) && a.country_code === selected,
      )
    )
      setSelectedAreas([]);
  }, [selected]);
  const chosen = countries.find((c) => c.code === selected),
    chosenAreas = locations.filter((a) => selectedAreas.includes(a.id));
  const chooseAreas = (ids: string[]) => {
    setActiveTab("areas");
    setSelectedAreas(ids);
    const codes = [
      ...new Set(
        locations.filter((a) => ids.includes(a.id)).map((a) => a.country_code),
      ),
    ];
    setSelected(codes.length === 1 ? codes[0] : "");
  };
  const chooseCountry = (code: string) => {
    setActiveTab("areas");
    setSelectedAreas([]);
    setSelected(code);
  };
  const flowAge = live?.observed_at
      ? Math.max(0, Math.floor((now - Date.parse(live.observed_at)) / 1000))
      : null,
    updateAge = live
      ? Math.max(0, Math.floor((now - Date.parse(live.as_of)) / 1000))
      : null;
  const delayed = error || (updateAge !== null && updateAge > 30),
    status = recent
      ? !live
        ? error
          ? "Recent view unavailable"
          : "Loading recent observations…"
        : delayed
          ? "Updates delayed"
          : live.state === "fresh" && flowAge !== null && flowAge <= 90
            ? "Near-live observations"
            : live.state === "partial"
              ? "Recent view exceeds limits"
              : live.state === "unavailable"
                ? "Recent view unavailable"
                : "Flow observations aging"
      : data.window.label;
  const geo = recent ? live?.geo || data.geo : data.geo;
  const total = locations.reduce((n, a) => n + a.count, 0),
    mapped = locations
      .filter((a) => a.precision === "area")
      .reduce((n, a) => n + a.count, 0),
    unplaced = total - mapped;
  const expired = recent && total === 0 && (live?.locations?.length || 0) > 0;
  const known = recent
    ? live?.endpoints !== null && !!live
    : data.metrics.destinations !== null;
  const listed = selected
    ? locations.filter((a) => a.country_code === selected)
    : locations;
  const expiredSelection = selectedAreas.length > 0 && !chosenAreas.length;
  const selectionTitle =
    chosenAreas.length === 1
      ? `${chosenAreas[0].name} · ${chosenAreas[0].country_name}`
      : chosenAreas.length > 1
        ? `${chosenAreas.length} nearby areas`
        : chosen?.name || "Area selection";
  const selectionSummary = expiredSelection
    ? "Selected area is no longer present in this window"
    : `${chosenAreas.length ? chosenAreas.reduce((n, a) => n + a.count, 0) : chosen?.count || 0} public endpoints · ${recent ? "last 5 minutes" : data.window.label.toLowerCase()}`;
  const selection = (chosen || chosenAreas.length > 0 || expiredSelection) && (
    <div className="world-selection map-selection" role="status">
      <strong>{selectionTitle}</strong>
      <span>{selectionSummary}</span>
      {chosenAreas.length > 0 && (
        <div className="map-area-details">
          {chosenAreas.map((a) => (
            <div key={a.id}>
              <b>
                {a.name} · {a.count}
              </b>
              <span>
                {a.cities.length
                  ? `City labels include ${a.cities.join(", ")}${a.other_city_labels ? " and others" : ""}`
                  : "No usable city/region position"}
              </span>
              <small>
                {a.accuracy_radius_km === null
                  ? "Provider accuracy radius unavailable"
                  : `Provider radius metadata up to ${a.accuracy_radius_km} km, unverified`}
              </small>
            </div>
          ))}
        </div>
      )}
      {!recent && chosen && (
        <button className="world-details" onClick={onExplore}>
          Details
        </button>
      )}
      <button
        className="world-clear"
        aria-label="Clear map selection"
        onClick={() => {
          setSelected("");
          setSelectedAreas([]);
        }}
      >
        <X size={15} />
      </button>
    </div>
  );
  return (
    <>
      <section
        className={"world-view map-view" + (paneOpen ? " with-details" : "")}
        aria-label="External traffic map"
      >
        <div className="map-panel panel">
          <div className="map-main">
            <div className="world-heading">
              <div>
                <span className="eyebrow">APPROXIMATE IP LOCATIONS</span>
                <h2>External traffic map</h2>
                <p>
                  Explore nearby areas. IP estimates show relationships, not
                  verified server locations.
                </p>
              </div>
            </div>
            <div className="map-status">
              <div className="world-freshness">
                <strong>
                  <i
                    className={
                      "dot " +
                      (recent &&
                      (delayed ||
                        !live ||
                        live.state !== "fresh" ||
                        (flowAge || 0) > 90)
                        ? "amber"
                        : "")
                    }
                  />
                  {data.mode === "demo" ? "Demo · " : ""}
                  {status}
                </strong>
                <span>
                  {recent
                    ? `Last 5 minutes · newest router flow ${flowAge === null ? "unknown" : `${flowAge}s ago`} · checked ${updateAge === null ? "—" : `${updateAge}s ago`}`
                    : `Approximate areas · ${data.window.label.toLowerCase()}`}
                </span>
                {recent && error && (
                  <small>Refresh failed; saved observations keep aging.</small>
                )}
              </div>
              <div className="map-accounting" role="status">
                {known ? (
                  <>
                    <strong>
                      {expired
                        ? "Saved locations have aged out of the five-minute window"
                        : `${total} public endpoints`}
                    </strong>
                    <span>
                      {mapped} in mapped areas · {unplaced} not placed on the
                      map
                      {recent && delayed
                        ? " · saved observations continue aging"
                        : ""}
                    </span>
                  </>
                ) : (
                  <strong>
                    {(recent && live?.state === "partial") ||
                    (!recent && data.location_state === "withheld")
                      ? "Locations withheld because the query limit was reached"
                      : "Locations unavailable in this window"}
                  </strong>
                )}
              </div>
            </div>
            {!geo.available && (
              <p className="map-warning" role="status">
                Geolocation database unavailable · location estimates may be
                missing.
              </p>
            )}
            <DestinationMap
              locations={locations}
              selected={selectedAreas}
              country={selected}
              onSelect={chooseAreas}
              nearLive={recent}
              now={now}
            />
            {selection && !paneOpen && (
              <div className="map-selection-summary" role="status">
                <div>
                  <strong>{selectionTitle}</strong>
                  <span>{selectionSummary}</span>
                </div>
                <button
                  className="text-button"
                  onClick={() => {
                    setActiveTab("areas");
                    paneFocus.current = "selection";
                    setPaneOpen(true);
                  }}
                >
                  View selection details <PanelRightOpen size={16} />
                </button>
              </div>
            )}
          </div>
        </div>
        {!paneOpen && (
          <button
            ref={paneToggle}
            className="pane-edge-toggle"
            aria-label="Show details"
            title="Show network details"
            aria-expanded={false}
            aria-controls="network-details-pane"
            onClick={() => {
              paneFocus.current = "tab";
              setPaneOpen(true);
            }}
          >
            <PanelRightOpen size={18} aria-hidden="true" />
          </button>
        )}
        {paneOpen && (
          <aside
            className="details-pane"
            id="network-details-pane"
            aria-label="Network details"
          >
            <div className="details-pane-heading">
              <div>
                <span className="eyebrow">EXPLORE YOUR NETWORK</span>
                <h2>Network details</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Collapse details pane"
                onClick={() => {
                  paneFocus.current = "toggle";
                  setPaneOpen(false);
                }}
              >
                <PanelRightClose size={18} />
              </button>
            </div>
            <div className="details-pane-controls">
              <span className="pane-control-label">Map time view</span>
              <div
                className="world-mode"
                role="group"
                aria-label="Map time view"
              >
                <button
                  aria-pressed={recent}
                  onClick={() => {
                    setRecent(true);
                    setNearSelected("");
                    onSummarySelect("");
                    setSelectedAreas([]);
                  }}
                >
                  Near-live
                </button>
                <button
                  aria-pressed={!recent}
                  onClick={() => {
                    setRecent(false);
                    setNearSelected("");
                    onSummarySelect("");
                    setSelectedAreas([]);
                  }}
                >
                  Summary
                </button>
              </div>
            </div>
            <div
              className="details-tabs"
              role="tablist"
              aria-label="Network details"
            >
              {detailTabs.map((tab, index) => (
                <button
                  key={tab.id}
                  ref={(button) => {
                    tabButtons.current[tab.id] = button;
                  }}
                  id={`details-tab-${tab.id}`}
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  aria-controls={`details-panel-${tab.id}`}
                  tabIndex={activeTab === tab.id ? 0 : -1}
                  onClick={() => setActiveTab(tab.id)}
                  onKeyDown={(event) => {
                    const nextIndex =
                      event.key === "ArrowRight"
                        ? (index + 1) % detailTabs.length
                        : event.key === "ArrowLeft"
                          ? (index + detailTabs.length - 1) % detailTabs.length
                          : event.key === "Home"
                            ? 0
                            : event.key === "End"
                              ? detailTabs.length - 1
                              : null;
                    if (nextIndex === null) return;
                    event.preventDefault();
                    const next = detailTabs[nextIndex].id;
                    setActiveTab(next);
                    tabButtons.current[next]?.focus();
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div
              className="details-pane-body"
              id="details-panel-areas"
              role="tabpanel"
              aria-labelledby="details-tab-areas"
              hidden={activeTab !== "areas"}
              tabIndex={0}
            >
              <section
                className="pane-section"
                aria-labelledby="map-selection-heading"
              >
                <h3
                  id="map-selection-heading"
                  ref={selectionHeading}
                  tabIndex={-1}
                >
                  Map selection
                </h3>
                {selection || (
                  <p className="pane-empty">
                    Select a country or an area on the map to explore its
                    observed endpoints.
                  </p>
                )}
              </section>
              <section
                className="pane-section"
                aria-labelledby="map-areas-heading"
              >
                <h3 id="map-areas-heading">Observed areas</h3>
                <p className="muted">
                  {chosen?.name || "All countries"} ·{" "}
                  {recent ? "last 5 minutes" : data.window.label.toLowerCase()}
                </p>
                {listed.length > 0 && (
                  <div
                    className="map-location-list"
                    aria-label="Approximate IP areas"
                  >
                    {listed.map((a) => (
                      <button
                        key={a.id}
                        data-location-id={a.id}
                        data-precision={a.precision}
                        aria-pressed={selectedAreas.includes(a.id)}
                        onClick={() => chooseAreas([a.id])}
                      >
                        <span>
                          {a.name}
                          {a.precision === "area" && a.cities.length
                            ? ` · ${a.cities.join(", ")}`
                            : ""}
                          <small>
                            {a.country_name}
                            {a.precision !== "area" ? " · not plotted" : ""}
                          </small>
                        </span>
                        <b>{a.count}</b>
                      </button>
                    ))}
                  </div>
                )}

                {!listed.length && (
                  <p className="pane-empty">
                    No location areas available in this window.
                  </p>
                )}
              </section>
              <div className="pane-section">
                <details className="map-method">
                  <summary>About location estimates and timing</summary>
                  <div className="map-quality">
                    <span>
                      {!geo.available
                        ? "Geolocation database unavailable · "
                        : ""}
                      {geo.provider} · database age{" "}
                      {geo.age_days === null
                        ? "unknown"
                        : `${geo.age_days} days`}
                      {geo.build_utc
                        ? ` · built ${geo.build_utc.slice(0, 10)}`
                        : ""}
                    </span>
                    <span>
                      Areas grouped on a {geo.grid_degrees || 0.5}° grid; this
                      is not an accuracy guarantee. Zoom does not make the IP
                      estimates more precise. Lines show relationships, not
                      packet routes.
                    </span>
                    {recent && (
                      <small>
                        {live?.note ||
                          "Received NetFlow exports can lag by minutes; these are public IP endpoints, not verified host positions."}
                      </small>
                    )}
                  </div>
                </details>
              </div>
            </div>
            <div
              className="details-pane-body"
              id="details-panel-activity"
              role="tabpanel"
              aria-labelledby="details-tab-activity"
              hidden={activeTab !== "activity"}
              tabIndex={0}
            >
              {children}
            </div>
          </aside>
        )}
      </section>
      <section className="lower-grid">
        <CountryActivity
          countries={countries}
          selected={selected}
          onSelect={chooseCountry}
          scope={recent ? "last 5 minutes" : data.window.label.toLowerCase()}
          emptyMessage={
            expired
              ? "Saved locations have aged out of the five-minute window."
              : (recent && live?.state === "partial") ||
                  (!recent && data.location_state === "withheld")
                ? "Locations withheld because the query limit was reached."
                : !known
                  ? "Locations unavailable in this window."
                  : "No public endpoints observed in this window."
          }
        />
        {activity}
      </section>
    </>
  );
}
