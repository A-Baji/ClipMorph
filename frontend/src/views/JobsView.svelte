<script>
  import Icon from '../components/Icon.svelte';
  import Badge from '../components/Badge.svelte';
  import Tabs from '../components/Tabs.svelte';
  import Progress from '../components/Progress.svelte';
  import Thumbnail from '../components/Thumbnail.svelte';
  import {
    app,
    cardAction,
    cancelScheduledAttempt,
    loadWorkspace,
    openJob,
    openJobFolder,
    requestConfirm,
    setJobsTab,
    startWizard,
  } from '../lib/store.svelte.js';
  import {
    statusTone,
    humanize,
    soonestScheduledPublish,
    formatDateTime,
  } from '../lib/format.js';

  /**
   * The Jobs tab (issue #259 B20): two sub-tabs — Completed (the archive,
   * the default) and Queue (the kanban board). "New" lives above both
   * sub-tabs. The board (B2/12/3) always renders its four columns; completed
   * jobs never appear on it and never render progress bars (B19).
   */
  const QUEUED_PRE_RUN = ['queued', 'created', 'pending'];

  const COLUMNS = [
    { id: 'running', label: 'Running', statuses: ['running', ...QUEUED_PRE_RUN] },
    { id: 'awaiting_review', label: 'Awaiting review', statuses: ['awaiting_review'] },
    { id: 'scheduled', label: 'Scheduled', statuses: ['scheduled'] },
    { id: 'failed', label: 'Failed', statuses: ['failed', 'cancelled', 'partial_failure'] },
  ];

  const jobsTabs = $derived([
    { id: 'completed', label: 'Completed' },
    // B20: the WIP count badge moved here from the sidebar item.
    { id: 'queue', label: 'Queue', count: wipCount || null },
  ]);

  let collapsed = $state({});

  const boardJobs = $derived(app.jobs.filter((job) => job.status !== 'completed'));
  const wipCount = $derived(boardJobs.length);
  const completedJobs = $derived(app.jobs.filter((job) => job.status === 'completed'));

  function columnJobs(column) {
    return boardJobs.filter((job) => column.statuses.includes(job.status));
  }

  function columnQueuedCount(column) {
    return columnJobs(column).filter((job) => QUEUED_PRE_RUN.includes(job.status)).length;
  }

  function jobTitle(job) {
    return (
      job.configuration?.upload?.content?.title ||
      job.configuration?.general?.source ||
      job.job_id
    );
  }

  /** Completed time: the upload checkpoint's completion, else the last job update. */
  function completedTime(job) {
    return formatDateTime(job.checkpoints?.upload?.completed_at || job.updated_at);
  }

  function scheduledAttempt(job) {
    return (job.upload_attempts || []).find((attempt) => attempt.status === 'scheduled');
  }

  function canResume(job) {
    return ['failed', 'cancelled', 'partial_failure', ...QUEUED_PRE_RUN].includes(job.status);
  }

  function canCancel(job) {
    return !['completed', 'cancelled', 'failed'].includes(job.status);
  }

  function resumeLabel(job) {
    return QUEUED_PRE_RUN.includes(job.status) ? 'Run' : 'Resume';
  }

  function confirmDelete(job) {
    requestConfirm({
      title: 'Delete this job?',
      message: 'The job and its local output are moved to trash. Remote posts are not touched.',
      confirmLabel: 'Delete job',
      danger: true,
      onConfirm: () => cardAction(job, 'delete'),
    });
  }

  function confirmCancel(job) {
    requestConfirm({
      title: 'Cancel this job?',
      message: 'Queued and running work is aborted. Scheduled attempts are cancelled.',
      confirmLabel: 'Cancel job',
      danger: true,
      onConfirm: () => cardAction(job, 'cancel'),
    });
  }

  function confirmCancelAttempt(job) {
    const attempt = scheduledAttempt(job);
    if (!attempt) return;
    requestConfirm({
      title: 'Cancel this scheduled attempt?',
      message: `${attempt.platform} will not publish this attempt.`,
      confirmLabel: 'Cancel attempt',
      danger: true,
      onConfirm: () => cancelScheduledAttempt(job, attempt.attempt_id),
    });
  }

  function toggleColumn(id) {
    collapsed = { ...collapsed, [id]: !collapsed[id] };
  }
</script>

