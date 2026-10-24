require("node:fs").mkdirSync("artifacts", { recursive: true });
const base = process.env.PREVIEW_URL || "http://127.0.0.1:8096";
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("node:fs"),
  assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    const p = await browser.newPage({
        viewport: { width: 1440, height: 1000 },
        reducedMotion: "reduce",
      }),
      errors = [],
      external = [];
    p.on("pageerror", (e) => errors.push(e.message));
    p.on("request", (r) => {
      if (!r.url().startsWith(base)) external.push(r.url());
    });
    await p.goto(base);
    await p.getByRole("heading", { name: "External traffic map" }).waitFor();
    await p.locator(".map-marker").first().waitFor();
    await p
      .locator(".world-view")
      .screenshot({ path: "artifacts/map-initial-desktop.png" });
    await p.setViewportSize({ width: 390, height: 844 });
    await p
      .locator(".country-row")
      .filter({ hasText: "United States" })
      .click();
    await p.getByRole("button", { name: "Fit selected country" }).click();
    await p
      .locator(".world-view")
      .screenshot({ path: "artifacts/map-initial-mobile.png" });
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    console.log(
      JSON.stringify({
        errors,
        external,
        markerCount: await p.locator(".map-marker").count(),
      }),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e.stack);
  process.exit(1);
});
