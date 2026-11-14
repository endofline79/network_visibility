/** In-memory stale-while-revalidate cache and idle prefetch for the console. */

export const LOADING_DELAY_MS = 150;
export const PREFETCH_LIMIT = 2;

export function sameData(a, b) {
  if (a === b) return true;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch (err) {
    return false;
  }
}

export function networkUrl(kind, range, id = "") {
  const q = `range=${encodeURIComponent(range)}`;
  if (kind === "overview" || kind === "hosts")
    return `/api/network/overview?${q}`;
  if (kind === "host")
    return `/api/network/host/${encodeURIComponent(id)}?${q}`;
  if (kind === "firewall") return `/api/network/firewall?${q}`;
  if (kind === "dns")
    return id
      ? `/api/network/dns?${q}&host=${encodeURIComponent(id)}`
      : `/api/network/dns?${q}`;
  if (kind === "alerts") return "/api/alerts";
  return "";
}

/** Views to warm after the current one lands. Host detail is included on the hosts list. */
export function otherViewUrls(range, kind, hostId = "") {
  const current = networkUrl(kind, range, hostId);
  const urls = ["overview", "firewall", "dns"]
    .map((name) => networkUrl(name, range))
    .filter((url) => url && url !== current);
  if (kind === "hosts" && hostId) urls.push(networkUrl("host", range, hostId));
  return urls;
}

/** Keep the current page on screen while a new time range is still uncached. */
export function holdForRange(view, route) {
  return !!(
    view &&
    view.body != null &&
    view.kind === route.kind &&
    view.id === route.id
  );
}

/** How a navigation should paint. Cached data never waits on a loading frame. */
export function paintMode(cached, hold) {
  if (cached) return "immediate";
  if (hold) return "dim";
  return "cold";
}

export function createCache(fetchJson) {
  const entries = new Map();

  function peek(url) {
    const entry = entries.get(url);
    if (!entry || !Object.prototype.hasOwnProperty.call(entry, "data"))
      return undefined;
    return entry.data;
  }

  function settle(url, promise, data) {
    const current = entries.get(url);
    if (!current || current.promise !== promise) return;
    entries.set(url, { data });
  }

  function fail(url, promise, previous) {
    const current = entries.get(url);
    if (!current || current.promise !== promise) return;
    if (previous && Object.prototype.hasOwnProperty.call(previous, "data"))
      entries.set(url, { data: previous.data });
    else entries.delete(url);
  }

  function start(url, previous) {
    let promise;
    promise = Promise.resolve()
      .then(() => fetchJson(url))
      .then(
        (data) => {
          settle(url, promise, data);
          return data;
        },
        (err) => {
          fail(url, promise, previous);
          throw err;
        },
      );
    const next = { promise };
    if (previous && Object.prototype.hasOwnProperty.call(previous, "data"))
      next.data = previous.data;
    entries.set(url, next);
    return promise;
  }

  function load(url) {
    const entry = entries.get(url);
    if (entry?.promise) return entry.promise;
    if (entry && Object.prototype.hasOwnProperty.call(entry, "data"))
      return Promise.resolve(entry.data);
    return start(url, null);
  }

  function revalidate(url) {
    const entry = entries.get(url);
    if (entry?.promise) return entry.promise;
    return start(url, entry);
  }

  function clear() {
    entries.clear();
  }

  return { peek, load, revalidate, clear };
}

export function createLimiter(limit) {
  let active = 0;
  const queue = [];

  function drain() {
    while (active < limit && queue.length) {
      const job = queue.shift();
      active += 1;
      Promise.resolve()
        .then(job.fn)
        .then(job.resolve, job.reject)
        .finally(() => {
          active -= 1;
          drain();
        });
    }
  }

  function run(fn) {
    return new Promise((resolve, reject) => {
      queue.push({ fn, resolve, reject });
      drain();
    });
  }

  function reset() {
    queue.length = 0;
  }

  return {
    run,
    reset,
    get active() {
      return active;
    },
    get waiting() {
      return queue.length;
    },
  };
}

export function createPrefetch({
  has,
  load,
  idle,
  limit = PREFETCH_LIMIT,
} = {}) {
  const limiter = createLimiter(limit);
  let generation = 0;
  let idleCancel = () => {};

  function schedule(urls) {
    const gen = ++generation;
    limiter.reset();
    idleCancel();
    const unique = [];
    const seen = new Set();
    for (const url of urls || []) {
      if (!url || seen.has(url) || has(url)) continue;
      seen.add(url);
      unique.push(url);
    }
    if (!unique.length) {
      idleCancel = () => {};
      return;
    }
    const cancelIdle = idle(() => {
      if (gen !== generation) return;
      for (const url of unique) {
        limiter.run(() => {
          if (gen !== generation || has(url)) return undefined;
          return Promise.resolve()
            .then(() => load(url))
            .catch(() => undefined);
        });
      }
    });
    idleCancel = typeof cancelIdle === "function" ? cancelIdle : () => {};
  }

  function cancel() {
    generation += 1;
    limiter.reset();
    idleCancel();
    idleCancel = () => {};
  }

  return { schedule, cancel, limiter };
}

export function whenIdle(fn) {
  if (typeof requestIdleCallback === "function") {
    const id = requestIdleCallback(() => fn(), { timeout: 1500 });
    return () => {
      if (typeof cancelIdleCallback === "function") cancelIdleCallback(id);
    };
  }
  const id = setTimeout(fn, 32);
  return () => clearTimeout(id);
}
