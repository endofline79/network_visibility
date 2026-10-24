require("node:fs").mkdirSync("artifacts", { recursive: true });
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright"),
  assert = require("node:assert/strict"),
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
    const seedPage = await browser.newPage(),
      overview = await (
        await seedPage.request.get(base + "/api/overview")
      ).json(),
      live = await (await seedPage.request.get(base + "/api/globe")).json();
    await seedPage.close();
    const area = overview.locations.find((a) => a.region === "California"),
      t = new Date(Date.now() - 2000).toISOString();
    const country = {
      code: "US",
      name: "United States",
      latitude: null,
      longitude: null,
      count: 3,
      percent: 100,
    };
    const unplaced = {
      ...area,
      id: "country-only",
      country_code: "US",
      country_name: "United States",
      name: "United States · country only",
      precision: "country",
      latitude: null,
      longitude: null,
      region: null,
      cities: [],
      count: 3,
      last_seen: t,
      activity_id: "old",
      age_buckets: [{ last_seen: t, count: 3 }],
    };
    for (const mode of ["Near-live", "Summary"])
      for (const kind of [
        "country",
        "unknown",
        "overflow",
        "withheld",
        "stale",
      ]) {
        const page = await browser.newPage({
          viewport: { width: 390, height: 844 },
          reducedMotion: "reduce",
        });
        page.on("pageerror", (e) => errors.push(e.message));
        const ov = structuredClone(overview),
          lv = structuredClone(live);
        let countries = [country],
          locations = [unplaced],
          count = 3;
        if (kind === "unknown") {
          countries = [{ ...country, code: "??", name: "Unknown location" }];
          locations = [
            {
              ...unplaced,
              id: "unknown",
              country_code: "??",
              country_name: "Unknown location",
              name: "Unknown IP location",
              precision: "unknown",
            },
          ];
          ov.geo.available = false;
          lv.geo.available = false;
        }
        if (kind === "overflow") {
          locations = [
            {
              ...area,
              id: "west",
              count: 2,
              last_seen: t,
              activity_id: "west",
              age_buckets: [{ last_seen: t, count: 2 }],
            },
            {
              ...unplaced,
              id: "overflow",
              precision: "overflow",
              name: "United States · additional areas",
              count: 1,
              age_buckets: [{ last_seen: t, count: 1 }],
            },
          ];
        }
        if (kind === "withheld") {
          countries = [];
          locations = [];
          count = null;
          ov.location_state = "withheld";
          lv.state = "partial";
        }
        if (kind === "stale") {
          lv.state = "stale";
          lv.observed_at = new Date(Date.now() - 480000).toISOString();
          locations = [
            {
              ...unplaced,
              last_seen: lv.observed_at,
              age_buckets: [{ last_seen: lv.observed_at, count: 3 }],
            },
          ];
        }
        ov.countries = countries;
        ov.locations = locations;
        ov.metrics.destinations = count;
        lv.countries = countries;
        lv.locations = locations;
        lv.endpoints = count;
        await page.route("**/api/overview?*", (r) => r.fulfill({ json: ov }));
        await page.route("**/api/globe?*", (r) => r.fulfill({ json: lv }));
        await page.goto(base);
        const view = page.locator(".world-view");
        await view.getByRole("button", { name: mode, exact: true }).click();
        await page.waitForTimeout(100);
        const expectedMapped = kind === "overflow" ? 2 : 0;
        assert.equal(
          await view
            .locator(".map-marker")
            .evaluateAll((es) =>
              es.reduce((n, e) => n + Number(e.dataset.count), 0),
            ),
          expectedMapped,
        );
        if (kind === "withheld")
          assert.match(
            await view.locator(".map-accounting").innerText(),
            /withheld/,
          );
        else if (kind === "stale" && mode === "Near-live")
          assert.match(
            await view.locator(".map-accounting").innerText(),
            /aged out/,
          );
        else {
          assert.match(
            await view.locator(".map-accounting").innerText(),
            /3 public endpoints/,
          );
          assert.match(
            await view.locator(".map-accounting").innerText(),
            new RegExp(
              `${expectedMapped} in mapped areas · ${3 - expectedMapped} not placed`,
            ),
          );
        }
        if (kind === "country" || kind === "unknown") {
          await view.locator(".map-location-list button").click();
          assert(
            await view
              .getByRole("button", { name: "Fit selected areas" })
              .isDisabled(),
          );
          assert.equal(await view.locator(".map-marker").count(), 0);
        }
        if (kind === "unknown") {
          assert(await view.locator(".map-warning").isVisible());
          await view.locator(".map-method summary").click();
          assert.match(
            await view.locator(".map-quality").innerText(),
            /database unavailable/,
          );
          await view.locator(".map-method summary").click();
        }
        if (kind === "overflow") {
          await view
            .locator('.map-location-list button[data-precision="overflow"]')
            .click();
          assert(
            await view
              .getByRole("button", { name: "Fit selected areas" })
              .isDisabled(),
          );
          assert.match(
            await view.locator(".world-selection").innerText(),
            /1 public endpoints/,
          );
        }
        for (let n = 0; n < 10; n++) {
          const zoom = view.getByRole("button", { name: "Zoom map in" });
          if (!(await zoom.isDisabled())) await zoom.click();
        }
        assert.equal(
          await view
            .locator(".map-marker")
            .evaluateAll((es) =>
              es.reduce((n, e) => n + Number(e.dataset.count), 0),
            ),
          expectedMapped,
        );
        passed.push(
          `${mode}: ${kind} locations keep honest counts at Fit and maximum zoom`,
        );
        await page.close();
      }
    assert.deepEqual(errors, []);
    fs.writeFileSync(
      "artifacts/map-quality-results.json",
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
