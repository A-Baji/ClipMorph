/**
 * Global dashboard state and actions (Svelte 5 runes module).
 *
 * Views read from ``app`` and call the exported actions; no view talks to the
 * API directly. The creation flow is a two-step wizard whose in-progress state
 * is a localStorage draft (issue #257): the wizard draft survives refreshes and
 * tab switches and is discarded explicitly or on a successful create.
 */

import { api } from './api.js';
import { toLocalInput, toUtcTimestamp } from './format.js';

const FALLBACK_CONFIGURATION = {
  source_dir: 'sources',
  output_dir: 'output',
  job_defaults: {},
  layouts: [],
};

const FALLBACK_PLATFORMS = ['youtube', 'instagram', 'tiktok', 'twitter', 'facebook'];

const DRAFT_KEY = 'clipmorph.wizard.draft.v1';

function emptyDraft() {
  return { title: '', description: '', tags: '', publishAt: '' };
}

function emptyWizard() {
  return {
    active: false,
    step: 1,
    selected: [],
    extras: [], // [{ name, path }] transient out-of-folder clips
    batch: { values: {}, overrides: [] },
    jobs: {}, // source -> { values, overrides }
    activeJob: '',
    validation: null,
    validating: false,
  };
}

export const app = $state({
  ready: false,
  online: true,
  view: 'queue',
  selectedJobId: '',
  detailTab: 'overview',
  mobileNav: false,
  jobs: [],
  sources: [],
  layouts: [],
  configuration: { ...FALLBACK_CONFIGURATION },
  credentials: {},
  probeResults: {},
  platforms: [...FALLBACK_PLATFORMS],
  formSpec: null,
  artifacts: [],
  attempts: [],
  metrics: [],
  metricsComparison: [],
  metricFilterPlatform: '',
  platformSummaries: {},
  uploadProgress: {},
  transcript: null,
  wizard: emptyWizard(),
  publish: {
    draft: emptyDraft(),
    contentKind: 'reel',
    selectedPlatforms: [],
    attemptFilters: { status: '', platform: '', since: '' },
    suggestionEdits: {},
  },
  notice: '',
  errors: [],
  busy: false,
  confirm: null,
});

let noticeTimer = null;
let progressStream = null;
let validationTimer = null;

export function notify(message) {
  app.notice = message;
  if (noticeTimer) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => {
    app.notice = '';
    noticeTimer = null;
  }, 3200);
}

export function report(error) {
  app.errors = [error?.message || String(error)];
}

export function clearErrors() {
  app.errors = [];
}

/* Confirmation is a single app-level dialog so every destructive action asks the
   same way. ``requestConfirm`` opens it; the dialog calls ``settleConfirm``. */
export function requestConfirm(spec) {
  app.confirm = spec;
}

export function settleConfirm(confirmed) {
  const spec = app.confirm;
  app.confirm = null;
  if (confirmed && typeof spec?.onConfirm === 'function') spec.onConfirm();
}

export function setView(view) {
  clearErrors();
  app.mobileNav = false;
  app.view = view;
  if (view !== 'wizard') app.wizard.active = false;
  if (view !== 'queue') app.selectedJobId = '';
  if (view === 'metrics') loadMetrics();
  if (view === 'layouts') {
    api.listLayouts().then((items) => (app.layouts = items)).catch(report);
  }
}

export function openJob(jobId) {
  app.selectedJobId = jobId;
  app.detailTab = 'overview';
  loadJobDetails().catch(report);
}

export function closeJob() {
  closeProgressStream();
  app.selectedJobId = '';
  app.transcript = null;
}

/* --- Path helpers (tri-state config resolution) -------------------------- */

function getPath(object, path) {
  return path
    .split('.')
    .reduce((node, key) => (node == null ? undefined : node[key]), object);
}

