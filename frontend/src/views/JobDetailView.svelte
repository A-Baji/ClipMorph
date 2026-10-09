<script>
  import Icon from '../components/Icon.svelte';
  import Badge from '../components/Badge.svelte';
  import Card from '../components/Card.svelte';
  import Field from '../components/Field.svelte';
  import Tabs from '../components/Tabs.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import PlatformMark from '../components/PlatformMark.svelte';
  import SegmentEditor from '../components/SegmentEditor.svelte';
  import ArtifactRow from '../components/ArtifactRow.svelte';
  import SuggestionCard from '../components/SuggestionCard.svelte';
  import AttemptRow from '../components/AttemptRow.svelte';
  import {
    app,
    selectedJob,
    closeJob,
    jobAction,
    acceptCheckpoint,
    retryCheckpoint,
    loadTranscript,
    saveTranscript,
    saveComposition,
    saveUploadDraft,
    submitUpload,
    generateSuggestions,
    acceptAllSuggestions,
    clearSuggestions,
    applyAttemptFilters,
    pullMetrics,
    requestConfirm,
    pruneArtifacts,
  } from '../lib/store.svelte.js';
  import {
    statusTone,
    humanize,
    formatDateTime,
    groupMetricPosts,
    metricRows,
    formatDelta,
    platformLabel,
  } from '../lib/format.js';

  const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'review', label: 'Review' },
    { id: 'publish', label: 'Publish' },
    { id: 'metrics', label: 'Metrics' },
  ];

  const CHECKPOINT_STAGES = ['transcript', 'conversion', 'upload'];

  const job = $derived(selectedJob());

  let compositionJson = $state('{}');
  let loadedJobId = $state('');

  $effect(() => {
    if (job && job.job_id !== loadedJobId) {
      loadedJobId = job.job_id;
      compositionJson = JSON.stringify(job.configuration?.conversion?.layout || {}, null, 2);
    }
  });

  $effect(() => {
    if (app.detailTab === 'review' && job?.active_transcript && !app.transcript) {
      loadTranscript().catch((error) => (app.errors = [error.message]));
    }
  });

  const title = $derived(
    job?.configuration?.upload?.content?.title || job?.configuration?.general?.source || '',
  );
  const suggestionBlock = $derived(job?.configuration?.upload?.suggestions || {});
  const suggestionProvider = $derived(suggestionBlock.provider || 'template');
  const suggestions = $derived(
    Object.entries(suggestionBlock)
      .filter(([key]) => key !== 'provider' && key !== 'model')
      .map(([platform, row]) => ({ platform, ...row })),
  );
  const latestAttempts = $derived.by(() => {
    const latest = {};
    for (const attempt of job?.upload_attempts || []) latest[attempt.platform] = attempt;
    return latest;
  });
  const canResume = $derived(['failed', 'cancelled', 'partial_failure'].includes(job?.status));
  const canCancel = $derived(!['completed', 'cancelled', 'failed'].includes(job?.status));

  function confirmDelete() {
    requestConfirm({
      title: 'Delete this job?',
      message: 'The job and its local output are moved to trash. Remote posts are not touched.',
      confirmLabel: 'Delete job',
      danger: true,
      onConfirm: () => jobAction('delete'),
    });
  }

  function confirmCancel() {
    requestConfirm({
      title: 'Cancel this job?',
      message: 'Queued and running work is aborted. Scheduled attempts are cancelled.',
      confirmLabel: 'Cancel job',
      danger: true,
      onConfirm: () => jobAction('cancel'),
    });
  }

  function confirmPrune() {
    requestConfirm({
      title: 'Prune stale artifacts?',
      message: 'Recycles superseded artifact revisions for this job to free disk space.',
      confirmLabel: 'Prune',
      onConfirm: () => pruneArtifacts(),
    });
  }
</script>

