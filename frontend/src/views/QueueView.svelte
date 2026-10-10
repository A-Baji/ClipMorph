<script>
  import Icon from '../components/Icon.svelte';
  import Badge from '../components/Badge.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import Progress from '../components/Progress.svelte';
  import {
    app,
    cardAction,
    cancelScheduledAttempt,
    loadWorkspace,
    openJob,
    requestConfirm,
    startWizard,
  } from '../lib/store.svelte.js';
  import { statusTone, humanize, soonestScheduledPublish } from '../lib/format.js';

  /**
   * Queue = kanban board (issue #257). Columns are pipeline statuses; WIP
   * counters per column; collapsing a column filters it out. No drag-and-drop:
   * column membership is pipeline-driven.
   */
  const COLUMNS = [
    { id: 'queued', label: 'Queued', statuses: ['queued', 'created', 'pending'] },
    { id: 'running', label: 'Running', statuses: ['running'] },
    { id: 'awaiting_review', label: 'Awaiting review', statuses: ['awaiting_review'] },
    { id: 'scheduled', label: 'Scheduled', statuses: ['scheduled'] },
    { id: 'completed', label: 'Completed', statuses: ['completed'] },
    { id: 'failed', label: 'Failed', statuses: ['failed', 'cancelled', 'partial_failure'] },
  ];

  let collapsed = $state({});

  function columnJobs(column) {
    return app.jobs.filter((job) => column.statuses.includes(job.status));
  }

  function jobTitle(job) {
    return (
      job.configuration?.upload?.content?.title ||
      job.configuration?.general?.source ||
      job.job_id
    );
  }

  function scheduledAttempt(job) {
    return (job.upload_attempts || []).find((attempt) => attempt.status === 'scheduled');
  }

  function canResume(job) {
    return ['failed', 'cancelled', 'partial_failure', 'queued', 'created'].includes(job.status);
  }

  function canCancel(job) {
    return !['completed', 'cancelled', 'failed'].includes(job.status);
  }

  function resumeLabel(job) {
    return ['queued', 'created'].includes(job.status) ? 'Run' : 'Resume';
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
  <div class="section-head">
    <div>
      <h2>Queue</h2>
      <p>Every job by pipeline status. Click a card for its full detail.</p>
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

  {#if !app.jobs.length}
    <EmptyState
      icon="queue"
      title="Your queue is empty"
      message="Create your first job to see it move across the board."
    />
  {:else}
    <div class="board">
      {#each COLUMNS as column (column.id)}
        {@const jobs = columnJobs(column)}
        <section class="column" class:collapsed={collapsed[column.id]} aria-label={column.label}>
          <button
            type="button"
            class="column-head"
            aria-expanded={!collapsed[column.id]}
            onclick={() => toggleColumn(column.id)}
          >
            <span class="column-title">{column.label}</span>
            <span class="wip">{jobs.length}</span>
            <Icon name={collapsed[column.id] ? 'chevronRight' : 'chevronDown'} size={14} />
          </button>
          {#if !collapsed[column.id]}
            <div class="column-body">
              {#each jobs as job (job.job_id)}
                {@const attempt = scheduledAttempt(job)}
                <article class="card">
                  <button class="card-main" onclick={() => openJob(job.job_id)}>
                    <span class="card-head">
                      <span class="card-thumb"><Icon name="video" size={16} /></span>
                      <span class="card-title">{jobTitle(job)}</span>
                    </span>
                    <span class="card-meta">
                      <Badge tone={statusTone(job.status)}>{humanize(job.status)}</Badge>
                      {#if job.current_checkpoint}
                        <span class="badge">{humanize(job.current_checkpoint)}</span>
                      {/if}
                    </span>
                    <span class="faint mono card-source">{job.configuration?.general?.source}</span>
                    {#if app.uploadProgress[job.job_id] && Object.keys(app.uploadProgress[job.job_id]).length}
                      {#each Object.entries(app.uploadProgress[job.job_id]) as [platform, percent] (platform)}
                        <Progress value={percent} small label={`${platform}: ${percent}%`} />
                      {/each}
                    {:else if attempt}
                      <span class="faint mono">{soonestScheduledPublish(job)}</span>
                    {/if}
                  </button>
                  <div class="card-actions">
                    {#if canResume(job)}
                      <button class="btn btn-ghost btn-sm" onclick={() => cardAction(job, 'resume')}>
                        <Icon name="play" size={14} /> {resumeLabel(job)}
                      </button>
                    {/if}
                    {#if attempt}
                      <button class="btn btn-ghost btn-sm" onclick={() => confirmCancelAttempt(job)}>
                        Cancel attempt
                      </button>
                    {/if}
                    {#if canCancel(job)}
                      <button class="btn btn-ghost btn-sm" onclick={() => confirmCancel(job)}>Cancel</button>
                    {/if}
                    <button
                      class="btn btn-ghost btn-sm"
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
  {/if}
</div>

<style>
  .board {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: var(--space-3);
    align-items: start;
    overflow-x: auto;
  }

  .column {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    min-width: 180px;
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
  }

  .card {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    display: grid;
  }

  .card-main {
    display: grid;
    gap: var(--space-1);
    text-align: left;
    padding: var(--space-3);
    background: none;
    border: none;
    cursor: pointer;
    color: inherit;
  }

  .card-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .card-thumb {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
    color: var(--color-text-muted);
  }

  .card-title {
    font-weight: 600;
  }

  .card-meta {
    display: flex;
    gap: var(--space-1);
    flex-wrap: wrap;
  }

  .card-source {
    font-size: var(--text-xs);
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .card-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    padding: 0 var(--space-2) var(--space-2);
  }

  .column-empty {
    padding: var(--space-2);
    font-size: var(--text-xs);
  }

  @media (max-width: 1100px) {
    .board {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }

  @media (max-width: 700px) {
    .board {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