function setPath(object, path, value) {
  const keys = path.split('.');
  let node = object;
  for (const key of keys.slice(0, -1)) {
    if (typeof node[key] !== 'object' || node[key] === null) node[key] = {};
    node = node[key];
  }
  node[keys[keys.length - 1]] = value;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/* --- Loaders ------------------------------------------------------------- */

function platformsFromConfiguration(configuration) {
  const keys = Object.keys(configuration?.job_defaults?.platforms || {});
  return keys.length ? keys : [...FALLBACK_PLATFORMS];
}

export async function loadWorkspace() {
  try {
    const [jobs, sources, layouts, settings, formSpec] = await Promise.all([
      api.listJobs(),
      api.listSources(),
      api.listLayouts(),
      api.getConfiguration(),
      api.getFormSpec().catch(() => null),
    ]);
    app.jobs = jobs;
    app.sources = sources;
    app.layouts = layouts;
    app.configuration = settings.configuration || { ...FALLBACK_CONFIGURATION };
    app.credentials = settings.credentials || {};
    app.platforms = platformsFromConfiguration(app.configuration);
    if (formSpec) app.formSpec = formSpec;
    app.online = true;
    app.ready = true;
    restoreWizardDraft();
  } catch (error) {
    app.online = false;
    app.ready = true;
    report(error);
  }
}

export async function loadJobDetails() {
  if (!app.selectedJobId) return;
  const jobId = app.selectedJobId;
  const [job, artifacts, attempts, metrics, draft] = await Promise.all([
    api.getJob(jobId),
    api.listArtifacts(jobId),
    api.listUploads(jobId),
    api.getMetrics(jobId, true),
    api.getUploadDraft(jobId),
  ]);
  app.jobs = app.jobs.map((item) => (item.job_id === jobId ? job : item));
  app.artifacts = artifacts;
  app.attempts = attempts;
  app.metrics = metrics;
  app.transcript = null;
  app.platformSummaries = draft.platform_summaries || {};
  app.publish.selectedPlatforms = app.platforms.filter(
    (platform) => app.platformSummaries[platform]?.participates,
  );
  app.publish.draft = {
    title: job.configuration?.upload?.content?.title || '',
    description: job.configuration?.upload?.content?.description || '',
    tags: (job.configuration?.upload?.content?.tags || []).join(', '),
    publishAt: toLocalInput(job.configuration?.upload?.schedule?.publish_at),
  };
  app.publish.contentKind =
    job.configuration?.platforms?.facebook?.content_kind || 'reel';
  app.publish.suggestionEdits = {};
  app.publish.attemptFilters = { status: '', platform: '', since: '' };
  openProgressStream(jobId);
}

export async function loadTranscript() {
  const job = selectedJob();
  if (!job?.active_transcript) {
    app.transcript = null;
    return;
  }
  const transcript = await api.getTranscript(job.job_id);
  transcript.segments = transcript.segments.map((segment) => ({
    ...segment,
    typography: { ...(segment.typography || {}) },
  }));
  app.transcript = transcript;
}

export async function loadMetrics() {
  try {
    app.metricsComparison = await api.compareMetrics(app.metricFilterPlatform);
  } catch (error) {
    report(error);
  }
}

export function selectedJob() {
  return app.jobs.find((job) => job.job_id === app.selectedJobId) || null;
}

/* --- Live progress ------------------------------------------------------- */

function closeProgressStream() {
  if (progressStream) {
    progressStream.close();
    progressStream = null;
  }
}

function openProgressStream(jobId) {
  closeProgressStream();
  if (!jobId || typeof EventSource === 'undefined') return;
  const source = new EventSource(api.eventsUrl(jobId));
  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      app.uploadProgress = {
        ...app.uploadProgress,
        [jobId]: data.upload_progress || {},
      };
      if (['completed', 'failed', 'cancelled'].includes(data.status)) {
        source.close();
        if (progressStream === source) progressStream = null;
      }
    } catch {
      /* ignore malformed events */
    }
  };
  source.onerror = () => {
    source.close();
    if (progressStream === source) progressStream = null;
  };
  progressStream = source;
}

/* --- Wizard: selection --------------------------------------------------- */

export function startWizard() {
  app.wizard.active = true;
  app.view = 'wizard';
  if (app.wizard.step !== 2) app.wizard.step = 1;
  persistWizardDraft();
}

export function discardWizard() {
  clearWizardDraft();
  app.wizard.active = false;
  app.view = 'queue';
}

