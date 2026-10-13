#!/usr/bin/env node
/**
 * gate-guard.mjs — mechanical anti-cheating check for the QA gate config.
 *
 *   node gate-guard.mjs --base <git-sha-or-ref> [--config tests/qa/qa-ui.config.json] [--allow-remove stateA,stateB]
 *
 * Fails (exit 1) when, compared with the base commit, the config has:
 *   - an allowlist entry without a written `reason` (10+ chars),
 *   - a lower minTarget or minGap (looser thresholds),
 *   - fewer viewports or states than before (unless named in --allow-remove),
 *   - focusCheck switched from true to false,
 *   - the gate script (tests/qa/qa-ui.cjs or .mjs) shrinking by more than 10% of its lines or
 *     losing `check:` definitions (override with --allow-script-change).
 * Run it after every fix so "make it green" cannot be done by weakening the gate.
 */
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

const args = process.argv.slice(2);
const flag = (n, d) => { const i = args.indexOf('--' + n); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const base = flag('base', null);
const cfgPath = flag('config', 'tests/qa/qa-ui.config.json');
const allowScriptChange = args.includes('--allow-script-change');
const allowRemove = (flag('allow-remove', '') || '').split(',').map(s => s.trim()).filter(Boolean);
if (!fs.existsSync(cfgPath)) { console.error('Config not found: ' + cfgPath); process.exit(2); }
const cur = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));

let prev = null;
if (base) {
  try {
    const rel = execFileSync('git', ['ls-files', '--full-name', cfgPath], { encoding: 'utf8' }).trim() || cfgPath;
    prev = JSON.parse(execFileSync('git', ['show', `${base}:${rel}`], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }));
  } catch { prev = null; }
}

const problems = [];
(cur.allowlist || []).forEach((a, i) => {
  if (!a.reason || String(a.reason).trim().length < 10) {
    problems.push(`allowlist[${i}] (${a.check || '*'} ${a.selector || ''}) has no written reason (10+ chars)`);
  }
});
if (prev) {
  for (const key of ['minTarget', 'minGap']) {
    if (typeof prev[key] === 'number' && typeof cur[key] === 'number' && cur[key] < prev[key]) {
      problems.push(`${key} was loosened: ${prev[key]} -> ${cur[key]}`);
    }
  }
  if (prev.focusCheck === true && cur.focusCheck === false) problems.push('focusCheck was switched off');
  const names = (arr) => (arr || []).map(x => x.name);
  for (const field of ['viewports', 'states']) {
    const removed = names(prev[field]).filter(n => !names(cur[field]).includes(n) && !allowRemove.includes(n));
    if (removed.length) problems.push(`${field} removed: ${removed.join(', ')}`);
  }
  const grew = (cur.allowlist || []).length - (prev.allowlist || []).length;
  if (grew > 0) console.log(`note: allowlist grew by ${grew} (each new entry has a reason; list them in the report)`);
} else if (base) {
  console.log('note: no config at base ref; only the reason check ran');
}
// The gate script must not be gutted to get a green run.
if (base && !allowScriptChange) {
  for (const sp of ['tests/qa/qa-ui.cjs', 'tests/qa/qa-ui.mjs']) {
    if (!fs.existsSync(sp)) continue;
    let old = null;
    try { old = execFileSync('git', ['show', `${base}:${sp}`], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }); } catch { continue; }
    const now = fs.readFileSync(sp, 'utf8');
    const lines = s => s.split(/\r?\n/).length;
    const defs = s => (s.match(/check:\s*['"]/g) || []).length;
    if (lines(now) < lines(old) * 0.9) problems.push(`${sp} shrank from ${lines(old)} to ${lines(now)} lines`);
    if (defs(now) < defs(old)) problems.push(`${sp} lost check definitions (${defs(old)} -> ${defs(now)})`);
  }
}
if (problems.length) {
  console.error('gate-guard: FAIL');
  problems.forEach(p => console.error('  - ' + p));
  process.exit(1);
}
console.log('gate-guard: OK');
