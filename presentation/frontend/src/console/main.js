import "./console.css";
import { backingSize, debounce, pointerIndex } from "./chartFit.js";

const P = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  hosts:
    '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  shield:
    '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6z"/><path d="m9 12 2 2 4-4"/>',
  shieldx:
    '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6z"/><path d="m9.5 9.5 5 5m0-5-5 5"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.6 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  down: '<path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 20h14"/>',
  devices:
    '<rect x="3" y="5" width="13" height="10" rx="1.5"/><rect x="15" y="9" width="6" height="11" rx="1.5"/><path d="M6 19h6"/>',
  server:
    '<rect x="4" y="3.5" width="16" height="7" rx="1.5"/><rect x="4" y="13.5" width="16" height="7" rx="1.5"/><path d="M8 7h.01M8 17h.01M12 7h5M12 17h5"/>',
  monitor:
    '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  tv: '<rect x="2.5" y="5" width="19" height="12" rx="2"/><path d="M8 21h8M9 2l3 3 3-3"/>',
  speaker:
    '<rect x="2.5" y="8" width="19" height="8" rx="3"/><path d="M7 12h.01M11 12h.01M15 12h.01"/>',
  bellring:
    '<rect x="7" y="2.5" width="10" height="19" rx="3"/><circle cx="12" cy="9" r="2.3"/><path d="M10 16h4"/>',
  mic: '<circle cx="12" cy="13" r="7.5"/><path d="M8.5 13h.01M12 13h.01M15.5 13h.01M10 10h.01M14 10h.01M10 16h.01M14 16h.01"/>',
  thermo: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v4.5l3 2"/>',
  nas: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.5"/><path d="M4.5 5.5v13c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-13M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5"/>',
  router:
    '<rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 16.5h.01M11 16.5h.01M8 9a6 6 0 0 1 8 0M5.5 6.5a9.5 9.5 0 0 1 13 0"/>',
  wifi: '<path d="M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M2 9a14 14 0 0 1 20 0"/><circle cx="12" cy="19.5" r=".8"/>',
  dns: '<path d="M4 5h16v5H4zM4 14h16v5H4z"/><path d="M7.5 7.5h.01M7.5 16.5h.01"/>',
  rule: '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5M8.5 13h7M8.5 17h5"/>',
  swap: '<path d="M4 12a8 8 0 0 1 13.7-5.6L20 9M20 4v5h-5M20 12a8 8 0 0 1-13.7 5.6L4 15M4 20v-5h5"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
  back: '<path d="m15 6-6 6 6 6"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
};
const CATC = {
  Streaming: "#2dd4bf",
  "Apple services": "#a78bfa",
  CDN: "#60a5fa",
  "Vendor cloud": "#fbbf24",
  "Cloud storage": "#a78bfa",
  "AI models": "#2dd4bf",
  Containers: "#60a5fa",
  Updates: "#fbbf24",
  Dev: "#f472b6",
  Work: "#60a5fa",
  "Remote access": "#f472b6",
  STUN: "#f87171",
  "DNS upstream": "#2dd4bf",
  "Security feeds": "#a78bfa",
  Blocklists: "#f472b6",
  Music: "#2dd4bf",
  Ads: "#f87171",
  Other: "#64748b",
};
const RANGES = ["1h", "24h", "7d"];
const TZ = "America/New_York";

function lsGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (e) {
    return null;
  }
}
function lsSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (e) {
    /* private mode and blocked storage still render */
  }
}
const ic = (name, extra = "") =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ${extra}>${P[name] || ""}</svg>`;
const esc = (value) =>
  String(value ?? "").replace(
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
const tipAttr = (html) => `data-tip="${html.replace(/"/g, "&quot;")}"`;
function clip(text, cls = "") {
  const safe = esc(text);
  const klass = cls ? `clip ${cls}` : "clip";
  return `<span class="${klass}" title="${safe}">${safe}</span>`;
}
function chartBox(id, height) {
  return `<div class="chart" id="${id}" style="--chart-h:${Number(height)}px"></div>`;
}

