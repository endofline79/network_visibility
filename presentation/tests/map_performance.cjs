require("node:fs").mkdirSync("artifacts", { recursive: true });
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright"),
  assert = require("node:assert/strict"),
  fs = require("node:fs");
const base = process.env.PREVIEW_URL || "http://127.0.0.1:8096";
(async () => {
  const b = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const p = await b.newPage({ viewport: { width: 1440, height: 1000 } }),
      requests = [],
      errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    p.on("request", (r) => {
      if (r.url().includes("/api/globe")) requests.push(Date.now());
    });
    await p.goto(base);
    const v = p.locator(".world-view"),
      vp = v.locator(".map-viewport");
    await v.locator(".map-marker").first().waitFor();
    await p.waitForTimeout(20500);
    assert(requests.length >= 3);
    const intervals = requests.slice(1).map((t, i) => t - requests[i]);
    assert(intervals.every((n) => n >= 9900 && n < 12000));
    await p
      .locator(".country-row")
      .filter({ hasText: "United States" })
      .click();
    await v.getByRole("button", { name: "Fit selected country" }).click();
    const camera = () =>
      vp.evaluate((el) => [el.dataset.zoom, el.dataset.panX, el.dataset.panY]);
    const before = await camera();
    await p.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await p.waitForTimeout(300);
    assert.deepEqual(await camera(), before);
    await p.evaluate(() => {
      window.mapMutations = 0;
      window.mapObserver = new MutationObserver(
        (records) => (window.mapMutations += records.length),
      );
      window.mapObserver.observe(document.querySelector(".map-viewport"), {
        subtree: true,
        attributes: true,
        childList: true,
      });
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await p.waitForTimeout(100);
    const network = requests.length,
      mutations = await p.evaluate(() => window.mapMutations);
    await p.waitForTimeout(10500);
    assert.equal(requests.length, network);
    assert.equal(await p.evaluate(() => window.mapMutations), mutations);
    await p.evaluate(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: false,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await p.waitForTimeout(300);
    assert(requests.length > network);
    const box = await vp.boundingBox(),
      frameTimes = [];
    await p.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.5);
    await p.mouse.down();
    for (let i = 0; i < 12; i++) {
      const start = Date.now();
      await p.mouse.move(
        box.x + box.width * 0.4 + i * 5,
        box.y + box.height * 0.5 + i * 2,
      );
      await p.evaluate(async () => {
        await new Promise(requestAnimationFrame);
        await new Promise(requestAnimationFrame);
      });
      frameTimes.push(Date.now() - start);
    }
    await p.mouse.up();
    assert(Math.max(...frameTimes) < 100);
    assert.deepEqual(errors, []);
    const result = {
      passed: [
        "ten-second polling bounded",
        "selected camera stable across refresh",
        "hidden page pauses requests and SVG aging updates",
        "visibility resume requests promptly",
        "interactive pan frame budget under 100ms",
      ],
      poll_intervals_ms: intervals,
      pan_two_frame_ms: frameTimes,
      pan_max_two_frame_ms: Math.max(...frameTimes),
      errors,
    };
    fs.writeFileSync(
      "artifacts/map-performance-results.json",
      JSON.stringify(result, null, 2),
    );
    console.log(JSON.stringify(result));
  } finally {
    await b.close();
  }
})().catch((e) => {
  console.error(e.stack);
  process.exit(1);
});
