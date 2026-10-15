#!/usr/bin/env node
/**
 * canary.mjs — calibrates a vision reviewer model with planted defects.
 *
 *   node canary.mjs shoot [--out qa-out/canary]
 *       Screenshots canary/canary.html at 1366 and 1024 wide.
 *   node canary.mjs score <review.md> [--min 4]
 *       Scores the reviewer's findings (lines containing "|") against the six
 *       planted defects. Exit 0 if >= min were found, else 1.
 *
 * Run from the folder where `playwright` is installed. The scoring is a
 * keyword check: it proves the reviewer can see and name obvious defects, not
 * that it finds everything.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const canaryHtml = path.join(here, '..', 'canary', 'canary.html');
const [cmd, ...rest] = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = rest.indexOf('--' + name);
  return i >= 0 && rest[i + 1] ? rest[i + 1] : fallback;
};

const PLANTED = [
  { id: 'C1', name: 'Save draft / Publish buttons touching',
    re: /(touch|no gap|no space|adjacent|flush|butt|overlap|abut|cramped|glued|zero gap|no padding between|no separation)/ },
  { id: 'C2', name: 'Caption renderer label truncated',
    re: /((caption|label|renderer).*(truncat|ellipsis|cut off|cut-off|clipped|\.\.\.))|((truncat|ellipsis|cut off|cut-off|clipped|\.\.\.).*(caption|label|renderer))/ },
  { id: 'C3', name: 'Preview thumbnail stretched',
    re: /(stretch|distort|squash|squish|oval|aspect|elliptical|ellipse|flatten|warp)/ },
  { id: 'C4', name: 'Download icon misaligned with text',
    re: /(misalign|baseline|not (vertically )?(centered|aligned)|offset|icon.*(low|lower|high|below|above|sits)|vertical(ly)? alignment|out of line)/ },
  { id: 'C5', name: 'Last synced text low contrast',
    re: /(contrast|faint|light gr[ae]y|illegible|washed|hard to read|barely (visible|legible|readable)|pale)/ },
  { id: 'C6', name: 'Middle summary card padding uneven',
    re: /((padding|spacing|inconsistent|uneven|mismatch).*card)|(card.*(padding|spacing|inconsistent|uneven|mismatch|tight|cramped))/ },
];

async function shoot() {
  const out = flag('out', path.join('qa-out', 'canary'));
  const require = createRequire(path.join(process.cwd(), 'package.json'));
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch { console.error('Cannot load "playwright" from ' + process.cwd()); process.exit(2); }
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const files = [];
  try {
    for (const width of [1366, 1024]) {
      const ctx = await browser.newContext({ viewport: { width, height: 768 }, reducedMotion: 'reduce' });
      const page = await ctx.newPage();
      await page.goto(pathToFileURL(canaryHtml).href, { waitUntil: 'load' });
      const file = path.join(out, `canary__${width}.png`);
      await page.screenshot({ path: file, fullPage: true, animations: 'disabled' });
      files.push(file);
      await ctx.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({ files }, null, 2));
}

function score() {
  const file = rest.find(a => !a.startsWith('--'));
  if (!file || !fs.existsSync(file)) { console.error('Usage: canary.mjs score <review.md> [--min 4]'); process.exit(2); }
  const min = Number(flag('min', 4));
  const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(l => l.includes('|')).map(l => l.toLowerCase());
  let found = 0;
  for (const d of PLANTED) {
    const hit = lines.find(l => d.re.test(l));
    if (hit) found++;
    console.log(`${hit ? 'FOUND ' : 'MISSED'} ${d.id} ${d.name}${hit ? '  <- ' + hit.trim().slice(0, 90) : ''}`);
  }
  const pass = found >= min;
  console.log(`\ncanary score: ${found}/${PLANTED.length} (need ${min}) -> ${pass ? 'PASS' : 'FAIL'}`);
  process.exit(pass ? 0 : 1);
}

if (cmd === 'shoot') await shoot();
else if (cmd === 'score') score();
else { console.error('Usage: canary.mjs shoot|score ...'); process.exit(2); }
