#!/usr/bin/env node
/**
 * review-manifest.mjs — turns a qa-out folder of screenshots into capped review batches,
 * so no human (and no parent agent) has to pick or open images.
 *
 *   node review-manifest.mjs [--dir tests/qa/qa-out] [--batch 40] [--out <dir>/review-manifest.json]
 *
 * Understands names like  <state>__<viewport>.png  (full page) and
 * <state>__<viewport>__<component>.png / <state>__<viewport>___<component>.png (crop).
 * Selection per state: the full-page image at the primary (largest or first) viewport, plus
 * every component crop at the primary and the smallest viewport. Everything else is skipped.
 */
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const flag = (n, d) => { const i = args.indexOf('--' + n); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const dir = flag('dir', path.join('tests', 'qa', 'qa-out'));
const batchSize = Math.max(1, Number(flag('batch', 40)));
const outFile = flag('out', path.join(dir, 'review-manifest.json'));
if (!fs.existsSync(dir)) { console.error('Folder not found: ' + dir); process.exit(2); }

const pat = /^(.+?)__([A-Za-z0-9]+)(?:_+(.+))?\.png$/;
const items = [];
for (const f of fs.readdirSync(dir).sort()) {
  const m = pat.exec(f);
  if (!m) continue;
  items.push({ file: path.join(dir, f), state: m[1], vp: m[2], comp: m[3] || null });
}
if (!items.length) { console.error('No screenshots matching <state>__<viewport>[__component].png in ' + dir); process.exit(2); }

const rank = (vp, all) => /^\d+$/.test(vp) ? Number(vp) : (all.length - all.indexOf(vp));
const selected = [];
for (const state of [...new Set(items.map(i => i.state))]) {
  const rows = items.filter(i => i.state === state);
  const vps = [...new Set(rows.map(r => r.vp))];
  const sorted = [...vps].sort((a, b) => rank(b, vps) - rank(a, vps));
  const primary = sorted[0], smallest = sorted[sorted.length - 1];
  for (const r of rows) {
    const keep = (!r.comp && r.vp === primary) || (r.comp && (r.vp === primary || r.vp === smallest));
    if (keep) selected.push(r);
  }
}

const batches = [];
for (let i = 0; i < selected.length; i += batchSize) {
  const files = selected.slice(i, i + batchSize).map(s => s.file.replace(/\\/g, '/'));
  batches.push({ id: batches.length + 1, count: files.length, files });
}
const manifest = { generated: new Date().toISOString(), dir: dir.replace(/\\/g, '/'), totalScreenshots: items.length,
  selected: selected.length, skipped: items.length - selected.length, batchSize, batches };
fs.writeFileSync(outFile, JSON.stringify(manifest, null, 2));
console.log(`Screenshots: ${items.length}, selected for review: ${selected.length}, skipped: ${manifest.skipped}`);
console.log(`Batches: ${batches.length} (<= ${batchSize} images each) -> ${outFile}`);
