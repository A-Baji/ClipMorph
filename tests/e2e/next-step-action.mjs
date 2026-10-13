// AP-021: the job card's primary action follows the job's state. This is a
// pure-logic check of `nextStepAction` / `statusLabel`; run with
// `node tests/e2e/next-step-action.mjs` (no browser, no dependencies).
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const { nextStepAction, statusLabel } = await import(
  pathToFileURL(path.join(repoRoot, 'frontend', 'src', 'lib', 'format.js')).href);

const job = (status, checkpoints = {}) => ({ job_id: 'j1', status, checkpoints });

assert.deepEqual(nextStepAction(job('running')), { kind: 'processing' });
assert.deepEqual(
  nextStepAction(job('awaiting_review', { transcript: { status: 'awaiting_review' } })),
  { kind: 'accept', stage: 'transcript' });
assert.deepEqual(
  nextStepAction(job('awaiting_review', {
    transcript: { status: 'completed' },
    conversion: { status: 'awaiting_review' },
  })),
  { kind: 'accept', stage: 'conversion' });
assert.deepEqual(
  nextStepAction(job('awaiting_review', {
    transcript: { status: 'completed' },
    conversion: { status: 'completed' },
    upload: { status: 'awaiting_review' },
  })),
  { kind: 'upload' });
// The earliest gate wins when several await review.
assert.deepEqual(
  nextStepAction(job('awaiting_review', {
    transcript: { status: 'awaiting_review' },
    upload: { status: 'awaiting_review' },
  })),
  { kind: 'accept', stage: 'transcript' });
// Other states keep their own actions (Run/Resume/none).
for (const status of ['queued', 'created', 'pending', 'failed', 'cancelled',
  'partial_failure', 'completed', 'scheduled']) {
  assert.equal(nextStepAction(job(status)), null, status);
}
assert.equal(nextStepAction(job('awaiting_review', {})), null);

assert.equal(statusLabel('awaiting_review'), 'Awaiting review');
assert.equal(statusLabel('failed'), 'Failed');
assert.equal(statusLabel(''), '');
assert.equal(statusLabel(undefined), '');

console.log('next-step-action: OK');
