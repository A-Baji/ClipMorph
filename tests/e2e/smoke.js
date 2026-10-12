// Issue #259 Playwright smoke test (issue-level Verification block).
//
// Minimal acceptance flow, run against the shared harness server:
//   fixtures → board renders → create flow reaches the board
//
// Booted via tests/e2e/harness.js (the node wrapper around
// harness.py --serve) so the smoke test, the audit, and the re-audit all
// serve the identical seeded workspace. Playwright is resolved from the
// frontend/ install — the repository structure policy forbids a root
// package.json, so tests must not depend on one.
'use strict';

const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { startServer } = require('./harness.js');

const FRONTEND_DIR = path.join(__dirname, '..', '..', 'frontend');

let playwright;
try {
  playwright = require(require.resolve('playwright', { paths: [FRONTEND_DIR] }));
} catch (error) {
  console.error(
    'Playwright is not installed. Run `npm --prefix frontend install` and\n' +
    'install its chromium browser first:\n' +
    '  npx --prefix frontend playwright install chromium\n' +
    String(error),
  );
  process.exit(1);
}

const BROWSER = process.env.CLIPMORPH_BROWSER || 'chromium';

/** Poll the API until the seeded fixture sources answer. */
async function waitForFixture(baseUrl, { timeoutMs = 15000 } = {}) {
  const started = Date.now();
  for (;;) {
    try {
      const response = await fetch(`${baseUrl}/api/v1/sources`);
      if (response.ok) {
        const sources = await response.json();
        if (Array.isArray(sources) && sources.some((item) => item.name && item.name.startsWith('status-'))) {
          return;
        }
      }
    } catch {
      /* server not up yet */
    }
    if (Date.now() - started > timeoutMs) {
      throw new Error(`fixture sources not visible within ${timeoutMs}ms`);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
}

/**
 * A unique transient clip for the wizard's in-place add (the seeded sources
 * all share one content hash, so creating one of them would be rejected as a
 * duplicate and the create could never land).
 */
function makeTransientClip() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'clipmorph-smoke-'));
  const file = path.join(dir, 'smoke-clip.mp4');
  fs.writeFileSync(file, Buffer.from(`clipmorph-smoke-${Date.now()}`, 'utf8'));
  return { dir, file };
}

/** Best-effort removal of the transient clip directory. */
function cleanup(clip) {
  try {
    fs.rmSync(clip.dir, { recursive: true, force: true });
  } catch {
    /* best effort */
  }
}

async function main() {
  const server = await startServer({ scenario: 'states' });
  // The harness reports the base URL with a trailing slash; API paths below
  // are appended so it must be stripped once (FastAPI rejects `//api/v1/...`).
  const base = server.url.replace(/\/+$/, '');
  const clip = makeTransientClip();
  let browserRef = null;
  try {
    await waitForFixture(base);
    browserRef = await playwright[BROWSER].launch();
    const page = await browserRef.newPage({
      viewport: server.viewports.desktop,
    });
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(String(error)));
    await page.goto(base, { waitUntil: 'domcontentloaded' });

    // A1: the Topbar header names the workspace.
    await page.waitForSelector('header.topbar h1', { timeout: 15000 });
    assert.equal(
      (await page.textContent('header.topbar h1')).trim(),
      'Your Clip Queue',
      'the Topbar reads the Clip Queue header',
    );

    // Issue #261: one board, no Completed/Queue sub-tabs — the six-column
    // pipeline board is the default (items 4/5/6).
    await page.waitForSelector('div.board', { timeout: 15000 });
    const columnLabels = await page.$$eval(
      'section.column .column-title',
      (nodes) => nodes.map((node) => node.textContent.trim()),
    );
    assert.deepEqual(
      columnLabels,
      ['Pending', 'Transcribe', 'Convert', 'Upload', 'Complete', 'Failed'],
      'the six pipeline columns render in order',
    );

    // C4/C5: board cards carry the fixed anatomy — thumbnail, title, actions.
    await page.waitForSelector('article.card .thumb', { timeout: 15000 });
    await page.waitForSelector('article.card .card-title', { timeout: 15000 });
    await page.waitForSelector('article.card .card-actions', { timeout: 15000 });
    const cardsBeforeBoardOnly = await page.$$eval('main.main article.card', (n) => n.length);
    assert.ok(cardsBeforeBoardOnly > 0, 'board cards are present');

    // Create flow (item 3): the New action opens the wizard modal.
    await page.click('button:has-text("New")');
    await page.waitForSelector('.wizard-modal div.clip-grid', { timeout: 15000 });

    // Add one transient clip ("Add a clip from another folder") — the seeded
    // sources share a content hash, so a fresh file is the creation candidate.
    await page.fill('input[aria-label="Transient clip path"]', clip.file);
    await page.click('.wizard-modal button:has-text("Add")');
    await page.click('.wizard-modal button:has-text("Next: Configure")');
    await page.waitForSelector('.wizard-modal button:has-text("Create 1")', { timeout: 15000 });
    await page.click('.wizard-modal button:has-text("Create 1")');

    // D24 landing: the created clip leaves the rail and the modal closes
    // onto the Jobs board (item 6). The board is live behind the overlay, so
    // wait on the overlay's detach — not on the board.
    await page.waitForSelector('.wizard-modal', { state: 'detached', timeout: 30000 });
    await page.waitForSelector('article.card', { timeout: 15000 });

    assert.deepEqual(pageErrors, [], 'no uncaught page errors during the flow');
    console.log('smoke.js: fixtures -> board -> create flow OK');
  } finally {
    if (browserRef) await browserRef.close();
    server.stop();
    cleanup(clip);
  }
}

main()
  .then(() => {
    process.exit(0);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
