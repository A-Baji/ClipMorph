<script>
  import Badge from './Badge.svelte';
  import PlatformMark from './PlatformMark.svelte';
  import { app, retryUpload } from '../lib/store.svelte.js';
  import { statusTone, humanize, scheduleLabel } from '../lib/format.js';

  /** One upload attempt row in the publish history. */
  let { attempt, jobId } = $props();

  const live = $derived(app.uploadProgress[jobId]?.[attempt.platform]);
  const url = $derived(attempt.result?.platform_url || attempt.platform_url || '');
  const finalPercent = $derived(attempt.result?.progress_percent);
</script>

<div class="list-row">
  <PlatformMark platform={attempt.platform} />
  <div class="grow">
    <b>
      <Badge tone={statusTone(attempt.status)}>{humanize(attempt.status)}</Badge>
      {attempt.configuration_snapshot?.content?.title || attempt.attempt_id}
    </b>
    <small>{attempt.artifact_id || 'no artifact'}{scheduleLabel(attempt) ? ` · ${scheduleLabel(attempt)}` : ''}</small>
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