/** Leave the wizard for the board while preserving the in-progress draft. */
export function leaveWizard() {
  persistWizardDraft();
  app.wizard.active = false;
  app.view = 'queue';
}

export function wizardGoStep(step) {
  if (step === 2 && !wizardSelected().length) {
    report(new Error('Select at least one clip first'));
    return;
  }
  app.wizard.step = step;
  if (step === 2 && !app.wizard.activeJob) {
    app.wizard.activeJob = wizardSelected()[0] || '';
  }
  persistWizardDraft();
}

export function wizardToggleSource(name, checked) {
  app.wizard.selected = checked
    ? [...new Set([...app.wizard.selected, name])]
    : app.wizard.selected.filter((item) => item !== name);
  syncWizardJobs();
  persistWizardDraft();
}

export function wizardSelectAll(names) {
  app.wizard.selected = [...names];
  syncWizardJobs();
  persistWizardDraft();
}

export function wizardClearSelection() {
  app.wizard.selected = [];
  syncWizardJobs();
  persistWizardDraft();
}

export function wizardAddExtra(path) {
  const trimmed = String(path || '').trim();
  if (!trimmed) return;
  const name = trimmed.split(/[\\/]/).pop();
  if (!name) return;
  if (app.wizard.extras.some((extra) => extra.path === trimmed)) return;
  app.wizard.extras = [...app.wizard.extras, { name, path: trimmed }];
  syncWizardJobs();
  persistWizardDraft();
}

export function wizardRemoveExtra(path) {
  app.wizard.extras = app.wizard.extras.filter((extra) => extra.path !== path);
  syncWizardJobs();
  persistWizardDraft();
}

/** The ordered union of selected root clips and transient extras. */
export function wizardSelected() {
  const extras = app.wizard.extras.map((extra) => extra.name);
  return [...app.wizard.selected, ...extras.filter((name) => !app.wizard.selected.includes(name))];
}

export function wizardSetActiveJob(source) {
  app.wizard.activeJob = source;
  persistWizardDraft();
}

function syncWizardJobs() {
  const keep = new Set(wizardSelected());
  for (const source of Object.keys(app.wizard.jobs)) {
    if (!keep.has(source)) delete app.wizard.jobs[source];
  }
  for (const source of keep) {
    if (!app.wizard.jobs[source]) app.wizard.jobs[source] = { values: {}, overrides: [] };
  }
  if (!keep.has(app.wizard.activeJob)) app.wizard.activeJob = wizardSelected()[0] || '';
}

/* --- Wizard: tri-state configuration ------------------------------------- */

export function globalDefault(path) {
  return getPath(app.configuration.job_defaults || {}, path);
}

export function batchHasOverride(path) {
  return app.wizard.batch.overrides.includes(path);
}

export function batchValue(path) {
  return batchHasOverride(path)
    ? getPath(app.wizard.batch.values, path)
    : globalDefault(path);
}

export function jobHasOverride(source, path) {
  return (app.wizard.jobs[source]?.overrides || []).includes(path);
}

export function jobValue(source, path) {
  return jobHasOverride(source, path)
    ? getPath(app.wizard.jobs[source].values, path)
    : batchValue(path);
}

function upsert(target, path, value) {
  setPath(target.values, path, value);
  if (!target.overrides.includes(path)) target.overrides = [...target.overrides, path];
}

function removeOverride(target, path) {
  target.overrides = target.overrides.filter((item) => item !== path);
  const keys = path.split('.');
  let node = target.values;
  for (const key of keys.slice(0, -1)) {
    if (typeof node?.[key] !== 'object' || node[key] === null) return;
    node = node[key];
  }
  delete node[keys[keys.length - 1]];
}

export function setBatchField(path, value) {
  upsert(app.wizard.batch, path, value);
  persistWizardDraft();
  scheduleValidation();
}

export function clearBatchField(path) {
  removeOverride(app.wizard.batch, path);
  persistWizardDraft();
  scheduleValidation();
}

export function setJobField(source, path, value) {
  if (!app.wizard.jobs[source]) app.wizard.jobs[source] = { values: {}, overrides: [] };
  upsert(app.wizard.jobs[source], path, value);
  persistWizardDraft();
  scheduleValidation();
}