function fBytes(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const value = Number(n);
  if (value < 1000) return `${Math.round(value)} B`;
  const g = value / 1e9;
  if (g >= 1000) return `${(g / 1000).toFixed(g >= 10000 ? 0 : 1)} TB`;
  if (g >= 100) return `${g.toFixed(0)} GB`;
  if (g >= 1) return `${g.toFixed(1)} GB`;
  const m = value / 1e6;
  if (m >= 10) return `${m.toFixed(0)} MB`;
  if (m >= 1) return `${m.toFixed(1)} MB`;
  const k = value / 1e3;
  return `${k >= 10 ? k.toFixed(0) : k.toFixed(1)} kB`;
}
function fBytesParts(n) {
  const text = fBytes(n);
  const index = text.lastIndexOf(" ");
  if (index < 0) return [text, ""];
  return [text.slice(0, index), text.slice(index + 1)];
}
function fN(n) {
  const value = Math.round(Number(n) || 0);
  if (value >= 1e6)
    return `${(value / 1e6).toFixed(value >= 1e7 ? 0 : 1).replace(/\.0$/, "")}M`;
  if (value >= 1e5) return `${(value / 1e3).toFixed(0)}k`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1).replace(/\.0$/, "")}k`;
  return String(value);
}
const fInt = (n) => Math.round(Number(n) || 0).toLocaleString("en-US");
function mbps(bytes, seconds) {
  if (!seconds) return 0;
  return (Number(bytes) * 8) / seconds / 1e6;
}
function fMbps(v) {
  if (v >= 10) return `${v.toFixed(1)} Mbps`;
  if (v >= 1) return `${v.toFixed(2)} Mbps`;
  return `${(v * 1000).toFixed(0)} kbps`;
}
const mFmt = (v) =>
  v === 0
    ? "0"
    : v < 1
      ? `${(v * 1000).toFixed(0)}k`
      : v % 1
        ? v.toFixed(1)
        : v.toFixed(0);

function partsOf(iso, options) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    ...options,
  }).formatToParts(date);
}
function part(parts, type) {
  return parts ? parts.find((item) => item.type === type)?.value || "" : "";
}
function fullTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return (
    new Intl.DateTimeFormat("en-US", {
      timeZone: TZ,
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
    }).format(date) + " ET"
  );
}
function timeLabel(iso, range) {
  const clock = partsOf(iso, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  if (!clock) return "";
  const hour = part(clock, "hour");
  const minute = part(clock, "minute");
  const day = part(clock, "dayPeriod");
  if (range === "7d") {
    const week = partsOf(iso, { weekday: "short" });
    return part(week, "weekday");
  }
  if (range === "1h") return `${hour}:${minute}`;
  return minute === "00" ? `${hour} ${day}` : `${hour}:${minute} ${day}`;
}
function xTicks(points, range) {
  const out = [];
  points.forEach((point, index) => {
    const clock = partsOf(point.time, {
      hour: "numeric",
      minute: "numeric",
      hourCycle: "h23",
    });
    const hour = Number(part(clock, "hour"));
    const minute = Number(part(clock, "minute"));
    if (range === "1h" && minute % 15 === 0) out.push(index);
    else if (range === "24h" && minute === 0 && hour % 4 === 0) out.push(index);
    else if (range === "7d" && hour === 0 && minute === 0) out.push(index);
  });
  if (!out.length && points.length) out.push(0);
  return out;
}
function shortTime(iso) {
  const clock = partsOf(iso, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  if (!clock) return "";
  const minute = part(clock, "minute");
  const hour = part(clock, "hour");
  const day = part(clock, "dayPeriod");
  return minute === "00" ? `${hour} ${day}` : `${hour}:${minute} ${day}`;
}

const saved = lsGet("nd-range");
const state = {
  range: RANGES.includes(saved) ? saved : "24h",
  showAll: false,
  login: false,
  loginError: "",
  error: "",
  mode: "",
  view: null,
  alerts: null,
};
const cache = new Map();
let token = 0;
let lastFetched = 0;
let chartReg = [];
let chartObserver = null;
let dprMedia = null;
const scheduleChartDraw = debounce(() => drawCharts(), 80);

function routeOf() {
  const parts = (location.hash.replace(/^#\/?/, "") || "overview").split("/");
  const page = parts[0] || "overview";
  const id = decodeURIComponent(parts[1] || "");
  const q = `range=${encodeURIComponent(state.range)}`;
  if (page === "hosts")
    return { kind: "hosts", id: "", url: `/api/network/overview?${q}` };
  if (page === "host")
    return {
      kind: "host",
      id,
      url: `/api/network/host/${encodeURIComponent(id)}?${q}`,
    };
  if (page === "firewall")
    return { kind: "firewall", id: "", url: `/api/network/firewall?${q}` };
  if (page === "dns")
    return { kind: "dns", id: "", url: `/api/network/dns?${q}` };
  if (page === "alerts") return { kind: "alerts", id: "", url: "/api/alerts" };
  if (page === "settings") return { kind: "settings", id: "", url: "" };
  return { kind: "overview", id: "", url: `/api/network/overview?${q}` };
}
function titleFor(route) {
  return (
    {
      overview: "Home Network",
      hosts: "Hosts",
      host: "Host",
      firewall: "Firewall",
      dns: "DNS",
      alerts: "Alerts",
      settings: "Settings",
    }[route.kind] || "Home Network"
  );
}
function shared(a, b) {
  return (
    (a === "overview" || a === "hosts") && (b === "overview" || b === "hosts")
  );
}

async function fetchJson(url) {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status === 401) {
    state.login = true;
    throw new Error("Sign in required");
  }
  if (response.status === 404)
    throw new Error("That host is not on the network list.");
  if (!response.ok) throw new Error("This view is unavailable right now.");
  return response.json();
}
async function cached(url) {
  if (!cache.has(url)) {
    cache.set(
      url,
      fetchJson(url).catch((err) => {
        cache.delete(url);
        throw err;
      }),
    );
  }
  return cache.get(url);
}
async function refreshAlerts() {
  try {
    state.alerts = await cached("/api/alerts");
  } catch (err) {
    if (state.login) throw err;
  }
}
async function show(force = false) {
  const seq = ++token;
  const route = routeOf();
  state.error = "";
  const matches =
    state.view &&
    state.view.range === state.range &&
    state.view.id === route.id &&
    (state.view.kind === route.kind || shared(state.view.kind, route.kind));
  if (!force && matches) {
    state.view = { ...state.view, kind: route.kind };
    render();
    return;
  }
  if (!force) render();
  try {
    if (route.kind === "settings") {
      await refreshAlerts();
      if (seq !== token) return;
      state.view = { kind: "settings", range: state.range, id: "", body: null };
    } else {
      const body = await cached(route.url);
      if (seq !== token) return;
      if (body && body.mode) state.mode = body.mode;
      if (route.kind !== "alerts") await refreshAlerts();
      if (seq !== token) return;
      state.view = { kind: route.kind, range: state.range, id: route.id, body };
    }
    if (state.alerts && state.alerts.mode) state.mode = state.alerts.mode;
    lastFetched = Date.now();
    state.login = false;
  } catch (err) {
    if (seq !== token) return;
    if (!state.login && !force) {
      state.error = err.message || "This view is unavailable right now.";
      state.view = null;
    }
  }
  render();
}

function niceMax(v) {
  if (v <= 0) return 1;
  const step = v / 4;
  const exp = 10 ** Math.floor(Math.log10(step));
  const n = step / exp;
  return 4 * (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * exp;
}
function smooth(pts) {
  if (pts.length < 3)
    return pts.map((p, i) => (i ? "L" : "M") + p[0] + "," + p[1]).join("");
  let d = `M${pts[0][0]},${pts[0][1]}`;
  const t = 0.18;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    d += `C${p1[0] + (p2[0] - p0[0]) * t},${p1[1] + (p2[1] - p0[1]) * t} ${p2[0] - (p3[0] - p1[0]) * t},${p2[1] - (p3[1] - p1[1]) * t} ${p2[0]},${p2[1]}`;
  }
  return d;
}
function chart(id, options) {
  chartReg.push([id, options]);
}
function drawChart(el, o) {
  if (!el) return;
  const values = o.series[0] && o.series[0].values;
  if (!values || values.length < 2) {
    el.innerHTML = `<div class="note">Not enough samples for a chart.</div>`;
    delete el.dataset.fit;
    return;
  }
  const rect = el.getBoundingClientRect();
  const box = backingSize(
    rect.width,
    rect.height,
    window.devicePixelRatio || 1,
  );
  if (
    box.cssWidth < 20 ||
    box.cssHeight < 20 ||
    box.width < 2 ||
    box.height < 2
  ) {
    if (el.dataset.fit) {
      el.innerHTML = "";
      delete el.dataset.fit;
    }
    return;
  }
  const sig = `${box.width}x${box.height}`;
  if (el.dataset.fit === sig && el.querySelector("svg")) return;
  const dpr = box.dpr;
  const S = (n) => n * dpr;
  const W = box.width;
  const H = box.height;
  const n = values.length;
  const stacks = [];
  let acc = new Array(n).fill(0);
  o.series.forEach((s) => {
    const lo = acc.slice();
    acc = acc.map((a, i) => a + (o.stacked ? s.values[i] : 0));
    stacks.push({
      lo: o.stacked ? lo : new Array(n).fill(0),
      hi: o.stacked ? acc.slice() : s.values.slice(),
    });
  });
  const max =
    o.max || niceMax(Math.max(...stacks.map((s) => Math.max(...s.hi))) * 1.08);
  const label = String(o.yFmt(max));
  const pl = S(Math.max(o.pl ?? 46, Math.ceil(label.length * 6.6) + 18));
  const pr = S(12);
  const pt = S(o.pt ?? 14);
  const pb = S(26);
  const w = W - pl - pr;
  const h = H - pt - pb;
  if (w < S(8) || h < S(8)) return;
  const X = (i) => pl + (i / (n - 1)) * w;
  const Y = (v) => pt + h - (Math.min(v, max) / max) * h;
  const fs = (px) => (px * dpr).toFixed(2);
  let g = "<defs>";
  o.series.forEach((s, k) => {
    g += `<linearGradient id="${el.id}g${k}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity="${s.op ?? 0.38}"/><stop offset="1" stop-color="${s.color}" stop-opacity=".03"/></linearGradient>`;
  });
  g += "</defs>";
  for (let k = 0; k <= 4; k++) {
    const v = (max * k) / 4;
    const y = Y(v);
    g += `<line class="gridl" x1="${pl}" x2="${W - pr}" y1="${y}" y2="${y}" stroke-width="${S(1)}" stroke-dasharray="${S(3)} ${S(4)}"/><text class="axis" x="${pl - S(10)}" y="${y + S(4)}" text-anchor="end" font-size="${fs(11)}">${o.yFmt(v)}</text>`;
  }
  (o.xt || []).forEach((i) => {
    const x = X(i);
    const anchor =
      x < pl + S(28) ? "start" : x > W - pr - S(28) ? "end" : "middle";
    g += `<text class="axis" x="${x}" y="${H - S(6)}" text-anchor="${anchor}" font-size="${fs(11)}">${esc(o.xl(i))}</text>`;
  });
  o.series.forEach((s, k) => {
    const top = stacks[k].hi.map((v, i) => [X(i), Y(v)]);
    const bot = stacks[k].lo.map((v, i) => [X(i), Y(v)]).reverse();
    const line = smooth(top);
    const back = smooth(bot).replace(/^M/, "L");
    g += `<path d="${line}${back}Z" fill="url(#${el.id}g${k})"/><path d="${line}" fill="none" stroke="${s.color}" stroke-width="${S(o.sw || 1.8)}" stroke-linejoin="round"/>`;
  });
  if (o.marker) {
    const m = o.marker;
    const x = X(m.i);
    const y = Y(stacks[stacks.length - 1].hi[m.i]);
    const textLen = Math.max(
      String(m.t1 || "").length,
      String(m.t2 || "").length,
    );
    const boxW = S(Math.max(92, Math.min(220, Math.ceil(textLen * 6.8) + 20)));
    const boxH = S(38);
    let bx = x - pl > boxW + S(28) ? x - boxW - S(14) : x + S(14);
    bx = Math.max(pl, Math.min(bx, W - pr - boxW));
    const by = Math.max(Math.min(y - S(6), H - pb - boxH), pt);
    g += `<line x1="${x}" x2="${x}" y1="${y}" y2="${pt + h}" stroke="${m.color}" stroke-width="${S(1)}" stroke-dasharray="${S(3)} ${S(3)}" opacity=".7"/><circle cx="${x}" cy="${y}" r="${S(4.5)}" fill="${m.color}" stroke="#0f1420" stroke-width="${S(2)}"/>`;
    g += `<g transform="translate(${bx},${by})"><rect width="${boxW}" height="${boxH}" rx="${S(8)}" fill="#0b0f18" stroke="#2b3548" stroke-width="${S(1)}"/><text x="${boxW / 2}" y="${S(16)}" text-anchor="middle" fill="#e6ebf3" font-size="${fs(12)}" font-weight="600">${esc(m.t1)}</text><text x="${boxW / 2}" y="${S(30)}" text-anchor="middle" fill="${m.color}" font-size="${fs(11)}">${esc(m.t2)}</text></g>`;
  }
  g += `<g class="hov" style="display:none"><line class="hl" y1="${pt}" y2="${pt + h}" stroke="#4a5569" stroke-width="${S(1)}"/>${o.series.map((s) => `<circle r="${S(3.5)}" fill="${s.color}" stroke="#0f1420" stroke-width="${S(2)}"/>`).join("")}</g>`;
  g += `<rect x="${pl}" y="${pt}" width="${w}" height="${h}" fill="transparent" class="ov"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">${g}</svg>`;
  el.dataset.fit = sig;
  const ov = el.querySelector(".ov");
  const hov = el.querySelector(".hov");
  const cs = hov.querySelectorAll("circle");
  const hl = hov.querySelector(".hl");
  const pad = pl / dpr;
  const tail = pr / dpr;
  ov.addEventListener("mousemove", (e) => {
    const rc = el.getBoundingClientRect();
    const i = pointerIndex(e.clientX - rc.left - pad, rc.width - pad - tail, n);
    hov.style.display = "";
    hl.setAttribute("x1", X(i));
    hl.setAttribute("x2", X(i));
    cs.forEach((c, k) => {
      c.setAttribute("cx", X(i));
      c.setAttribute("cy", Y(stacks[k].hi[i]));
    });
    showTip(o.tip(i), e.clientX, e.clientY);
  });
  ov.addEventListener("mouseleave", () => {
    hov.style.display = "none";
    hideTip();
  });
}
function drawCharts() {
  chartReg.forEach(([id, options]) =>
    drawChart(document.getElementById(id), options),
  );
}
function bindChartResize() {
  if (chartObserver) {
    chartObserver.disconnect();
    chartObserver = null;
  }
  const nodes = chartReg
    .map(([id]) => document.getElementById(id))
    .filter(Boolean);
  if (typeof ResizeObserver === "function" && nodes.length) {
    chartObserver = new ResizeObserver(() => scheduleChartDraw());
    nodes.forEach((node) => chartObserver.observe(node));
  }
  drawCharts();
}
function onDprChange() {
  watchResolution();
  scheduleChartDraw();
}
function watchResolution() {
  if (typeof matchMedia !== "function") return;
  if (dprMedia) dprMedia.removeEventListener("change", onDprChange);
  dprMedia = matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
  dprMedia.addEventListener("change", onDprChange);
}
const tip = document.getElementById("tip");
function showTip(html, x, y) {
  tip.innerHTML = html;
  tip.style.opacity = 1;
  const rect = tip.getBoundingClientRect();
  let left = x + 14;
  let top = y + 14;
  if (left + rect.width > innerWidth - 8) left = x - rect.width - 14;
  if (top + rect.height > innerHeight - 8) top = y - rect.height - 14;
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}
function hideTip() {
  tip.style.opacity = 0;
}
document.addEventListener("mouseover", (e) => {
  const node = e.target.closest("[data-tip]");
  if (node) showTip(node.dataset.tip, e.clientX, e.clientY);
});
document.addEventListener("mousemove", (e) => {
  const node = e.target.closest("[data-tip]");
  if (node) showTip(node.dataset.tip, e.clientX, e.clientY);
});
document.addEventListener("mouseout", (e) => {
  const node = e.target.closest("[data-tip]");
  if (node && !node.contains(e.relatedTarget)) hideTip();
});

