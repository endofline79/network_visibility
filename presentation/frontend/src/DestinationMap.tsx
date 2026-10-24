import { useEffect, useMemo, useRef, useState } from "react";
import { geoEquirectangular, geoPath, geoGraticule10 } from "d3-geo";
import { feature } from "topojson-client";
import topology from "@d3-maps/atlas/world/countries/countries-110m";
import { ZoomIn, ZoomOut, Maximize, LocateFixed } from "lucide-react";
import type { Location } from "./types";
import { updateHistory, type HistoryEntry } from "./observationHistory";
const HOME: [number, number] = [-77.6088, 43.1566];
const land = feature(topology, topology.objects.features);
type View = { zoom: number; x: number; y: number };
export function DestinationMap({
  locations,
  selected,
  country,
  onSelect,
  nearLive,
  now,
}: {
  locations: Location[];
  selected: string[];
  country: string;
  onSelect: (ids: string[]) => void;
  nearLive: boolean;
  now: number;
}) {
  const viewport = useRef<HTMLDivElement>(null),
    [size, setSize] = useState({ width: 700, height: 400 });
  const [view, setView] = useState<View>({ zoom: 1, x: 0, y: 0 }),
    viewRef = useRef(view);
  const [gestures, setGestures] = useState(false),
    [dragging, setDragging] = useState(false);
  const [reduced, setReduced] = useState(
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const history = useRef(new Map<string, HistoryEntry>()),
    initialized = useRef(false);
  useEffect(() => {
    const q = matchMedia("(prefers-reduced-motion: reduce)"),
      change = () => setReduced(q.matches);
    q.addEventListener("change", change);
    return () => q.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    const el = viewport.current!;
    const measure = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width && height)
        setSize((old) =>
          Math.abs(old.width - width) < 0.5 &&
          Math.abs(old.height - height) < 0.5
            ? old
            : { width, height },
        );
    };
    measure();
    const r = new ResizeObserver(measure);
    r.observe(el);
    return () => r.disconnect();
  }, []);
  const scale = Math.min(
      (size.width - 32) / (2 * Math.PI),
      (size.height - 32) / Math.PI,
    ),
    cx = size.width / 2,
    cy = size.height / 2;
  const projection = useMemo(
    () => geoEquirectangular().translate([cx, cy]).scale(scale),
    [cx, cy, scale],
  );
  const path = useMemo(() => geoPath(projection), [projection]);
  const clamp = (v: View) => {
    const zoom = Math.max(1, Math.min(8, v.zoom)),
      mx = Math.max(0, (scale * 2 * Math.PI * zoom - size.width) / 2 + 16),
      my = Math.max(0, (scale * Math.PI * zoom - size.height) / 2 + 16);
    return {
      zoom,
      x: Math.max(-mx, Math.min(mx, v.x)),
      y: Math.max(-my, Math.min(my, v.y)),
    };
  };
  const change = (v: View) => {
    const next = clamp(v);
    viewRef.current = next;
    setView(next);
  };
  useEffect(() => {
    change(viewRef.current);
  }, [size.width, size.height]);
  const zoom = (factor: number, at?: [number, number]) => {
    const old = viewRef.current,
      next = Math.max(1, Math.min(8, old.zoom * factor)),
      ratio = next / old.zoom,
      p = at || [cx, cy];
    change({
      zoom: next,
      x: (old.x + cx - p[0]) * ratio + p[0] - cx,
      y: (old.y + cy - p[1]) * ratio + p[1] - cy,
    });
  };
  useEffect(() => {
    const el = viewport.current!;
    const wheel = (e: WheelEvent) => {
      if (!gestures) return;
      e.preventDefault();
      const b = el.getBoundingClientRect();
      zoom(Math.exp(-Math.max(-120, Math.min(120, e.deltaY)) * 0.002), [
        e.clientX - b.x,
        e.clientY - b.y,
      ]);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [gestures, size]);
  const areas = locations.filter(
    (a) =>
      a.precision === "area" && a.latitude !== null && a.longitude !== null,
  );
  useEffect(() => {
    updateHistory(history.current, initialized, areas, nearLive, Date.now());
  }, [locations, nearLive]);
  const groups = useMemo(() => {
    const bins = new Map<
      string,
      {
        ids: string[];
        names: string[];
        countries: Set<string>;
        count: number;
        x: number;
        y: number;
        n: number;
        newest: number;
      }
    >();
    for (const a of areas) {
      const p = projection([a.longitude!, a.latitude!])!;
      // Anchored to world coordinates: panning cannot reshuffle area membership.
      const partition = country
        ? a.country_code === country
          ? "selected"
          : "other"
        : "all";
      const key = `${partition}:${Math.floor(((p[0] - cx) * view.zoom) / 32)}:${Math.floor(((p[1] - cy) * view.zoom) / 32)}`;
      let b = bins.get(key);
      if (!b) {
        b = {
          ids: [],
          names: [],
          countries: new Set(),
          count: 0,
          x: 0,
          y: 0,
          n: 0,
          newest: 0,
        };
        bins.set(key, b);
      }
      b.ids.push(a.id);
      b.names.push(a.name);
      b.countries.add(a.country_code);
      b.count += a.count;
      b.newest = Math.max(b.newest, Date.parse(a.last_seen || "") || 0);
      b.x += p[0];
      b.y += p[1];
      b.n++;
    }
    return [...bins.values()]
      .map((b) => ({
        ...b,
        x: b.x / b.n,
        y: b.y / b.n,
        ids: b.ids.sort(),
        names: [...new Set(b.names)].sort(),
      }))
      .sort((a, b) => a.ids[0].localeCompare(b.ids[0]));
  }, [locations, projection, view.zoom, country]);
  const focusable = areas.filter((a) =>
    selected.length
      ? selected.includes(a.id)
      : country
        ? a.country_code === country
        : true,
  );
  const focus = () => {
    const chosen = focusable;
    if (!chosen.length) return;
    const points = chosen.map((a) => projection([a.longitude!, a.latitude!])!);
    const xs = points.map((p) => p[0]),
      ys = points.map((p) => p[1]),
      left = Math.min(...xs),
      right = Math.max(...xs),
      top = Math.min(...ys),
      bottom = Math.max(...ys);
    const z = Math.min(
      8,
      Math.max(
        1,
        Math.min(
          (size.width - 80) / Math.max(40, right - left),
          (size.height - 80) / Math.max(40, bottom - top),
        ),
      ),
    );
    change({
      zoom: z,
      x: (cx - (left + right) / 2) * z,
      y: (cy - (top + bottom) / 2) * z,
    });
  };
  const pointers = useRef(new Map<number, { x: number; y: number }>()),
    consumed = useRef(false),
    suppressUntil = useRef(0);
  const drag = useRef<{
      id: number;
      x: number;
      y: number;
      view: View;
      touch: boolean;
      ids: string[];
    } | null>(null),
    pinch = useRef<{
      distance: number;
      view: View;
      mid: [number, number];
    } | null>(null);
  const distance = () => {
    const [a, b] = [...pointers.current.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };
  const finish = (id: number, canceled = false) => {
    if (!pointers.current.has(id)) return;
    if (canceled) consumed.current = true;
    if (consumed.current) suppressUntil.current = performance.now() + 600;
    pointers.current.delete(id);
    drag.current = null;
    pinch.current = null;
    setDragging(pointers.current.size > 0);
  };
  const home = projection(HOME)!;
  const transform = `translate(${view.x + cx * (1 - view.zoom)} ${view.y + cy * (1 - view.zoom)}) scale(${view.zoom})`;
  // Selected-region annotations are passive and avoid marker/Home hit areas.
  // Omit a label when no clean position fits; full names remain in the detail panel.
  const screenPoint = (x: number, y: number) => [
    view.x + cx + (x - cx) * view.zoom,
    view.y + cy + (y - cy) * view.zoom,
  ];
  type Box = { x: number; y: number; width: number; height: number };
  const overlap = (a: Box, b: Box) =>
    a.x < b.x + b.width + 4 &&
    a.x + a.width + 4 > b.x &&
    a.y < b.y + b.height + 4 &&
    a.y + a.height + 4 > b.y;
  const occupied: Box[] = groups.map((b) => {
    const [x, y] = screenPoint(b.x, b.y);
    return {
      x: x - 18,
      y: y - 18,
      width: Math.max(36, 40 + b.count.toString().length * 7),
      height: 36,
    };
  });
  const [hx, hy] = screenPoint(home[0], home[1]);
  occupied.push(
    { x: hx - 12, y: hy - 12, width: 24, height: 24 },
    { x: hx - 54, y: hy - 29, width: 48, height: 20 },
  );
  const labels: { key: string; text: string; point: number[]; box: Box }[] = [];
  for (const b of groups) {
    if (!b.ids.some((id) => selected.includes(id))) continue;
    const point = screenPoint(b.x, b.y);
    if (
      point[0] < 0 ||
      point[0] > size.width ||
      point[1] < 0 ||
      point[1] > size.height
    )
      continue;
    const names = b.names.join(", "),
      text =
        (names.length > 25 ? names.slice(0, 24) + "…" : names) +
        " · " +
        b.count;
    const width = Math.min(260, text.length * 7.5 + 16),
      height = 26;
    const candidates = [
      [point[0] + 24, point[1] - height - 24],
      [point[0] - width - 24, point[1] - height - 24],
      [point[0] + 24, point[1] + 24],
      [point[0] - width - 24, point[1] + 24],
      [point[0] - width / 2, point[1] - height - 24],
      [point[0] - width / 2, point[1] + 24],
    ];
    for (const [x, y] of candidates) {
      const box = {
        x: Math.max(6, Math.min(size.width - width - 6, x)),
        y: Math.max(6, Math.min(size.height - height - 6, y)),
        width,
        height,
      };
      if (occupied.some((b) => overlap(box, b))) continue;
      labels.push({ key: b.ids.join(":"), text, point, box });
      occupied.push(box);
      break;
    }
  }
  return (
    <div className="destination-map">
      <div
        ref={viewport}
        className={
          "map-viewport " +
          (gestures ? "gestures-enabled " : "") +
          (dragging ? "dragging" : "")
        }
        data-zoom={view.zoom}
        data-pan-x={view.x}
        data-pan-y={view.y}
      >
        <svg
          viewBox={`0 0 ${size.width} ${size.height}`}
          role="group"
          tabIndex={0}
          aria-label="Interactive destination map. Arrow keys pan, plus and minus zoom, Home fits the world. Wheel and pinch require Zoom gestures."
          onKeyDown={(e) => {
            if (e.target !== e.currentTarget) return;
            const keys = [
              "ArrowLeft",
              "ArrowRight",
              "ArrowUp",
              "ArrowDown",
              "+",
              "=",
              "-",
              "_",
              "Home",
            ];
            if (!keys.includes(e.key)) return;
            e.preventDefault();
            if (e.key === "Home") change({ zoom: 1, x: 0, y: 0 });
            else if (["+", "="].includes(e.key)) zoom(1.3);
            else if (["-", "_"].includes(e.key)) zoom(1 / 1.3);
            else
              change({
                ...viewRef.current,
                x:
                  viewRef.current.x +
                  (e.key === "ArrowLeft"
                    ? 60
                    : e.key === "ArrowRight"
                      ? -60
                      : 0),
                y:
                  viewRef.current.y +
                  (e.key === "ArrowUp" ? 60 : e.key === "ArrowDown" ? -60 : 0),
              });
          }}
          onClickCapture={(e) => {
            if (
              e.detail > 0 &&
              (consumed.current ||
                pointers.current.size > 0 ||
                performance.now() < suppressUntil.current)
            ) {
              e.preventDefault();
              e.stopPropagation();
            }
          }}
          onPointerDown={(e) => {
            if (e.button !== 0 || pointers.current.size >= 2) return;
            const target = (e.target as Element).closest("[data-map-ids]");
            if (!pointers.current.size) {
              consumed.current = false;
              suppressUntil.current = 0;
            }
            pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
            e.currentTarget.setPointerCapture(e.pointerId);
            setDragging(true);
            if (pointers.current.size === 2) {
              consumed.current = true;
              drag.current = null;
              if (gestures) {
                const [a, b] = [...pointers.current.values()],
                  box = e.currentTarget.getBoundingClientRect();
                pinch.current = {
                  distance: Math.max(1, distance()),
                  view: viewRef.current,
                  mid: [(a.x + b.x) / 2 - box.x, (a.y + b.y) / 2 - box.y],
                };
              }
            } else
              drag.current = {
                id: e.pointerId,
                x: e.clientX,
                y: e.clientY,
                view: viewRef.current,
                touch: e.pointerType === "touch",
                ids: target?.getAttribute("data-map-ids")?.split(",") || [],
              };
          }}
          onPointerMove={(e) => {
            if (!pointers.current.has(e.pointerId)) return;
            pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
            if (pinch.current && pointers.current.size === 2 && gestures) {
              const p = pinch.current,
                next = Math.max(
                  1,
                  Math.min(8, (p.view.zoom * distance()) / p.distance),
                ),
                ratio = next / p.view.zoom;
              change({
                zoom: next,
                x: (p.view.x + cx - p.mid[0]) * ratio + p.mid[0] - cx,
                y: (p.view.y + cy - p.mid[1]) * ratio + p.mid[1] - cy,
              });
              return;
            }
            const d = drag.current;
            if (!d || d.id !== e.pointerId || pointers.current.size !== 1)
              return;
            const dx = e.clientX - d.x,
              dy = e.clientY - d.y;
            if (Math.abs(dx) + Math.abs(dy) > 6) consumed.current = true;
            if (
              d.touch &&
              !gestures &&
              (Math.abs(dx) < 6 || Math.abs(dx) < Math.abs(dy) * 1.25)
            )
              return;
            change({ ...d.view, x: d.view.x + dx, y: d.view.y + dy });
          }}
          onPointerUp={(e) => {
            const d = drag.current;
            if (
              d &&
              d.id === e.pointerId &&
              Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 6
            )
              consumed.current = true;
            if (
              d?.id === e.pointerId &&
              d.ids.length &&
              pointers.current.size === 1 &&
              !consumed.current
            ) {
              onSelect(d.ids);
              suppressUntil.current = performance.now() + 600;
            }
            finish(e.pointerId);
          }}
          onPointerCancel={(e) => finish(e.pointerId, true)}
          onLostPointerCapture={(e) => finish(e.pointerId, true)}
        >
          <rect width={size.width} height={size.height} fill="#071c2a" />
          <g transform={transform} className="map-scene">
            <path d={path(geoGraticule10()) || ""} className="map-grid" />
            <path d={path(land) || ""} className="map-land" />
            {groups.map((b) => (
              <path
                key={"line" + b.ids.join(":")}
                d={`M${home[0]},${home[1]}L${b.x},${b.y}`}
                className="map-relationship"
                vectorEffect="non-scaling-stroke"
                opacity={country && !b.countries.has(country) ? 0.12 : 0.35}
              />
            ))}
            <g
              className="map-home"
              role="img"
              aria-label="Home origin in Rochester"
              pointerEvents="none"
            >
              <title>Home origin · Rochester</title>
              <circle
                cx={home[0]}
                cy={home[1]}
                r={7 / view.zoom}
                fill="#baffbd"
                stroke="#082639"
                strokeWidth={2 / view.zoom}
              />
              <text
                x={home[0] - 9 / view.zoom}
                y={home[1] - 12 / view.zoom}
                fontSize={12 / view.zoom}
                textAnchor="end"
              >
                Home
              </text>
            </g>
            {groups.map((b) => {
              const chosen = b.ids.some((id) => selected.includes(id)),
                active =
                  nearLive &&
                  !reduced &&
                  b.ids.some(
                    (id) => now < (history.current.get(id)?.until || 0),
                  ),
                dim = country && !b.countries.has(country);
              return (
                <g
                  key={b.ids.join(":")}
                  className={
                    "map-marker " +
                    (active ? "new-observation " : "") +
                    (chosen ? "chosen" : "")
                  }
                  data-map-ids={b.ids.join(",")}
                  data-count={b.count}
                  data-x={b.x}
                  data-y={b.y}
                  role="button"
                  tabIndex={0}
                  aria-label={`Explore ${b.names.join(", ")}: ${b.count} public endpoints in ${b.ids.length} approximate areas`}
                  onClick={() => onSelect(b.ids)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.stopPropagation();
                      onSelect(b.ids);
                    }
                  }}
                  opacity={
                    (dim ? 0.3 : 1) *
                    (nearLive && b.newest
                      ? Math.max(0.12, 1 - Math.max(0, now - b.newest) / 300000)
                      : 1)
                  }
                >
                  <title>{`${b.names.join(", ")} · ${b.count} public endpoints · approximate IP areas`}</title>
                  <circle
                    cx={b.x}
                    cy={b.y}
                    r={15 / view.zoom}
                    fill="transparent"
                  />
                  <circle
                    cx={b.x}
                    cy={b.y}
                    r={(chosen ? 9 : 7) / view.zoom}
                    fill={chosen ? "#f8b94f" : "#38d9c0"}
                    stroke="#062131"
                    strokeWidth={2 / view.zoom}
                  />
                  <text
                    x={b.x + 11 / view.zoom}
                    y={b.y + 4 / view.zoom}
                    fontSize={11 / view.zoom}
                  >
                    {b.count}
                  </text>
                </g>
              );
            })}
          </g>
          <g
            className="map-selected-labels"
            pointerEvents="none"
            aria-hidden="true"
          >
            {labels.map((label) => (
              <g key={label.key}>
                <line
                  x1={label.point[0]}
                  y1={label.point[1]}
                  x2={Math.max(
                    label.box.x,
                    Math.min(label.box.x + label.box.width, label.point[0]),
                  )}
                  y2={Math.max(
                    label.box.y,
                    Math.min(label.box.y + label.box.height, label.point[1]),
                  )}
                  stroke="#f8b94f"
                  strokeWidth="1"
                  strokeDasharray="3 2"
                />
                <rect
                  {...label.box}
                  rx="5"
                  fill="#102733"
                  fillOpacity=".96"
                  stroke="#ba9a5c"
                />
                <text
                  x={label.box.x + 8}
                  y={label.box.y + 18}
                  fontSize="13"
                  fill="#f4ebd3"
                >
                  {label.text}
                </text>
              </g>
            ))}
          </g>
        </svg>
      </div>
      <div className="map-controls" role="group" aria-label="Map navigation">
        <button
          aria-label="Zoom map out"
          disabled={view.zoom <= 1}
          onClick={() => zoom(1 / 1.3)}
        >
          <ZoomOut size={17} />
        </button>
        <output aria-label="Map zoom">{Math.round(view.zoom * 100)}%</output>
        <button
          aria-label="Zoom map in"
          disabled={view.zoom >= 8}
          onClick={() => zoom(1.3)}
        >
          <ZoomIn size={17} />
        </button>
        <button onClick={() => change({ zoom: 1, x: 0, y: 0 })}>
          <Maximize size={15} />
          Fit world
        </button>
        <button onClick={focus} disabled={!focusable.length}>
          <LocateFixed size={15} />
          {selected.length
            ? "Fit selected areas"
            : country
              ? "Fit selected country"
              : "Fit observed areas"}
        </button>
        <button
          aria-pressed={gestures}
          onClick={() => {
            pointers.current.clear();
            drag.current = null;
            pinch.current = null;
            setDragging(false);
            setGestures(!gestures);
          }}
        >
          Zoom gestures {gestures ? "on" : "off"}
        </button>
      </div>
      <p className="map-hint">
        Drag to pan ·{" "}
        {gestures
          ? "Wheel or pinch to zoom · Scroll outside the map for details"
          : "Zoom gestures off · Wheel and touch scroll panels"}{" "}
        · Nearby areas combine at wider views.
      </p>
    </div>
  );
}