export function clearJobField(source, path) {
  if (!app.wizard.jobs[source]) return;
  removeOverride(app.wizard.jobs[source], path);
  persistWizardDraft();
  scheduleValidation();
}

/** Materialize one job's effective config from global + batch + job overrides. */
export function materializeJobConfig(source) {
  const config = clone(app.configuration.job_defaults || {});
  for (const path of app.wizard.batch.overrides) {
    setPath(config, path, getPath(app.wizard.batch.values, path));
  }
  const job = app.wizard.jobs[source];
  for (const path of job?.overrides || []) {
    setPath(config, path, getPath(job.values, path));
  }
  config.general = { ...(config.general || {}), source };
  return config;
}

export function buildWizardPayload() {
  const selected = wizardSelected();
  return {
    source_names: [...app.wizard.selected],
    sources: app.wizard.extras.map((extra) => extra.path),
    job_configs: selected.map((source) => materializeJobConfig(source)),
    overrides: {},
  };
}

/* --- Wizard: live validation + create ------------------------------------ */

function scheduleValidation() {
  if (!app.wizard.active || app.wizard.step !== 2) return;
  if (validationTimer) clearTimeout(validationTimer);
  validationTimer = setTimeout(() => {
    validationTimer = null;
    validateWizard().catch(report);
  }, 500);
}

export async function validateWizard() {
  if (!wizardSelected().length) {
    app.wizard.validation = null;
    return null;
  }
  app.wizard.validating = true;
  try {
    const result = await api.validateJobs(buildWizardPayload());
    app.wizard.validation = {
      at: Date.now(),
      perSource: Object.fromEntries(
        (result.failed || []).map((item) => [item.source, item.message]),
      ),
    };
    return result;
  } catch (error) {
    report(error);
    return null;
  } finally {
    app.wizard.validating = false;
  }
}

export function wizardJobError(source) {
  return app.wizard.validation?.perSource?.[source] || '';
}

export async function createFromWizard() {
  app.busy = true;
  clearErrors();
  try {
    const payload = buildWizardPayload();
    const validation = await api.validateJobs(payload);
    const invalid = new Set((validation.failed || []).map((item) => item.source));
    app.wizard.validation = {
      at: Date.now(),
      perSource: Object.fromEntries(
        (validation.failed || []).map((item) => [item.source, item.message]),
      ),
    };
    if (invalid.size) {
      app.errors = (validation.failed || []).map(
        (item) => `${item.source || 'record'}: ${item.message}`,
      );
    }
    const validSources = new Set(
      payload.job_configs
        .map((config) => config.general?.source)
        .filter((source) => !invalid.has(source)),
    );
    const filtered = {
      source_names: payload.source_names.filter((name) => validSources.has(name)),
      sources: app.wizard.extras
        .filter((extra) => validSources.has(extra.name))
        .map((extra) => extra.path),
      job_configs: payload.job_configs.filter(
        (config) => validSources.has(config.general?.source),
      ),
      overrides: {},
    };
    if (!filtered.job_configs.length && !filtered.sources.length) {
      app.busy = false;
      return;
    }
    const result = await api.createJobs(filtered);
    if (result.failed?.length) {
      app.errors = result.failed.map((item) => `${item.source || 'record'}: ${item.message}`);
      app.busy = false;
      return;
    }
    clearWizardDraft();
    app.wizard = emptyWizard();
    app.view = 'queue';
    await loadWorkspace();
    notify(
      `${result.summary?.created ?? result.created.length} created · ` +
        `${result.summary?.skipped ?? 0} skipped`,
    );
  } catch (error) {
    report(error);
  } finally {
    app.busy = false;
  }
}

/* --- Wizard: draft persistence ------------------------------------------- */

export function persistWizardDraft() {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify($state.snapshot(app.wizard)));
  } catch {
    /* storage full or unavailable: the draft stays in memory only */
  }
}

