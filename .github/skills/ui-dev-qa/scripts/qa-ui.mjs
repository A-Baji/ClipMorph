#!/usr/bin/env node
/**
 * qa-ui.mjs — objective UI QA gate for a running web app.
 *
 * Usage (run from the folder where `playwright` is installed, e.g. frontend/):
 *   node tests/qa/qa-ui.mjs [--config tests/qa/qa-ui.config.json] [--out qa-out]
 *
 * For every state x viewport in the config it checks:
 *   Geometry   page/element overflow, off-screen content, clipped text, touching
 *              controls, distorted or broken images
 *   WCAG 2.2   2.5.8 target size (24x24 CSS px with the spacing and inline
 *              exceptions), 2.4.7 focus visible (keyboard Tab walk, first
 *              viewport only), 4.1.2 names on icon-only controls, 1.3.1/3.3.2
 *              labels on fields; plus axe-core (wcag2a/aa, 21a/aa, 22aa,
 *              best-practice) when @axe-core/playwright is installed
 *   Runtime    console errors, page errors, failed requests
 * It saves a viewport screenshot and 2x crops of configured components, writes
 * <out>/report.md + report.json, and exits 1 if any error-level issue remains.
 *
 * This is a heuristic gate, not a conformance audit: automated checks catch a
 * subset of accessibility and visual defects. Keep the screenshot review.
 * Readiness: pages are loaded with `load`, never `networkidle` (Playwright
 * discourages it, and it never settles on apps that poll). Use a per-state
 * `ready` selector for client-rendered content.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';

const require = createRequire(path.join(process.cwd(), 'package.json'));
let chromium;
try {
  ({ chromium } = require('playwright'));
} catch {
  console.error('Cannot load "playwright" from ' + process.cwd() +
    '. Run this from the folder where it is installed (npm i -D playwright).');
  process.exit(2);
}
let AxeBuilder = null;
try {
  const mod = require('@axe-core/playwright');
  AxeBuilder = mod.default || mod.AxeBuilder || mod;
} catch { /* axe is optional */ }

// ---------- args + config ----------
const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf('--' + name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const configPath = arg('config', 'tests/qa/qa-ui.config.json');
const outDir = arg('out', 'qa-out');
if (!fs.existsSync(configPath)) {
  console.error('Config not found: ' + configPath);
  process.exit(2);
}
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const settings = {
  baseUrl: cfg.baseUrl || 'http://localhost:5173',
  viewports: cfg.viewports || [
    { name: 'desktop', width: 1920, height: 1080 },
    { name: 'laptop', width: 1366, height: 768 },
    { name: 'small', width: 1024, height: 768 },
  ],
  states: cfg.states || [{ name: 'home', path: '/' }],
  components: cfg.components || [],
  colorScheme: cfg.colorScheme || undefined, // 'light' | 'dark'
  minGap: cfg.minGap ?? 4,          // heuristic: controls closer than this look glued together
  minTarget: cfg.minTarget ?? 24,   // WCAG 2.2 SC 2.5.8 (AA)
  spacingUnit: cfg.spacingUnit ?? 4,
  focusCheck: cfg.focusCheck ?? true,
  maxTabStops: cfg.maxTabStops ?? 25,
  axeTags: cfg.axeTags || ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'],
  allowlist: cfg.allowlist || [],   // [{ check, selector }] selector may be a substring
  maxPerCheck: cfg.maxPerCheck ?? 8,
};

fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(outDir, { recursive: true });

// ---------- optional dev server (killed as a whole process tree) ----------
let server = null;
let stopped = false;
function stopServer() {
  if (!server || stopped) return;
  stopped = true;
  try {
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/pid', String(server.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      process.kill(-server.pid, 'SIGTERM'); // negative pid = the whole process group
    }
  } catch { /* already gone */ }
}
async function waitFor(url, ms = 60000) {
  const start = Date.now();
  while (Date.now() - start < ms) {
    try { const r = await fetch(url); if (r.status < 500) return; } catch { /* retry */ }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error('Timed out waiting for ' + url);
}
if (cfg.startCommand) {
  server = spawn(cfg.startCommand, {
    shell: true, stdio: 'ignore', windowsHide: true,
    detached: process.platform !== 'win32', // own process group on POSIX so the tree can be killed
  });
}
process.on('exit', stopServer);
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { stopServer(); process.exit(130); });

