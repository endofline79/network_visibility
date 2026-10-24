require("node:fs").mkdirSync("artifacts", { recursive: true });
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("node:fs"),
  assert = require("node:assert/strict");
const base = process.env.PREVIEW_URL || "http://127.0.0.1:8096";
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  const passed = [],
    errors = [],
    external = [];
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
      reducedMotion: "reduce",
    });
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (!r.url().startsWith(base)) external.push(r.url());
    });
    await page.goto(base);
    const view = page.locator(".world-view"),
      viewport = view.locator(".map-viewport"),
      svg = viewport.locator("svg");
    await view.getByRole("heading", { name: "External traffic map" }).waitFor();
    await view.locator(".map-marker").first().waitFor();
    const z = async () => +(await viewport.getAttribute("data-zoom")),
      pan = async () => [
        +(await viewport.getAttribute("data-pan-x")),
        +(await viewport.getAttribute("data-pan-y")),
      ];
    const counts = async () => ({
      map: await view
        .locator(".map-marker")
        .evaluateAll((es) =>
          es.reduce((n, e) => n + Number(e.dataset.count), 0),
        ),
      list: await view
        .locator(".map-location-list button b")
        .evaluateAll((es) => es.reduce((n, e) => n + Number(e.textContent), 0)),
    });
    assert.deepEqual(await counts(), { map: 196, list: 200 });
    assert.match(
      await view.locator(".map-accounting").innerText(),
      /196 in mapped areas · 4 not placed/,
    );
    assert.equal(await view.locator('[data-precision="unknown"]').count(), 1);
    passed.push("mapped/unplaced counts conserve all 200 public endpoints");
    const regions = await view.locator(".map-location-list").innerText();
    assert.match(regions, /California/);
    assert.match(regions, /Virginia/);
    assert.match(regions, /New York/);
    const method = view.locator(".map-method summary");
    await method.click();
    assert.match(
      await view.locator(".map-quality").innerText(),
      /not an accuracy guarantee/,
    );
    await method.click();
    assert.equal(await view.locator(".confidence-circle").count(), 0);
    passed.push("US California/East Coast areas and honest quality labels");
    await page
      .locator(".country-row")
      .filter({ hasText: "United States" })
      .click();
    assert.equal(
      (await view.locator(".map-location-list button").all()).length,
      3,
    );
    assert.match(
      await view.locator(".world-selection").innerText(),
      /84 public endpoints/,
    );
    await view.getByRole("button", { name: "Fit selected country" }).click();
    assert((await z()) > 1);
    const before = await pan();
    await view
      .locator(".map-location-list button")
      .filter({ hasText: "California" })
      .click();
    assert.match(
      await view.locator(".world-selection").innerText(),
      /California/,
    );
    assert.match(
      await view.locator(".world-selection").innerText(),
      /34 public endpoints/,
    );
    assert.match(
      await view.locator(".world-selection").innerText(),
      /accuracy radius unavailable/,
    );
    assert.deepEqual(await pan(), before);
    passed.push("country filter, Fit selected and area detail preserve pan");
    await view.getByRole("button", { name: "Fit world" }).click();
    assert.equal(await z(), 1);
    assert.deepEqual(await pan(), [0, 0]);
    for (let i = 0; i < 12; i++) {
      const b = view.getByRole("button", { name: "Zoom map in" });
      if (!(await b.isDisabled())) await b.click();
    }
    assert.equal(await z(), 8);
    assert.deepEqual(await counts(), { map: 196, list: 84 });
    assert(
      await view.getByRole("button", { name: "Zoom map in" }).isDisabled(),
    );
    await svg.focus();
    await page.keyboard.press("ArrowLeft");
    assert.notDeepEqual(await pan(), [0, 0]);
    await page.keyboard.press("-");
    assert((await z()) < 8);
    await page.keyboard.press("Home");
    assert.equal(await z(), 1);
    passed.push("hard zoom bounds and keyboard pan/fit");
    await viewport.scrollIntoViewIfNeeded();
    let box = await viewport.boundingBox();
    await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.65);
    const scroll = await page.evaluate(() => scrollY);
    await page.mouse.wheel(0, 160);
    await page.waitForTimeout(150);
    assert.equal(await z(), 1);
    assert.equal(await page.evaluate(() => scrollY), scroll);
    passed.push("ordinary wheel does not zoom or move the fixed page");
    await view.getByRole("button", { name: "Zoom gestures off" }).click();
    await viewport.scrollIntoViewIfNeeded();
    box = await viewport.boundingBox();
    await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.5);
    await page.mouse.wheel(0, -200);
    await page.waitForTimeout(100);
    assert((await z()) > 1);
    passed.push("opt-in wheel zoom");
    await view.getByRole("button", { name: "Fit world" }).click();
    await view.getByRole("button", { name: "Clear map selection" }).click();
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.waitForTimeout(100);
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      assert.deepEqual(await counts(), { map: 196, list: 200 });
    }
    passed.push(
      "five responsive sizes preserve all mapped and unplaced counts",
    );
    await page.setViewportSize({ width: 1440, height: 1000 });
    await view.getByRole("button", { name: "Summary", exact: true }).click();
    assert.deepEqual(await counts(), { map: 196, list: 200 });
    await page
      .locator(".country-row")
      .filter({ hasText: "United States" })
      .click();
    await view.getByRole("button", { name: "Fit selected country" }).click();
    await view.screenshot({ path: "artifacts/map-summary-desktop.png" });
    await view
      .locator(".map-location-list button")
      .filter({ hasText: "Virginia" })
      .click();
    await view.getByRole("button", { name: "Details", exact: true }).click();
    await page.locator("dialog[open]").waitFor();
    await page.keyboard.press("Escape");
    passed.push("Summary keeps domestic spread and historical Details");
    await page.getByLabel("Preview state").selectOption("unavailable");
    await page.waitForTimeout(150);
    assert.equal(await view.locator(".map-marker").count(), 0);
    assert.equal(await view.locator(".map-location-list button").count(), 0);
    assert.match(
      await view.locator(".map-accounting").innerText(),
      /unavailable/,
    );
    await page.getByLabel("Preview state").selectOption("normal");
    await view.locator(".map-marker").first().waitFor();
    passed.push("unavailable observations do not become fake points");
    await page.close();
    // Trusted mobile touches exercise the same pointer handlers used for marker taps.
    const mobile = await browser.newPage({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      reducedMotion: "reduce",
    });
    mobile.on("pageerror", (e) => errors.push(e.message));
    await mobile.goto(base);
    const mv = mobile.locator(".world-view"),
      vp = mv.locator(".map-viewport");
    await mv.locator(".map-marker").first().waitFor();
    const mz = async () => +(await vp.getAttribute("data-zoom"));
    await mobile
      .locator(".country-row")
      .filter({ hasText: "United States" })
      .click();
    await mv.getByRole("button", { name: "Fit selected country" }).click();
    await vp.scrollIntoViewIfNeeded();
    const ca = mv.locator(".map-marker").filter({
      has: mobile.locator("title").filter({ hasText: "California" }),
    });
    let b = await ca.locator("circle").last().boundingBox();
    await mobile.touchscreen.tap(b.x + b.width / 2, b.y + b.height / 2);
    assert.match(
      await mv.locator(".world-selection").innerText(),
      /California/,
    );
    assert.match(
      await mv.locator(".world-selection").innerText(),
      /34 public endpoints/,
    );
    passed.push("trusted mobile California tap selects the advertised area");
    const cdp = await mobile.context().newCDPSession(mobile),
      touch = (type, touchPoints) =>
        cdp.send("Input.dispatchTouchEvent", { type, touchPoints });
    for (const enabled of [false, true]) {
      const clear = mv.getByRole("button", { name: "Clear map selection" });
      if (await clear.count()) await clear.click();
      await mobile
        .locator(".country-row")
        .filter({ hasText: "United States" })
        .click();
      await mv.getByRole("button", { name: "Fit selected country" }).click();
      await mv.getByRole("button", { name: "Clear map selection" }).click();
      const toggle = mv.getByRole("button", { name: /Zoom gestures (on|off)/ });
      if ((await toggle.getAttribute("aria-pressed")) !== String(enabled))
        await toggle.click();
      await vp.scrollIntoViewIfNeeded();
      b = await ca.locator("circle").last().boundingBox();
      const x = b.x + b.width / 2,
        y = b.y + b.height / 2;
      await touch("touchStart", [{ id: 1, x, y }]);
      await touch("touchMove", [{ id: 1, x: x + 40, y }]);
      await mobile.waitForTimeout(850);
      await touch("touchEnd", []);
      assert.equal(await mv.locator(".world-selection").count(), 0);
      passed.push(`held marker drag never selects, gestures ${enabled}`);
    }
    await vp.scrollIntoViewIfNeeded();
    b = await vp.boundingBox();
    const x = b.x + b.width / 2,
      y = b.y + b.height / 2,
      old = await mz();
    await touch("touchStart", [
      { id: 1, x: x - 25, y },
      { id: 2, x: x + 25, y },
    ]);
    await touch("touchMove", [
      { id: 1, x: x - 90, y },
      { id: 2, x: x + 90, y },
    ]);
    await touch("touchEnd", []);
    assert((await mz()) >= old && (await mz()) <= 8);
    assert.equal(await mv.locator(".world-selection").count(), 0);
    passed.push("pinch is bounded and cannot select an area");
    await mv.getByRole("button", { name: "Fit world" }).click();
    await mv.getByRole("button", { name: "Zoom gestures on" }).click();
    await vp.scrollIntoViewIfNeeded();
    b = await vp.boundingBox();
    const scrollBefore = await mobile
      .locator("main")
      .evaluate((e) => e.scrollTop);
    await touch("touchStart", [
      { id: 1, x: b.x + b.width * 0.85, y: b.y + b.height * 0.75 },
    ]);
    await touch("touchMove", [
      { id: 1, x: b.x + b.width * 0.85, y: b.y + b.height * 0.25 },
    ]);
    await touch("touchEnd", []);
    await mobile.waitForTimeout(250);
    assert(
      (await mobile.locator("main").evaluate((e) => e.scrollTop)) >
        scrollBefore,
    );
    assert.equal(await mobile.evaluate(() => scrollY), 0);
    assert.equal(await mz(), 1);
    passed.push(
      "default vertical touch scrolls the mobile center pane, not the page",
    );
    await mobile
      .locator(".country-row")
      .filter({ hasText: "United States" })
      .click();
    await mv.getByRole("button", { name: "Fit selected country" }).click();
    await mv.screenshot({ path: "artifacts/map-nearlive-mobile.png" });
    assert.equal(await mv.locator(".new-observation").count(), 0);
    passed.push("reduced motion does not pulse");
    await mobile.close();
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    passed.push("no JS errors or external requests");
    fs.writeFileSync(
      "artifacts/map-qa-results.json",
      JSON.stringify({ passed, errors, external }, null, 2),
    );
    console.log(JSON.stringify({ passed, errors, external }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e.stack);
  process.exit(1);
});
