require("node:fs").mkdirSync("artifacts", { recursive: true });
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({
    viewport: { width: 1600, height: 1100 },
    deviceScaleFactor: 1,
  });
  const errors = [],
    external = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (!r.url().startsWith(process.env.PREVIEW_URL || "http://127.0.0.1:8096"))
      external.push(r.url());
  });
  await page.goto(process.env.PREVIEW_URL || "http://127.0.0.1:8096");
  await page.getByText("DEMO DATA", { exact: true }).waitFor();
  await page
    .getByRole("heading", { name: "Network details", exact: true })
    .waitFor();
  const areasTab = page.getByRole("tab", {
    name: "Observed areas",
    exact: true,
  });
  const activityTab = page.getByRole("tab", {
    name: "Recent activity",
    exact: true,
  });
  assert.equal(await areasTab.getAttribute("aria-selected"), "true");
  assert.equal(await page.getByRole("tabpanel").count(), 1);
  assert.equal(await page.locator(".world-heading button").count(), 0);
  assert.equal(
    await page
      .locator(".details-pane")
      .getByRole("group", { name: "Map time view" })
      .count(),
    1,
  );
  await areasTab.focus();
  for (const [key, name] of [
    ["ArrowRight", "Recent activity"],
    ["ArrowRight", "Observed areas"],
    ["ArrowLeft", "Recent activity"],
    ["Home", "Observed areas"],
    ["End", "Recent activity"],
  ]) {
    await page.keyboard.press(key);
    const active = page.getByRole("tab", { name, exact: true });
    assert.equal(await active.getAttribute("aria-selected"), "true");
    assert(await active.evaluate((e) => document.activeElement === e));
    assert.equal(
      await page.getByRole("tabpanel", { name, exact: true }).count(),
      1,
    );
  }
  await page
    .getByRole("heading", { name: "Recent activity", exact: true })
    .waitFor();
  assert(!(await page.locator(".map-location-list").isVisible()));
  await page.getByRole("button", { name: "Summary", exact: true }).click();
  assert.equal(
    await page
      .getByRole("button", { name: "Summary", exact: true })
      .getAttribute("aria-pressed"),
    "true",
  );
  assert.equal(await activityTab.getAttribute("aria-selected"), "true");
  await page.getByRole("button", { name: "Near-live", exact: true }).click();
  assert.equal(
    await page
      .getByRole("button", { name: "Near-live", exact: true })
      .getAttribute("aria-pressed"),
    "true",
  );
  await areasTab.click();
  await page.locator(".map-location-list button").first().waitFor();
  const countryCard = page.getByRole("region", {
    name: "Where activity is going",
    exact: true,
  });
  assert.equal(
    await page.locator(".map-browser, .world-country-list").count(),
    0,
  );
  assert.equal(await countryCard.locator(".country-row").count(), 9);
  assert.equal(
    await countryCard
      .locator(".country-row")
      .evaluateAll((rows) =>
        rows.reduce((sum, row) => sum + Number(row.dataset.endpoints), 0),
      ),
    200,
  );
  assert.match(
    await countryCard.locator(".panel-title p").innerText(),
    /last 5 minutes/,
  );
  const unknown = countryCard.getByRole("button", {
    name: /^Unknown locations:/,
  });
  await unknown.click();
  assert.match(
    await page.locator(".world-selection").innerText(),
    /4 public endpoints/,
  );
  assert.equal(
    await page.locator('.map-location-list [data-precision="unknown"]').count(),
    1,
  );
  assert.equal(
    await page
      .getByRole("button", { name: "Near-live", exact: true })
      .getAttribute("aria-pressed"),
    "true",
  );
  await countryCard
    .getByRole("button", { name: "All countries", exact: true })
    .click();
  assert.equal(await page.locator(".world-selection").count(), 0);
  await page.getByRole("button", { name: "Summary", exact: true }).click();
  assert.match(
    await countryCard.locator(".panel-title p").innerText(),
    /last hour/,
  );
  await page.getByRole("button", { name: "Near-live", exact: true }).click();
  await page.locator(".map-location-list button").first().waitFor();
  const expandedWidth = (await page.locator(".map-panel").boundingBox()).width;
  const frame = await page.evaluate(() => {
    const rect = (s) => document.querySelector(s).getBoundingClientRect();
    return {
      height: innerHeight,
      documentHeight: document.documentElement.scrollHeight,
      leftTop: rect(".sidebar").top,
      rightTop: rect(".details-pane").top,
      rightBottom: rect(".details-pane").bottom,
      rightWidth: rect(".details-pane").width,
      bottomCards: rect(".lower-grid").bottom,
    };
  });
  assert.equal(frame.documentHeight, frame.height);
  assert.equal(frame.rightTop, frame.leftTop);
  assert.equal(frame.rightBottom, frame.height);
  assert(frame.rightWidth < 300);
  assert(frame.bottomCards <= frame.height);
  const areas = page.locator(".map-location-list");
  const areaBox = await areas.boundingBox();
  await page.mouse.move(
    areaBox.x + areaBox.width / 2,
    areaBox.y + areaBox.height / 2,
  );
  await page.mouse.wheel(0, 160);
  await page.waitForTimeout(150);
  assert((await areas.evaluate((e) => e.scrollTop)) > 0);
  assert.equal(await page.evaluate(() => scrollY), 0);
  await page
    .getByRole("button", { name: "Collapse details pane", exact: true })
    .click();
  assert.equal(await page.locator(".details-pane").count(), 0);
  assert(
    await page
      .getByRole("button", { name: "Show details", exact: true })
      .evaluate((e) => document.activeElement === e),
  );
  assert(
    (await page.locator(".map-panel").boundingBox()).width > expandedWidth,
  );
  await page.reload();
  assert.equal(await page.locator(".details-pane").count(), 0);
  await page.getByRole("button", { name: "Show details", exact: true }).click();
  await page
    .getByRole("heading", { name: "Observed areas", exact: true })
    .waitFor();
  await page.reload();
  await page
    .getByRole("heading", { name: "Observed areas", exact: true })
    .waitFor();
  await page.getByRole("button", { name: "Summary", exact: true }).click();
  await activityTab.click();
  await page
    .locator(".country-row")
    .filter({ hasText: "United Kingdom" })
    .click();
  await page.locator(".world-selection:visible").waitFor();
  assert.match(
    await page.locator(".world-selection:visible").innerText(),
    /United Kingdom/,
  );
  const selectedText = await page.locator(".world-selection").innerText();
  await activityTab.click();
  assert(!(await page.locator(".world-selection").isVisible()));
  await areasTab.click();
  assert.equal(
    await page.locator(".world-selection").innerText(),
    selectedText,
  );
  const selectedZoom = await page
    .locator(".map-viewport")
    .getAttribute("data-zoom");
  await activityTab.click();
  await page
    .getByRole("button", { name: "Collapse details pane", exact: true })
    .click();
  assert.match(
    await page.locator(".map-selection-summary").innerText(),
    /United Kingdom/,
  );
  await page
    .getByRole("button", { name: "View selection details", exact: true })
    .click();
  assert(
    await page
      .locator("#map-selection-heading")
      .evaluate((e) => document.activeElement === e),
  );
  assert.equal(
    await page.locator(".world-selection").innerText(),
    selectedText,
  );
  assert.equal(
    await page.locator(".map-viewport").getAttribute("data-zoom"),
    selectedZoom,
  );
  await page
    .locator(".world-selection:visible")
    .getByRole("button", { name: "Details", exact: true })
    .click();
  await page.locator("dialog[open]").waitFor();
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("dialog[open]").count(), 0);
  await page
    .getByRole("button", { name: "Clear map selection", exact: true })
    .click();
  await page.getByRole("button", { name: "Devices", exact: true }).click();
  await page.getByRole("textbox", { name: "Search devices" }).fill("Phone");
  assert.equal(await page.locator(".detail-card").count(), 1);
  await page.getByRole("button", { name: "Close details" }).click();
  await page.getByRole("button", { name: "Coverage", exact: true }).click();
  await page
    .getByText("Capture kernel drops are unmeasured.", { exact: false })
    .waitFor();
  await page.getByRole("button", { name: "Close details" }).click();
  await page.getByLabel("Preview state").selectOption("stale");
  await page
    .locator(".metric")
    .filter({ hasText: "Needs attention" })
    .getByText("5", { exact: true })
    .waitFor();
  await page.getByLabel("Preview state").selectOption("unavailable");
  await page
    .locator(".metric")
    .filter({ hasText: "Devices seen" })
    .getByText("—", { exact: true })
    .waitFor();
  assert.equal(await page.locator(".map-marker").count(), 0);
  await page.getByLabel("Preview state").selectOption("normal");
  await page.getByText("Living room TV", { exact: true }).waitFor();
  await page.getByLabel("Preview state").selectOption("error");
  await page.getByRole("alert").waitFor();
  assert.equal(
    await page.getByText("Living room TV", { exact: true }).count(),
    1,
  );
  await page.getByLabel("Preview state").selectOption("normal");
  await page.getByRole("alert").waitFor({ state: "hidden" });
  await page.getByLabel("Time window").selectOption("15m");
  await page
    .locator(".metric.cyan")
    .getByText("Public endpoints · last 15 minutes", { exact: true })
    .waitFor();
  await page.getByLabel("Time window").selectOption("1h");
  await page
    .locator(".metric.cyan")
    .getByText("Public endpoints · last hour", { exact: true })
    .waitFor();
  await page.waitForTimeout(500);
  await page.screenshot({
    path: "artifacts/desktop-preview.png",
    fullPage: true,
  });
  for (const width of [390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollHeight),
      844,
    );
    if (width === 390) {
      await page.screenshot({
        path: "artifacts/mobile-preview.png",
        fullPage: true,
      });
      await page
        .getByRole("button", { name: "Collapse details pane", exact: true })
        .click();
      assert.equal(await page.locator(".details-pane").count(), 0);
      await page
        .getByRole("button", { name: "Show details", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "Observed areas", exact: true })
        .waitFor();
    }
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  console.log(
    JSON.stringify({
      passed: [
        "details pane starts open",
        "single country list includes all countries and conserves endpoint totals",
        "unknown locations filter and clear without switching Near-live to Summary",
        "country list follows map time view",
        "tabs switch with arrows, Home and End; only the selected panel is exposed",
        "map time controls work in the sidebar on either tab",
        "tab changes preserve map selection; country selection opens Observed areas",
        "viewport stays fixed with bottom cards visible",
        "right sidebar aligns with left navigation and scrolls its areas independently",
        "collapse expands map and restores focus",
        "pane preference survives reload",
        "selection survives pane collapse",
        "country selection and details",
        "keyboard dialog dismissal",
        "device search",
        "coverage drill-down",
        "stale/unavailable/error states",
        "window selection",
        "desktop/mobile/tablet layouts",
        "no external requests",
        "no JS errors",
      ],
      viewportWidths: [1600, 768, 390],
    }),
  );
  await browser.close();
})().catch((e) => {
  console.error(e.stack);
  process.exit(1);
});
