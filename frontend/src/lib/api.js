/**
 * Typed-ish client for the ClipMorph FastAPI surface (`/api/v1/*`).
 *
 * One function per route the dashboard uses. Nothing here invents endpoints:
 * every path below already exists in `clipmorph/web.py`, except `listPlatforms`
 * which is derived from `GET /configuration` (see store.svelte.js).
 */

const BASE = '/api/v1';

function query(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, value);
    }
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : '';
}

async function request(path, { method = 'GET', body, form } = {}) {
  const options = { method };
  if (form instanceof FormData) {
    options.body = form;
  } else if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`${BASE}${path}`, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.error;
    const message =
      detail?.message ||
      payload.detail?.message ||
      (typeof payload.detail === 'string' ? payload.detail : null) ||
      `Request failed (${response.status})`;
    const failure = new Error(message);
    failure.status = response.status;
    failure.code = detail?.code;
    failure.fields = detail?.fields;
    throw failure;
  }
  return payload;
}

export const api = {
  // Configuration / credentials
  getConfiguration: () => request('/configuration'),
  saveConfiguration: (configuration) =>
    request('/configuration', { method: 'PUT', body: { configuration } }),
  probeCredential: (platform) =>
    request(`/credentials/${platform}/probe`, { method: 'POST' }),

  // Sources
  listSources: () => request('/sources'),
  uploadSource: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('/sources', { method: 'POST', form });
  },

  // Layouts
  listLayouts: () => request('/layouts'),
  createLayout: (name, layout) =>
    request('/layouts', { method: 'POST', body: { name, layout } }),
  deleteLayout: (id) =>
    request(`/layouts/${id}${query({ confirm: true })}`, { method: 'DELETE' }),

  // Jobs
  listJobs: (status) => request(`/jobs${query({ status })}`),
  getJob: (id) => request(`/jobs/${id}`),
  validateJobs: (payload) => request('/jobs/validate', { method: 'POST', body: payload }),
  createJobs: (payload) => request('/jobs/bulk', { method: 'POST', body: payload }),
  patchJobConfiguration: (id, patch, expectedConfigurationHash, reopen = false) =>
    request(`/jobs/${id}/configuration`, {
      method: 'PATCH',
      body: {
        patch,
        expected_configuration_hash: expectedConfigurationHash,
        reopen,
      },
    }),
  deleteJob: (id) =>
    request(`/jobs/${id}${query({ confirm: true })}`, { method: 'DELETE' }),
  cancelJob: (id) =>
    request(`/jobs/${id}/cancel`, { method: 'POST', body: { confirm: true } }),
  resumeJob: (id) => request(`/jobs/${id}/resume`, { method: 'POST' }),
  retryCheckpoint: (id, stage, expectedRevision) =>
    request(`/jobs/${id}/checkpoints/${stage}/retry`, {
      method: 'POST',
      body: { expected_revision: expectedRevision },
    }),
  renderJob: (id, group) =>
    request(`/jobs/${id}/render`, { method: 'POST', body: group ? { group } : {} }),
  acceptCheckpoint: (id, stage, expectedRevision, group) =>
    request(`/jobs/${id}/checkpoints/${stage}/accept`, {
      method: 'POST',
      body: { expected_revision: expectedRevision, ...(group ? { group } : {}) },
    }),

  // Transcript
  getTranscript: (id) => request(`/jobs/${id}/transcript`),
  saveTranscript: (id, payload) =>
    request(`/jobs/${id}/transcript`, { method: 'PUT', body: payload }),

  // Upload draft / suggestions / attempts
  getUploadDraft: (id) => request(`/jobs/${id}/checkpoints/upload`),
  saveUploadDraft: (id, payload) =>
    request(`/jobs/${id}/checkpoints/upload`, { method: 'PUT', body: payload }),
  suggestUpload: (id, payload) =>
    request(`/jobs/${id}/checkpoints/upload/suggest`, { method: 'POST', body: payload }),
  acceptSuggestions: (id, platforms) =>
    request(`/jobs/${id}/checkpoints/upload/suggestions/accept`, {
      method: 'POST',
      body: { platforms },
    }),
  listUploads: (id, filters = {}) => request(`/jobs/${id}/uploads${query(filters)}`),
  submitUpload: (id, payload) =>
    request(`/jobs/${id}/upload`, { method: 'POST', body: payload }),
  retryUpload: (id, platform, payload) =>
    request(`/jobs/${id}/uploads/${platform}/retry`, { method: 'POST', body: payload }),

  // Artifacts
  listArtifacts: (id) => request(`/jobs/${id}/artifacts`),
  patchArtifact: (id, artifactId, displayName) =>
    request(`/jobs/${id}/artifacts/${artifactId}`, {
      method: 'PATCH',
      body: { display_name: displayName },
    }),
  deleteArtifact: (id, artifactId) =>
    request(`/jobs/${id}/artifacts/${artifactId}${query({ confirm: true })}`, {
      method: 'DELETE',
    }),
  pruneArtifacts: (id) =>
    request(`/jobs/${id}/artifacts/prune`, { method: 'POST' }),
  previewUrl: (id, artifactId) => `${BASE}/jobs/${id}/artifacts/${artifactId}/preview`,
  downloadUrl: (id, artifactId) => `${BASE}/jobs/${id}/artifacts/${artifactId}/download`,

  // Metrics
  getMetrics: (id, includeDimensions = false) =>
    request(`/jobs/${id}/metrics${query({ include: includeDimensions ? 'dimensions' : '' })}`),
  pullMetrics: (id) => request(`/jobs/${id}/metrics/pull`, { method: 'POST' }),
  compareMetrics: (platform, limit) =>
    request(`/metrics/comparison${query({ platform, limit })}`),

  // Live events
  eventsUrl: (id) => `${BASE}/jobs/${id}/events`,
};
