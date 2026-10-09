/**
 * Global dashboard state and actions (Svelte 5 runes module).
 *
 * Views read from ``app`` and call the exported actions; no view talks to the
 * API directly. Derived values are computed in the components with
 * ``$derived`` so the store stays a plain, testable state container.
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

function emptyDraft() {
  return { title: '', description: '', tags: '', publishAt: '' };
}

function emptyCreate() {
  return {
    selectedSources: [],
    expandedSource: '',
    perSource: {},
    title: '',
    description: '',
    tags: '',
    renderer: 'overlay',
    layoutId: '',
    validateOnly: false,
    include: [],
    advanced: {
      noConfirm: false,
      clean: false,
      conversionSkip: false,
      subtitlesSkip: false,
      strict: false,
      uploadSkip: false,
    },
    result: null,
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
  artifacts: [],
  attempts: [],
  metrics: [],
  metricsComparison: [],
  metricFilterPlatform: '',
  platformSummaries: {},
  uploadProgress: {},
  transcript: null,
  create: emptyCreate(),
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
  if (view === 'metrics') loadMetrics();
  if (view === 'layouts') {
    api.listLayouts().then((items) => (app.layouts = items)).catch(report);
  }
}

export function openJob(jobId) {
  app.selectedJobId = jobId;
  app.detailTab = 'overview';
  app.view = 'job';
  loadJobDetails().catch(report);
}

export function closeJob() {
  closeProgressStream();
  app.view = 'queue';
  app.selectedJobId = '';
  app.transcript = null;
}

/* --- Loaders ------------------------------------------------------------- */

function platformsFromConfiguration(configuration) {
  const keys = Object.keys(configuration?.job_defaults?.platforms || {});
  return keys.length ? keys : [...FALLBACK_PLATFORMS];
}

export async function loadWorkspace() {
  try {
    const [jobs, sources, layouts, settings] = await Promise.all([
      api.listJobs(),
      api.listSources(),
      api.listLayouts(),
      api.getConfiguration(),
    ]);
    app.jobs = jobs;
    app.sources = sources;
    app.layouts = layouts;
    app.configuration = settings.configuration || { ...FALLBACK_CONFIGURATION };
    app.credentials = settings.credentials || {};
    app.platforms = platformsFromConfiguration(app.configuration);
    if (!app.create.include.length) app.create.include = [...app.platforms];
    app.online = true;
    app.ready = true;
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

/* --- Creation flow ------------------------------------------------------- */

export function resetCreate() {
  const include = [...app.platforms];
  app.create = { ...emptyCreate(), include };
}

function buildCreatePayload() {
  const form = app.create;
  const selected = form.selectedSources.length
    ? form.selectedSources
    : app.sources.map((source) => source.name);
  const jobConfigs = selected.map((source) => {
    const perSource = form.perSource[source] || {};
    const content = {};
    for (const key of ['title', 'description', 'tags']) {
      const value = perSource[key];
      if (typeof value === 'string' && value.trim()) {
        content[key] =
          key === 'tags'
            ? value.split(',').map((tag) => tag.trim()).filter(Boolean)
            : value;
      }
    }
    return {
      general: { source },
      ...(Object.keys(content).length ? { upload: { content } } : {}),
    };
  });
  const advanced = form.advanced;
  const platformOverrides = {};
  for (const platform of app.platforms) {
    platformOverrides[platform] = {
      upload: { skip: !form.include.includes(platform) },
    };
  }
  const overrides = {
    general: { no_confirm: advanced.noConfirm, clean: advanced.clean },
    conversion: {
      skip: advanced.conversionSkip,
      strict: advanced.strict,
      subtitles: { skip: advanced.subtitlesSkip, renderer: form.renderer },
      ...(form.layoutId ? { layout_id: form.layoutId } : {}),
    },
    upload: {
      skip: advanced.uploadSkip,
      content: {
        title: form.title,
        description: form.description,
        tags: form.tags
          ? form.tags.split(',').map((tag) => tag.trim()).filter(Boolean)
          : [],
      },
    },
    platforms: platformOverrides,
  };
  return { source_names: form.selectedSources.length ? selected : null, job_configs: jobConfigs, overrides };
}

export async function submitCreate() {
  const form = app.create;
  app.busy = true;
  clearErrors();
  try {
    if (form.uploadFile) {
      const uploaded = await api.uploadSource(form.uploadFile);
      form.selectedSources = [...new Set([...form.selectedSources, uploaded.name])];
      form.uploadFile = null;
    }
    const payload = buildCreatePayload();
    if (form.validateOnly) {
      const validation = await api.validateJobs(payload);
      if (!validation.valid) {
        app.errors = validation.failed.map(
          (item) => `${item.source || 'record'}: ${item.message}`,
        );
        return;
      }
      notify(`Validation passed for ${validation.summary.created} source(s)`);
      return;
    }
    const result = await api.createJobs(payload);
    app.create.result = result;
    await loadWorkspace();
    if (result.created.length) {
      notify(
        `${result.summary.created} created · ${result.summary.skipped} skipped · ` +
          `${result.summary.failed} failed`,
      );
    }
    if (result.failed.length) {
      app.errors = result.failed.map(
        (item) => `${item.source || 'record'}: ${item.message}`,
      );
    }
  } catch (error) {
    report(error);
  } finally {
    app.busy = false;
  }
}

/* --- Job actions --------------------------------------------------------- */

export async function jobAction(action) {
  const job = selectedJob();
  if (!job) return;
  try {
    if (action === 'delete') {
      await api.deleteJob(job.job_id);
      closeJob();
      await loadWorkspace();
      notify('Job moved to trash');
    } else if (action === 'cancel') {
      await api.cancelJob(job.job_id);
      await refreshSelected();
      notify('Cancellation requested');
    } else if (action === 'resume') {
      await api.resumeJob(job.job_id);
      await refreshSelected();
      notify('Resume requested');
    } else if (action === 'render') {
      await api.renderJob(job.job_id);
      await refreshSelected();
      notify('Render requested');
    }
  } catch (error) {
    report(error);
  }
}

export async function retryCheckpoint(stage) {
  const job = selectedJob();
  if (!job) return;
  try {
    await api.retryCheckpoint(job.job_id, stage, job.checkpoints[stage].revision);
    await refreshSelected();
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
    await refreshSelected();
    notify(`${stage} review accepted`);
  } catch (error) {
    report(error);
  }
}

async function refreshSelected() {
  if (app.selectedJobId) await loadJobDetails();
  else await loadWorkspace();
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
      await refreshSelected();
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
    await refreshSelected();
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
    await refreshSelected();
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
    await refreshSelected();
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
    await refreshSelected();
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
    await refreshSelected();
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