function sidebar(active) {
  const dot =
    state.alerts && state.alerts.open && state.alerts.open.length
      ? `<span class="dot"></span>`
      : "";
  const items = [
    ["overview", "home", "Overview"],
    ["hosts", "hosts", "Hosts"],
    ["firewall", "shield", "Firewall"],
    ["dns", "globe", "DNS"],
    ["alerts", "bell", "Alerts"],
  ];
  return (
    `<div class="logo">nd</div>` +
    items
      .map(
        ([key, icon, label]) =>
          `<a href="#/${key}" class="${active === key ? "on" : ""}" aria-label="${label}">${ic(icon)}<span class="tt">${label}</span>${key === "alerts" ? dot : ""}</a>`,
      )
      .join("") +
    `<div class="sp"></div><a href="#/settings" class="${active === "settings" ? "on" : ""}" aria-label="Settings">${ic("gear")}<span class="tt">Settings</span></a>`
  );
}
function pill() {
  return `<div class="pill" role="group" aria-label="Time range">${RANGES.map((key) => `<button type="button" data-range="${key}" class="${key === state.range ? "on" : ""}" aria-pressed="${key === state.range}">${key}</button>`).join("")}</div>`;
}
function healthLine(health) {
  if (!health) return "";
  const klass =
    health.state === "degraded"
      ? " degraded"
      : health.state === "unavailable"
        ? " unavailable"
        : "";
  const emphasis = health.emphasis ? ` <em>${esc(health.emphasis)}</em>` : "";
  const detail = health.detail ? ` · ${esc(health.detail)}` : "";
  return `<div class="sub"><span class="health${klass}"><i></i>${esc(health.text)}${emphasis}${detail}</span></div>`;
}
function topbar({ title, health, crumb, icon, sub, data }) {
  const badge =
    data && data.illustrative ? `<span class="badge">Example data</span>` : "";
  return `<div class="top"><div>${crumb ? `<div class="crumb">${crumb}</div>` : ""}<div class="ttl">${icon ? `<div class="hicon">${ic(icon)}</div>` : ""}<div><h1 title="${esc(title)}">${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}${health || ""}</div></div></div><div class="right">${badge}${pill()}</div></div>`;
}
function kpi(icon, cls, label, val, sub, tip) {
  const title = tip ? ` title="${esc(tip)}"` : "";
  return `<div class="card kpi"><div class="ki ${cls}">${ic(icon)}</div><div><div class="kl">${esc(label)}</div><div class="kv num"${title}>${val}</div><div class="ks">${sub}</div></div></div>`;
}
function foot(data) {
  const when = data && data.as_of ? `Updated ${esc(fullTime(data.as_of))}` : "";
  const example = data && data.illustrative ? " · Example data" : "";
  const note = data && data.footnote ? ` · ${esc(data.footnote)}` : "";
  return `<div class="foot"><span>Sources: NetFlow · Pi-hole · OPNsense filterlog (VictoriaLogs)${note} · <a href="/legacy">Ops &amp; map</a></span><span>${when}${example}</span></div>`;
}
function stack(down, up, max) {
  const denom = Math.max(max, 1);
  const a = (100 * down) / denom;
  const b = (100 * up) / denom;
  return `<div class="bar">${down > 0 ? `<i class="d" style="width:${a}%" ${tipAttr(`<i style="background:#2dd4bf"></i>Download <b>${fBytes(down)}</b>`)}></i>` : ""}${up > 0 ? `<i class="u" style="width:${b}%" ${tipAttr(`<i style="background:#a78bfa"></i>Upload <b>${fBytes(up)}</b>`)}></i>` : ""}</div>`;
}
function letterIcon(name, cat) {
  const color = CATC[cat] || "#64748b";
  const letter =
    !name || name === "other" || name === "unattributed"
      ? "…"
      : esc(name[0].toUpperCase());
  return `<div class="letter" style="background:${color}">${letter}</div>`;
}
function legend() {
  return `<span class="legend"><span><i style="background:var(--teal)"></i>Download</span><span><i style="background:var(--violet)"></i>Upload</span></span>`;
}
function hostTotal(h) {
  if (h.download_bytes == null && h.upload_bytes == null) return null;
  return (h.download_bytes || 0) + (h.upload_bytes || 0);
}
function hostRow(h, max, wide) {
  const total = hostTotal(h);
  const sub = [h.type, h.location].filter(Boolean).join(" · ");
  const ip = wide ? `<div class="ip">${clip(h.ip)}</div>` : "";
  return `<a class="row click ${wide ? "hostrow hostwide" : "hostrow"}" href="#/host/${encodeURIComponent(h.id)}"><div class="ic">${ic(h.icon)}</div><div class="nm">${clip(h.name)}${sub ? `<small>${clip(sub)}</small>` : ""}</div>${ip}${stack(h.download_bytes || 0, h.upload_bytes || 0, max)}<div class="val">${fBytes(total)}</div><div class="chev">${ic("chev", 'width="14" height="14"')}</div></a>`;
}
function otherText(other) {
  if (!other || (!other.bytes && !other.hosts)) return "";
  const count = other.hosts ? `${other.hosts} others ` : "other ";
  return ` · ${count}${fBytes(other.bytes || 0)}`;
}
function windowLabel(data) {
  return (data.window && data.window.label) || "";
}