<div class="content board-view">
  <div class="jobs-head">
    <div class="row">
      <Tabs tabs={jobsTabs} active={app.jobsTab} onSelect={setJobsTab} />
    </div>
    <div class="row">
      <button class="btn btn-ghost btn-sm" onclick={loadWorkspace}>
        <Icon name="refresh" /> Refresh
      </button>
      <button class="btn btn-primary" onclick={startWizard}>
        <Icon name="plus" /> New
      </button>
    </div>
  </div>

  {#if app.jobsTab === 'queue'}
    <div class="board">
      {#each COLUMNS as column (column.id)}
        {@const jobs = columnJobs(column)}
        {@const queuedCount = columnQueuedCount(column)}
        <section class="column" class:collapsed={collapsed[column.id]} aria-label={column.label}>
          <button
            type="button"
            class="column-head"
            aria-expanded={!collapsed[column.id]}
            onclick={() => toggleColumn(column.id)}
          >
            <span class="column-title">{column.label}</span>
            {#if column.id === 'running' && queuedCount > 0}
              <span class="badge queued-badge">queued {queuedCount}</span>
            {/if}
            <span class="wip">{jobs.length}</span>
            <Icon name={collapsed[column.id] ? 'chevronRight' : 'chevronDown'} size={14} />
          </button>
          {#if !collapsed[column.id]}
            <div class="column-body">
              {#each jobs as job (job.job_id)}
                {@const attempt = scheduledAttempt(job)}
                {@const sourceName = job.configuration?.general?.source}
                <article class="card">
                  <button
                    class="card-main"
                    aria-label={`Open ${jobTitle(job)}`}
                    onclick={() => openJob(job.job_id)}
                  >
                    <!-- C5: real poster frame; the icon is the fallback only. -->
                    <Thumbnail name={sourceName} size={48} alt="" />
                    <span class="card-text">
                      <span class="card-title truncate">{jobTitle(job)}</span>
                      <span class="card-meta">
                        <Badge tone={statusTone(job.status)}>{humanize(job.status)}</Badge>
                        {#if job.current_checkpoint}
                          <span class="badge">{humanize(job.current_checkpoint)}</span>
                        {/if}
                      </span>
                      <span class="faint mono card-source truncate">{sourceName}</span>
                      {#if job.status === 'completed'}
                        <!-- B19: completed jobs never render progress bars. -->
                      {:else if app.uploadProgress[job.job_id] && Object.keys(app.uploadProgress[job.job_id]).length}
                        {#each Object.entries(app.uploadProgress[job.job_id]) as [platform, percent] (platform)}
                          <Progress value={percent} small label={`${platform}: ${percent}%`} />
                        {/each}
                      {:else if attempt}
                        <span class="faint mono card-source truncate">{soonestScheduledPublish(job)}</span>
                      {/if}
                    </span>
                  </button>
                  <!-- C4: quick actions are one bottom row of compact icon
                       buttons, each with a tooltip and an accessible name. -->
                  <div class="card-actions">
                    {#if canResume(job)}
                      <button
                        class="btn btn-ghost btn-icon"
                        title={`${resumeLabel(job)} ${jobTitle(job)}`}
                        aria-label={`${resumeLabel(job)} ${jobTitle(job)}`}
                        onclick={() => cardAction(job, 'resume')}
                      >
                        <Icon name="play" size={14} />
                      </button>
                    {/if}
                    {#if attempt}
                      <button
                        class="btn btn-ghost btn-icon"
                        title="Cancel attempt"
                        aria-label={`Cancel the scheduled attempt of ${jobTitle(job)}`}
                        onclick={() => confirmCancelAttempt(job)}
                      >
                        <Icon name="calendarX" size={14} />
                      </button>
                    {/if}
                    {#if canCancel(job)}
                      <button
                        class="btn btn-ghost btn-icon"
                        title={`Cancel ${jobTitle(job)}`}
                        aria-label={`Cancel ${jobTitle(job)}`}
                        onclick={() => confirmCancel(job)}
                      >
                        <Icon name="x" size={14} />
                      </button>
                    {/if}
                    <button
                      class="btn btn-ghost btn-icon"
                      title={`Delete ${jobTitle(job)}`}
                      aria-label={`Delete ${jobTitle(job)}`}
                      onclick={() => confirmDelete(job)}
                    >
                      <Icon name="trash" size={14} />
                    </button>
                  </div>
                </article>
              {/each}
              {#if !jobs.length}
                <p class="faint column-empty">No jobs</p>
              {/if}
            </div>
          {/if}
        </section>
      {/each}
    </div>
  {:else}
    {#if completedJobs.length}
      <div class="archive">
        {#each completedJobs as job (job.job_id)}
          {@const sourceName = job.configuration?.general?.source}
          <article class="archive-row">
            <button class="archive-main" onclick={() => openJob(job.job_id)}>
              <!-- C5: real poster frame; the icon is the fallback only. -->
              <Thumbnail name={sourceName} size={48} alt="" />
              <span class="archive-main-text">
                <b class="archive-title truncate">{jobTitle(job)}</b>
                <span class="faint mono archive-source truncate">{sourceName}</span>
              </span>
              <span class="faint archive-time">completed {completedTime(job)}</span>
            </button>
            <div class="archive-actions">
              <button
                class="btn btn-ghost btn-sm"
                disabled={!job.current_artifact_id}
                title="Reveal the exported file in its folder"
                aria-label={`Open the folder of ${jobTitle(job)}`}
                onclick={() => openJobFolder(job)}
              >
                <Icon name="external" size={14} /> Open folder
              </button>
              <button
                class="btn btn-ghost btn-icon"
                title={`Delete ${jobTitle(job)}`}
                aria-label={`Delete ${jobTitle(job)}`}
                onclick={() => confirmDelete(job)}
              >
                <Icon name="trash" size={14} />
              </button>
            </div>
          </article>
        {/each}
      </div>
    {:else}
      <div class="empty" role="status">
        <p>Nothing completed yet — start with <strong>New</strong></p>
      </div>
    {/if}
  {/if}
</div>

<style>
  .board-view {
    display: flex;
    flex-direction: column;
  }

  .jobs-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    flex-wrap: wrap;
  }

  /* --- Board (B3): fills the content area, columns share the full width,
         each column scrolls internally, the container scrolling horizontally
         below the 1400px breakpoint. --- */
  .board {
    flex: 1;
    min-height: 0;
    display: flex;
    gap: var(--space-3);
    overflow-x: auto;
    align-items: stretch;
  }

  .column {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    flex: 1 1 0;
    min-width: 280px;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  @media (min-width: 1400px) {
    .column {
      min-width: 220px;
    }
  }

  .column-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3);
    cursor: pointer;
    width: 100%;
    text-align: left;
    color: inherit;
    background: none;
    border: none;
    border-bottom: 1px solid var(--color-border);
  }

  .column-title {
    font-weight: 600;
    flex: 1;
    font-size: var(--text-sm);
    white-space: nowrap;
  }

  .queued-badge {
    color: var(--color-text-muted);
    flex-shrink: 0;
  }

  .wip {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }

  .column-body {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-2);
    align-content: start;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }

  /* C4: the fixed card anatomy — thumbnail left, title strong, status +
     checkpoint badges, single-line muted source, then the compact icon
     action row; everything on the 8px rhythm. */
  .card {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    display: grid;
    gap: var(--space-2);
  }

  .card-main {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    text-align: left;
    padding: var(--space-3);
    background: none;
    border: none;
    cursor: pointer;
    color: inherit;
  }

  .card-text {
    min-width: 0;
    flex: 1;
    display: grid;
    gap: var(--space-2);
    justify-items: start;
  }

  .card-title {
    font-weight: var(--weight-semibold);
    max-width: 100%;
  }

  .card-meta {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .card-source {
    font-size: var(--text-xs);
    max-width: 100%;
  }

  .card-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: 0 var(--space-3) var(--space-3);
  }

  .column-empty {
    padding: var(--space-2);
    font-size: var(--text-xs);
  }

  /* --- Completed archive (B20) --- */
  .archive {
    display: grid;
    gap: var(--space-2);
    align-content: start;
  }

  .archive-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
  }

  .archive-main {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    flex: 1;
    min-width: 0;
    background: none;
    border: none;
    color: inherit;
    cursor: pointer;
    text-align: left;
    padding: 0;
  }

  .archive-main-text {
    display: grid;
    gap: var(--space-1);
    min-width: 0;
    flex: 1;
  }

  .archive-title {
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    /* The text node truncates inside the flex row via .truncate. */
    flex: 1;
  }

  .archive-source {
    max-width: 100%;
  }

  .archive-time {
    font-size: var(--text-xs);
    flex-shrink: 0;
  }

  .archive-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-shrink: 0;
  }
</style>
