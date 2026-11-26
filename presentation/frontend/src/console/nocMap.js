/** Local D3 vector world map for the Real-Time NOC front page.
 *
 * Uses bundled @d3-maps/atlas 110m countries (no external tile requests).
 * Draws curved glowing arcs from Rochester, NY to active NetFlow areas (cyan)
 * and OPNsense firewall-blocked public areas (amber/orange).
 */

import { geoNaturalEarth1, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import topology from "@d3-maps/atlas/world/countries/countries-110m";

const WORLD_FEATURES = feature(
  topology,
  topology.objects.features,
).features.filter((f) => {
  const id = String(f.id ?? f.properties?.iso_n3 ?? "");
  const name = String(f.properties?.name ?? "").toLowerCase();
  // Omit Antarctica so the populated continents fill the NOC viewport cleanly.
  return id !== "010" && name !== "antarctica";
});

const WORLD_COLLECTION = {
  type: "FeatureCollection",
  features: WORLD_FEATURES,
};

// Map ISO-3166 numeric IDs or alpha-2 codes if present on atlas properties.
function countryCodeOf(feat) {
  const props = feat.properties || {};
  return String(
    props.iso_a2 || props.ISO_A2 || props.code || props.a2 || "",
  ).toUpperCase();
}

function countryNameOf(feat) {
  const props = feat.properties || {};
  return String(props.name || props.NAME || "");
}

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[ch],
  );
}

function tipAttr(html) {
  return `data-tip="${html.replace(/"/g, "&quot;")}"`;
}

