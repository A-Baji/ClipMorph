/** Presentational formatters shared by every view. */

export function formatBytes(bytes) {
  if (typeof bytes !== 'number' || Number.isNaN(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = -1;
  do {
    value /= 1024;
    unit += 1;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

export function formatDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ``datetime-local`` speaks wall-clock time with no offset, so the stored UTC
// timestamp is shifted before it reaches the input and read back the same way.
export function toLocalInput(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

export function toUtcTimestamp(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export function scheduleLabel(attempt) {
  if (attempt.status !== 'scheduled' || !attempt.scheduled_publish_at) return '';
  const then = new Date(attempt.scheduled_publish_at);
  if (Number.isNaN(then.getTime())) return '';
  const delta = then.getTime() - Date.now();
  const hours = Math.floor(delta / 3600000);
  const minutes = Math.floor((delta % 3600000) / 60000);
  const countdown =
    delta <= 0 ? 'due now' : hours > 0 ? `in ${hours}h ${minutes}m` : `in ${minutes}m`;
  return `${then.toLocaleString()} (${countdown})`;
}

export function formatDelta(delta) {
  if (delta === null || delta === undefined) return '—';
  return delta > 0 ? `+${delta}` : String(delta);
}

export function soonestScheduledPublish(job) {
  const stamps = (job.upload_attempts || [])
    .filter((attempt) => attempt.status === 'scheduled' && attempt.scheduled_publish_at)
    .map((attempt) => new Date(attempt.scheduled_publish_at))
    .filter((date) => !Number.isNaN(date.getTime()));
  if (!stamps.length) return '';
  stamps.sort((a, b) => a.getTime() - b.getTime());
  return stamps[0].toLocaleString();
}

const STATUS_TONES = {
  completed: 'success',
  published: 'success',
  ok: 'success',
  running: 'info',
  scheduled: 'info',
  partial_failure: 'warning',
  awaiting_review: 'warning',
  pending: 'neutral',
  created: 'neutral',
  stale: 'warning',
  failed: 'danger',
  cancelled: 'danger',
  unavailable: 'neutral',
  skipped: 'neutral',
  deleted: 'neutral',
};

export function statusTone(status) {
  return STATUS_TONES[status] || 'neutral';
}

export function humanize(value) {
  if (!value) return '';
  return String(value).replace(/_/g, ' ');
}

export function artifactLabel(artifact) {
  if (!artifact) return '';
  return artifact.display_name || artifact.kind || artifact.id;
}

const PLATFORM_LABELS = {
  youtube: 'YouTube',
  instagram: 'Instagram',
  tiktok: 'TikTok',
  twitter: 'Twitter / X',
  facebook: 'Facebook',
};

export function platformLabel(platform) {
  return PLATFORM_LABELS[platform] || platform;
}

/** Collapse a metric snapshot list into one entry per published post. */
export function groupMetricPosts(snapshots) {
  const posts = {};
  for (const snapshot of snapshots || []) {
    const key = `${snapshot.platform}:${snapshot.platform_post_id}`;
    if (!posts[key]) posts[key] = [];
    posts[key].push(snapshot);
  }
  return Object.values(posts).map((history) => ({
    platform: history[0].platform,
    platform_post_id: history[0].platform_post_id,
    platform_url: history[history.length - 1].platform_url,
    first: history[0],
    latest: history[history.length - 1],
  }));
}

export function metricRows(post) {
  const names = [
    ...new Set([
      ...(post.first.metrics ? Object.keys(post.first.metrics) : []),
      ...(post.latest.metrics ? Object.keys(post.latest.metrics) : []),
    ]),
  ];
  return names.map((name) => {
    const before = post.first.metrics?.[name];
    const after = post.latest.metrics?.[name];
    const delta =
      typeof before === 'number' && typeof after === 'number' ? after - before : null;
    return { name, value: after ?? before ?? null, delta };
  });
}