export function restoreWizardDraft() {
  if (typeof localStorage === 'undefined') return;
  let raw;
  try {
    raw = localStorage.getItem(DRAFT_KEY);
  } catch {
    return;
  }
  if (!raw) return;
  try {
    const draft = JSON.parse(raw);
    if (!draft || typeof draft !== 'object') return;
    const hasWork =
      (draft.selected?.length || 0) > 0 ||
      (draft.extras?.length || 0) > 0 ||
      (draft.batch?.overrides?.length || 0) > 0;
    if (!hasWork) return;
    app.wizard = { ...emptyWizard(), ...draft, active: false, validating: false };
    syncWizardJobs();
  } catch {
    /* ignore a malformed draft */
  }
}

export function clearWizardDraft() {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* nothing to clear */
  }
}

/* --- Job actions --------------------------------------------------------- */

async function performJobAction(job, action, arg) {
  if (!job) return;
  try {
    if (action === 'delete') {
      await api.deleteJob(job.job_id);
      if (app.selectedJobId === job.job_id) closeJob();
      await loadWorkspace();
      notify('Job moved to trash');
    } else if (action === 'cancel') {
      await api.cancelJob(job.job_id);
      await refreshJob(job.job_id);
      notify('Cancellation requested');
    } else if (action === 'resume') {
      await api.resumeJob(job.job_id);
      await refreshJob(job.job_id);
      notify('Resume requested');
    } else if (action === 'render') {
      await api.renderJob(job.job_id, arg || undefined);
      await refreshJob(job.job_id);
      notify(arg ? `Render requested for group ${arg}` : 'Render requested');
    }
  } catch (error) {
    report(error);
  }
}

export async function jobAction(action, arg) {
  await performJobAction(selectedJob(), action, arg);
}

export async function cardAction(job, action) {
  await performJobAction(job, action);
}

export async function cancelScheduledAttempt(job, attemptId) {
  try {
    await api.cancelScheduledAttempt(job.job_id, attemptId);
    await refreshJob(job.job_id);
    notify('Scheduled attempt cancelled');
  } catch (error) {
    report(error);
  }
}

async function refreshJob(jobId) {
  if (app.selectedJobId === jobId) await loadJobDetails();
  else await loadWorkspace();
}

export async function retryCheckpoint(stage) {
  const job = selectedJob();
  if (!job) return;
  try {
    await api.retryCheckpoint(job.job_id, stage, job.checkpoints[stage].revision);
    await refreshJob(job.job_id);
    notify(`${stage} retry requested`);
  } catch (error) {
    report(error);
  }
}

export async function acceptCheckpoint(stage, group) {
  const job = selectedJob();
  if (!job) return;
  try {
    await api.acceptCheckpoint(job.job_id, stage, job.checkpoints[stage].revision, group);
    await refreshJob(job.job_id);
    notify(`${stage} review accepted`);
  } catch (error) {
    report(error);
  }
}

/* --- Transcript / composition ------------------------------------------- */

export function updateSegment(segment, key, value) {
  if (!app.transcript) return;
  const segments = app.transcript.segments;
  const index = segments.indexOf(segment);
  if (index < 0) return;
  segments[index] = { ...segment, [key]: value };
  app.transcript = { ...app.transcript, segments: [...segments] };
}

export function updateSegmentTypography(segment, key, value) {
  const typography = { ...(segment.typography || {}) };
  if (key === 'bold' || key === 'italic' || key === 'underline') {
    typography[key] = value;
  } else if (value === '') {
    delete typography[key];
  } else {
    typography[key] = key === 'size' ? Number(value) : value;
  }
  updateSegment(segment, 'typography', typography);
}

export async function saveTranscript() {
  const job = selectedJob();
  if (!job || !app.transcript || !job.active_transcript) return;
  try {
    app.transcript = await api.saveTranscript(job.job_id, {
      ...app.transcript,
      expected_revision: job.active_transcript.revision,
      expected_checkpoint_revision: job.checkpoints.transcript.revision,
    });
    await loadWorkspace();
    notify('Transcript revision saved');
  } catch (error) {
    report(error);
  }
}

