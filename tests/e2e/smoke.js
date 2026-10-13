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
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { PYTHON, startServer } = require('./harness.js');

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

async function assertReviewActionLayout(page, title, secondaryLabel, primaryLabel) {
  await page.locator(`article.card:has-text('${title}') .card-main`).click();
  await page.waitForSelector('.detail-modal', { timeout: 15000 });
  await page.click('.detail-modal button.tab:has-text("Review")');
  const toolbar = page.locator('.detail-modal .review-action-bar');
  await toolbar.waitFor({ timeout: 15000 });
  const secondary = toolbar.getByRole('button', { name: secondaryLabel });
  const primary = toolbar.getByRole('button', { name: primaryLabel });
  assert.equal(await secondary.count(), 1, `${secondaryLabel} is in the shared review toolbar`);
  assert.equal(await primary.count(), 1, `${primaryLabel} is in the shared review toolbar`);
  const positions = await toolbar.evaluate((bar) => {
    const barRect = bar.getBoundingClientRect();
    const bounds = (selector) => {
      const rect = bar.querySelector(selector).getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
      };
    };
    return {
      bar: { left: barRect.left, right: barRect.right },
      buttons: bounds('.review-action-buttons'),
      secondary: bounds('.review-action-buttons .btn-secondary'),
      primary: bounds('.review-action-buttons .btn-primary'),
      context: bar.querySelector('.review-action-context')
        ? bounds('.review-action-context')
        : null,
      renderVariant: bar.querySelector('.variant-picker select')
        ? bounds('.variant-picker select')
        : null,
    };
  });
  assert.ok(
    Math.abs(positions.secondary.top - positions.primary.top) <= 1,
    `${primaryLabel} stays on the secondary-action row`,
  );
  assert.ok(
    positions.secondary.right <= positions.primary.left,
    `${secondaryLabel} is left of ${primaryLabel}`,
  );
  assert.ok(
    Math.abs(positions.buttons.right - positions.bar.right) <= 1,
    `review actions are aligned to the toolbar's right edge`,
  );
  assert.ok(
    Math.abs(positions.primary.right - positions.bar.right) <= 1,
    `${primaryLabel} is aligned to the review toolbar's right edge`,
  );
  if (secondaryLabel === 'Re-render' && page.viewportSize().width > 1400) {
    const actionCenter = (positions.buttons.top + positions.buttons.bottom) / 2;
    const selectorCenter = (positions.renderVariant.top + positions.renderVariant.bottom) / 2;
    const centerDelta = Math.abs(actionCenter - selectorCenter);
    assert.ok(
      centerDelta <= 2,
      `conversion actions align vertically with the render-variant control; offset ${centerDelta}px`,
    );
  }
  if (secondaryLabel === 'Save draft') {
    const fieldGap = await toolbar.evaluate((bar) => {
      const next = bar.nextElementSibling;
      return next.getBoundingClientRect().top - bar.getBoundingClientRect().bottom;
    });
    assert.ok(fieldGap >= 16, `Upload draft fields need 16px after the toolbar; got ${fieldGap}px`);
  }
  await page.keyboard.press('Escape');
  await page.waitForSelector('.detail-modal', { state: 'detached', timeout: 15000 });
}

async function assertEmptyUploadState(page) {
  await page.locator(
    "article.card:has-text('Status fixture: completed') .card-main",
  ).click();
  await page.waitForSelector('.detail-modal', { timeout: 15000 });
  await page.click('.detail-modal button.tab:has-text("Review")');
  for (const checkbox of await page.locator('.detail-modal .checks input').all()) {
    await checkbox.setChecked(false);
  }
  const state = await page.evaluate(() => {
    const button = document.querySelector('.detail-modal .review-action-bar .btn-primary');
    const hint = document.querySelector('.detail-modal .upload-platform-hint');
    const title = [...document.querySelectorAll('.detail-modal .field > span')]
      .find((item) => item.textContent.trim() === 'Title')?.parentElement;
    const checks = document.querySelector('.detail-modal .checks');
    return {
      disabled: button.disabled,
      hintToTitle: title.getBoundingClientRect().top - hint.getBoundingClientRect().bottom,
      columnGap: parseFloat(getComputedStyle(checks).columnGap),
    };
  });
  assert.equal(state.disabled, true, 'upload is disabled without selected platforms');
  assert.ok(state.hintToTitle >= 8, `empty-platform hint needs separation from fields; got ${state.hintToTitle}px`);
  assert.ok(state.columnGap >= 8, `platform checkboxes need separation; got ${state.columnGap}px`);
  await page.keyboard.press('Escape');
  await page.waitForSelector('.detail-modal', { state: 'detached', timeout: 15000 });
}

