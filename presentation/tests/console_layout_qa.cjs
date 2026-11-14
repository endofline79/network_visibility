const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const base = (process.env.PREVIEW_URL || "http://127.0.0.1:8096").replace(
  /\/$/,
  "",
);
const outDir = process.env.ARTIFACT_DIR || path.join(__dirname, "..", "artifacts");
fs.mkdirSync(outDir, { recursive: true });

const pages = [
  ["overview", "#/overview", "Home Network"],
  ["hosts", "#/hosts", "Hosts"],
  ["host", "#/host/apple-tv", "Living-Room Apple TV"],
  ["firewall", "#/firewall", "Firewall"],
  ["dns", "#/dns", "DNS"],
];
const viewports = [
  [1920, 1080],
  [1366, 768],
  [390, 844],
];

function shot(name) {
  return path.join(outDir, name);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
  });
  const errors = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await page.goto(base + "/#/overview", { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Home Network" }).waitFor();
  assert.equal(errors.length, 0, errors.join("\n"));

  for (const [width, height] of viewports) {
    await page.setViewportSize({ width, height });
    for (const [slug, hash, heading] of pages) {
      await page.goto(base + "/" + hash, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: heading, exact: true }).waitFor();
      await page.waitForTimeout(120);
      const layout = await page.evaluate(() => {
        const doc = document.documentElement;
        const main = document.querySelector("main");
        const nav = document.querySelector(".sb");
        const kpis = [...document.querySelectorAll(".kpis .kpi, .kpis a.kpi")];
        const rows = document.querySelector(".rows");
        const chart = document.querySelector(".chart");
        const svg = chart && chart.querySelector("svg");
        const clipped = document.querySelector(".clip");
        const mainBox = main.getBoundingClientRect();
        const navBox = nav.getBoundingClientRect();
        return {
          pageOverflow: doc.scrollWidth - doc.clientWidth,
          clientWidth: doc.clientWidth,
          mainRight: mainBox.right,
          navW: navBox.width,
          navH: navBox.height,
          navTop: navBox.top,
          kpiYs: kpis.slice(0, 3).map((el) => Math.round(el.getBoundingClientRect().top)),
          rowScroll:
            rows == null
              ? null
              : {
                  overflow: getComputedStyle(rows).overflowX,
                  sw: rows.scrollWidth,
                  cw: rows.clientWidth,
                },
          chart:
            svg == null
              ? null
              : {
                  cssW: chart.getBoundingClientRect().width,
                  cssH: chart.getBoundingClientRect().height,
                  vbW: svg.viewBox.baseVal.width,
                  vbH: svg.viewBox.baseVal.height,
                  attrW: svg.getAttribute("width"),
                  dpr: window.devicePixelRatio,
                },
          title: clipped ? clipped.getAttribute("title") : "",
          clipText: clipped ? clipped.textContent : "",
        };
      });
      assert.ok(
        layout.pageOverflow <= 1,
        `${slug} ${width} overflows the page by ${layout.pageOverflow}`,
      );
      assert.ok(
        layout.mainRight >= layout.clientWidth - 2,
        `${slug} ${width} main ends at ${layout.mainRight} of ${layout.clientWidth}`,
      );
      if (width >= 1366) {
        assert.ok(layout.navH > layout.navW, `${width} sidebar should be a vertical rail`);
        assert.ok(Math.abs(layout.navW - 68) < 2, `rail width ${layout.navW}`);
        if (layout.kpiYs.length >= 3)
          assert.equal(layout.kpiYs[0], layout.kpiYs[2], `${width} KPIs should share a row`);
      }
      if (width === 390) {
        assert.ok(layout.navW > layout.navH, "narrow nav should be a top bar");
        assert.ok(layout.navW > 300, `top bar width ${layout.navW}`);
        if (layout.kpiYs.length >= 2)
          assert.ok(layout.kpiYs[1] > layout.kpiYs[0], "narrow KPIs should stack");
        if (layout.rowScroll) {
          assert.equal(layout.rowScroll.overflow, "auto");
          assert.ok(
            layout.rowScroll.sw > layout.rowScroll.cw,
            `${slug} table should scroll inside its panel`,
          );
        }
      }
      if (layout.chart) {
        assert.equal(layout.chart.attrW, null, "chart svg must not have a fixed width");
        assert.equal(
          layout.chart.vbW,
          Math.round(layout.chart.cssW * layout.chart.dpr),
        );
        assert.equal(
          layout.chart.vbH,
          Math.round(layout.chart.cssH * layout.chart.dpr),
        );
        assert.ok(layout.chart.cssW <= width, "chart wider than the viewport");
      }
      if (layout.title)
        assert.equal(layout.title, layout.clipText, `${slug} title tooltip`);
      await page.screenshot({
        path: shot(`${slug}-${width}x${height}.png`),
        fullPage: true,
      });
    }
  }

  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto(base + "/#/overview", { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Home Network" }).waitFor();
  const mid = await page.evaluate(() => {
    const kpis = [...document.querySelectorAll(".kpis .kpi")].slice(0, 3);
    const tops = kpis.map((el) => Math.round(el.getBoundingClientRect().top));
    const nav = document.querySelector(".sb").getBoundingClientRect();
    return { tops, navW: nav.width, navH: nav.height };
  });
  assert.equal(mid.tops[0], mid.tops[1], "1024 keeps two KPI columns");
  assert.ok(mid.tops[2] > mid.tops[0], "1024 wraps the third KPI");
  assert.ok(mid.navH > mid.navW, "1024 keeps the icon rail");

  async function fittedWidth() {
    await page.waitForFunction(() => {
      const el = document.querySelector("#thr");
      const svg = el && el.querySelector("svg");
      if (!svg) return false;
      const cssW = el.getBoundingClientRect().width;
      return (
        Math.abs(svg.viewBox.baseVal.width - Math.round(cssW * devicePixelRatio)) <
        1
      );
    });
    return page.locator("#thr svg").evaluate((svg) => svg.viewBox.baseVal.width);
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(base + "/#/overview", { waitUntil: "networkidle" });
  const before = await fittedWidth();
  await page.setViewportSize({ width: 1920, height: 1080 });
  const grown = await fittedWidth();
  if (!(grown > before))
    throw new Error(`chart did not grow (${before} -> ${grown})`);
  const resized = await page.locator("#thr").evaluate((el) => {
    const svg = el.querySelector("svg");
    const box = el.getBoundingClientRect();
    return {
      cssW: box.width,
      vbW: svg.viewBox.baseVal.width,
      dpr: window.devicePixelRatio,
    };
  });
  assert.ok(resized.vbW > before, `chart did not grow (${before} -> ${resized.vbW})`);
  assert.equal(resized.vbW, Math.round(resized.cssW * resized.dpr));
  await page.locator("#thr").screenshot({ path: shot("chart-after-resize.png") });

  const crisp = await browser.newPage({
    viewport: { width: 1200, height: 800 },
    deviceScaleFactor: 2,
  });
  await crisp.goto(base + "/#/overview", { waitUntil: "networkidle" });
  await crisp.locator("#thr svg").waitFor();
  await crisp.waitForTimeout(150);
  const hi = await crisp.locator("#thr").evaluate((el) => {
    const svg = el.querySelector("svg");
    const box = el.getBoundingClientRect();
    return {
      cssW: box.width,
      vbW: svg.viewBox.baseVal.width,
      dpr: window.devicePixelRatio,
    };
  });
  assert.equal(hi.dpr, 2);
  assert.equal(hi.vbW, Math.round(hi.cssW * 2));
  await crisp.locator("#thr").screenshot({ path: shot("chart-device-pixel-ratio.png") });
  await crisp.close();

  assert.equal(errors.length, 0, errors.join("\n"));
  await browser.close();
  console.log("console layout ok");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
