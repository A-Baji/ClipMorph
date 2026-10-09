<script>
  import Card from '../components/Card.svelte';
  import Field from '../components/Field.svelte';
  import JobCard from '../components/JobCard.svelte';
  import Icon from '../components/Icon.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import PlatformMark from '../components/PlatformMark.svelte';
  import {
    app,
    submitCreate,
    loadWorkspace,
    openJob,
  } from '../lib/store.svelte.js';
  import { formatBytes } from '../lib/format.js';

  /** Default surface: pick clips and upload, with the queue a glance away. */
  const STATUS_FILTERS = [
    { id: '', label: 'All' },
    { id: 'awaiting_review', label: 'Review' },
    { id: 'running', label: 'Running' },
    { id: 'scheduled', label: 'Scheduled' },
    { id: 'completed', label: 'Done' },
    { id: 'failed', label: 'Failed' },
  ];

  let statusFilter = $state('');

  const filteredJobs = $derived(
    statusFilter ? app.jobs.filter((job) => job.status === statusFilter) : app.jobs,
  );
  const reviewCount = $derived(app.jobs.filter((job) => job.status === 'awaiting_review').length);
  const doneCount = $derived(app.jobs.filter((job) => job.status === 'completed').length);
  const scheduledCount = $derived(app.jobs.filter((job) => job.status === 'scheduled').length);

  function toggleSource(name, checked) {
    app.create.selectedSources = checked
      ? [...new Set([...app.create.selectedSources, name])]
      : app.create.selectedSources.filter((source) => source !== name);
  }

  function setOverride(source, key, value) {
    const next = { ...(app.create.perSource[source] || {}) };
    if (value === '') delete next[key];
    else next[key] = value;
    app.create.perSource = { ...app.create.perSource, [source]: next };
  }

  function togglePlatform(platform, checked) {
    app.create.include = checked
      ? [...new Set([...app.create.include, platform])]
      : app.create.include.filter((item) => item !== platform);
  }

  function onFile(event) {
    app.create.uploadFile = event.currentTarget.files?.[0] || null;
  }

  function create() {
    app.create.advanced.noConfirm = !app.create.validateOnly;
    submitCreate();
  }
</script>