async function assertPlatformSummary(page) {
  await page.locator(
    "article.card:has-text('Status fixture: completed') .card-main",
  ).click();
  await page.waitForSelector('.detail-modal', { timeout: 15000 });
  await page.click('.detail-modal button.tab:has-text("Review")');
  const rows = await page.evaluate(() => [
    ...document.querySelectorAll('.detail-modal .platform-summary-row'),
  ].map((row) => {
    const note = row.querySelector('small');
    return {
      clipped: note.scrollWidth - note.clientWidth,
      configId: row.querySelector('.config-id')?.textContent.trim() || '',
    };
  }));
  assert.ok(rows.length > 0, 'per-platform summary lists participating platforms');
  // AP-038: the schedule picker glyph is lightened on the dark surface.
  const pickerFilter = await page.evaluate(() => {
    const input = document.querySelector('.detail-modal input[type="datetime-local"]');
    if (!input) return null;
    for (const sheet of document.styleSheets) {
      for (const rule of sheet.cssRules) {
        if (!rule.selectorText?.includes('::-webkit-calendar-picker-indicator')) continue;
        const base = rule.selectorText.replace('::-webkit-calendar-picker-indicator', '');
        if (input.matches(base) && rule.style.filter) return rule.style.filter;
      }
    }
    return 'none';
  });
  assert.ok(pickerFilter && pickerFilter !== 'none', `upload schedule picker icon is not lightened (filter: ${pickerFilter})`);
  for (const row of rows) {
    assert.ok(row.clipped <= 0, `platform summary subline is clipped by ${row.clipped}px`);
    assert.match(row.configId, /^[0-9a-f]{12}$/, 'platform summary shows its config id');
  }
  await page.keyboard.press('Escape');
  await page.waitForSelector('.detail-modal', { state: 'detached', timeout: 15000 });
}