// ---------- in-page checks (serialized into the browser) ----------
function inPageChecks({ minGap, minTarget, spacingUnit }) {
  const issues = [];
  const vw = window.innerWidth;
  const label = (el) => {
    const id = el.id ? '#' + el.id : '';
    const cls = typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : '';
    const txt = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 24);
    return el.tagName.toLowerCase() + id + cls + (txt ? ` "${txt}"` : '');
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const add = (check, severity, el, detail) =>
    issues.push({ check, severity, element: label(el), detail });

  const all = [...document.body.querySelectorAll('*')].filter(visible);

  // 1. page-level horizontal scroll
  if (document.documentElement.scrollWidth > vw + 1) {
    issues.push({ check: 'page-overflow', severity: 'error', element: 'document',
      detail: `page scrolls horizontally (${document.documentElement.scrollWidth}px > ${vw}px)` });
  }

  for (const el of all) {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();

    // 2. element extends past the right edge and is not inside a horizontal scroller
    if (r.right > vw + 1) {
      let scroller = false;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        if (/(auto|scroll)/.test(getComputedStyle(p).overflowX)) { scroller = true; break; }
      }
      if (!scroller) add('offscreen', 'error', el, `right edge at ${Math.round(r.right)}px, viewport is ${vw}px`);
    }

    // 3. text clipped without an ellipsis, tooltip or label
    if (/(hidden|clip)/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1 && el.children.length === 0 &&
        el.textContent.trim() && s.textOverflow !== 'ellipsis' && !el.title && !el.getAttribute('aria-label')) {
      add('clipped-text', 'error', el, `text is cut off (${el.scrollWidth}px content in ${el.clientWidth}px box)`);
    }

    // 4. broken or distorted images
    if (el.tagName === 'IMG') {
      if (el.complete && el.naturalWidth === 0) add('broken-image', 'error', el, 'image failed to load');
      else if (el.naturalWidth && s.objectFit === 'fill') {
        const natural = el.naturalWidth / el.naturalHeight;
        const shown = r.width / r.height;
        if (Math.abs(natural - shown) / natural > 0.05) {
          add('distorted-image', 'error', el, `aspect ${shown.toFixed(2)} vs natural ${natural.toFixed(2)} (set object-fit)`);
        }
      }
    }
  }

  // 5. interactive controls
  const controlSel = 'button,a[href],input:not([type=hidden]),select,textarea,[role=button],[role=tab],[role=menuitem]';
  const isUAControl = (el) => el.tagName === 'INPUT' && /^(checkbox|radio|file|range|color)$/.test(el.type);
  const inlineInText = (el) => getComputedStyle(el).display === 'inline' && el.parentNode &&
    [...el.parentNode.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
  const controls = [...document.querySelectorAll(controlSel)].filter(visible);

  for (const el of controls) {
    const isButtonLike = el.tagName === 'BUTTON' || el.getAttribute('role') === 'button' || el.tagName === 'A';
    if (isButtonLike) {
      const name = (el.textContent || '').trim() || el.getAttribute('aria-label') ||
        el.getAttribute('aria-labelledby') || el.getAttribute('title');
      if (!name && !el.querySelector('img[alt]:not([alt=""]),svg title')) {
        add('no-accessible-name', 'error', el, 'icon-only control has no aria-label, title or text (WCAG 4.1.2)');
      }
    }
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) {
      const hasLabel = el.labels?.length || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title');
      if (!hasLabel) add('no-label', 'error', el, 'form field has no associated label (WCAG 1.3.1 / 3.3.2)');
    }
  }

  // 5a. WCAG 2.5.8 target size: >= minTarget, OR the spacing exception (a minTarget-diameter
  //     circle centered on the target touches no other target or undersized target's circle),
  //     OR inline in text, OR a user-agent control.
  const targets = controls.filter(el => !isUAControl(el) && !inlineInText(el));
  const rects = targets.map(el => el.getBoundingClientRect());
  const rad = minTarget / 2;
  targets.forEach((el, i) => {
    const r = rects[i];
    if (r.width >= minTarget && r.height >= minTarget) return;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    for (let j = 0; j < targets.length; j++) {
      if (j === i || targets[j].contains(el) || el.contains(targets[j])) continue;
      const o = rects[j];
      const dx = Math.max(o.left - cx, 0, cx - o.right);
      const dy = Math.max(o.top - cy, 0, cy - o.bottom);
      const touchesBox = Math.hypot(dx, dy) < rad;
      const oSmall = o.width < minTarget || o.height < minTarget;
      const ocx = o.left + o.width / 2, ocy = o.top + o.height / 2;
      const circlesMeet = oSmall && Math.hypot(ocx - cx, ocy - cy) < minTarget;
      if (touchesBox || circlesMeet) {
        add('small-target', 'warn', el,
          `${Math.round(r.width)}x${Math.round(r.height)}px and too close to ${label(targets[j])} (WCAG 2.5.8: need ${minTarget}px size or spacing)`);
        return;
      }
    }
  });

  // 5b. controls glued together (heuristic; the standards-based check is 5a)
  const seen = new Set();
  for (let i = 0; i < controls.length; i++) {
    for (let j = i + 1; j < controls.length; j++) {
      const a = controls[i], b = controls[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const hGap = Math.max(rb.left - ra.right, ra.left - rb.right);
      const vGap = Math.max(rb.top - ra.bottom, ra.top - rb.bottom);
      const vOverlap = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top) > 1;
      const hOverlap = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left) > 1;
      if ((vOverlap && hGap < minGap) || (hOverlap && vGap < minGap)) {
        const key = label(a) + '|' + label(b);
        if (seen.has(key)) continue;
        seen.add(key);
        const gap = vOverlap ? hGap : vGap;
        add('touching-controls', 'error', a, `${gap < 0 ? 'overlaps' : 'only ' + Math.round(gap) + 'px from'} ${label(b)}`);
      }
    }
  }

  // 6. spacing off the scale (warning only; noisy by nature, grouped)
  const off = {};
  for (const el of all) {
    const s = getComputedStyle(el);
    for (const prop of ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'rowGap', 'columnGap']) {
      const v = parseFloat(s[prop]);
      if (v > 2 && Math.abs(v / spacingUnit - Math.round(v / spacingUnit)) > 0.01) {
        (off[`${v}px`] = off[`${v}px`] || []).push(label(el));
      }
    }
  }
  for (const [value, els] of Object.entries(off)) {
    issues.push({ check: 'off-scale-spacing', severity: 'warn', element: els[0],
      detail: `${value} is not a multiple of ${spacingUnit}px (${els.length} uses)` });
  }
  return issues;
}

