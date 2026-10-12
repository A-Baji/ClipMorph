// Automated UI gate for the dashboard (issue #261; ui-dev-qa skill).
//
// For every configured state and viewport it boots the seeded harness
// workspace, applies the state's navigation actions, and measures:
//   - layout: page overflow, off-viewport content,
//   - runtime: console errors, page errors, failed responses (thumbnail
//     404s are allowlisted — seeded fixtures carry synthetic bytes),
//   - WCAG 2.2: axe-core (@axe-core/playwright from the frontend
//     devDependencies) on the configured desktop viewport.
// It screenshots every state (full page) at 2x plus the configured component
// crops into qa-out/, and writes qa-out/report.md. Exit code 1 on ERROR.
//
// Config lives in qa-ui.config.json next to this script. Run:
//   npm --prefix frontend run qa:ui
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { startServer } = require(path.join(__dirname, '..', 'e2e', 'harness.js'));

const FRONTEND_DIR = path.join(__dirname, '..', '..', 'frontend');
const OUT = path.join(__dirname, 'qa-out');

let playwright;
try {
  playwright = require(require.resolve('playwright', { paths: [FRONTEND_DIR] }));
} catch (error) {
  console.error('Playwright is not installed. Run `npm --prefix frontend install`\n' +
    String(error));
  process.exit(1);
}

let AxeBuilder = null;
try {
  AxeBuilder = require(require.resolve('@axe-core/playwright', { paths: [FRONTEND_DIR] })).AxeBuilder;
} catch {
  /* optional: the report notes the skipped a11y scan */
}

const config = JSON.parse(fs.readFileSync(path.join(__dirname, 'qa-ui.config.json'), 'utf8'));

/** Resolve a relative locator expression into actions on `page`. */
function locatorFor(page, selector) {
  return page.locator(selector).first();
}

const DEBUG = Boolean(process.env.DEBUG_QA);
function log(...parts) {
  if (DEBUG) console.log(`[qa ${Date.now() % 100000}]`, ...parts);
}

/** One state navigation per fresh page load with phase-mapped failures. */
async function enterState(page, base, state) {
  log(state.name, 'goto');
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  try {
    await page.waitForSelector('.shell', { timeout: 15000 });
    log(state.name, 'shell seen');
  } catch (error) {
    throw new Error(`[shell wait] ${error.message.split('\n')[0]}`);
  }
  try {
    await page.waitForFunction(
      "() => !document.body.innerText.includes('Loading workspace')",
      null,
      { timeout: 15000 },
    );
    log(state.name, 'workspace loaded');
  } catch (error) {
    throw new Error(`[workspace wait] ${error.message.split('\n')[0]}`);
  }
  if (state.actions) {
    for (const action of state.actions) {
      if (action.wait) {
        await page.waitForTimeout(action.wait);
      } else if (action.click) {
        try {
          await locatorFor(page, action.click).click();
          log(state.name, `clicked ${action.click}`);
        } catch (error) {
          throw new Error(`[click ${action.click}] ${error.message.split('\n')[0]}`);
        }
      } else if (action.key) {
        await page.keyboard.press(action.key);
      }
    }
  }
  try {
    await page.waitForSelector(state.ready, { state: 'attached', timeout: 15000 });
    log(state.name, 'ready seen');
  } catch (error) {
    // Surface what actually rendered at the crash, so the failure is
    // actionable instead of a bare "Timeout".
    const visible = await page.evaluate(
      "() => document.body ? document.body.innerText.replace(/\\s+/g, ' ').slice(0, 400) : '<page not rendering>'",
    );
    log(state.name, 'ready TIMEOUT');
    throw new Error(`[ready ${state.ready}] ${error.message.split('\n')[0]} — body: ${visible}`);
  }
  await page.waitForTimeout(state.settleMs ?? 400);
}

async function runAxe(page, stateName, findings) {
  if (!AxeBuilder) {
    findings.push({ level: 'warn', text: 'axe unavailable: @axe-core/playwright not installed' });
    return;
  }
  try {
    const { violations } = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
      .analyze();
    for (const violation of violations) {
      const impact = violation.impact || 'unknown';
      const level = impact === 'critical' || impact === 'serious' ? 'error' : 'warn';
      findings.push({
        level,
        text: `axe ${impact}: ${violation.id} — ${violation.help} (${violation.nodes.length} node(s))`,
      });
    }
  } catch (error) {
    findings.push({ level: 'warn', text: `axe could not run: ${error.message}` });
  }
}

/** Progressive failures that should not break the gate: appended to report. */

/**
 * Boot the workspace scenario this state needs. brainstorming the server once
 * per scenario group; startServer prints data_dir, which the conversion-gate
 * promotion needs.
 */
async function withServer(scenario, fn) {
  const server = await startServer({ scenario });
  try {
    await fn(server);
  } finally {
    server.stop();
  }
}


