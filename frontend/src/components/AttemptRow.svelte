<script>
  import Badge from './Badge.svelte';
  import PlatformMark from './PlatformMark.svelte';
  import { app, retryUpload } from '../lib/store.svelte.js';
  import { statusTone, humanize, scheduleLabel, formatDateTime } from '../lib/format.js';

  /** One upload attempt row in the publish history. */
  let { attempt, jobId } = $props();

  const live = $derived(app.uploadProgress[jobId]?.[attempt.platform]);
  const url = $derived(attempt.result?.platform_url || attempt.platform_url || '');
  const finalPercent = $derived(attempt.result?.progress_percent);
  // U16: a missing snapshot title never falls back to the raw attempt id —
  // the stamp of the attempt (the platform mark beside it carries the name).
  const label = $derived(
    attempt.configuration_snapshot?.content?.title
      || (attempt.started_at || attempt.created_at
        ? `Attempt · ${formatDateTime(attempt.started_at || attempt.created_at)}`
        : 'Upload attempt'),
  );
  // F7 (spec review): the small line names the artifact by its display name,
  // never the raw artifact id.
  const artifactName = $derived(
    app.artifacts.find((a) => a.id === attempt.artifact_id)?.display_name
      || (attempt.artifact_id ? 'artifact' : 'no artifact'),
  );
</script>

<div class="list-row">
  <PlatformMark platform={attempt.platform} />
  <div class="grow">
    <b class="attempt-label">
      <Badge tone={statusTone(attempt.status)}>{humanize(attempt.status)}</Badge>
      <span class="truncate">{label}</span>
    </b>
    <small>{artifactName}{scheduleLabel(attempt) ? ` · ${scheduleLabel(attempt)}` : ''}</small>
  </div>
  {#if typeof live === 'number'}
    <span class="mono">{live}%</span>
  {:else if finalPercent !== undefined}
    <span class="mono">{finalPercent}%</span>
  {/if}
  {#if url}
    <a class="btn btn-ghost btn-sm" href={url} target="_blank" rel="noreferrer">View post</a>
  {/if}
  {#if attempt.status === 'failed'}
    <button class="btn btn-secondary btn-sm" onclick={() => retryUpload(attempt)}>Retry</button>
  {/if}
</div>

<style>
  /* U9/U16: one-line truncation for the fallback label row. */
  .attempt-label {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    min-width: 0;
  }
</style>