// WCAG 2.4.7 focus visible: Tab through the page; every focused element must look
// different from its unfocused self (outline, shadow, border, background, color, underline).
async function focusVisibleCheck(page, max) {
  const issues = [];
  const sig = (i) => page.evaluate((idx) => {
    const el = document.querySelector(`[data-qa-tab="${idx}"]`);
    if (!el) return null;
    const s = getComputedStyle(el);
    return JSON.stringify([s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.borderTopColor,
      s.backgroundColor, s.color, s.textDecorationLine]);
  }, i);
  const describe = (idx) => page.evaluate((i) => {
    const el = document.querySelector(`[data-qa-tab="${i}"]`);
    if (!el) return '';
    const txt = (el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 24);
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (txt ? ` "${txt}"` : '');
  }, idx);

  await page.evaluate(() => { document.activeElement?.blur?.(); });
  const focusedSigs = [];
  let count = 0;
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab');
    await page.waitForTimeout(120); // let :focus-visible transitions finish
    const status = await page.evaluate((idx) => {
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return 'end';
      if (el.hasAttribute('data-qa-tab')) return 'cycled';
      el.setAttribute('data-qa-tab', String(idx));
      return 'ok';
    }, i);
    if (status !== 'ok') break;
    focusedSigs[i] = await sig(i);
    count = i + 1;
  }
  // blur everything, then compare each element's unfocused signature
  await page.evaluate(() => { document.activeElement?.blur?.(); });
  await page.waitForTimeout(120);
  for (let i = 0; i < count; i++) {
    const unfocused = await sig(i);
    if (unfocused && unfocused === focusedSigs[i]) {
      issues.push({ check: 'no-focus-indicator', severity: 'error', element: await describe(i),
        detail: 'focused element looks identical to its unfocused state (WCAG 2.4.7)' });
    }
  }
  await page.evaluate(() => document.querySelectorAll('[data-qa-tab]').forEach(e => e.removeAttribute('data-qa-tab')));
  return issues;
}

// ---------- helpers ----------
function allowed(issue) {
  return settings.allowlist.some(a =>
    (!a.check || a.check === issue.check) && (!a.selector || (issue.element || '').includes(a.selector)));
}
async function runAction(page, a) {
  if (a.click) await page.locator(a.click).first().click();
  else if (a.fill) await page.locator(a.fill[0]).first().fill(a.fill[1]);
  else if (a.press) await page.keyboard.press(a.press);
  else if (a.wait) await page.locator(a.wait).first().waitFor();
  else if (a.hover) await page.locator(a.hover).first().hover();
  else if (a.waitMs) await page.waitForTimeout(a.waitMs);
}

