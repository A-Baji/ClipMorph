<script>
  import Icon from './Icon.svelte';
  import Badge from './Badge.svelte';
  import Progress from './Progress.svelte';
  import { app, openJob } from '../lib/store.svelte.js';
  import {
    statusTone,
    humanize,
    soonestScheduledPublish,
    formatDateTime,
  } from '../lib/format.js';

  /** One queue row; clicking opens the job detail. */
  let { job } = $props();

  const title = $derived(
    job.configuration?.upload?.content?.title ||
      job.configuration?.general?.source ||
      job.job_id,
  );
  const progress = $derived(app.uploadProgress[job.job_id] || {});
  const hasProgress = $derived(Object.keys(progress).length > 0);
  const iconName = $derived(
    job.status === 'completed' ? 'check'
    : job.status === 'scheduled' ? 'calendar'
    : job.status === 'failed' ? 'alert'
    : 'play',
  );
</script>

<button class="job-card" onclick={() => openJob(job.job_id)}>
  <span class="job-thumb"><Icon name={iconName} /></span>
  <span class="job-main">
    <span class="title">{title}</span>
    <span class="meta">
      <Badge tone={statusTone(job.status)}>{humanize(job.status)}</Badge>
      <span>{job.configuration?.general?.source}</span>
      <span>·</span>
      <span>{humanize(job.current_checkpoint) || 'no review'}</span>
    </span>
  </span>
  <span class="job-side">
    <span class="faint mono">{formatDateTime(job.updated_at)}</span>
    {#if hasProgress}
      <span class="job-progress">
        {#each Object.entries(progress) as [platform, percent] (platform)}
          <Progress value={percent} small label={`${platform}: ${percent}%`} />
        {/each}
      </span>
    {:else if job.status === 'scheduled'}
      <span class="faint mono">{soonestScheduledPublish(job)}</span>
    {/if}
  </span>
</button>
