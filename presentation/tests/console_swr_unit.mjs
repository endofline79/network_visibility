import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  LOADING_DELAY_MS,
  PREFETCH_LIMIT,
  createCache,
  createPrefetch,
  holdForRange,
  networkUrl,
  otherViewUrls,
  paintMode,
  sameData,
  whenIdle,
} from "../frontend/src/console/swr.js";

assert.equal(LOADING_DELAY_MS, 150);
assert.equal(PREFETCH_LIMIT, 2);

assert.equal(paintMode(true, true), "immediate");
assert.equal(paintMode(true, false), "immediate");
assert.equal(paintMode(false, true), "dim");
assert.equal(paintMode(false, false), "cold");

assert.equal(sameData({ a: 1 }, { a: 1 }), true);
assert.equal(sameData({ a: 1 }, { a: 2 }), false);
assert.equal(sameData(null, null), true);
assert.equal(sameData({ a: 1 }, null), false);

const view = { kind: "overview", id: "", body: { hosts: [] } };
assert.equal(holdForRange(view, { kind: "overview", id: "" }), true);
assert.equal(holdForRange(view, { kind: "hosts", id: "" }), false);
assert.equal(holdForRange(view, { kind: "overview", id: "other" }), false);
assert.equal(holdForRange({ kind: "settings", id: "", body: null }, { kind: "settings", id: "" }), false);
assert.equal(holdForRange(null, { kind: "overview", id: "" }), false);

assert.equal(networkUrl("overview", "24h"), "/api/network/overview?range=24h");
assert.equal(networkUrl("hosts", "1h"), networkUrl("overview", "1h"));
assert.equal(
  networkUrl("host", "7d", "a b"),
  "/api/network/host/a%20b?range=7d",
);
assert.equal(networkUrl("dns", "24h"), "/api/network/dns?range=24h");
assert.equal(
  networkUrl("dns", "24h", "apple-tv"),
  "/api/network/dns?range=24h&host=apple-tv",
);
assert.deepEqual(otherViewUrls("24h", "overview"), [
  "/api/network/firewall?range=24h",
  "/api/network/dns?range=24h",
]);
assert.deepEqual(otherViewUrls("24h", "hosts", "apple-tv"), [
  "/api/network/firewall?range=24h",
  "/api/network/dns?range=24h",
  "/api/network/host/apple-tv?range=24h",
]);
assert.deepEqual(otherViewUrls("1h", "firewall"), [
  "/api/network/overview?range=1h",
  "/api/network/dns?range=1h",
]);
assert.deepEqual(otherViewUrls("24h", "host", "apple-tv"), [
  "/api/network/overview?range=24h",
  "/api/network/firewall?range=24h",
  "/api/network/dns?range=24h",
]);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function tick() {
  for (let i = 0; i < 6; i++) await Promise.resolve();
}

const calls = [];
const pending = [];
const cache = createCache((url) => {
  calls.push(url);
  const job = deferred();
  pending.push(job);
  return job.promise;
});

assert.equal(cache.peek("/a"), undefined);
const first = cache.load("/a");
const second = cache.load("/a");
assert.equal(first, second);
await tick();
assert.equal(calls.length, 1);
assert.equal(cache.peek("/a"), undefined);
pending[0].resolve({ n: 1 });
assert.deepEqual(await first, { n: 1 });
assert.deepEqual(cache.peek("/a"), { n: 1 });
assert.deepEqual(await cache.load("/a"), { n: 1 });
assert.equal(calls.length, 1);

const again = cache.revalidate("/a");
await tick();
assert.equal(calls.length, 2);
assert.deepEqual(cache.peek("/a"), { n: 1 });
pending[1].resolve({ n: 2 });
assert.deepEqual(await again, { n: 2 });
assert.deepEqual(cache.peek("/a"), { n: 2 });

const failed = cache.revalidate("/a");
await tick();
assert.equal(calls.length, 3);
pending[2].reject(new Error("offline"));
await assert.rejects(failed, /offline/);
assert.deepEqual(cache.peek("/a"), { n: 2 });

const missing = cache.load("/missing");
await tick();
pending[3].reject(new Error("nope"));
await assert.rejects(missing, /nope/);
assert.equal(cache.peek("/missing"), undefined);
assert.equal(calls.length, 4);
cache.load("/missing");
await tick();
assert.equal(calls.length, 5);
pending[4].resolve({ ok: true });
await tick();
cache.clear();
assert.equal(cache.peek("/a"), undefined);

let active = 0;
let maxActive = 0;
const blocked = [];
const prefetched = [];
const prefetchCache = createCache((url) => {
  active += 1;
  maxActive = Math.max(maxActive, active);
  const job = deferred();
  blocked.push({
    url,
    done() {
      active -= 1;
      job.resolve({ url });
    },
  });
  return job.promise;
});
const seen = [];
const prefetch = createPrefetch({
  has: (url) => prefetchCache.peek(url) !== undefined,
  load: (url) => {
    prefetched.push(url);
    return prefetchCache.load(url);
  },
  idle: (fn) => {
    seen.push(fn);
    return () => {
      const index = seen.indexOf(fn);
      if (index >= 0) seen.splice(index, 1);
    };
  },
  limit: PREFETCH_LIMIT,
});

prefetch.schedule(["/a", "/b", "/c", "/d", "/a"]);
prefetch.schedule(["/a", "/e", "/f"]);
assert.equal(seen.length, 1);
seen[0]();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(prefetched, ["/a", "/e"]);
assert.equal(maxActive, 2);
assert.equal(active, 2);
blocked[0].done();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(prefetched.slice(), ["/a", "/e", "/f"]);
assert.equal(maxActive, 2);
assert.ok(active <= 2);

let idleRan = false;
const cancelIdle = whenIdle(() => {
  idleRan = true;
});
cancelIdle();
await new Promise((resolve) => setTimeout(resolve, 50));
assert.equal(idleRan, false);

const root = new URL("../frontend/src/console/", import.meta.url);
const js = readFileSync(new URL("main.js", root), "utf8");
const css = readFileSync(new URL("console.css", root), "utf8");
assert.match(js, /cache:\s*"no-store"/);
assert.match(js, /paintMode\(/);
assert.match(js, /LOADING_DELAY_MS/);
assert.match(js, /whenIdle/);
assert.match(js, /preserveScroll:\s*true/);
assert.match(js, /setInterval\(refreshCurrent,\s*60000\)/);
assert.match(js, /sameData\(/);
assert.doesNotMatch(js, /setInterval\(\(\) => \{[\s\S]*cache\.clear\(\)/);
assert.doesNotMatch(js, /<nav class="sb">\$\{sidebar/);
assert.match(css, /main\.pending/);
assert.match(css, /pointer-events:\s*none/);
assert.match(css, /main\.pending \.pill[\s\S]*pointer-events:\s*auto/);

console.log("console swr ok");
