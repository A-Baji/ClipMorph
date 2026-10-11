// E14 store-level test (issue #259): no poll iteration between a gate accept
// and the resumed Running status ever renders the job as queued, and the
// Running column's "queued N" sub-badge cannot count it.
//
// The store is a Svelte 5 runes module (`store.svelte.js`); there is no JS
// test harness in the repo, so this script *is* the store-level harness: it
// compiles the runes module with the svelte compiler the project already
// ships, swaps in a mocked `api` module, and drives `acceptCheckpoint`
// against a mocked poll sequence. Run: `node tests/e2e/e14-store-poll.mjs`
// (needs `npm --prefix frontend install`, i.e. svelte in node_modules).
'use strict';

import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFile as readFileCb } from 'node:fs';
import { promisify } from 'node:util';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const storeSource = path.join(repoRoot, 'frontend', 'src', 'lib', 'store.svelte.js');
const formatAbsolute = pathToFileURL(
  path.join(repoRoot, 'frontend', 'src', 'lib', 'format.js')).href;
// Node resolves package specifiers relative to the importing file, so the
// svelte compiler is imported by absolute path into frontend/node_modules.
const svelteCompilerUrl = pathToFileURL(
  path.join(repoRoot, 'frontend', 'node_modules', 'svelte', 'src', 'compiler', 'index.js')).href;
const moduleDir = path.join(repoRoot, 'frontend', 'node_modules', '.e14-store-tmp');

const { compileModule } = await import(svelteCompilerUrl);

const work = mkdtempSync(path.join(tmpdir(), 'clipmorph-e14-'));
mkdirSync(moduleDir, { recursive: true });

// Shared mocked API: the store resolves ``./api.js`` here. Any method the
// test does not explicitly mock fails loudly.
writeFileSync(path.join(moduleDir, 'mock-api.js'), `
export const api = new Proxy(Object.create(null), {
  get(target, prop) {
    if (!(prop in target)) {
      return () => {
        throw new Error('mock api: unexpected call ' + String(prop));
      };
    }
    return target[prop];
  },
});
`);

const readFile = promisify(readFileCb);
const source = await readFile(storeSource, 'utf8');
// Point the two relative imports at absolute URLs (the compiled module is
// written inside node_modules so ``svelte/internal/client`` resolves).
const rewritten = source
  .replace("from './api.js'", `from ${JSON.stringify(pathToFileURL(path.join(moduleDir, 'mock-api.js')).href)}`)
  .replace("from './format.js'", `from ${JSON.stringify(formatAbsolute)}`);

const compiled = compileModule(rewritten, {
  filename: 'store.svelte.js',
  generate: 'client',
});
writeFileSync(path.join(moduleDir, 'compiled-store.js'), compiled.js.code);

const mockApi = await import(pathToFileURL(path.join(moduleDir, 'mock-api.js')).href);
const store = await import(pathToFileURL(path.join(moduleDir, 'compiled-store.js')).href);
const { app, acceptCheckpoint, loadWorkspace, PRERUN_STATUSES } = store;
const api = mockApi.api;

/** The store's rendered board status for the job (what cards/columns see). */
function displayed(jobId) {
  return app.jobs.find((job) => job.job_id === jobId)?.status ?? '';
}

const observations = [];

function assertRenderedNeverQueued(jobId, label) {
  const status = displayed(jobId);
  observations.push(`${label}: ${status}`);
  if (PRERUN_STATUSES.includes(status)) {
    throw new Error(
      `E14 violated (${label}): poll/store renders the accepted job as "${status}"`,
    );
  }
  // The Running column's "queued N" sub-badge counts PRERUN_STATUSES over
  // displayed statuses (JobsView imports the same list), so a job rendered
  // without a pre-run status can never be counted by the sub-badge.
  return status;
}

const JOB = {
  job_id: 'e14-job',
  status: 'awaiting_review',
  configuration: { general: { source: 'clip.mp4' } },
  checkpoints: {
    transcript: { revision: 1, status: 'awaiting_review' },
    conversion: { revision: 0, status: 'pending' },
    upload: { revision: 0, status: 'pending' },
  },
};

app.jobs = [{ ...JOB }];
app.selectedJobId = 'e14-job';
app.validating = false;