function arcPath(x0, y0, x1, y1) {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const dist = Math.hypot(dx, dy);
  const mx = (x0 + x1) / 2;
  const my = (y0 + y1) / 2;
  // Lift curves gracefully northward (negative Y) proportionally to span.
  const lift = Math.min(135, Math.max(24, dist * 0.28));
  const cx = mx - dy * 0.06;
  const cy = my - lift;
  return `M${x0.toFixed(1)},${y0.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
}

function locationTip(loc, kindLabel, color, isBlock) {
  const cities =
    loc.cities && loc.cities.length ? loc.cities.join(", ") : loc.name;
  const area =
    loc.country_name && cities && !cities.includes(loc.country_name)
      ? `${cities}, ${loc.country_name}`
      : loc.country_name || loc.name || "Approximate area";
  const plural = loc.count === 1 ? "endpoint" : "endpoints";
  const dir = loc.direction ? ` · ${esc(loc.direction)}` : "";
  const hits =
    isBlock && loc.hits && loc.hits > loc.count ? ` · ${loc.hits} drops` : "";
  const hosts =
    loc.hosts && loc.hosts.length
      ? `<div style="margin-top:3px;color:#cbd5e1">Hosts: <b>${esc(loc.hosts.join(", "))}</b></div>`
      : "";
  const ports =
    loc.ports && loc.ports.length
      ? `<div style="color:#94a3b8">Ports: ${esc(loc.ports.join(", "))}</div>`
      : "";
  return (
    `<div class="tl">${esc(area)}</div>` +
    `<i style="background:${color}"></i><b>${loc.count}</b> ${kindLabel} ${plural}${hits}${dir}` +
    hosts +
    ports +
    `<div style="margin-top:4px;color:#8b96a8;font-size:11px">Approximate 0.5° DB-IP area</div>`
  );
}

/**
 * Render the NOC vector world map into `el`.
 * @param {HTMLElement|null} el
 * @param {object} mapData - `payload.map` from `/api/network/live`
 * @param {{ showFlows?: boolean, showBlocks?: boolean }} opts
 */
export function drawNocMap(el, mapData, opts = {}) {
  if (!el || !mapData) return;
  const rect = el.getBoundingClientRect();
  const width = Math.max(420, Math.round(rect.width || 720));
  const height = Math.max(260, Math.round(rect.height || 400));
  const showFlows = opts.showFlows !== false;
  const showBlocks = opts.showBlocks !== false;

  const dataKey = (list) =>
    (list || [])
      .slice(0, 12)
      .map(
        (l) =>
          `${l.id}:${l.count}:${l.hits || 0}:${(l.hosts || []).join(",")}:${(l.ports || []).join(",")}`,
      )
      .join("|");
  const sig = `${width}x${height}:${showFlows ? 1 : 0}:${showBlocks ? 1 : 0}:${(mapData.flows || []).length}:${(mapData.blocks || []).length}:${dataKey(mapData.flows)}:${dataKey(mapData.blocks)}`;
  if (el.dataset.mapSig === sig && el.querySelector("svg")) return;

  const padX = Math.round(width * 0.01);
  const padTop = Math.round(height * 0.03);
  const padBot = Math.round(height * 0.02);
  const projection = geoNaturalEarth1().fitExtent(
    [
      [padX, padTop],
      [width - padX, height - padBot],
    ],
    WORLD_COLLECTION,
  );
  const pathGen = geoPath(projection);

  const homeCoord = mapData.home || {
    lat: 43.1566,
    lon: -77.6088,
    label: "Rochester, NY",
  };
  const homePt = projection([homeCoord.lon, homeCoord.lat]) || [
    width * 0.28,
    height * 0.36,
  ];
  const [hx, hy] = homePt;

  const flowNames = new Set(
    (mapData.flow_countries || []).map((c) =>
      String(c.name || "").toLowerCase(),
    ),
  );
  const flowCodes = new Set(
    (mapData.flow_countries || []).map((c) =>
      String(c.code || "").toUpperCase(),
    ),
  );
  const blockNames = new Set(
    (mapData.block_countries || []).map((c) =>
      String(c.name || "").toLowerCase(),
    ),
  );
  const blockCodes = new Set(
    (mapData.block_countries || []).map((c) =>
      String(c.code || "").toUpperCase(),
    ),
  );

  const landSvg = WORLD_FEATURES.map((feat) => {
    const d = pathGen(feat);
    if (!d) return "";
    const code = countryCodeOf(feat);
    const name = countryNameOf(feat).toLowerCase();
    const hasFlow =
      showFlows &&
      ((code && flowCodes.has(code)) || (name && flowNames.has(name)));
    const hasBlock =
      showBlocks &&
      ((code && blockCodes.has(code)) || (name && blockNames.has(name)));
    let cls = "noc-land";
    if (hasFlow && hasBlock) cls += " both";
    else if (hasBlock) cls += " block";
    else if (hasFlow) cls += " flow";
    return `<path class="${cls}" d="${d}"/>`;
  }).join("");

  const flows = showFlows ? (mapData.flows || []).slice(0, 36) : [];
  const blocks = showBlocks ? (mapData.blocks || []).slice(0, 36) : [];
  const maxFlow = Math.max(1, ...flows.map((l) => l.count || 1));
  const maxBlock = Math.max(1, ...blocks.map((l) => l.count || 1));

  let defs = `<defs>
    <filter id="nocGlowCyan" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="3.4" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="nocGlowAmber" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="3.2" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <radialGradient id="nocNodeCyan" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#e0faff" stop-opacity="1"/>
      <stop offset="45%" stop-color="#38bdf8" stop-opacity="0.85"/>
      <stop offset="100%" stop-color="#2dd4bf" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="nocNodeAmber" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#fff3d6" stop-opacity="1"/>
      <stop offset="45%" stop-color="#fb923c" stop-opacity="0.85"/>
      <stop offset="100%" stop-color="#f59e0b" stop-opacity="0"/>
    </radialGradient>
  </defs>`;

  const renderArcs = (items, maxCount, kind) => {
    const isFlow = kind === "flow";
    const stroke = isFlow ? "#38bdf8" : "#fb923c";
    const glowStroke = isFlow ? "#2dd4bf" : "#f59e0b";
    const filter = isFlow ? "url(#nocGlowCyan)" : "url(#nocGlowAmber)";
    const nodeGrad = isFlow ? "url(#nocNodeCyan)" : "url(#nocNodeAmber)";
    const label = isFlow ? "active flow" : "blocked";
    let arcs = "";
    let dots = "";
    for (const loc of items) {
      if (loc.latitude == null || loc.longitude == null) continue;
      const pt = projection([loc.longitude, loc.latitude]);
      if (!pt) continue;
      const [x, y] = pt;
      const weight = Math.max(0.25, Math.sqrt((loc.count || 1) / maxCount));
      const d = arcPath(hx, hy, x, y);
      const sw = (1.1 + weight * 1.6).toFixed(2);
      const haloR = (6 + weight * 9).toFixed(1);
      const dotR = (2.1 + weight * 1.9).toFixed(1);
      const tip = tipAttr(locationTip(loc, label, stroke, !isFlow));
      arcs +=
        `<path class="noc-arc-glow" d="${d}" fill="none" stroke="${glowStroke}" stroke-width="${(Number(sw) * 2.5).toFixed(2)}" opacity="0.24" filter="${filter}"/>` +
        `<path class="noc-arc" d="${d}" fill="none" stroke="${stroke}" stroke-width="${sw}" opacity="${(0.55 + weight * 0.4).toFixed(2)}" stroke-linecap="round" ${tip}/>`;
      dots +=
        `<g class="noc-pt" ${tip}>` +
        `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${haloR}" fill="${nodeGrad}" opacity="0.72"/>` +
        `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${dotR}" fill="${isFlow ? "#e0faff" : "#fff1d6"}" stroke="${stroke}" stroke-width="1"/>` +
        `</g>`;
    }
    return { arcs, dots };
  };

  const flowLayer = renderArcs(flows, maxFlow, "flow");
  const blockLayer = renderArcs(blocks, maxBlock, "block");

  const homeTip = tipAttr(
    `<div class="tl">${esc(homeCoord.label || "Rochester, NY")}</div><i style="background:#2dd4bf"></i>Home gateway · OPNsense`,
  );
  const homeSvg =
    `<g class="noc-home" ${homeTip}>` +
    `<circle class="noc-home-pulse" cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="13" fill="none" stroke="#2dd4bf" stroke-width="1.4" opacity="0.55"/>` +
    `<circle cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="10" fill="url(#nocNodeCyan)" opacity="0.9"/>` +
    `<circle cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="3.4" fill="#ffffff" stroke="#2dd4bf" stroke-width="1.4"/>` +
    `</g>`;

  el.innerHTML =
    `<svg class="noc-map-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Global traffic and firewall block map">` +
    defs +
    `<g class="noc-lands">${landSvg}</g>` +
    `<g class="noc-arcs">${blockLayer.arcs}${flowLayer.arcs}</g>` +
    `<g class="noc-dots">${blockLayer.dots}${flowLayer.dots}${homeSvg}</g>` +
    `</svg>`;
  el.dataset.mapSig = sig;
}
