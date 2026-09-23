import { useEffect, useMemo, useRef, useState } from "react";
import {
  geoCentroid,
  geoDistance,
  geoGraticule10,
  geoInterpolate,
  geoNaturalEarth1,
  geoOrthographic,
  geoPath,
} from "d3-geo";
import { feature } from "topojson-client";
import type { FeatureCollection } from "geojson";
import type { Topology, GeometryCollection } from "topojson-specification";
import world from "@d3-maps/atlas/world/countries/countries-110m";
import { Globe2, Map as MapIcon } from "lucide-react";
import type { FirewallEvent, Geo, Snapshot } from "./types";

const topology = world as unknown as Topology<{ features: GeometryCollection }>;
const countries = (
  feature(topology, topology.objects.features) as FeatureCollection
).features;
const graticule = geoGraticule10();
type Point = {
  key: string;
  geo: Geo;
  action: string;
  count: number;
  ips: Set<string>;
  latest: string;
};

export function WorldMap({
  events,
  locations,
  lab,
  selectedCountry,
  onCountry,
  asOf,
}: {
  events: FirewallEvent[];
  locations: Record<string, Geo>;
  lab: Snapshot["lab"];
  selectedCountry: string;
  onCountry: (code: string) => void;
  asOf: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(960);
  const [mode, setMode] = useState<"map" | "globe">("globe");
  const [rotation, setRotation] = useState<[number, number]>([30, -20]);
  const [hover, setHover] = useState<Point | null>(null);
  const drag = useRef<{
    x: number;
    y: number;
    rotation: [number, number];
    moved: boolean;
  } | null>(null);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const points = useMemo(() => {
    const groups = new Map<string, Point>();
    for (const event of events) {
      // One event counts once at each distinct remote location, never as bytes.
      const seen = new Set<string>();
      for (const ip of [event.source, event.destination]) {
        const geo = locations[ip];
        if (!geo) continue;
        const key = `${geo.country_code}:${geo.latitude.toFixed(1)}:${geo.longitude.toFixed(1)}:${event.action}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const p = groups.get(key) || {
          key,
          geo,
          action: event.action,
          count: 0,
          ips: new Set<string>(),
          latest: event.time,
        };
        if (event.time > p.latest) p.latest = event.time;
        p.count++;
        p.ips.add(ip);
        groups.set(key, p);
      }
    }
    return [...groups.values()].sort((a, b) => b.count - a.count);
  }, [events, locations]);
  useEffect(() => {
    if (!selectedCountry || !lab) return;
    const p = points.find((p) => p.geo.country_code === selectedCountry);
    if (!p) return;
    const center = geoInterpolate(
      [lab.longitude, lab.latitude],
      [p.geo.longitude, p.geo.latitude],
    )(0.5);
    setRotation([-center[0], -center[1]]);
  }, [selectedCountry, lab, points]);
  const height = Math.max(265, Math.min(480, width * 0.5));
  const projection = useMemo(
    () =>
      mode === "globe"
        ? geoOrthographic()
            .rotate(rotation)
            .fitExtent(
              [
                [22, 12],
                [width - 22, height - 12],
              ],
              { type: "Sphere" },
            )
        : geoNaturalEarth1().fitExtent(
            [
              [16, 6],
              [width - 16, height - 6],
            ],
            { type: "Sphere" },
          ),
    [mode, rotation, width, height],
  );
  const path = geoPath(projection);
  const center = projection.invert?.([width / 2, height / 2]) || [0, 0];
  const visible = (coords: [number, number]) =>
    mode !== "globe" || geoDistance(center, coords) < Math.PI / 2;
  const drawn = points.slice(0, 80);
  const hub: [number, number] | null = lab
    ? [lab.longitude, lab.latitude]
    : null;
  const hubXY = hub ? projection(hub) : null;
  const hue = (action: string) =>
    action === "pass"
      ? "var(--allowed)"
      : action === "block"
        ? "var(--blocked)"
        : "var(--muted)";
  return (
    <section className="map-panel" aria-label="Geographic firewall activity">
      <div className="panel-heading">
        <div>
          <h2>Across the network</h2>
          <p>Approximate remote locations · select a point to explore</p>
        </div>
        <div className="map-controls">
          <div className="legend">
            <span>
              <i />
              Allowed
            </span>
            <span>
              <i className="blocked" />
              Blocked
            </span>
          </div>
          <div className="segmented">
            <button
              aria-label="World map"
              aria-pressed={mode === "map"}
              onClick={() => setMode("map")}
            >
              <MapIcon size={16} />
              <span>Map</span>
            </button>
            <button
              aria-label="Globe"
              aria-pressed={mode === "globe"}
              onClick={() => setMode("globe")}
            >
              <Globe2 size={16} />
              <span>Globe</span>
            </button>
          </div>
        </div>
      </div>
      <div className={`map-stage ${mode}`} ref={container}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          height={height}
          role="group"
          aria-label="Map of observed public endpoints"
          className="world"
          onPointerDown={(e) => {
            if (mode !== "globe") return;
            drag.current = {
              x: e.clientX,
              y: e.clientY,
              rotation,
              moved: false,
            };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (!d) return;
            const dx = e.clientX - d.x,
              dy = e.clientY - d.y;
            if (Math.abs(dx) + Math.abs(dy) > 5) d.moved = true;
            setRotation([
              d.rotation[0] + dx * 0.3,
              Math.max(-85, Math.min(85, d.rotation[1] - dy * 0.3)),
            ]);
          }}
          onPointerUp={() => {
            setTimeout(() => {
              drag.current = null;
            }, 0);
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
        >
          <title>Observed public endpoints</title>
          <desc>
            Connections represent logged events, not packet routes or bandwidth.
            The lab marker is a city-level anchor.
          </desc>
          <path d={path({ type: "Sphere" }) || ""} className="ocean" />
          <path d={path(graticule) || ""} className="graticule" />
          {countries.map((c, i) => (
            <path key={i} d={path(c) || ""} className="land" />
          ))}
          {hub &&
            drawn.map((p) => (
              <path
                key={p.key}
                d={
                  path({
                    type: "LineString",
                    coordinates: [hub, [p.geo.longitude, p.geo.latitude]],
                  }) || ""
                }
                fill="none"
                stroke={hue(p.action)}
                strokeWidth={Math.min(3.3, 0.8 + Math.log2(p.count + 1) * 0.24)}
                strokeOpacity={0.55}
                strokeDasharray={p.action === "block" ? "4 5" : undefined}
              />
            ))}
          {drawn
            .filter((p) => visible([p.geo.longitude, p.geo.latitude]))
            .map((p) => {
              const xy = projection([p.geo.longitude, p.geo.latitude]);
              if (!xy) return null;
              return (
                <g
                  key={p.key}
                  transform={`translate(${xy[0]},${xy[1]})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${p.geo.city || p.geo.country}, ${p.geo.country}, ${p.count} ${p.action === "pass" ? "allowed" : p.action === "block" ? "blocked" : p.action} endpoint observations`}
                  onClick={() => {
                    if (!drag.current?.moved) onCountry(p.geo.country_code);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onCountry(p.geo.country_code);
                    }
                  }}
                  onMouseEnter={() => setHover(p)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(p)}
                  onBlur={() => setHover(null)}
                  className="map-point"
                >
                  <circle r={14} fill="transparent" />
                  <circle
                    r={Math.min(6, 2.6 + Math.log2(p.count + 1) * 0.35)}
                    fill={hue(p.action)}
                  />
                  <circle
                    key={p.latest}
                    r={7}
                    fill="none"
                    stroke={hue(p.action)}
                    className="activity-ring"
                  />
                </g>
              );
            })}
          {hub && hubXY && visible(hub) && (
            <g
              transform={`translate(${hubXY[0]},${hubXY[1]})`}
              className="lab-point"
            >
              <circle r={11} />
              <circle r={5} />
              <text y={27} textAnchor="middle">
                {width > 480 ? lab?.label || "Lab" : "Lab"}
              </text>
            </g>
          )}
        </svg>
        {!drawn.length && (
          <div className="map-empty">
            No located public endpoints in the selected events.
            <small>Local and unlocated addresses remain in the log view.</small>
          </div>
        )}
        {hover && (
          <div className="map-tooltip" role="status">
            <strong>
              {hover.geo.city ? `${hover.geo.city}, ` : ""}
              {hover.geo.country}
            </strong>
            <span>
              {hover.count.toLocaleString()} endpoint observations ·{" "}
              {hover.ips.size} IP{hover.ips.size === 1 ? "" : "s"}
            </span>
            <span className={hover.action === "pass" ? "allowed" : "blocked"}>
              {hover.action === "pass"
                ? "Allowed"
                : hover.action === "block"
                  ? "Blocked"
                  : hover.action}
            </span>
          </div>
        )}
      </div>
      <div className="map-footer">
        <span>
          {mode === "globe" ? "Drag to rotate · " : ""}Lines show logged
          activity, not bandwidth or routes
        </span>
        <span>
          {points.length > 80
            ? `Showing 80 of ${points.length.toLocaleString()} locations`
            : `${points.length.toLocaleString()} remote locations`}
        </span>
      </div>
    </section>
  );
}
