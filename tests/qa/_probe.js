/* Probe: time the column-expand state end-to-end under gate conditions. */
'use strict';
const path = require('node:path');
const { startServer } = require(path.join(__dirname, '..', 'e2e', 'harness.js'));
const FRONTEND_DIR = path.join(__dirname, '..', '..', 'frontend');
const playwright = require(require.resolve('playwright', { paths: [FRONTEND_DIR] }));

async function main() {
  const server = await startServer({ scenario: 'states' });
  const base = server.url.replace(/\/+$/, '');
  const browser = await playwright.chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  const t0 = Date.now();
  const stamp = () => `${((Date.now() - t0) / 1000).toFixed(1)}s`;
  // Gate-identical listeners.
  page.on('console', () => {});
  page.on('pageerror', () => {});
  page.on('response', () => {});
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  console.log(stamp(), 'goto done');
  await page.waitForSelector('.shell', { timeout: 15000 });
  console.log(stamp(), 'shell seen');
  await page.waitForFunction(
    "() => !document.body.innerText.includes('Loading workspace')", null, { timeout: 15000 });
  console.log(stamp(), 'workspace loaded');
  console.log(stamp(), 'cards now:', await page.locator('article.card').count());
  await page.locator("section.column[aria-label='Complete'] .column-head").click();
  console.log(stamp(), 'clicked');
  for (let i = 0; i < 30; i += 1) {
    const count = await page.locator('.jcard .jcard-title').count();
    if (count) { console.log(stamp(), `jcards visible (${count})`); break; }
    await page.waitForTimeout(500);
  }
  console.log(stamp(), 'final check via waitForSelector…');
  await page.waitForSelector('.jcard .jcard-title', { state: 'attached', timeout: 8000 });
  console.log(stamp(), 'READY check passes');
  await browser.close();
  server.stop();
}

main().then(() => process.exit(0)).catch((e) => { console.error(e.message.split('\n')[0]); process.exit(1); });