function overviewPage(data) {
  const hosts = data.hosts || [];
  const shown = state.showAll ? hosts : hosts.slice(0, 10);
  const max = hosts.reduce((m, h) => Math.max(m, hostTotal(h) || 0), 1);
  const total = data.totals.bytes;
  const step = data.throughput.step_seconds;
  const points = data.throughput.points || [];
  const values = points.map((p) => mbps(p.bytes, step));
  const peak = values.length ? Math.max(...values) : 0;
  const pi = values.indexOf(peak);
  if (points.length > 1) {
    chart("thr", {
      h: state.showAll ? 520 : 410,
      series: [{ color: "#2dd4bf", values }],
      xt: xTicks(points, state.range),
      xl: (i) => timeLabel(points[i].time, state.range),
      yFmt: mFmt,
      tip: (i) =>
        `<div class="tl">${esc(fullTime(points[i].time))}</div><i style="background:#2dd4bf"></i>${fMbps(values[i])}`,
    });
  }
  const active =
    data.totals.active_hosts == null
      ? "—"
      : `${data.totals.active_hosts}${data.totals.active_hosts_capped ? "+" : ""}`;
  const blockedSub = `firewall drops · ${data.totals.dns_blocked == null ? "—" : fN(data.totals.dns_blocked)} DNS`;
  const peakText = points.length
    ? ` · peak ${fMbps(peak)} at ${esc(timeLabel(points[pi].time, state.range === "7d" ? "24h" : state.range))}`
    : "";
  return (
    topbar({ title: "Home Network", health: healthLine(data.health), data }) +
    `<div class="kpis">${kpi("down", "c-teal", "Total traffic", fBytes(total), esc(windowLabel(data)))}${kpi("devices", "c-violet", "Active hosts", active, esc(windowLabel(data)))}<a href="#/firewall" class="card kpi link"><div class="ki c-coral">${ic("shieldx")}</div><div><div class="kl">Blocked</div><div class="kv num">${data.totals.firewall_blocks == null ? "—" : fN(data.totals.firewall_blocks)}</div><div class="ks">${blockedSub}</div></div></a></div>` +
    `<div class="grid split"><div class="card"><h3><span>Traffic by host <span class="h3s">— ${esc(windowLabel(data))}</span></span>${legend()}</h3><div class="rows">${shown.map((h) => hostRow(h, max, false)).join("") || `<div class="note">No LAN hosts in this window.</div>`}</div>${hosts.length > 10 ? `<button type="button" class="more" data-act="toggleAll">${state.showAll ? "Show top 10" : `Show all ${hosts.length} hosts`}${otherText(data.other)}</button>` : `<div class="note">${otherText(data.other).replace(/^ · /, "")}</div>`}</div>` +
    `<div class="card"><h3><span>Total throughput <span class="h3s">— ${esc(windowLabel(data))}</span></span></h3><div class="statline"><b>${total == null ? "—" : fMbps(mbps(total, data.window.seconds))}</b><span>average</span><span>${peakText}</span></div>${chartBox("thr", state.showAll ? 520 : 410)}</div></div>` +
    foot(data)
  );
}
function hostsPage(data) {
  const hosts = data.hosts || [];
  const max = hosts.reduce((m, h) => Math.max(m, hostTotal(h) || 0), 1);
  const active =
    data.totals.active_hosts == null ? hosts.length : data.totals.active_hosts;
  return (
    topbar({
      title: "Hosts",
      health: healthLine({
        state: data.health.state,
        text: `${active} active · ${hosts.length} listed`,
      }),
      data,
    }) +
    `<div class="card"><h3><span>All listed hosts <span class="h3s">— ${esc(windowLabel(data))}</span></span>${legend()}</h3><div class="rows">${hosts.map((h) => hostRow(h, max, true)).join("") || `<div class="note">No LAN hosts in this window.</div>`}</div></div>` +
    foot(data)
  );
}
function hostPage(data) {
  const h = data.host;
  const total = hostTotal(h);
  const sites = data.sites || [];
  const max = sites.reduce(
    (m, s) => Math.max(m, (s.download_bytes || 0) + (s.upload_bytes || 0)),
    1,
  );
  const cats = {};
  sites.forEach((s) => {
    const bytes = (s.download_bytes || 0) + (s.upload_bytes || 0);
    cats[s.category || "Other"] = (cats[s.category || "Other"] || 0) + bytes;
  });
  const catArr = Object.entries(cats).sort(
    (a, b) => (a[0] === "Other") - (b[0] === "Other") || b[1] - a[1],
  );
  const denom = catArr.reduce((sum, item) => sum + item[1], 0) || total || 1;
  const C = 2 * Math.PI * 52;
  let off = 0;
  const segs = catArr
    .map(([c, v]) => {
      const L = (v / denom) * C;
      const color = CATC[c] || "#64748b";
      const seg = `<circle class="seg" cx="70" cy="70" r="52" fill="none" stroke="${color}" stroke-width="16" stroke-dasharray="${Math.max(L - 2, 0.5)} ${C}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)" ${tipAttr(`<i style="background:${color}"></i>${esc(c)} <b>${fBytes(v)}</b> · ${((100 * v) / denom).toFixed(0)}%`)}/>`;
      off += L;
      return seg;
    })
    .join("");
  const [num, unit] = fBytesParts(total || 0);
  const points = (data.throughput && data.throughput.points) || [];
  const step = data.throughput.step_seconds;
  const values = points.map((p) => mbps(p.bytes, step));
  if (points.length > 1) {
    const mid = Math.floor((points.length - 1) / 2);
    chart("hthr", {
      h: 150,
      pl: 52,
      series: [{ color: "#2dd4bf", values }],
      xt: [0, mid, points.length - 1],
      xl: (i) =>
        i === points.length - 1
          ? "Now"
          : timeLabel(points[i].time, state.range),
      yFmt: mFmt,
      tip: (i) =>
        `<div class="tl">${esc(fullTime(points[i].time))}</div><i style="background:#2dd4bf"></i>${fMbps(values[i])}`,
    });
  }
  const dnsBlocked =
    data.blocked_total != null
      ? Number(data.blocked_total) || 0
      : (data.blocked || []).reduce(
          (sum, item) => sum + (item.queries || 0),
          0,
        );
  const fw = data.firewall_blocks || 0;
  const blockedTotal = dnsBlocked + fw;
  const blockedSub = fw
    ? `${fN(fw)} firewall · ${fN(dnsBlocked)} DNS`
    : `DNS queries · ${data.blocked && data.blocked.length ? `${data.blocked.length} domains` : "none"}`;
  const down = h.download_bytes == null ? "—" : fBytes(h.download_bytes);
  const up = h.upload_bytes == null ? "—" : fBytes(h.upload_bytes);
  const crumb = `<a href="#/overview">${ic("back", 'width="12" height="12" style="vertical-align:-1px"')} Overview</a><span class="sep">/</span><a href="#/hosts">Hosts</a><span class="sep">/</span><b title="${esc(h.name)}">${esc(h.name)}</b>`;
  const subBits = [`<span class="num">${esc(h.ip)}</span>`];
  if (h.location) subBits.push(esc(h.location));
  if (h.type)
    subBits.push(`<span style="color:var(--teal)">${esc(h.type)}</span>`);
  const tags = (data.blocked || [])
    .map(
      (b) =>
        `<span class="chip c" title="${esc(b.name)}" ${tipAttr(`${esc(b.name)}<br><b>${fInt(b.queries)}</b> queries blocked · ${esc(windowLabel(data))}`)}>${ic("shieldx")}${clip(b.name)} <b>${fN(b.queries)}</b></span>`,
    )
    .join("");
  const fwChip = fw
    ? `<a href="#/firewall" class="chip c" ${tipAttr(`<b>${fInt(fw)}</b> logged drops from ${esc(h.ip)}`)}>${ic("shield")}firewall drops <b>${fN(fw)}</b></a>`
    : "";
  const none =
    !tags && !fwChip
      ? `<span class="note" style="margin:0">Nothing blocked in this window.</span>`
      : "";
  const who = fw ? "by Pi-hole and OPNsense" : "by Pi-hole";
  return (
    topbar({
      title: h.name,
      icon: h.icon,
      crumb,
      sub: subBits.join('<span class="sep">·</span>'),
      data,
    }) +
    `<div class="grid split host"><div class="grid"><div class="kpis" style="margin:0">${kpi("down", "c-teal", "Total", fBytes(total), `${down} down · ${up} up`)}${kpi("globe", "c-violet", "Sites contacted", data.sites_contacted == null ? "—" : `${data.sites_contacted}${data.sites_capped ? "+" : ""}`, esc(windowLabel(data)))}${kpi("shieldx", "c-coral", "Blocked", fN(blockedTotal), blockedSub)}</div>` +
    `<div class="card"><h3><span>Traffic by site <span class="h3s">— ${esc(windowLabel(data))}</span></span>${legend()}</h3><div class="rows">${
      sites
        .map((s) => {
          const bytes = (s.download_bytes || 0) + (s.upload_bytes || 0);
          const color = CATC[s.category] || "#64748b";
          return `<div class="row siterow">${letterIcon(s.name, s.category)}<div class="nm">${clip(s.name)}</div><span class="cat" title="${esc(s.category || "Other")}"><i style="background:${color}"></i>${esc(s.category || "Other")}</span>${stack(s.download_bytes || 0, s.upload_bytes || 0, max)}<div class="val">${fBytes(bytes)}</div></div>`;
        })
        .join("") || `<div class="note">No site names in this window.</div>`
    }</div><div style="margin-top:16px;padding-top:14px;border-top:1px solid #1c2433"><h3 style="margin-bottom:10px;font-size:13px"><span>Blocked <span class="h3s">— ${who}</span></span></h3><div class="blk">${tags}${fwChip}${none}</div></div></div></div>` +
    `<div class="grid"><div class="card"><h3>By category</h3><div class="donut"><svg width="140" height="140" viewBox="0 0 140 140" style="flex:none"><circle cx="70" cy="70" r="52" fill="none" stroke="#1c2433" stroke-width="16"/>${segs}<text x="70" y="68" text-anchor="middle" fill="#e6ebf3" font-size="18" font-weight="650" class="num">${esc(num)}</text><text x="70" y="86" text-anchor="middle" fill="#8b96a8" font-size="11">${esc(unit)}</text></svg><div class="dleg">${catArr.map(([c, v]) => `<div><i style="background:${CATC[c] || "#64748b"}"></i><span>${esc(c)}<small>${fBytes(v)}</small></span><span class="pc">${((100 * v) / denom).toFixed(0)}%</span></div>`).join("") || `<div class="note">No categories.</div>`}</div></div></div>` +
    `<div class="card"><h3><span>Throughput <span class="h3s">— ${esc(windowLabel(data))}</span></span></h3><div class="statline"><b>${total == null ? "—" : fMbps(mbps(total, data.window.seconds))}</b><span>average</span></div>${chartBox("hthr", 150)}</div>` +
    `<div class="card" style="padding:14px 20px"><div class="note" style="margin:0">${esc(data.site_note || "")} <a href="#/dns">DNS for this host →</a></div></div></div></div>` +
    foot(data)
  );
}
function firewallPage(data) {
  const points = (data.series && data.series.points) || [];
  const values = points.map((p) => p.blocks || 0);
  const spike = data.spike;
  if (points.length > 1) {
    chart("fwc", {
      h: 230,
      series: [{ color: "#f87171", values, op: 0.45 }],
      xt: xTicks(points, state.range),
      xl: (i) => timeLabel(points[i].time, state.range),
      yFmt: (v) => fN(v),
      marker:
        spike && spike.index < values.length
          ? {
              i: spike.index,
              color: "#f87171",
              t1: shortTime(spike.time),
              t2: spike.detail || "spike",
            }
          : null,
      tip: (i) =>
        `<div class="tl">${esc(fullTime(points[i].time))}</div><i style="background:#f87171"></i>${fInt(values[i])} blocked`,
    });
  }
  const sources = data.sources || [];
  const smax = Math.max(
    1,
    ...sources.map((s) => s.count),
    data.other ? data.other.count : 0,
  );
  const both = (data.blocked || 0) + (data.allowed || 0);
  const pct = both ? ((100 * data.blocked) / both).toFixed(2) : null;
  const rule = data.top_rule;
  const ruleTitle = rule
    ? rule.name
      ? `${rule.label} ${rule.name}`
      : rule.label
    : "—";
  const ruleSub = rule
    ? `${rule.percent}% of ${esc(data.rule_scope || "blocks")}`
    : esc(windowLabel(data));
  const chip = spike
    ? `<span class="chip c">1 spike${spike.resolved ? ` · resolved ${esc(shortTime(spike.resolved))}` : ""}</span>`
    : `<span class="chip t">no spikes</span>`;
  return (
    topbar({ title: "Firewall", health: healthLine(data.health), data }) +
    `<div class="kpis">${kpi("shieldx", "c-coral", "Blocked", data.blocked == null ? "—" : fN(data.blocked), `${pct == null ? "" : `${pct}% of connections · `}${esc(windowLabel(data))}`)}${kpi("swap", "c-teal", "Allowed", data.allowed == null ? "—" : fN(data.allowed), esc(windowLabel(data)))}${kpi("rule", "c-violet", "Top rule", esc(ruleTitle), ruleSub, ruleTitle)}</div>` +
    `<div class="card" style="margin-bottom:16px"><h3><span>Blocks over time <span class="h3s">— ${esc(windowLabel(data))}</span></span>${chip}</h3>${chartBox("fwc", 230)}</div>` +
    `<div class="grid split even"><div class="card"><h3>Top blocked sources</h3><div class="rows">${sources
      .map((s) => {
        const inner = `<span class="sdot" style="background:${s.count && sources[0] && s.id === sources[0].id ? "var(--coral)" : "var(--dim)"}"></span><div class="nm">${clip(s.name)}</div><span class="ip">${clip(s.ip)}</span><div class="bar"><i class="b" style="width:${(100 * s.count) / smax}%" ${tipAttr(`${esc(s.name)}<br><b>${fInt(s.count)}</b> blocked`)}></i></div><div class="val">${fN(s.count)}</div><div class="chev">${ic("chev", 'width="14" height="14"')}</div>`;
        return s.link && s.id
          ? `<a class="row click srcrow" href="#/host/${encodeURIComponent(s.id)}">${inner}</a>`
          : `<div class="row srcrow">${inner}</div>`;
      })
      .join(
        "",
      )}${data.other && data.other.count ? `<div class="row srcrow"><span class="sdot"></span><div class="nm" style="color:var(--muted)">other${data.other.hosts ? ` <small style="display:inline">(${data.other.hosts} hosts)</small>` : ""}</div><span></span><div class="bar"><i class="b" style="width:${(100 * data.other.count) / smax}%;opacity:.55"></i></div><div class="val">${fN(data.other.count)}</div><span></span></div>` : ""}</div></div>` +
    `<div class="card"><h3>Top blocked destinations</h3><div class="rows">${(
      data.destinations || []
    )
      .map(
        (d) =>
          `<div class="row dstrow" ${tipAttr(`${esc(d.name)} · ${esc(d.protocol)} ${esc(d.port)}<br>${esc(d.label)}<br><b>${fInt(d.count)}</b> blocked`)}><span class="dsti">${ic("target")}</span><div class="nm">${clip(d.name, "mono")}<small>${clip(d.label || "")}</small></div><span class="chip v">${esc(d.protocol)}</span><span class="chip">${esc(d.port)}</span><div class="val">${fN(d.count)}</div></div>`,
      )
      .join(
        "",
      )}</div>${data.lists_capped ? `<div class="note">${esc(data.note || "")}</div>` : ""}</div></div>` +
    foot(data)
  );
}
function dnsPage(data) {
  const points = (data.series && data.series.points) || [];
  const answered = points.map((p) => p.answered || 0);
  const blocked = points.map((p) => p.blocked || 0);
  if (points.length > 1) {
    chart("dnsc", {
      h: 190,
      stacked: true,
      series: [
        { color: "#f87171", values: blocked, op: 0.7 },
        { color: "#2dd4bf", values: answered, op: 0.3 },
      ],
      xt: xTicks(points, state.range),
      xl: (i) => timeLabel(points[i].time, state.range),
      yFmt: (v) => fN(v),
      tip: (i) => {
        const sum = answered[i] + blocked[i];
        const pct = sum ? ((100 * blocked[i]) / sum).toFixed(1) : "0.0";
        return `<div class="tl">${esc(fullTime(points[i].time))}</div><i style="background:#2dd4bf"></i>Answered ${fInt(answered[i])}<br><i style="background:#f87171"></i>Blocked ${fInt(blocked[i])} · ${pct}%`;
      },
    });
  }
  const domains = data.domains || [];
  const dmax = domains.length ? domains[0].queries : 1;
  const queries = data.queries;
  const blockedN = data.blocked;
  const pct = queries ? ((100 * blockedN) / queries).toFixed(1) : "—";
  return (
    topbar({ title: "DNS", health: healthLine(data.health), data }) +
    `<div class="kpis">${kpi("globe", "c-teal", "Queries", queries == null ? "—" : fN(queries), esc(windowLabel(data)))}<div class="card kpi"><div class="ki c-coral">${ic("shieldx")}</div><div><div class="kl">Blocked</div><div class="kv num" style="color:var(--coral)">${pct === "—" ? "—" : `${pct}%`}</div><div class="ks">${blockedN == null ? "—" : fN(blockedN)} queries</div></div></div>${kpi("layers", "c-violet", "Unique domains", data.unique_domains == null ? "—" : fInt(data.unique_domains), esc(windowLabel(data)))}</div>` +
    `<div class="card" style="margin-bottom:16px"><h3><span>Queries over time <span class="h3s">— ${esc(windowLabel(data))}</span></span><span class="legend"><span><i style="background:var(--teal)"></i>Answered</span><span><i style="background:var(--coral)"></i>Pi-hole blocked</span></span></h3>${chartBox("dnsc", 190)}</div>` +
    `<div class="grid split even"><div class="card"><h3>Top domains</h3><div class="rows">${domains
      .map((d, i) => {
        const color = CATC[d.category] || "#64748b";
        return `<div class="row lrow"><span class="rank">${i + 1}</span><div class="nm dn"><span class="letter" style="background:${color};width:20px;height:20px;font-size:10px">${esc(d.name[0].toUpperCase())}</span>${clip(d.name)}</div><div class="bar"><i class="d" style="width:${(100 * d.queries) / dmax}%" ${tipAttr(`${esc(d.name)}<br><b>${fInt(d.queries)}</b> queries`)}></i></div><div class="val">${d.queries < 1e4 ? fInt(d.queries) : fN(d.queries)}</div></div>`;
      })
      .join("")}</div></div>` +
    `<div class="card"><h3><span>Top clients</span><span class="h3s" style="font-size:12px">blocked %</span></h3><div class="rows">${(
      data.clients || []
    )
      .map((c) => {
        const p = c.queries ? (100 * c.blocked) / c.queries : 0;
        const klass = p > 5 ? "c" : "t";
        const soft = p <= 15 && p > 5 ? "opacity:.75" : "";
        const inner = `<div class="ic">${ic(c.icon)}</div><div class="nm">${clip(c.name)}<small class="num">${clip(c.ip)}</small></div><div class="val">${fN(c.queries)}</div><span class="chip ${klass}" style="justify-self:end;${soft}" ${tipAttr(`${esc(c.name)}: ${fInt(c.blocked)} of ${fInt(c.queries)} queries blocked`)}>${ic("shield")}${p.toFixed(1)}%</span><div class="chev">${ic("chev", 'width="14" height="14"')}</div>`;
        return c.link && c.id
          ? `<a class="row click clrow" href="#/host/${encodeURIComponent(c.id)}">${inner}</a>`
          : `<div class="row clrow">${inner}</div>`;
      })
      .join("")}</div></div></div>` +
    foot(data)
  );
}
function alertsPage(alerts) {
  const open = (alerts && alerts.open) || [];
  const rows = open
    .map(
      (item) =>
        `<div class="row" style="grid-template-columns:minmax(0,1fr) auto;min-width:0"><div class="nm">${clip(item.summary || item.subject)}<small>${clip(`${item.severity || ""} · ${item.subject || ""}`)}</small></div><div class="val">${esc(item.state || "")}</div></div>`,
    )
    .join("");
  return (
    topbar({
      title: "Alerts",
      health: healthLine({
        state: open.length ? "degraded" : "healthy",
        text:
          alerts && alerts.illustrative
            ? "Example alerts"
            : open.length
              ? `${open.length} open`
              : "No open alerts",
        emphasis: open.length ? null : "clear",
      }),
      data: alerts,
    }) +
    `<div class="card"><h3>Open alerts</h3><div class="rows">${rows || `<div class="note">Nothing is open.</div>`}</div><p class="note"><a href="/legacy">Open the operations view</a> for freshness, talkers, and the full alert list.</p></div>` +
    foot(alerts)
  );
}
function settingsPage() {
  const signOut =
    state.mode === "live"
      ? `<div class="card" style="margin-top:16px"><h3>Session</h3><p class="note" style="margin-top:0">Sign out of this viewer session on this browser.</p><p><button type="button" class="more" data-act="logout">Sign out</button></p></div>`
      : "";
  return (
    topbar({ title: "Settings" }) +
    `<div class="card"><h3>Ops &amp; map</h3><p class="note" style="margin-top:0">The map, destinations, and daily operations pages are still available. They use the same sign-in and do not change how this console reads telemetry.</p><p><a class="more" href="/legacy">Open Ops &amp; map</a></p></div>` +
    signOut +
    `<div class="foot"><span><a href="/legacy">Ops &amp; map</a></span><span></span></div>`
  );
}
function loginHtml() {
  return `<div class="login-wrap"><form class="card login" id="login"><div class="logo">nd</div><h1>Home Network</h1><p>Sign in to view your network.</p><label>Username<input name="username" autocomplete="username" required maxlength="80"></label><label>Password<input name="password" type="password" autocomplete="current-password" required maxlength="512"></label>${state.loginError ? `<p class="err" role="alert">${esc(state.loginError)}</p>` : ""}<button type="submit">Sign in</button></form></div>`;
}
function pageHtml(route, body) {
  if (route.kind === "overview") return overviewPage(body);
  if (route.kind === "hosts") return hostsPage(body);
  if (route.kind === "host") return hostPage(body);
  if (route.kind === "firewall") return firewallPage(body);
  if (route.kind === "dns") return dnsPage(body);
  if (route.kind === "alerts") return alertsPage(body);
  return settingsPage();
}
function render() {
  if (chartObserver) {
    chartObserver.disconnect();
    chartObserver = null;
  }
  chartReg = [];
  hideTip();
  const app = document.getElementById("app");
  if (state.login) {
    app.innerHTML = loginHtml();
    return;
  }
  const route = routeOf();
  const active = route.kind === "host" ? "hosts" : route.kind;
  const ready =
    state.view &&
    !state.error &&
    state.view.range === state.range &&
    state.view.id === route.id &&
    (state.view.kind === route.kind || shared(state.view.kind, route.kind));
  let html;
  if (state.error) {
    html =
      topbar({ title: titleFor(route) }) +
      `<div class="card empty">${esc(state.error)}<br><a href="#/overview" style="color:var(--teal)">Back to overview</a></div>`;
  } else if (!ready) {
    html =
      topbar({ title: titleFor(route) }) +
      `<div class="card empty">Loading…</div>`;
  } else html = pageHtml(route, state.view.body);
  app.innerHTML = `<nav class="sb">${sidebar(active)}</nav><main>${html}</main>`;
  bindChartResize();
}