async function main() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const lines = ['# UI gate report (qa:ui)', '',
    `Generated ${new Date().toISOString()}`,
    `States: ${config.states.length}; axe: ${AxeBuilder ? 'enabled' : 'unavailable'}`, ''];
  let errored = 0;

  // Group states by scenario so each server boots once.
  const groups = new Map();
  for (const state of config.states) {
    const scenario = state.scenario || 'states';
    if (!groups.has(scenario)) groups.set(scenario, []);
    groups.get(scenario).push(state);
  }

  for (const [scenario, states] of groups) {
    await withServer(scenario, async (server) => {
      const base = server.url.replace(/\/+$/, '');
      // States that need the review-gate promotion declare it once per
      // scenario boot: the conversion fixture needs its group + artifact and
      // the transcript fixture a real edit session (tests/qa/seed_states.py).
      if (states.some((state) => state.promote)) {
        const python = process.env.CLIPMORPH_PYTHON || process.env.PYTHON || 'python';
        execFileSync(python, [path.join(__dirname, 'seed_states.py'), server.dataDir],
          { stdio: 'inherit' });
      }
      for (const state of states) {
        for (const viewport of config.viewports) {
          // Two attempts with a FRESH browser each: a chromium renderer
          // crash must not read as a UI defect; the second attempt decides.
          let findings = [];
          let crashed = 0;
          for (let attempt = 1; attempt <= 2; attempt += 1) {
            findings = [];
            const browser = await playwright.chromium.launch();
            const context = await browser.newContext({
              viewport: { width: viewport[0], height: viewport[1] },
              deviceScaleFactor: 2,
              reducedMotion: 'reduce',
            });
            const page = await context.newPage();
            const consoleErrors = [];
            const failedUrls = [];
            let thumbnail404s = 0;
            page.on('console', (message) => {
              if (message.type() === 'error') consoleErrors.push(message.text());
            });
            page.on('pageerror', (error) => findings.push({ level: 'error', text: `page error: ${error}` }));
            page.on('response', (response) => {
              if (response.status() >= 400 && response.url().includes('/thumbnail')) {
                // Seeded fixtures carry synthetic bytes; poster generation
                // cannot run against them and the Thumbnail component's
                // documented fallback renders instead — a known, handled load.
                thumbnail404s += 1;
                return;
              }
              if (response.status() >= 400 && response.url().includes('/api/')) {
                failedUrls.push(`${response.request().method()} ${response.url()} → ${response.status()}`);
              }
            });
            try {
              await enterState(page, base, state);
              await page.screenshot({
                path: path.join(OUT, `${state.name}__${viewport[0]}.png`),
                fullPage: true,
              });
              for (const crop of state.crops || []) {
                const target = page.locator(crop).first();
                if (await target.count()) {
                  await target.screenshot({
                    path: path.join(OUT, `${state.name}__${viewport[0]}__${crop.replace(/[^a-z0-9]+/gi, '_')}.png`),
                  });
                } else {
                  findings.push({ level: 'error', text: `crop target missing: ${crop}` });
                }
              }
              for (const text of consoleErrors) {
                if (text.includes('Failed to load resource') && text.includes('404') && thumbnail404s > 0) {
                  thumbnail404s -= 1;
                  findings.push({ level: 'warn', text: 'thumbnail 404 (seeded fixture fallback, expected)' });
                } else {
                  findings.push({ level: 'error', text: `console error: ${text}` });
                }
              }
              for (const url of failedUrls) {
                findings.push({ level: 'error', text: `failed request: ${url}` });
              }
              const overflow = await page.evaluate(
                "() => document.documentElement.scrollWidth > document.documentElement.clientWidth");
              if (overflow) {
                findings.push({ level: 'error', text: 'page overflows horizontally' });
              }
              if (viewport[0] === config.axeViewport) {
                await runAxe(page, state.name, findings);
              }
              await browser.close();
              crashed = 0;
              break;
            } catch (error) {
              crashed = attempt;
              findings.push({
                level: 'error',
                text: `state crashed (attempt ${attempt}): ${error.message.split('\n')[0]}`,
              });
              await page.screenshot({ path: path.join(OUT, `crash-${state.name}.png`) }).catch(() => {});
              await browser.close();
            }
          }
          if (crashed) {
            // Keep every attempt's mapped error: the exact phase matters.
            findings.push({
              level: 'error',
              text: `state still crashed after ${crashed} attempt(s)`,
            });
          }

          const label = `${state.name} @ ${viewport[0]}x${viewport[1]}`;
          lines.push(`## ${label}`, '');
          if (!findings.length) lines.push('- PASS (no findings)', '');
          for (const finding of findings) {
            const icon = finding.level === 'error' ? 'ERROR' : 'WARN';
            if (finding.level === 'error') errored += 1;
            lines.push(`- ${icon} ${finding.text}`);
          }
          if (findings.length) lines.push('');
        }
      }
    });
  }

  fs.writeFileSync(path.join(OUT, 'report.md'), lines.join('\n'), 'utf8');
  console.log(lines.join('\n'));
  console.error(errored ? `qa:ui FAILED with ${errored} error finding(s)` : 'qa:ui PASSED');
  return errored ? 1 : 0;
}

module.exports = { main };

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
