<script>
  import Icon from '../components/Icon.svelte';
  import Badge from '../components/Badge.svelte';
  import Card from '../components/Card.svelte';
  import Field from '../components/Field.svelte';
  import Tabs from '../components/Tabs.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import PlatformMark from '../components/PlatformMark.svelte';
  import SegmentEditor from '../components/SegmentEditor.svelte';
  import ConfigForm from '../components/ConfigForm.svelte';
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
    saveUploadDraft,
    submitUpload,
    generateSuggestions,
    acceptAllSuggestions,
    clearSuggestions,
    applyAttemptFilters,
    pullMetrics,
    requestConfirm,
    pruneArtifacts,
    renderReview,
    reviewDirty,
  } from '../lib/store.svelte.js';
  import {
    statusTone,
    statusLabel,
    humanize,
    formatDateTime,
    groupMetricPosts,
    metricRows,
    formatDelta,
    platformLabel,
    platformListLabel,
  } from '../lib/format.js';
  import { api } from '../lib/api.js';

  const TABS = [
    { id: 'overview', label: 'Overview' },
    // Issue #261 item 19: the publish gate is a review gate — it renders
    // under Review, not as its own tab.
    { id: 'review', label: 'Review' },
    { id: 'metrics', label: 'Metrics' },
  ];

  const CHECKPOINT_STAGES = ['transcript', 'conversion', 'upload'];

  const job = $derived(selectedJob());

  let loadedJobId = $state('');
  let renderGroup = $state('');

  /** F15: the platforms a group is shared by, in the app's platform order. */
  function groupPlatforms(id) {
    const order = (platform) => app.platforms.indexOf(platform);
    return Object.entries(app.platformSummaries || {})
      .filter(([, summary]) => summary.group_id === id)
      .map(([platform]) => platform)
      .sort((a, b) => order(a) - order(b));
  }

  /**
   * F15: one entry per group, each carrying its member platforms so the
   * dropdown labels entries by the stored platform list instead of the raw
   * group id.
   */
  const renderGroupOptions = $derived(
    [...new Set(
      Object.values(app.platformSummaries || {})
        .map((summary) => summary.group_id)
        .filter(Boolean),
    )].map((id) => ({ id, platforms: groupPlatforms(id) })),
  );

  $effect(() => {
    if (job && job.job_id !== loadedJobId) {
      loadedJobId = job.job_id;
      renderGroup = '';
    }
  });

  /**
   * E17: the Review tab shows the current gate only. The earliest gate that
   * still awaits review drives which panel renders: the transcript editor,
   * or the conversion/composition review (media player + structured
   * composition), or nothing (the upload draft review lives on Publish).
   */
  const reviewGate = $derived.by(() => {
    if (!job) return null;
    if (job.checkpoints?.transcript?.status === 'awaiting_review') return 'transcript';
    if (job.checkpoints?.conversion?.status === 'awaiting_review') return 'conversion';
    return null;
  });

  const uploadAwaitingReview = $derived(
    Boolean(job?.checkpoints?.upload?.status === 'awaiting_review'),
  );

  /**
   * E17: the full converted artifact for the player. The job's current
   * artifact is the reviewed render; any registered artifact is a fallback.
   */
  const reviewArtifact = $derived.by(() => {
    if (!job) return null;
    const artifacts = app.artifacts || [];
    return artifacts.find((item) => item.id === job.current_artifact_id) ||
      artifacts[0] || null;
  });

  /**
   * E22: composition data as readable sections — every conversion value
   * renders as labeled text ("anything without a widget renders as labeled
   * text"); no raw JSON blob exists on any review surface.
   */
  /**
   * E22: composition data as readable sections — every conversion value
   * renders as labeled text ("anything without a widget renders as labeled
   * text"); no raw JSON blob exists on any review surface. Issue #261 item
   * 18: unset leaves render too (as —), so the layout config is complete
   * instead of only its set keys.
   */
  function labeledRows(value, label = '', rows = [], depth = 0) {
    if (value === undefined) return rows;
    if (value === null || value === '') {
      rows.push({ label, value: '—' });
      return rows;
    }
    if (Array.isArray(value)) {
      if (value.every((item) => item === null || typeof item !== 'object')) {
        rows.push({ label, value: value.filter((item) => item !== null).join(', ') || '—' });
      } else {
        value.forEach((item, index) => {
          labeledRows(item, label ? `${label} ${index + 1}` : `Item ${index + 1}`, rows, depth);
        });
      }
      return rows;
    }
    if (typeof value === 'object') {
      for (const [key, nested] of Object.entries(value)) {
        labeledRows(nested, label ? `${label} · ${humanize(key)}` : humanize(key), rows, depth + 1);
      }
      return rows;
    }
    rows.push({ label, value: String(value) });
    return rows;
  }

  const compositionSections = $derived.by(() => {
    const conversion = job?.configuration?.conversion || {};
    const parts = Object.entries(conversion)
      .filter(([key]) => !['skip'].includes(key))
      .map(([key, value]) => ({
        title: humanize(key),
        rows: labeledRows(value, humanize(key)),
      }))
      .filter((section) => section.rows.length);
    return parts;
  });

  $effect(() => {
    // E17: caption lines read from the active transcript revision in both
    // review gates (the transcript editor and the composition review).
    if (app.detailTab === 'review' && job?.active_transcript && !app.transcript) {
      loadTranscript().catch((error) => (app.errors = [error.message]));
    }
  });

  /**
   * Issue #261 item 18: the conversion review is EDITABLE. The editor renders
   * the form spec's conversion section (the whole layout config, not only the
   * caption keys) bound to a per-job draft; the transcription fields are
   * filtered out because a change there invalidates the accepted transcript
   * rather than the render under review. Re-render applies the draft through
   * the hash-guarded configuration PATCH, so the button renders something new.
   */
  function stripTranscriptionFields(section) {
    const fields = (section.fields || []).filter(
      (field) => !field.path.startsWith('conversion.subtitles.transcription'),
    );
    return {
      ...section,
      fields,
      sections: (section.sections || []).map(stripTranscriptionFields),
    };
  }

  const reviewFormSections = $derived.by(() => {
    if (!app.formSpec) return null;
    const conversion = app.formSpec.sections.find((item) => item.id === 'conversion');
    return conversion ? [stripTranscriptionFields(conversion)] : null;
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
      // U12: the dialog speaks for this one job's Cancel action only.
      message:
        'Running and queued work for this job is aborted, including its scheduled attempts.',
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
      <EmptyState title="Job not found" message="It may have been deleted. Return to the Jobs tab.">
        <button class="btn btn-primary" onclick={closeJob}>Back to jobs</button>
      </EmptyState>
    </Card>
  </div>
{:else}
  <div class="content">
    <div class="detail-head">
      <div class="row">
        <button class="btn btn-ghost btn-icon" aria-label="Back to jobs" onclick={closeJob}>
          <Icon name="arrowLeft" />
        </button>
        <div>
          <div class="title truncate">{title}</div>
          <div class="row faint">
            <Badge tone={statusTone(job.status)}>{statusLabel(job.status)}</Badge>
            <span class="mono">{job.configuration?.general?.source}</span>
            <span>· updated {formatDateTime(job.updated_at)}</span>
          </div>
        </div>
      </div>
      <div class="action-bar">
        {#if canResume}
          <div class="action-group">
            <button class="btn btn-secondary" onclick={() => jobAction('resume')}>
              <Icon name="play" /> Resume
            </button>
          </div>
        {/if}
        {#if canCancel}
          <div class="action-group">
            <button class="btn btn-secondary" onclick={confirmCancel}>Cancel</button>
          </div>
        {/if}
        <!-- Risky actions keep their own muted/danger group (E11/E16). -->
        <div class="action-group">
          <button class="btn btn-danger" onclick={confirmDelete}>
            <Icon name="trash" /> Delete
          </button>
        </div>
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
                <div class="name">{stage.charAt(0).toUpperCase() + stage.slice(1)}</div>
                <div class="row">
                  <!-- U7: the badge is the row's single status render. -->
                  <Badge tone={statusTone(checkpoint.status)}>{statusLabel(checkpoint.status) || 'Pending'}</Badge>
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
                    <Badge tone={statusTone(attempt.status)}>{statusLabel(attempt.status)}</Badge>
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
      <!-- E17: review affordances for the current gate only. -->
      {#if reviewGate === 'transcript'}        <Card title="Transcript" description="Edit timing and text, then save a new revision.">
          <!-- E11: one standard action bar, primary/secondary separated. -->
          <div class="action-bar action-lead-row">
            <span class="action-lead faint">
              {app.transcript ? `${app.transcript.segments.length} segments` : ''}
            </span>
            <div class="action-group">
              <button
                class="btn btn-secondary"
                disabled={!app.transcript}
                onclick={saveTranscript}
              >Save edits</button>
            </div>
            <div class="action-group">
              <button
                class="btn btn-primary"
                disabled={job.checkpoints?.transcript?.status !== 'awaiting_review'}
                onclick={() => acceptCheckpoint('transcript')}
              >Accept transcript</button>
            </div>
          </div>
          <!-- Issue #261 item 16: the two buttons were indistinguishable; the
               hint states the difference in one line. -->
          <small class="field-hint">
            Save keeps your edits as a revision without approving; Accept approves the current revision and resumes the pipeline.
          </small>
          {#if app.transcript}
            <div class="stack">
              {#each app.transcript.segments as segment, index (index)}
                <SegmentEditor {segment} {index} />
              {/each}
            </div>
          {:else}
            <EmptyState
              icon="pencil"
              title="No transcript revision loaded"
              message="This job has no active transcript revision to edit."
            />
          {/if}
        </Card>

      {:else if reviewGate === 'conversion'}
        <!-- E17/E22: the composition review plays the full converted artifact
             and renders composition data as labeled structured sections — no
             raw JSON anywhere in a review surface. -->
        <div class="review-grid">
          <Card title="Rendered clip" description="The full converted artifact for this job.">
            {#if reviewArtifact}
              <!-- The rendered artifact carries burned-in captions; a served
                   captions track is a follow-up (issue #259 F22 family). -->
              <!-- svelte-ignore a11y_media_has_caption -->
              <video
                class="review-player"
                controls
                preload="metadata"
                aria-label={`Play the converted artifact ${reviewArtifact.display_name || reviewArtifact.kind}`}
                src={api.previewUrl(job.job_id, reviewArtifact.id)}
              ></video>
            {:else}
              <EmptyState
                icon="video"
                title="No rendered artifact yet"
                message="Run a render to create the artifact this review plays."
              />
            {/if}
          </Card>

          <Card
            title="Composition"
            description="The conversion layout this job renders."
          >
            <div class="action-bar action-lead-row">
              <span class="action-lead faint">
                {app.transcript
                  ? `${app.transcript.segments.length} caption line${app.transcript.segments.length === 1 ? '' : 's'}`
                  : ''}
              </span>
              {#if renderGroupOptions.length}
                <!-- F15: human labels — "All variants" plus one entry per
                     group, labeled by the platform list sharing that render
                     variant; the raw group id is the value only. -->
                <span class="variant-picker">
                  <select aria-label="Render variant" bind:value={renderGroup}>
                    <option value="">All variants</option>
                    {#each renderGroupOptions as option (option.id)}
                      <option value={option.id}>{platformListLabel(option.platforms)}</option>
                    {/each}
                  </select>
                  <small class="faint">Each group is one render variant shared by the platforms it lists.</small>
                </span>
              {/if}
              <div class="action-group">
                <!-- Issue #261 item 18: the button is no longer a no-op —
                     edited config is PATCHed into the job (hash-guarded) and
                     the re-render produces the new output; with no edits it
                     is the plain re-render. -->
                <button
                  class="btn btn-secondary"
                  disabled={app.busy}
                  onclick={() => renderReview(renderGroup)}
                >
                  <Icon name="refresh" />
                  {reviewDirty() ? 'Apply changes & re-render' : 'Re-render'}
                </button>
              </div>
              <div class="action-group">
                <button
                  class="btn btn-primary"
                  disabled={job.checkpoints?.conversion?.status !== 'awaiting_review' || reviewDirty()}
                  title={reviewDirty()
                    ? 'Apply changes & re-render first — the acceptance reviews the edited conversion'
                    : ''}
                  onclick={() => acceptCheckpoint('conversion')}
                >Accept composition</button>
              </div>
            </div>

            {#if app.transcript}
              <div class="composition-block">
                <div class="composition-title">Caption lines</div>
                {#each app.transcript.segments as segment, index (index)}
                  <div class="composition-row">
                    <span class="faint mono">{segment.start}s → {segment.end}s</span>
                    <span class="truncate">{segment.text}</span>
                  </div>
                {/each}
              </div>
            {/if}

            {#if reviewFormSections}
              <!-- Item 18: the editable conversion config — General-free,
                   conversion-only, transcription keys filtered; the header
                   names what the draft edits. -->
              <div class="composition-block">
                <div class="composition-title">Conversion config</div>
                <div class="config-stack">
                  <ConfigForm sections={reviewFormSections} mode="review" />
                </div>
              </div>
            {/if}

            {#each compositionSections as section (section.title)}
              <div class="composition-block">
                <div class="composition-title">{section.title}</div>
                {#each section.rows as row (row.label + row.value)}
                  <div class="composition-row">
                    <span class="faint">{row.label}</span>
                    <span class="truncate">{row.value}</span>
                  </div>
                {/each}
              </div>
            {/each}
          </Card>
        </div>

      {:else if uploadAwaitingReview}
        <!-- Issue #261 item 19: the publish gate is a review gate — it renders
             here, and its separate tab is gone. -->
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

            <div class="action-bar">
              <div class="action-group">
                <button class="btn btn-secondary" onclick={saveUploadDraft}>
                  <Icon name="check" /> Save draft
                </button>
              </div>
              <div class="action-group">
                <button class="btn btn-primary" disabled={app.busy} onclick={submitUpload}>
                  <Icon name="upload" /> Submit upload
                </button>
              </div>
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
                      {#if summary.group_id}
                        <!-- F15: the group renders as its platform list, never a hash. -->
                        {@const members = groupPlatforms(summary.group_id)}
                        · {members.length > 1
                          ? `one render variant shared by ${platformListLabel(members)}`
                          : 'its own render variant'}
                      {/if}
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

      {:else}
        <EmptyState
          icon="check"
          title="No review pending"
          message="When the pipeline lands on a review gate, its review controls appear here."
        />
      {/if}

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

  /* Issue #261 item 17: the rendered clip previews at the size a desktop
     short-form platform player uses — a narrow 9:16 box not the whole
     column. */
  .review-player {
    display: block;
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
    background: var(--color-bg);
    border-radius: var(--radius-md);
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

  /* F15: the rerender variant dropdown with its one-line hint below. */
  .variant-picker {
    display: grid;
    gap: var(--space-1);
    justify-items: start;
  }
</style>