let failures = [];
function check(name, condition) {
  if (!condition) failures.push(name);
}

/* --- Scenario A: accepted -> resumed run (202) --------------------------- */

api.acceptCheckpoint = async () => ({
  ...JOB,
  status: 'queued', // the interim manifest the route derived pre-resume
  resumed: true,
  checkpoints: { transcript: { status: 'completed' } },
});

// The mocked poll sequence (issue map: "mocked poll sequence"): the backend
// still passes through queued twice before the resumed run reports running.
// Every response is a full manifest, exactly like GET /jobs/{id}.
const pollSequence = [
  { ...JOB, status: 'queued' },
  { ...JOB, status: 'queued' },
  { ...JOB, status: 'running' },
];
let pollDelay = 60;
api.getJob = async (jobId) => {
  // Assert the STORE state observed before this iteration is applied: every
  // poll iteration between accept and Running rendered non-queued.
  assertRenderedNeverQueued(jobId, 'poll-iteration-start');
  await new Promise((resolve) => setTimeout(resolve, pollDelay));
  pollDelay = Math.min(pollDelay, 20); // keep later ticks fast
  return pollSequence.shift() || { ...JOB, status: 'running' };
};

const ready = acceptCheckpoint('transcript');
check('gate resolves (E13 close-on-completing-accept handled by the view)', await ready === true);
check('optimistic acceptance renders Running immediately', displayed('e14-job') === 'running');
check('modal closed after the completing accept (E13)', app.selectedJobId === '');

// While the guard is active, workspace polls that carry the passthrough
// status must also render it as Running (and never count in "queued N").
api.listJobs = async () => [{ ...JOB, status: 'queued' }];
api.listSources = async () => [];
api.listLayouts = async () => [];
api.getConfiguration = async () => ({ configuration: {}, credentials: {} });
api.getFormSpec = async () => { throw Object.assign(new Error('no spec'), { }); };
await loadWorkspace();
assertRenderedNeverQueued('e14-job', 'loadWorkspace-during-guard');
check('loadWorkspace map keeps the passthrough unobservable', displayed('e14-job') === 'running');

// Wait out the bounded poll until the truth (running) lands.
await new Promise((resolve) => setTimeout(resolve, 2000));
assertRenderedNeverQueued('e14-job', 'after-resumed-run-status');
check('final observed status is the resumed run: running',
  displayed('e14-job') === 'running');

/* --- Scenario B: conversion gate accept -> upload review (no resume) ----- */

api.acceptCheckpoint = async () => ({
  ...JOB,
  status: 'awaiting_review',
  resumed: false,
  // One conversion group still awaits review (multi-group partial accept).
  checkpoints: {
    transcript: { status: 'completed' },
    conversion: { status: 'awaiting_review' },
  },
});
api.getJob = async () => ({ ...JOB, status: 'awaiting_review' });
api.listArtifacts = async () => [];
api.listUploads = async () => [];
api.getMetrics = async () => [];
api.getUploadDraft = async () => ({
  upload: {}, platforms: {}, platform_summaries: {}, checkpoint: {},
});

app.selectedJobId = 'e14-job'; // modal open again
const gateResolved = await acceptCheckpoint('conversion');
check('non-completing accept keeps the gate open', gateResolved === false);
check('modal stays open while a review surface remains', app.selectedJobId === 'e14-job');
check('board status follows the fetched awaiting review',
  displayed('e14-job') === 'awaiting_review');
if (displayed('e14-job') !== 'awaiting_review') {
  console.error('B debug: displayed=', displayed('e14-job'),
    'errors=', JSON.stringify(app.errors),
    'selected=', app.selectedJobId,
    'first-job-keys=', app.jobs[0] ? Object.keys(app.jobs[0]).join(',') : 'none');
}

if (!process.env.E14_KEEP_TEST_MODULE) {
  rmSync(moduleDir, { recursive: true, force: true });
}

if (failures.length) {
  console.error('E14 store test FAILED:');
  for (const failure of failures) console.error(' -', failure);
  console.error('observations:\n ' + observations.join('\n '));
  throw new Error('store-level mocked-poll test failed');
}
console.log('E14 mocked-poll store test OK\n ' + observations.join('\n '));
