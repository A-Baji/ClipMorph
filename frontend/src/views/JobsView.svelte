<script>
  import Icon from '../components/Icon.svelte';
  import Badge from '../components/Badge.svelte';
  import Progress from '../components/Progress.svelte';
  import Thumbnail from '../components/Thumbnail.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import {
    app,
    cardAction,
    cancelScheduledAttempt,
    openJob,
    openJobFolder,
    PRERUN_STATUSES,
    requestConfirm,
    startWizard,
  } from '../lib/store.svelte.js';
  import {
    statusTone,
    humanize,
    soonestScheduledPublish,
    formatDateTime,
  } from '../lib/format.js';

  /**
   * The Jobs view (issue #261 items 4/5/6): one board whose columns are the
   * real pipeline steps — Pending, Transcribe, Convert, Upload, Complete,
   * Failed. Running / Awaiting review / Scheduled render as status badges on
   * every card instead of columns. Clicking a column header expands that
   * stage into a full-width card grid (the Medal-style completed card from
   * item 2 lives here); "All stages" / Esc goes back. Statuses stay live via
   * the store's SSE job stream (item 1), so there is no Refresh affordance.
   */

  /** Stage → column resolution, in pipeline order. */
  const STAGE_COLUMNS = [
    { id: 'pending', label: 'Pending', hint: 'Accepted, not started yet' },
    { id: 'transcribe', label: 'Transcribe', stage: 'transcript',
      hint: 'Transcription running or awaiting review' },
    { id: 'convert', label: 'Convert', stage: 'conversion',
      hint: 'Conversion running or awaiting review' },
    { id: 'upload', label: 'Upload', stage: 'upload',
      hint: 'Uploads, including scheduled publishes' },
    { id: 'complete', label: 'Complete', hint: 'Finished jobs' },
    { id: 'failed', label: 'Failed', hint: 'Failed, cancelled, or partial' },
  ];

  const FAILED_STATUSES = ['failed', 'cancelled', 'partial_failure'];

  /** How many cards a mini column previews before the full view takes over. */
  const COLUMN_PREVIEW = 12;

  /** The pipeline stage a job currently occupies: its furthest incomplete checkpoint. */
  const STAGE_OF_CHECKPOINT = {
    transcript: 'transcribe',
    conversion: 'convert',
    upload: 'upload',
  };

  function jobColumnId(job) {
    if (job.status === 'completed') return 'complete';
    if (FAILED_STATUSES.includes(job.status)) return 'failed';
    if (job.status === 'scheduled') return 'upload';
    if (PRERUN_STATUSES.includes(job.status)) return 'pending';
    const checkpoints = job.checkpoints || {};
    for (const stage of ['transcript', 'conversion', 'upload']) {
      const status = checkpoints[stage]?.status;
      if (status && !['completed', 'skipped'].includes(status)) {
        return STAGE_OF_CHECKPOINT[stage];
      }
    }
    return STAGE_OF_CHECKPOINT[job.current_checkpoint] || 'transcribe';
  }

  let focused = $state('');

  function setFocused(id) {
    focused = id;
  }

  function labelOf(id) {
    return (STAGE_COLUMNS.find((column) => column.id === id) || {}).label || '';
  }

  function hintOf(id) {
    return (STAGE_COLUMNS.find((column) => column.id === id) || {}).hint || '';
  }

  function stageJobs(id) {
    return app.jobs.filter((job) => jobColumnId(job) === id);
  }

  function columnJobs(column) {
    const jobs = stageJobs(column.id);
    return column.id === 'complete' || column.id === 'failed'
      ? jobs.slice(0, COLUMN_PREVIEW)
      : jobs;
  }

  function needsFullView(column) {
    return stageJobs(column.id).length > COLUMN_PREVIEW;
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
    return ['failed', 'cancelled', 'partial_failure', ...PRERUN_STATUSES].includes(job.status);
  }

  function canCancel(job) {
    return !['completed', 'cancelled', 'failed'].includes(job.status);
  }

  function resumeLabel(job) {
    return PRERUN_STATUSES.includes(job.status) ? 'Run' : 'Resume';
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
      // U12: the dialog speaks for one card's Cancel action only.
      message:
        'Running and queued work for this job is aborted, including its scheduled attempts.',
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

  /** Esc returns to the Board from an expanded column when no modal is open. */
  function onWindowKeydown(event) {
    if (event.key !== 'Escape') return;
    if (!focused || app.selectedJobId || app.wizard.active || app.confirm) return;
    focused = '';
  }
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div class="content board-view">
  <div class="jobs-head">
    <div class="row">
      {#if focused}
        <button
          class="btn btn-ghost btn-sm"
          onclick={() => setFocused('')}
          title="Back to all stages (Esc)"
          aria-label="Back to all stages"
        >
          <Icon name="arrowLeft" size={14} /> All stages
        </button>
        <span class="focus-label">{labelOf(focused)}</span>
      {:else}
        <h1 class="board-hint">Pipeline</h1>
      {/if}
    </div>
    <div class="row">
      <!-- Issue #261 item 1: the SSE job stream keeps everything live, so the
           manual Refresh aria is removed; only New remains. -->
      <button class="btn btn-primary" onclick={startWizard}>
        <Icon name="plus" /> New
      </button>
    </div>
  </div>

  {#if focused}
    <div class="column-full" role="region" aria-label={`${labelOf(focused)} stage`}>
      <p class="faint focus-hint">{hintOf(focused)} · {stageJobs(focused).length} job{stageJobs(focused).length === 1 ? '' : 's'}</p>
      {#if stageJobs(focused).length}
        <div class="card-grid">
          {#each stageJobs(focused) as job (job.job_id)}
            {@const sourceName = job.configuration?.general?.source}
            {@const attempt = scheduledAttempt(job)}
            <article class="jcard">
              <button
                class="jcard-main"
                aria-label={`Open ${jobTitle(job)}`}
                onclick={() => openJob(job.job_id)}
              >
                <span class="jcard-art" aria-hidden="true">
                  <Thumbnail name={sourceName} size={110} alt="" />
                </span>
                <span class="jcard-title truncate">{jobTitle(job)}</span>
                <span class="jcard-badges">
                  <Badge tone={statusTone(job.status)}>{humanize(job.status)}</Badge>
                  {#if attempt}
                    <span class="badge">{humanize(attempt.platform)} · scheduled</span>
                  {/if}
                </span>
                <span class="faint mono jcard-source truncate">{sourceName}</span>
                <span class="faint jcard-time">
                  {job.status === 'completed' ? `completed ${completedTime(job)}` : `${soonestScheduledPublish(job) || ''}`}
                </span>
              </button>
              <div class="jcard-actions">
                {#if job.status === 'completed'}
                  <button
                    class="btn btn-ghost btn-sm"
                    disabled={!job.current_artifact_id}
                    title="Reveal the exported file in its folder"
                    aria-label={`Open the folder of ${jobTitle(job)}`}
                    onclick={() => openJobFolder(job)}
                  >
                    <Icon name="external" size={14} /> Open folder
                  </button>
                {/if}
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
        </div>
      {:else}
        <EmptyState
          icon="queue"
          title={`Nothing in ${labelOf(focused)}`}
          message="Jobs land here as the pipeline moves them."
        />
      {/if}
    </div>
  {:else}
    <div class="board">
      {#each STAGE_COLUMNS as column (column.id)}
        {@const jobs = stageJobs(column.id)}
        {@const preview = columnJobs(column)}
        <section class="column" aria-label={column.label}>
          <button
            type="button"
            class="column-head"
            aria-expanded="false"
            title={`Expand ${column.label}`}
            onclick={() => setFocused(column.id)}
          >
            <span class="column-title">{column.label}</span>
            <span class="wip">{jobs.length}</span>
            <Icon name="chevronDown" size={14} />
          </button>
          <div class="column-body">
            {#each preview as job (job.job_id)}
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
                    <span class="card-title truncate">
                      {jobTitle(job)}
                    </span>
                    <span class="card-meta">
                      <Badge tone={statusTone(job.status)}>{humanize(job.status)}</Badge>
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
            {#if needsFullView(column)}
              <button class="btn btn-ghost btn-sm show-all" onclick={() => setFocused(column.id)}>
                Show all {jobs.length}
              </button>
            {:else if !jobs.length}
              <p class="faint column-empty">No jobs</p>
            {/if}
          </div>
        </section>
      {/each}
    </div>
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

  .board-hint {
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    margin: 0;
  }

  .focus-label {
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
  }

  .focus-hint {
    margin: 0 0 var(--space-2);
    font-size: var(--text-xs);
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
    min-width: 240px;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  @media (min-width: 1400px) {
    .column {
      min-width: 200px;
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

  .show-all {
    justify-self: center;
  }

  /* C4: the fixed card anatomy — thumbnail left, title strong, status badge,
     single-line muted source, then the compact icon action row; everything on
     the 8px rhythm. */
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

  /* --- Expanded column: the full-width card grid (issue #261 items 2/6).
         Vertical Medal-style cards: art on top, title, status badges, meta. --- */
  .column-full {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }

  .card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: var(--space-3);
    align-content: start;
  }

  .jcard {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    display: grid;
    gap: var(--space-2);
    align-content: start;
  }

  .jcard-main {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-2);
    background: none;
    border: none;
    cursor: pointer;
    color: inherit;
    text-align: left;
    min-width: 0;
  }

  .jcard-art {
    aspect-ratio: 16 / 9;
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    width: 100%;
  }

  .jcard-art :global(.thumb) {
    width: 100%;
    height: 100%;
    border-radius: 0;
  }

  .jcard-art :global(.thumb img) {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .jcard-title {
    font-weight: var(--weight-semibold);
    max-width: 100%;
  }

  .jcard-badges {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .jcard-source,
  .jcard-time {
    font-size: var(--text-xs);
    max-width: 100%;
  }

  .jcard-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: 0 var(--space-2) var(--space-2);
  }
</style>