{#snippet artifactActions()}
  <button class="btn btn-ghost btn-sm" disabled={!app.artifacts.length} onclick={confirmPrune}>Prune</button>
{/snippet}

{#if !job}
  <div class="content">
    <Card flush>
      <EmptyState title="Job not found" message="It may have been deleted. Return to the queue.">
        <button class="btn btn-primary" onclick={closeJob}>Back to queue</button>
      </EmptyState>
    </Card>
  </div>
{:else}
  <div class="content">
    <div class="detail-head">
      <div class="row">
        <button class="btn btn-ghost btn-icon" aria-label="Back to queue" onclick={closeJob}>
          <Icon name="arrowLeft" />
        </button>
        <div>
          <div class="title">{title}</div>
          <div class="row faint">
            <Badge tone={statusTone(job.status)}>{humanize(job.status)}</Badge>
            <span class="mono">{job.configuration?.general?.source}</span>
            <span>· updated {formatDateTime(job.updated_at)}</span>
          </div>
        </div>
      </div>
      <div class="row">
        {#if canResume}
          <button class="btn btn-secondary" onclick={() => jobAction('resume')}>
            <Icon name="play" /> Resume
          </button>
        {/if}
        {#if canCancel}
          <button class="btn btn-secondary" onclick={confirmCancel}>Cancel</button>
        {/if}
        <button class="btn btn-danger" onclick={confirmDelete}>
          <Icon name="trash" /> Delete
        </button>
      </div>
    </div>

    <Tabs tabs={TABS} active={app.detailTab} onSelect={(id) => (app.detailTab = id)} />

    {#if app.detailTab === 'overview'}
      <div class="grid-2">
        <Card title="Pipeline">
          <div class="stack-tight">
            {#each CHECKPOINT_STAGES as stage (stage)}
              {@const checkpoint = job.checkpoints?.[stage] || {}}
              <div class="checkpoint-row">
                <Icon name={checkpoint.status === 'accepted' ? 'check' : 'dot'} />
                <div>
                  <div class="name">{stage.charAt(0).toUpperCase() + stage.slice(1)}</div>
                  <div class="desc">{humanize(checkpoint.status) || 'not started'}</div>
                </div>
                <div class="row">
                  <Badge tone={statusTone(checkpoint.status)}>{humanize(checkpoint.status) || 'pending'}</Badge>
                  {#if checkpoint.status === 'failed'}
                    <button class="btn btn-ghost btn-sm" onclick={() => retryCheckpoint(stage)}>Retry</button>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        </Card>

        <Card title="Platforms">
          <div class="stack-tight">
            {#each app.platforms as platform (platform)}
              {@const summary = app.platformSummaries[platform] || {}}
              {@const attempt = latestAttempts[platform]}
              <div class="health-row">
                <PlatformMark {platform} />
                <div class="health-name">
                  <b>{platformLabel(platform)}</b>
                  <small class="faint">
                    {summary.participates === false ? 'skipped' : summary.kind || 'participating'}
                  </small>
                </div>
                <div class="verdict">
                  {#if attempt}
                    <Badge tone={statusTone(attempt.status)}>{humanize(attempt.status)}</Badge>
                  {:else}
                    <Badge>{summary.participates === false ? 'skipped' : 'pending'}</Badge>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        </Card>
      </div>

      <Card
        title="Artifacts"
        description="Immutable render revisions for this job."
        actions={artifactActions}
      >
        {#if app.artifacts.length}
          <div class="list">
            {#each app.artifacts as artifact (artifact.id)}
              <ArtifactRow {artifact} />
            {/each}
          </div>
        {:else}
          <p class="faint">No artifacts yet. They appear once conversion completes.</p>
        {/if}
      </Card>

    {:else if app.detailTab === 'review'}
      <div class="review-grid">
        <Card title="Transcript" description="Edit timing and text, then save a new revision.">
          <div class="row-between">
            <span class="faint">{app.transcript ? `${app.transcript.segments.length} segments` : ''}</span>
            <div class="row">
              <button
                class="btn btn-secondary"
                disabled={!app.transcript}
                onclick={saveTranscript}
              >Save transcript revision</button>
              <button
                class="btn btn-primary"
                disabled={job.checkpoints?.transcript?.status !== 'awaiting_review'}
                onclick={() => acceptCheckpoint('transcript')}
              >Accept transcript</button>
            </div>
          </div>
          {#if app.transcript}
            <div class="stack">
              {#each app.transcript.segments as segment, index (index)}
                <SegmentEditor {segment} {index} />
              {/each}
            </div>
          {:else}
            <EmptyState
              icon="pencil"
              title="No transcript review pending"
              message="This job has no active transcript revision to edit."
            />
          {/if}
        </Card>

        <Card title="Composition" description="The conversion layout for this job. Saving marks the current render stale.">
          <div class="stack">
            <label class="field">
              <span>Job layout JSON</span>
              <textarea
                aria-label="Job composition layout"
                rows="12"
                spellcheck="false"
                bind:value={compositionJson}
              ></textarea>
            </label>
            <div class="row">
              <button class="btn btn-primary" onclick={() => saveComposition(compositionJson)}>
                Save job composition
              </button>
              <button class="btn btn-secondary" onclick={() => jobAction('render')}>
                <Icon name="refresh" /> Render
              </button>
              <button
                class="btn btn-secondary"
                disabled={job.checkpoints?.conversion?.status !== 'awaiting_review'}
                onclick={() => acceptCheckpoint('conversion')}
              >Accept composition</button>
            </div>
          </div>
        </Card>
      </div>

    {:else if app.detailTab === 'publish'}
      <div class="grid-2">
        <Card title="Upload draft" description="What each selected platform will receive.">
          <div class="stack">
            <Field label="Title">
              <input aria-label="Upload title" bind:value={app.publish.draft.title} />
            </Field>
            <Field label="Description">
              <textarea aria-label="Upload description" rows="3" bind:value={app.publish.draft.description}></textarea>
            </Field>
            <Field label="Tags">
              <input aria-label="Upload tags" bind:value={app.publish.draft.tags} placeholder="tag one, tag two" />
            </Field>
            <Field label="Schedule for" hint="Leave empty to upload now. A future time defers every selected platform.">
              <input aria-label="Upload schedule for" type="datetime-local" bind:value={app.publish.draft.publishAt} />
            </Field>

            <div class="field">
              <span>Platforms</span>
              <div class="checks">
                {#each app.platforms as platform (platform)}
                  <label class="check">
                    <input
                      type="checkbox"
                      checked={app.publish.selectedPlatforms.includes(platform)}
                      onchange={(event) =>
                        (app.publish.selectedPlatforms = event.currentTarget.checked
                          ? [...new Set([...app.publish.selectedPlatforms, platform])]
                          : app.publish.selectedPlatforms.filter((item) => item !== platform))}
                    />
                    {platformLabel(platform)}
                  </label>
                {/each}
              </div>
            </div>

            {#if app.publish.selectedPlatforms.includes('facebook')}
              <Field label="Facebook content kind">
                <select bind:value={app.publish.contentKind}>
                  <option value="reel">Reel</option>
                  <option value="video">Page video</option>
                </select>
              </Field>
            {/if}

            <div class="row">
              <button class="btn btn-secondary" onclick={saveUploadDraft}>
                <Icon name="check" /> Save draft
              </button>
              <button class="btn btn-primary" disabled={app.busy} onclick={submitUpload}>
                <Icon name="upload" /> Submit upload
              </button>
            </div>
          </div>
        </Card>

        <Card title="Per-platform summary" description="Read-only. Conversion overrides live in composition review.">
          <div class="stack-tight">
            {#each app.platforms as platform (platform)}
              {@const summary = app.platformSummaries[platform] || {}}
              {#if summary.participates}
                <div class="list-row">
                  <PlatformMark {platform} />
                  <div class="grow">
                    <b>{platformLabel(platform)} · {summary.kind || 'clip'}</b>
                    <small>
                      {summary.conversion?.skip ? 'uploads the source file' : 'uploads the rendered vertical'}
                      · group {summary.group_id || 'unassigned'}
                    </small>
                  </div>
                </div>
              {/if}
            {/each}
          </div>
        </Card>
      </div>

      <Card
        title="AI suggestions"
        description={`Provider: ${suggestionProvider}. Nothing publishes until you apply and submit.`}
      >
        <div class="row">
          <button class="btn btn-secondary" onclick={() => generateSuggestions(false)}>Generate suggestions</button>
          <button class="btn btn-secondary" disabled={!suggestions.length} onclick={() => generateSuggestions(true)}>Regenerate</button>
          <button
            class="btn btn-secondary"
            disabled={!suggestions.length}
            onclick={() => acceptAllSuggestions(suggestions.map((row) => row.platform))}
          >Apply all</button>
          <button class="btn btn-ghost" disabled={!suggestions.length} onclick={clearSuggestions}>Clear</button>
        </div>
        {#if suggestions.length}
          <div class="stack suggestion-list">
            {#each suggestions as row (row.platform)}
              <SuggestionCard {row} />
            {/each}
          </div>
        {:else}
          <p class="faint">No suggestions yet. Generate drafts from the transcript.</p>
        {/if}
      </Card>

      <Card title="Upload history" description="Append-only record of every attempt.">
        <div class="grid-2 filters">
          <Field label="Status">
            <select bind:value={app.publish.attemptFilters.status} onchange={applyAttemptFilters}>
              <option value="">All</option>
              {#each ['pending', 'scheduled', 'running', 'published', 'failed', 'cancelled'] as status (status)}
                <option value={status}>{status}</option>
              {/each}
            </select>
          </Field>
          <Field label="Platform">
            <select bind:value={app.publish.attemptFilters.platform} onchange={applyAttemptFilters}>
              <option value="">All</option>
              {#each app.platforms as platform (platform)}
                <option value={platform}>{platform}</option>
              {/each}
            </select>
          </Field>
          <Field label="Since">
            <input
              type="datetime-local"
              bind:value={app.publish.attemptFilters.since}
              onchange={applyAttemptFilters}
            />
          </Field>
        </div>
        {#if app.attempts.length}
          <div class="list">
            {#each app.attempts as attempt (attempt.attempt_id)}
              <AttemptRow {attempt} jobId={job.job_id} />
            {/each}
          </div>
        {:else}
          <p class="faint">No upload attempts yet.</p>
        {/if}
      </Card>

    {:else if app.detailTab === 'metrics'}
      <Card
        title="Engagement"
        description="First → latest snapshot per published post."
      >
        <div class="row between">
          <span class="faint">{app.metrics.length} snapshot(s)</span>
          <button class="btn btn-secondary" onclick={pullMetrics}>
            <Icon name="refresh" /> Pull fresh data
          </button>
        </div>
        {#if app.metrics.length}
          <div class="stack metric-cards">
            {#each groupMetricPosts(app.metrics) as post (post.platform + post.platform_post_id)}
              <div class="segment">
                <div class="suggestion-head">
                  <span class="row">
                    <PlatformMark platform={post.platform} size={18} />
                    <b>{platformLabel(post.platform)}</b>
                  </span>
                  {#if post.platform_url}
                    <a class="btn btn-ghost btn-sm" href={post.platform_url} target="_blank" rel="noreferrer">View post</a>
                  {/if}
                </div>
                {#if post.latest.unavailable}
                  <small class="faint">unavailable: {post.latest.unavailable_reason}</small>
                {:else}
                  {#each metricRows(post) as row (row.name)}
                    <div class="row-between metric-row">
                      <span class="faint">{row.name}</span>
                      <span>
                        <b class="mono">{row.value}</b>
                        <span class="mono {row.delta > 0 ? 'delta-up' : row.delta < 0 ? 'delta-down' : 'faint'}">
                          {formatDelta(row.delta)}
                        </span>
                      </span>
                    </div>
                  {/each}
                {/if}
              </div>
            {/each}
          </div>
        {:else}
          <EmptyState
            icon="chart"
            title="No metrics yet"
            message="Publish a clip, then pull fresh data to see engagement."
          />
        {/if}
      </Card>
    {/if}
  </div>
{/if}

<style>
  .health-name {
    display: grid;
    gap: var(--space-1);
  }

  .suggestion-list,
  .metric-cards {
    margin-top: var(--space-4);
  }

  .grid-2.filters {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    margin-bottom: var(--space-4);
  }

  @media (max-width: 860px) {
    .grid-2.filters {
      grid-template-columns: 1fr;
    }
  }

  .metric-row {
    padding: var(--space-2) 0;
    border-top: 1px solid var(--color-border);
  }

  .row.between {
    justify-content: space-between;
  }

  .row.between > .faint {
    margin-right: auto;
  }
</style>
