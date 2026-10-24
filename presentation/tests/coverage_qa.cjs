// Offline response fixtures verify aggregate status in the rendered dashboard.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const url = process.env.PREVIEW_URL || 'http://127.0.0.1:8096';
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_EXECUTABLE, args:['--no-sandbox']});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const response = await page.request.get(url + '/api/overview');
    assert.equal(response.status(), 200);
    const baseline = await response.json();
    let fixture;
    const emptyAlerts = {mode:'live', as_of:baseline.as_of, checker:'ok', illustrative:false, open:[], resolved:[]};
    await page.route('**/api/alerts', route => route.fulfill({json:emptyAlerts}));
    await page.route('**/api/overview?*', route => route.fulfill({json:fixture}));
    const cases = [
      ['router stopped beyond lookback', 'router', 'stale', 1],
      ['router has no observations', 'router', 'unavailable', 1],
      ['legacy quiet router cannot certify coverage', 'router', 'quiet', 1],
      ['router source missing from response', 'router', 'missing', 1],
      ['all sources unavailable', 'all', 'unavailable', 5],
      ['capture partial alongside healthy sources', 'capture', 'partial', 1],
    ];
    for (const [name,id,state,attention] of cases) {
      fixture = structuredClone(baseline);
      fixture.mode = 'live';
      fixture.metrics.attention = 0; // Defend against an incorrectly reassuring aggregate.
      if (state === 'missing') fixture.sources = fixture.sources.filter(s => s.id !== id);
      else for (const source of fixture.sources) if (id === 'all' || source.id === id) source.state = state;
      if (id === 'router' || id === 'all') {
        fixture.metrics.router_bytes = null;
        fixture.metrics.destinations = null;
        fixture.countries = [];
      }
      await page.goto(url);
      await page.getByText('Check updates', {exact:true}).waitFor();
      assert.equal(await page.getByText('Receiving data', {exact:true}).count(), 0, name);
      assert.equal(await page.getByText('No monitoring alerts', {exact:true}).count(), 0, name);
      await page.locator('.metric').filter({hasText:'Needs attention'}).getByText(String(attention), {exact:true}).waitFor();
    }
    fixture = structuredClone(baseline);
    fixture.mode = 'live';
    fixture.metrics.capture_bytes = 0;
    fixture.metrics.busiest = null;
    await page.goto(url);
    await page.getByText('Receiving data', {exact:true}).waitFor();
    await page.getByText('No monitoring alerts', {exact:true}).waitFor();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed:[...cases.map(c => c[0]), 'healthy capture heartbeat permits observed zero'],errors}));
  } finally { await browser.close(); }
})().catch(e => {console.error(e.stack);process.exit(1)});