<div class="content queue-layout">
  <section class="stats">
    <div class="stat"><strong>{app.jobs.length.toString().padStart(2, '0')}</strong><span>jobs</span></div>
    <div class="stat"><strong>{reviewCount.toString().padStart(2, '0')}</strong><span>awaiting review</span></div>
    <div class="stat"><strong>{scheduledCount.toString().padStart(2, '0')}</strong><span>scheduled</span></div>
    <div class="stat"><strong>{doneCount.toString().padStart(2, '0')}</strong><span>complete</span></div>
  </section>

  <div class="columns">
    <div class="section">
      <Card
        title="Create & upload"
        description="Pick clips, add a title if you like, and send them up. Everything else has a sensible default."
      >
        <div class="stack">
          <label class="field">
            <span>Upload a clip</span>
            <input type="file" accept="video/*" onchange={onFile} />
            {#if app.create.uploadFile}
              <small class="field-hint">{app.create.uploadFile.name}</small>
            {/if}
          </label>

          <div class="row-between">
            <span class="field-label">Clips in your source folder</span>
            <div class="row">
              <button
                class="btn btn-ghost btn-sm"
                onclick={() => (app.create.selectedSources = app.sources.map((source) => source.name))}
              >Select all</button>
              <button
                class="btn btn-ghost btn-sm"
                onclick={() => (app.create.selectedSources = [])}
              >Clear</button>
              <span class="mono faint">{app.create.selectedSources.length} selected</span>
            </div>
          </div>

          {#if app.sources.length}
            <div class="source-list">
              {#each app.sources as source (source.name)}
                <div class="source-entry">
                  <label class="source-option">
                    <input
                      type="checkbox"
                      checked={app.create.selectedSources.includes(source.name)}
                      onchange={(event) => toggleSource(source.name, event.currentTarget.checked)}
                    />
                    <span class="name">{source.name}</span>
                    <small>{formatBytes(source.size)}</small>
                  </label>
                  <button
                    class="override-toggle"
                    aria-expanded={app.create.expandedSource === source.name}
                    onclick={() =>
                      (app.create.expandedSource =
                        app.create.expandedSource === source.name ? '' : source.name)}
                  >Overrides: {source.name}</button>
                  {#if app.create.expandedSource === source.name}
                    <div class="override-panel">
                      <label class="field">
                        <span>Clip title</span>
                        <input
                          aria-label="Clip title"
                          value={app.create.perSource[source.name]?.title || ''}
                          oninput={(event) => setOverride(source.name, 'title', event.currentTarget.value)}
                        />
                      </label>
                      <label class="field">
                        <span>Clip description</span>
                        <input
                          value={app.create.perSource[source.name]?.description || ''}
                          oninput={(event) => setOverride(source.name, 'description', event.currentTarget.value)}
                        />
                      </label>
                      <label class="field">
                        <span>Clip tags</span>
                        <input
                          value={app.create.perSource[source.name]?.tags || ''}
                          placeholder="tag one, tag two"
                          oninput={(event) => setOverride(source.name, 'tags', event.currentTarget.value)}
                        />
                      </label>
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          {:else}
            <p class="faint">No clips yet. Upload one above to get started.</p>
          {/if}

          <div class="grid-2">
            <Field label="Title override" hint="Leave empty to use each filename.">
              <input bind:value={app.create.title} placeholder="Uses each filename" />
            </Field>
            <Field label="Tags">
              <input bind:value={app.create.tags} placeholder="clutch, ranked, highlights" />
            </Field>
          </div>
          <Field label="Description">
            <textarea bind:value={app.create.description} rows="2"></textarea>
          </Field>

          <div class="field">
            <span>Upload to</span>
            <div class="chips">
              {#each app.platforms as platform (platform)}
                <button
                  class="chip"
                  class:active={app.create.include.includes(platform)}
                  aria-pressed={app.create.include.includes(platform)}
                  onclick={() => togglePlatform(platform, !app.create.include.includes(platform))}
                >
                  <PlatformMark platform={platform} size={16} />
                  {platform}
                </button>
              {/each}
            </div>
          </div>

          <details class="advanced">
            <summary>Advanced options</summary>
            <div class="advanced-body">
              <div class="grid-2">
                <label class="field">
                  <span>Layout preset</span>
                  <select bind:value={app.create.layoutId}>
                    <option value="">No preset</option>
                    {#each app.layouts as layout (layout.id)}
                      <option value={layout.id}>{layout.name}</option>
                    {/each}
                  </select>
                </label>
                <label class="field">
                  <span>Caption renderer</span>
                  <select bind:value={app.create.renderer}>
                    <option value="overlay">Overlay</option>
                    <option value="stacked">Stacked</option>
                  </select>
                </label>
              </div>
              <div class="checks">
                <label class="check">
                  <input type="checkbox" bind:checked={app.create.advanced.conversionSkip} /> Skip conversion
                </label>
                <label class="check">
                  <input type="checkbox" bind:checked={app.create.advanced.subtitlesSkip} /> Skip transcript
                </label>
                <label class="check">
                  <input type="checkbox" bind:checked={app.create.advanced.uploadSkip} /> Skip upload
                </label>
                <label class="check">
                  <input type="checkbox" bind:checked={app.create.advanced.strict} /> Strict validation
                </label>
                <label class="check">
                  <input type="checkbox" bind:checked={app.create.advanced.clean} /> Clean generated files
                </label>
              </div>
            </div>
          </details>

          <div class="row-between">
            <label class="check">
              <input type="checkbox" bind:checked={app.create.validateOnly} /> Validate only
            </label>
            <button class="btn btn-primary" disabled={app.busy} onclick={create}>
              <Icon name={app.create.validateOnly ? 'check' : 'upload'} />
              {app.create.validateOnly ? 'Validate' : 'Create & upload'}
            </button>
          </div>
        </div>
      </Card>
    </div>

    <div class="section">
      <div class="section-head">
        <div>
          <h2>Queue</h2>
          <p>Click a job to open its detail.</p>
        </div>
        <button class="btn btn-ghost btn-sm" onclick={loadWorkspace}>
          <Icon name="refresh" /> Refresh
        </button>
      </div>

      <div class="chips">
        {#each STATUS_FILTERS as filter (filter.id)}
          <button
            class="chip"
            class:active={statusFilter === filter.id}
            onclick={() => (statusFilter = filter.id)}
          >{filter.label}</button>
        {/each}
      </div>

      {#if filteredJobs.length}
        <div class="job-list">
          {#each filteredJobs as job (job.job_id)}
            <JobCard {job} />
          {/each}
        </div>
      {:else}
        <Card flush>
          <EmptyState
            icon="queue"
            title={app.jobs.length ? 'No jobs match this filter' : 'Your queue is empty'}
            message={app.jobs.length
              ? 'Choose a different status.'
              : 'Select a clip on the left and upload to start your first job.'}
          />
        </Card>
      {/if}
    </div>
  </div>
</div>

<style>
  .columns {
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
    gap: var(--space-8);
    align-items: start;
  }

  .checks {
    display: grid;
    gap: var(--space-2);
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }

  @media (max-width: 980px) {
    .columns {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 520px) {
    .checks {
      grid-template-columns: 1fr;
    }
  }
</style>