async function assertConversionLabelsReadable(page) {
  await page.locator(
    "article.card:has-text('Checkpoint fixture: awaiting_review') .card-main",
  ).click();
  await page.waitForSelector('.detail-modal', { timeout: 15000 });
  await page.click('.detail-modal button.tab:has-text("Review")');
  await page.waitForTimeout(300);
  const clipped = await page.evaluate(() => [
    ...document.querySelectorAll('.detail-modal .config-label .check span'),
  ].filter((node) => node.scrollWidth > node.clientWidth + 1)
    .map((node) => `${node.textContent.trim()} (+${node.scrollWidth - node.clientWidth}px)`));
  assert.deepEqual(clipped, [], `AP-039: toggle labels are clipped: ${clipped.join(', ')}`);
  await page.keyboard.press('Escape');
  await page.waitForSelector('.detail-modal', { state: 'detached', timeout: 15000 });
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
    execFileSync(PYTHON, [
      path.join(__dirname, '..', 'qa', 'seed_states.py'),
      server.dataDir,
    ], { stdio: 'inherit' });
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

    // AP-037: one h1 per page. AP-036: the title sits beside the menu button.
    assert.equal(await page.locator('h1').count(), 1, 'the board has a single h1');
    await page.setViewportSize({ width: 812, height: 375 });
    const titleGap = await page.evaluate(() => {
      const menu = document.querySelector('.topbar .menu-toggle').getBoundingClientRect();
      const title = document.querySelector('.topbar-title').getBoundingClientRect();
      return title.left - menu.right;
    });
    assert.ok(titleGap <= 24, `topbar title floats ${titleGap}px from the menu button`);
    await page.setViewportSize(server.viewports.desktop);

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

    for (const viewport of [server.viewports.desktop, { width: 375, height: 812 }]) {
      await page.setViewportSize(viewport);
      await assertReviewActionLayout(
        page,
        'Status fixture: awaiting_review',
        'Save edits',
        'Accept transcript',
      );
      await assertReviewActionLayout(
        page,
        'Checkpoint fixture: awaiting_review',
        'Re-render',
        'Accept composition',
      );
      await assertReviewActionLayout(
        page,
        'Status fixture: completed',
        'Save draft',
        'Submit upload',
      );
      await assertPlatformSummary(page);
      await assertEmptyUploadState(page);
    }
    await page.setViewportSize({ width: 1024, height: 768 });
    await assertConversionLabelsReadable(page);
    await page.setViewportSize(server.viewports.desktop);

    const reviewCard = page.locator(
      "article.card:has-text('Status fixture: awaiting_review') .card-main",
    ).first();
    await reviewCard.click();
    await page.waitForSelector('.detail-modal .row.faint', { timeout: 15000 });
    const meta = page.locator('.detail-modal .row.faint').first();
    const separator = meta.locator('.job-meta-separator');
    assert.equal(await separator.count(), 1, 'job metadata separator is its own item');
    const metaGaps = await meta.evaluate((row) => {
      const source = row.querySelector('.mono').getBoundingClientRect();
      const dot = row.querySelector('.job-meta-separator').getBoundingClientRect();
      const updated = row.querySelector('.job-meta-updated').getBoundingClientRect();
      return [dot.left - source.right, updated.left - dot.right];
    });
    assert.ok(
      Math.abs(metaGaps[0] - metaGaps[1]) <= 1,
      `job metadata separator spacing is uneven: ${metaGaps.join('px, ')}px`,
    );
    await page.keyboard.press('Escape');
    await page.waitForSelector('.detail-modal', { state: 'detached', timeout: 15000 });

    // AP-033: a double-clicked board Approve sends exactly one accept request.
    let acceptRequests = 0;
    await page.route('**/api/v1/jobs/*/checkpoints/*/accept', async (route) => {
      acceptRequests += 1;
      await new Promise((resolve) => setTimeout(resolve, 400));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ resumed: true, checkpoints: {} }),
      });
    });
    await page
      .locator("article.card:has-text('Status fixture: awaiting_review') button.btn-primary.btn-icon")
      .first()
      .dblclick();
    await page.waitForTimeout(800);
    await page.unroute('**/api/v1/jobs/*/checkpoints/*/accept');
    assert.equal(acceptRequests, 1, 'double-clicking Approve sends one accept request');
    assert.equal(
      await page.evaluate(() => document.activeElement?.getAttribute('data-open-job') !== null),
      true,
      'focus lands on the card after Approve instead of <body>',
    );

    // Create flow (item 3): the New action opens the wizard modal.
    await page.click('button:has-text("New")');
    await page.waitForSelector('.wizard-modal div.clip-grid', { timeout: 15000 });

    // Add one transient clip ("Add a clip from another folder") — the seeded
    // sources share a content hash, so a fresh file is the creation candidate.
    await page.fill('input[aria-label="Transient clip path"]', clip.file);
    await page.click('.wizard-modal button:has-text("Add")');
    await page.click('.wizard-modal button:has-text("Next: Configure")');
    await page.waitForSelector('.wizard-modal button:has-text("Create 1")', { timeout: 15000 });
    // AP-035: the override count hint stays on one line.
    const hintLines = await page.$$eval('.wizard-modal .pane-head .faint', (nodes) =>
      nodes.map((node) => node.getBoundingClientRect().height / parseFloat(getComputedStyle(node).lineHeight)));
    assert.ok(hintLines.length > 0 && hintLines.every((n) => n < 1.5), `override hint wraps: ${hintLines}`);
    await page.click('.wizard-modal button:has-text("Create 1")');

    // D24 landing: the created clip leaves the rail and the modal closes
    // onto the Jobs board (item 6). The board is live behind the overlay, so
    // wait on the overlay's detach — not on the board.
    await page.waitForSelector('.wizard-modal', { state: 'detached', timeout: 30000 });
    await page.waitForSelector('article.card', { timeout: 15000 });

    await page.setViewportSize({ width: 375, height: 812 });
    await page.click('button.menu-toggle');
    await page.click("button.nav-item:has-text('Settings')");
    const settingsSave = page.locator('header.topbar button:has-text("Save app.yml")');
    await settingsSave.waitFor({ timeout: 15000 });
    const saveMetrics = await settingsSave.evaluate((button) => ({
      height: button.getBoundingClientRect().height,
      whiteSpace: getComputedStyle(button).whiteSpace,
    }));
    assert.ok(
      saveMetrics.height <= 44,
      `Settings Save should stay a single-line toolbar action, height ${saveMetrics.height}px`,
    );
    assert.equal(saveMetrics.whiteSpace, 'nowrap', 'Settings Save stays on one line');

    // AP-031: a failed job-list load shows a load-error state with Retry,
    // not six "No jobs" columns.
    const failing = await browserRef.newPage({ viewport: server.viewports.desktop });
    await failing.route('**/api/v1/jobs', (route) => route.abort());
    await failing.goto(base, { waitUntil: 'domcontentloaded' });
    await failing.waitForSelector('[data-load-error]', { timeout: 15000 });
    assert.equal(await failing.locator('section.column').count(), 0, 'no empty columns on load error');
    await failing.unroute('**/api/v1/jobs');
    await failing.click('[data-load-error] button:has-text("Retry")');
    await failing.waitForSelector('section.column', { timeout: 15000 });
    assert.equal(await failing.locator('[data-load-error]').count(), 0, 'load error clears after Retry');
    await failing.close();

    // Poll exhaustion: spinner while polling, then "Status unconfirmed" with
    // no Approve button (no duplicate approval) once the poll gives up.
    const stuck = await browserRef.newPage({ viewport: server.viewports.desktop });
    await stuck.route('**/api/v1/events*', (route) => route.abort());
    await stuck.route('**/api/v1/jobs/*/events*', (route) => route.abort());
    await stuck.goto(base, { waitUntil: 'domcontentloaded' });
    await stuck.waitForSelector('article.card', { timeout: 15000 });
    let stuckJob = null;
    let stuckPosts = 0;
    stuck.on('request', (request) => {
      const match = request.url().match(/jobs\/([0-9a-f]+)\/checkpoints/);
      if (match) { stuckJob = match[1]; stuckPosts += 1; }
    });
    await stuck.route('**/checkpoints/*/accept', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: '{"resumed":true,"checkpoints":{}}',
    }));
    await stuck.route(/\/api\/v1\/jobs\/[0-9a-f]+$/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      if (body.job_id === stuckJob) body.status = 'queued';
      return route.fulfill({ response, json: body });
    });
    const stuckCard = stuck.locator("article.card:has-text('Status fixture: awaiting_review')").first();
    await stuckCard.locator('button.btn-primary.btn-icon').click();
    await stuckCard.locator('.spinner').waitFor({ timeout: 5000 });
    await stuckCard.locator('.badge-warning:has-text("Status unconfirmed")').waitFor({ timeout: 15000 });
    assert.equal(await stuckCard.locator('.spinner').count(), 0, 'spinner clears when the poll gives up');
    assert.equal(await stuckCard.locator('button.btn-primary.btn-icon').count(), 0, 'no Approve button after poll exhaustion');
    assert.equal(stuckPosts, 1, 'poll exhaustion sends no duplicate approval');
    await stuck.close();

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