document.addEventListener("click", (e) => {
  const range = e.target.closest("[data-range]");
  if (range) {
    state.range = range.dataset.range;
    lsSet("nd-range", state.range);
    show();
    return;
  }
  const toggle = e.target.closest("[data-act='toggleAll']");
  if (toggle) {
    state.showAll = !state.showAll;
    render();
    return;
  }
  const logout = e.target.closest("[data-act='logout']");
  if (logout) {
    fetch("/api/session/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      credentials: "same-origin",
    })
      .catch(() => {})
      .finally(() => {
        cache.clear();
        state.view = null;
        state.alerts = null;
        state.login = true;
        render();
      });
  }
});
document.addEventListener("submit", async (e) => {
  const form = e.target.closest("#login");
  if (!form) return;
  e.preventDefault();
  const body = {
    username: new FormData(form).get("username"),
    password: new FormData(form).get("password"),
  };
  try {
    const response = await fetch("/api/session/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error("failed");
    state.login = false;
    state.loginError = "";
    cache.clear();
    show();
  } catch (err) {
    state.loginError =
      "Sign-in failed. Check your details, or wait a minute before trying again.";
    render();
  }
});
addEventListener("hashchange", () => {
  scrollTo(0, 0);
  show();
});
if (typeof ResizeObserver !== "function")
  addEventListener("resize", () => scheduleChartDraw());
watchResolution();
setInterval(() => {
  if (!document.hidden && !state.login) {
    cache.clear();
    show(true);
  }
}, 60000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !state.login && Date.now() - lastFetched >= 15000) {
    cache.clear();
    show(true);
  }
});
show();