export async function saveComposition(composition) {
  const job = selectedJob();
  if (!job) return false;
  let layout;
  try {
    layout = JSON.parse(composition);
  } catch (error) {
    app.errors = [`Invalid layout JSON: ${error.message}`];
    return false;
  }
  const apply = async () => {
    try {
      await api.patchJobConfiguration(
        job.job_id,
        { conversion: { layout } },
        job.current_configuration_hash,
        job.status === 'completed',
      );
      await refreshJob(job.job_id);
      notify('Job composition saved · render to apply');
      return true;
    } catch (error) {
      report(error);
      return false;
    }
  };
  if (job.status === 'completed') {
    requestConfirm({
      title: 'Reopen this completed job?',
      message: 'Saving reopens the job and marks its current render stale.',
      confirmLabel: 'Reopen & save',
      onConfirm: apply,
    });
    return false;
  }
  return apply();
}

/* --- Upload draft / suggestions / attempts ------------------------------ */

function buildPlatformOverrides() {
  const platformOverrides = {};
  for (const platform of app.platforms) {
    platformOverrides[platform] = {
      upload: { skip: !app.publish.selectedPlatforms.includes(platform) },
    };
  }
  if (app.publish.selectedPlatforms.includes('facebook')) {
    platformOverrides.facebook.content_kind = app.publish.contentKind;
  }
  return platformOverrides;
}

export async function saveUploadDraft() {
  const job = selectedJob();
  if (!job) return false;
  const draft = app.publish.draft;
  const upload = $state.snapshot(job.configuration.upload || {});
  upload.content = {
    ...(upload.content || {}),
    title: draft.title,
    description: draft.description,
    tags: draft.tags
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean),
  };
  const publishAt = toUtcTimestamp(draft.publishAt);
  if (publishAt) upload.schedule = { ...(upload.schedule || {}), publish_at: publishAt };
  else delete upload.schedule;
  try {
    await api.saveUploadDraft(job.job_id, {
      expected_revision: job.checkpoints.upload.revision,
      upload,
      platforms: buildPlatformOverrides(),
    });
    await loadWorkspace();
    notify('Upload draft saved');
    return true;
  } catch (error) {
    report(error);
    return false;
  }
}

export async function generateSuggestions(force = false) {
  const job = selectedJob();
  if (!job) return;
  try {
    await api.suggestUpload(job.job_id, {
      platforms: app.publish.selectedPlatforms,
      force,
    });
    await loadJobDetails();
    notify(force ? 'Suggestions regenerated' : 'Suggestions generated');
  } catch (error) {
    report(error);
  }
}

export async function acceptSuggestion(platform) {
  const job = selectedJob();
  if (!job) return;
  try {
    await api.acceptSuggestions(job.job_id, [platform]);
    await loadJobDetails();
    notify(`${platform} suggestion applied`);
  } catch (error) {
    report(error);
  }
}

export async function acceptAllSuggestions(platforms) {
  const job = selectedJob();
  if (!job || !platforms.length) return;
  try {
    await api.acceptSuggestions(job.job_id, platforms);
    await loadJobDetails();
    notify('All suggestions applied');
  } catch (error) {
    report(error);
  }
}

export async function clearSuggestions() {
  const job = selectedJob();
  if (!job) return;
  try {
    const upload = $state.snapshot(job.configuration.upload || {});
    const block = upload.suggestions || {};
    upload.suggestions = { provider: block.provider || 'template', model: block.model ?? null };
    await api.saveUploadDraft(job.job_id, {
      expected_revision: job.checkpoints.upload.revision,
      upload,
    });
    await loadJobDetails();
    notify('Suggestions cleared');
  } catch (error) {
    report(error);
  }
}

export function editSuggestion(row, key, value) {
  const current = app.publish.suggestionEdits[row.platform] || {
    title: row.title || '',
    description: row.description || '',
    hashtags: (row.hashtags || []).join(', '),
  };
  app.publish.suggestionEdits = {
    ...app.publish.suggestionEdits,
    [row.platform]: { ...current, [key]: value },
  };
}

