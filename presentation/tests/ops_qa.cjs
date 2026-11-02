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
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
  });
  const errors = [];
  const external = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (!request.url().startsWith(process.env.PREVIEW_URL || "http://127.0.0.1:8096"))
      external.push(request.url());
  });
  await page.goto(process.env.PREVIEW_URL || "http://127.0.0.1:8096");
  await page.getByText("DEMO DATA", { exact: true }).waitFor();
  await page.getByRole("heading", { name: "Your network, at a glance." }).waitFor();
  await page.getByRole("button", { name: "Ops", exact: true }).click();
  await page.getByRole("heading", { name: "Ops Home", exact: true }).waitFor();
  await page.getByText("DEMO DATA", { exact: true }).waitFor();
  await page
    .getByRole("article", { name: "OPNsense firewall: Warning" })
    .waitFor();
  await page.getByRole("article", { name: "NetFlow: Fresh" }).waitFor();
  await page.getByRole("article", { name: "Alert heartbeat: Fresh" }).waitFor();
  await page.getByRole("region", { name: "Open alerts" }).waitFor();
  await page.getByRole("button", { name: "All alerts", exact: true }).click();
  await page.getByRole("heading", { name: "Alerts", exact: true }).waitFor();
  await page.getByText("Illustrative demo alerts.").waitFor();
  await page.getByRole("button", { name: "Close details" }).click();
  await page.getByRole("table", { name: "Top LAN talkers" }).waitFor();
  await page.getByRole("cell", { name: "192.0.2.10" }).first().waitFor();
  await page.getByRole("table", { name: "Top firewall blocks" }).waitFor();
  await page.getByRole("cell", { name: "igc1", exact: true }).waitFor();
  await page.getByRole("table", { name: "Top DNS domains" }).waitFor();
  await page.getByRole("cell", { name: "example.com", exact: true }).waitFor();
  await page.getByRole("region", { name: "WAN gateway" }).getByText("Up", { exact: true }).waitFor();
  await page.getByLabel("Operations time window").selectOption("15m");
  await page.getByRole("heading", { name: "Ops Home", exact: true }).waitFor();
  await page.getByRole("button", { name: "Home", exact: true }).click();
  await page.getByRole("heading", { name: "Your network, at a glance." }).waitFor();
  assert.equal(await page.getByRole("heading", { name: "Ops Home" }).count(), 0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Ops", exact: true }).click();
  await page.getByRole("heading", { name: "Ops Home", exact: true }).waitFor();
  await page.getByRole("region", { name: "Source freshness" }).waitFor();
  await page.getByRole("table", { name: "Top firewall blocks" }).waitFor();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
  );
  assert.equal(overflow, true);
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  await browser.close();
  console.log("ops-home-layout-ok");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
