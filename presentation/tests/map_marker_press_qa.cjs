require("node:fs").mkdirSync("artifacts", { recursive: true });
// Trusted mouse/pen regressions from independent review of f4cae0f106f9.
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
    errors = [],
    cases = [];
  try {
    for (const mode of ["Near-live", "Summary"])
      for (const enabled of [false, true]) {
        const page = await browser.newPage({
          viewport: { width: 1440, height: 1000 },
          reducedMotion: "reduce",
        });
        page.on("pageerror", (e) => errors.push(e.message));
        await page.addInitScript(() =>
          document.addEventListener(
            "pointerdown",
            (e) => (window.lastPointerId = e.pointerId),
          ),
        );
        await page.goto(base);
        const view = page.locator(".world-view"),
          viewport = view.locator(".map-viewport"),
          svg = viewport.locator("svg");
        await view.getByRole("button", { name: mode, exact: true }).click();
        await view.locator(".map-marker").first().waitFor();
        const target = () =>
          view.locator(".map-marker").filter({
            has: page.locator("title").filter({ hasText: "California" }),
          });
        const position = async () => {
          const clear = view.getByRole("button", {
            name: "Clear map selection",
          });
          if (await clear.count()) await clear.click();
          await page
            .locator(".country-row")
            .filter({ hasText: "United States" })
            .click();
          await view
            .getByRole("button", { name: "Fit selected country" })
            .click();
          await view
            .getByRole("button", { name: "Clear map selection" })
            .click();
          const toggle = view.getByRole("button", {
            name: /Zoom gestures (on|off)/,
          });
          if ((await toggle.getAttribute("aria-pressed")) !== String(enabled))
            await toggle.click();
          await viewport.scrollIntoViewIfNeeded();
          const b = await target().locator("circle").last().boundingBox();
          return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
        };
        for (const pattern of ["small held move", "away and back"]) {
          const p = await position();
          await page.mouse.move(p.x, p.y);
          await page.mouse.down();
          await page.mouse.move(
            p.x + (pattern === "small held move" ? 8 : 40),
            p.y,
          );
          if (pattern === "away and back") await page.mouse.move(p.x, p.y);
          await page.waitForTimeout(850);
          await page.mouse.up();
          await page.waitForTimeout(100);
          const result = {
            mode,
            gestures: enabled,
            pattern,
            selection: await view.locator(".world-selection").allTextContents(),
          };
          cases.push(result);
          assert.equal(result.selection.length, 0, JSON.stringify(result));
          passed.push(`${mode}, gestures ${enabled}: ${pattern} never selects`);
        }
        // Real mouse press followed by explicit loss of its native pointer capture.
        {
          const p = await position();
          await page.mouse.move(p.x, p.y);
          await page.mouse.down();
          await page.mouse.move(p.x + 1, p.y);
          await svg.evaluate((el) =>
            el.releasePointerCapture(window.lastPointerId),
          );
          await page.mouse.move(p.x + 1, p.y);
          await page.waitForTimeout(850);
          await page.mouse.up();
          assert.equal(
            await view.locator(".world-selection").count(),
            0,
            "capture loss and late release cannot select",
          );
          passed.push(
            `${mode}, gestures ${enabled}: lost capture consumes late release`,
          );
        }
        // Fresh physical clicks reset consumption; keyboard remains independent.
        {
          const p = await position();
          await page.mouse.click(p.x, p.y);
          assert.match(
            await view.locator(".world-selection").innerText(),
            /California/,
          );
          assert.match(
            await view.locator(".world-selection").innerText(),
            /34 public endpoints/,
          );
          await view
            .getByRole("button", { name: "Clear map selection" })
            .click();
          await target().focus();
          await page.keyboard.press("Enter");
          assert.match(
            await view.locator(".world-selection").innerText(),
            /California/,
          );
          await view
            .getByRole("button", { name: "Clear map selection" })
            .click();
          await target().focus();
          await page.keyboard.press("Space");
          assert.match(
            await view.locator(".world-selection").innerText(),
            /California/,
          );
          passed.push(
            `${mode}, gestures ${enabled}: click, Enter and Space select normally`,
          );
        }
        // CDP pen input creates an actual active browser pointer, not a synthetic event.
        {
          const p = await position(),
            cdp = await page.context().newCDPSession(page);
          const pen = (type, x, buttons) =>
            cdp.send("Input.dispatchMouseEvent", {
              type,
              x,
              y: p.y,
              button: "left",
              buttons,
              clickCount: 1,
              pointerType: "pen",
            });
          await pen("mousePressed", p.x, 1);
          await pen("mouseMoved", p.x + 8, 1);
          await page.waitForTimeout(850);
          await pen("mouseReleased", p.x + 8, 0);
          assert.equal(await view.locator(".world-selection").count(), 0);
          passed.push(
            `${mode}, gestures ${enabled}: moved held pen cannot select`,
          );
        }
        const p = await position();
        await page.mouse.click(p.x, p.y);
        await view.screenshot({
          path: `artifacts/map-selected-${mode}-${enabled ? "on" : "off"}.png`,
        });
        const label = view.locator(".map-selected-labels");
        assert.equal(await label.getAttribute("pointer-events"), "none");
        assert.match(await label.textContent(), /California/);
        assert(
          +(await view
            .locator(".map-hint")
            .evaluate((e) => getComputedStyle(e).fontSize.replace("px", ""))) >=
            13,
        );
        assert(
          +(await view
            .locator(".map-quality")
            .evaluate((e) => getComputedStyle(e).fontSize.replace("px", ""))) >=
            13,
        );
        passed.push(
          `${mode}, gestures ${enabled}: legible hints and passive selected-region label`,
        );
        await page.close();
      }
    assert.deepEqual(errors, []);
    const result = { passed, cases, errors };
    fs.writeFileSync(
      "artifacts/map-marker-press-results.json",
      JSON.stringify(result, null, 2),
    );
    console.log(JSON.stringify({ passed, cases: cases.length, errors }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e.stack);
  process.exit(1);
});