export async function saveSuggestionEdits(platform) {
  const job = selectedJob();
  const edit = app.publish.suggestionEdits[platform];
  if (!job || !edit) return;
  try {
    const upload = $state.snapshot(job.configuration.upload || {});
    const block = upload.suggestions || {};
    block[platform] = {
      ...(block[platform] || {}),
      title: edit.title,
      description: edit.description,
      hashtags: edit.hashtags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
    };
    upload.suggestions = block;
    await api.saveUploadDraft(job.job_id, {
      expected_revision: job.checkpoints.upload.revision,
      upload,
    });
    await loadJobDetails();
    notify(`${platform} suggestion updated`);
  } catch (error) {
    report(error);
  }
}

export async function submitUpload() {
  const job = selectedJob();
  if (!job) return;
  try {
    const saved = await saveUploadDraft();
    if (saved === false) return;
    await loadWorkspace();
    const submitted = await api.submitUpload(job.job_id, {
      platforms: app.publish.selectedPlatforms,
    });
    await refreshJob(job.job_id);
    notify(
      submitted.scheduled
        ? 'Upload attempts scheduled for the chosen time'
        : 'Upload attempts started',
    );
  } catch (error) {
    report(error);
  }
}

export async function retryUpload(attempt) {
  const job = selectedJob();
  if (!job) return;
  try {
    await api.retryUpload(job.job_id, attempt.platform, {
      attempt_id: attempt.attempt_id,
    });
    await refreshJob(job.job_id);
    notify(`${attempt.platform} retry started`);
  } catch (error) {
    report(error);
  }
}

export async function applyAttemptFilters() {
  const job = selectedJob();
  if (!job) return;
  const filters = app.publish.attemptFilters;
  try {
    app.attempts = await api.listUploads(job.job_id, {
      status: filters.status,
      platform: filters.platform,
      since: filters.since ? new Date(filters.since).toISOString() : '',
    });
  } catch (error) {
    report(error);
  }
}

/* --- Artifacts ----------------------------------------------------------- */

export async function renameArtifact(artifact, displayName) {
  const job = selectedJob();
  if (!job || !displayName) return;
  try {
    await api.patchArtifact(job.job_id, artifact.id, displayName);
    await refreshJob(job.job_id);
    notify('Artifact renamed');
  } catch (error) {
    report(error);
  }
}

export async function deleteArtifact(artifact) {
  const job = selectedJob();
  if (!job) return;
  try {
    await api.deleteArtifact(job.job_id, artifact.id);
    await refreshJob(job.job_id);
    notify('Artifact moved to trash');
  } catch (error) {
    report(error);
  }
}

export async function pruneArtifacts() {
  const job = selectedJob();
  if (!job) return;
  try {
    const result = await api.pruneArtifacts(job.job_id);
    await refreshJob(job.job_id);
    notify(`Pruned ${(result.pruned || []).length} artifact(s)`);
  } catch (error) {
    report(error);
  }
}

/* --- Metrics ------------------------------------------------------------- */

export async function pullMetrics() {
  const job = selectedJob();
  if (!job) return;
  try {
    const result = await api.pullMetrics(job.job_id);
    app.metrics = await api.getMetrics(job.job_id, true);
    notify(`Metrics refreshed (${result.pulled || 0} snapshots)`);
  } catch (error) {
    report(error);
  }
}

/* --- Layouts ------------------------------------------------------------- */

export async function createLayout(name, layout) {
  try {
    await api.createLayout(name, layout);
    app.layouts = await api.listLayouts();
    notify('Layout saved');
  } catch (error) {
    report(error);
  }
}

export async function deleteLayout(id) {
  try {
    await api.deleteLayout(id);
    app.layouts = await api.listLayouts();
    notify('Layout removed');
  } catch (error) {
    report(error);
  }
}

/* --- Settings / credentials --------------------------------------------- */

export async function saveSettings() {
  try {
    const result = await api.saveConfiguration(app.configuration);
    app.configuration = result.configuration;
    app.platforms = platformsFromConfiguration(app.configuration);
    notify('app.yml saved');
  } catch (error) {
    report(error);
  }
}

export async function probeCredential(platform) {
  try {
    const record = await api.probeCredential(platform);
    app.probeResults = { ...app.probeResults, [platform]: record.probe };
  } catch (error) {
    report(error);
  }
}
