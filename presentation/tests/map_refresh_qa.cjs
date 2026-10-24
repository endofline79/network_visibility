require("node:fs").mkdirSync("artifacts", { recursive: true });
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict"),
  fs = require("node:fs");
const base = process.env.PREVIEW_URL || "http://127.0.0.1:8096";
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  const passed = [],
    errors = [];
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    page.on("pageerror", (e) => errors.push(e.message));
    let seed = await (await page.request.get(base + "/api/globe")).json();
    const start = Date.now() - 30000;
    seed.countries = [
      { ...seed.countries.find((c) => c.code === "US"), count: 3 },
    ];
    const example = seed.locations.find((a) => a.region === "California");
    seed.locations = [
      {
        ...example,
        count: 3,
        last_seen: new Date(start).toISOString(),
        activity_id: "initial",
        age_buckets: [{ last_seen: new Date(start).toISOString(), count: 3 }],
      },
    ];
    seed.endpoints = 3;
    let requests = 0,
      fail = false;
    await page.route("**/api/globe?*", (r) => {
      requests++;
      return r.fulfill(
        fail
          ? { status: 503, json: { detail: "Unavailable" } }
          : { json: seed },
      );
    });
    await page.goto(base);
    const view = page.locator(".world-view"),
      vp = view.locator(".map-viewport");
    await view.locator(".map-marker").waitFor();
    const countryTotal = async (target) =>
      target
        .locator(".country-row")
        .evaluateAll((rows) =>
          rows.reduce((sum, row) => sum + Number(row.dataset.endpoints), 0),
        );
    assert.equal(await countryTotal(page), 3);
    assert.equal(await view.locator(".new-observation").count(), 0);
    await view.locator(".map-location-list button").click();
    await view.getByRole("button", { name: "Fit selected areas" }).click();
    const camera = async () => [
      await vp.getAttribute("data-zoom"),
      await vp.getAttribute("data-pan-x"),
      await vp.getAttribute("data-pan-y"),
    ];
    const orientation = await camera();
    const refresh = async () => {
      const before = requests;
      await page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      );
      await page.waitForTimeout(300);
      assert.equal(requests, before + 1);
    };
    const newer = new Date(start + 1000).toISOString();
    seed = {
      ...seed,
      as_of: new Date().toISOString(),
      locations: [
        {
          ...seed.locations[0],
          count: 4,
          last_seen: newer,
          activity_id: "new",
          age_buckets: [{ last_seen: newer, count: 4 }],
        },
      ],
      endpoints: 4,
    };
    await refresh();
    await page.waitForTimeout(1200);
    assert.match(
      await view.locator(".world-selection").innerText(),
      /4 public endpoints/,
    );
    assert.equal(await countryTotal(page), 4);
    assert.deepEqual(await camera(), orientation);
    assert.equal(await view.locator(".new-observation").count(), 1);
    passed.push(
      "new flow timestamp updates area/count and pulses without camera reset",
    );
    await view.getByRole("button", { name: "Fit world" }).click();
    assert.equal(await view.locator(".new-observation").count(), 1);
    await view.getByRole("button", { name: "Zoom map in" }).click();
    assert.equal(await view.locator(".new-observation").count(), 1);
    passed.push(
      "screen regrouping and zoom never create observation identities",
    );
    const current = seed;
    seed = {
      ...current,
      as_of: new Date(Date.parse(current.as_of) - 5000).toISOString(),
      locations: [
        {
          ...current.locations[0],
          count: 999,
          age_buckets: [{ last_seen: newer, count: 999 }],
        },
      ],
    };
    await refresh();
    assert.match(
      await view.locator(".world-selection").innerText(),
      /4 public endpoints/,
    );
    passed.push(
      "out-of-order HTTP snapshot cannot overwrite newer observations",
    );
    seed = current;
    fail = true;
    await refresh();
    assert.match(
      await view.locator(".world-freshness").innerText(),
      /Updates delayed/,
    );
    assert.match(
      await view.locator(".world-selection").innerText(),
      /4 public endpoints/,
    );
    passed.push("HTTP failure preserves locations and reports delayed refresh");
    fail = false;
    for (const state of ["partial", "unavailable"]) {
      seed = {
        ...current,
        as_of: new Date().toISOString(),
        state,
        endpoints: null,
        countries: [],
        locations: [],
      };
      await refresh();
      assert.equal(await view.locator(".map-marker").count(), 0);
      assert.equal(await countryTotal(page), 0);
      assert.match(
        await page.locator(".countries .empty").innerText(),
        state === "partial" ? /withheld/ : /unavailable/,
      );
      assert.match(
        await view.locator(".map-accounting").innerText(),
        state === "partial" ? /withheld/ : /unavailable/,
      );
      seed = { ...current, as_of: new Date().toISOString() };
      await refresh();
      await page.waitForTimeout(1100);
      assert.equal(await view.locator(".new-observation").count(), 0);
      assert.match(
        await view.locator(".world-selection").innerText(),
        /4 public endpoints/,
      );
    }
    passed.push(
      "partial/unavailable recovery preserves high-water without replay",
    );
    await view.getByRole("button", { name: "Summary", exact: true }).click();
    assert.equal(await countryTotal(page), 200);
    await view.getByRole("button", { name: "Near-live", exact: true }).click();
    await page.waitForTimeout(1300);
    assert.equal(await view.locator(".new-observation").count(), 0);
    assert.equal(await countryTotal(page), 4);
    passed.push(
      "country card switches between distinct Summary and Near-live counts",
    );
    passed.push("Summary re-entry does not replay the same area observation");
    await page.close();
    // Install clock before application timers; prove per-endpoint expiry inside a cluster.
    const aging = await browser.newPage({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
    aging.on("pageerror", (e) => errors.push(e.message));
    let fixture = await (await aging.request.get(base + "/api/globe")).json();
    const now = Date.now(),
      old = new Date(now - 280000).toISOString(),
      fresh = new Date(now - 10000).toISOString();
    fixture.locations = [
      {
        ...example,
        count: 3,
        last_seen: fresh,
        activity_id: "aging",
        age_buckets: [
          { last_seen: old, count: 2 },
          { last_seen: fresh, count: 1 },
        ],
      },
    ];
    fixture.endpoints = 3;
    await aging.route("**/api/globe?*", (r) => r.fulfill({ json: fixture }));
    await aging.clock.install();
    await aging.goto(base);
    const av = aging.locator(".world-view");
    await av.locator(".map-marker").waitFor();
    assert.equal(await countryTotal(aging), 3);
    assert.match(
      await av.locator(".map-accounting").innerText(),
      /3 public endpoints/,
    );
    await aging.clock.fastForward(21000);
    await aging.clock.runFor(1100);
    assert.match(
      await av.locator(".map-accounting").innerText(),
      /1 public endpoints/,
    );
    assert.equal(
      await av.locator(".map-marker").getAttribute("data-count"),
      "1",
    );
    assert.equal(await countryTotal(aging), 1);
    passed.push(
      "individual old endpoints expire without dropping the whole fresh area",
    );
    await aging.clock.fastForward(300000);
    await aging.clock.runFor(1100);
    assert.equal(await av.locator(".map-marker").count(), 0);
    assert.equal(await av.locator(".map-location-list button").count(), 0);
    assert.match(await av.locator(".map-accounting").innerText(), /aged out/);
    assert.equal(await countryTotal(aging), 0);
    assert.match(
      await aging.locator(".countries .empty").innerText(),
      /aged out/,
    );
    passed.push(
      "all expired saved observations disappear without claiming measured zero",
    );
    await aging.close();
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      "artifacts/map-refresh-results.json",
      JSON.stringify({ passed, errors }, null, 2),
    );
    console.log(JSON.stringify({ passed, errors }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e.stack);
  process.exit(1);
});