const report = { generated: new Date().toISOString(), results: [], totals: { error: 0, warn: 0 } };
let browser;
try {
  if (cfg.startCommand) await waitFor(cfg.readyUrl || settings.baseUrl);
  browser = await chromium.launch();
  for (const [vpIndex, vp] of settings.viewports.entries()) {
    const ctx = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: 2,
      reducedMotion: 'reduce',
      colorScheme: settings.colorScheme,
    });
    for (const state of settings.states) {
      const page = await ctx.newPage();
      const runtime = [];
      page.on('console', m => { if (m.type() === 'error') runtime.push({ check: 'console-error', severity: 'error', element: 'console', detail: m.text().slice(0, 200) }); });
      page.on('pageerror', e => runtime.push({ check: 'page-error', severity: 'error', element: 'page', detail: String(e).slice(0, 200) }));
      page.on('requestfailed', r => {
        const err = r.failure()?.errorText || 'failed';
        if (!/ERR_ABORTED/.test(err)) runtime.push({ check: 'request-failed', severity: 'error', element: r.url().slice(0, 80), detail: err });
      });

      const tag = `${state.name}__${vp.name}`;
      let issues = [];
      try {
        await page.goto(settings.baseUrl + (state.path || '/'), { waitUntil: 'load' });
        await page.evaluate(() => document.fonts?.ready);
        if (state.ready) await page.locator(state.ready).first().waitFor();
        for (const action of state.actions || []) await runAction(page, action);
        await page.waitForTimeout(state.settleMs ?? 200);

        issues = await page.evaluate(inPageChecks, settings);
        if (AxeBuilder) {
          const axe = await new AxeBuilder({ page }).withTags(settings.axeTags).analyze();
          for (const v of axe.violations) {
            if (v.id === 'target-size') continue; // covered by the spacing-aware check above
            const sev = ['critical', 'serious'].includes(v.impact) ? 'error' : 'warn';
            issues.push({ check: 'axe:' + v.id, severity: sev, element: v.nodes[0]?.target?.join(' ') || '', detail: `${v.help} (${v.nodes.length} nodes)` });
          }
        }
        await page.screenshot({ path: path.join(outDir, `${tag}.png`), scale: 'css', animations: 'disabled', caret: 'hide' });
        for (const comp of settings.components) {
          const loc = page.locator(comp.selector).first();
          if (await loc.count()) {
            await loc.screenshot({ path: path.join(outDir, `${tag}__${comp.name}.png`), scale: 'device', animations: 'disabled', caret: 'hide' }).catch(() => {});
          }
        }
        if (settings.focusCheck && vpIndex === 0) {
          issues.push(...await focusVisibleCheck(page, settings.maxTabStops));
        }
      } catch (e) {
        issues.push({ check: 'state-failed', severity: 'error', element: tag, detail: String(e.message || e).split('\n')[0] });
      }
      issues = [...issues, ...runtime].filter(i => !allowed(i));

      // cap noisy checks so the report stays readable
      const counts = {};
      const trimmed = [];
      for (const i of issues) {
        counts[i.check] = (counts[i.check] || 0) + 1;
        if (counts[i.check] <= settings.maxPerCheck) trimmed.push(i);
      }
      const omitted = Object.entries(counts).filter(([, n]) => n > settings.maxPerCheck)
        .map(([c, n]) => `${c}: +${n - settings.maxPerCheck} more`);
      report.results.push({ state: state.name, viewport: vp.name, issues: trimmed, omitted });
      for (const i of issues) report.totals[i.severity]++;
      await page.close();
    }
    await ctx.close();
  }
} finally {
  await browser?.close();
  stopServer();
}

// ---------- report ----------
fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2));
const lines = [`# UI QA report`, '',
  `Errors: **${report.totals.error}**  Warnings: ${report.totals.warn}`, '',
  `Screenshots are in \`${outDir}/\` — view them; this report cannot judge hierarchy or balance.`, ''];
for (const r of report.results) {
  lines.push(`## ${r.state} @ ${r.viewport}`);
  if (!r.issues.length) lines.push('No issues.');
  for (const i of r.issues) lines.push(`- [${i.severity.toUpperCase()}] ${i.check}: ${i.element} — ${i.detail}`);
  for (const o of r.omitted) lines.push(`- (${o})`);
  lines.push('');
}
fs.writeFileSync(path.join(outDir, 'report.md'), lines.join('\n'));
console.log(lines.join('\n'));
process.exit(report.totals.error > 0 ? 1 : 0);
