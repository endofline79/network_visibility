const fs = require("node:fs"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const helper = fs
  .readFileSync("frontend/src/observationTime.ts", "utf8")
  .replace(
    "export function observationTime(value: string): bigint | null",
    "function observationTime(value)",
  );
const observationTime = vm.runInNewContext(helper + ";observationTime");
assert(
  observationTime("2026-10-06T01:00:00.000200Z") >
    observationTime("2026-10-06T01:00:00.000100Z"),
);
assert.equal(
  observationTime("2026-10-06T01:00:00.000100Z"),
  observationTime("2026-10-06T02:00:00.000100+01:00"),
);
assert.equal(observationTime("invalid"), null);
const s = fs.readFileSync("frontend/src/observationHistory.ts", "utf8"),
  begin = s.indexOf("  const visibleIds"),
  end = s.lastIndexOf("}");
assert(begin > 0 && end > begin);
const update = vm.runInNewContext(
  "function updateHistory(history,initialized,locations,nearLive,receivedAt){" +
    s.slice(begin, end) +
    "};updateHistory",
  { observationTime },
);
const history = new Map(),
  initialized = { current: false };
let now = Date.parse("2026-10-06T01:00:00Z");
const first = {
  id: "US-CA-area",
  last_seen: new Date(now - 30000).toISOString(),
  activity_id: "baseline",
};
const apply = (a, live = true) => update(history, initialized, a, live, now);
apply([first]);
assert.equal(history.get(first.id).until, 0);
apply([]);
apply([first]);
assert.equal(history.get(first.id).until, 0);
const newer = {
  ...first,
  last_seen: new Date(now - 10000).toISOString(),
  activity_id: "new",
};
apply([newer]);
assert.equal(history.get(first.id).until, now + 8000);
apply([]);
assert.equal(history.get(first.id).until, 0);
apply([newer]);
assert.equal(history.get(first.id).until, 0);
apply([first]);
assert.equal(history.get(first.id).lastSeen, newer.last_seen);
apply([], false);
apply([newer]);
assert.equal(history.get(first.id).until, 0);
const many = Array.from({ length: 300 }, (_, i) => ({
  id: "area" + i,
  last_seen: new Date(now - 5000 + i).toISOString(),
  activity_id: String(i),
}));
apply(many);
assert.equal(history.size, 256);
assert(history.has("area299"));
now += 600001;
apply([]);
assert.equal(history.size, 0);
console.log(
  JSON.stringify({
    passed: [
      "timestamp precision and normalization",
      "actual helper preserves initial baseline",
      "disappearance cancels pulse without replay",
      "older and duplicate area observations cannot replay",
      "Summary re-entry preserves history",
      "actual area history bounded to 256 and expires after ten minutes",
    ],
  }),
);
