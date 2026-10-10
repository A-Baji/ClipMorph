<script>
  import Icon from '../components/Icon.svelte';
  import ConfigForm from '../components/ConfigForm.svelte';
  import {
    app,
    createFromWizard,
    discardWizard,
    leaveWizard,
    requestConfirm,
    wizardAddExtra,
    wizardClearSelection,
    wizardGoStep,
    wizardJobError,
    wizardRemoveExtra,
    wizardSelectAll,
    wizardSelected,
    wizardSetActiveJob,
    wizardToggleSource,
  } from '../lib/store.svelte.js';
  import { formatBytes } from '../lib/format.js';

  /** Two-step batch-creation wizard: clips -> configure -> create (#257). */

  let extraPath = $state('');

  const selected = $derived(wizardSelected());
  const spec = $derived(app.formSpec);
  const jobError = $derived(
    app.wizard.activeJob ? wizardJobError(app.wizard.activeJob) : '',
  );
  const activeJobConfig = $derived(
    app.wizard.jobs[app.wizard.activeJob] || { overrides: [] },
  );

  function addExtra() {
    wizardAddExtra(extraPath);
    extraPath = '';
  }

  function overrideCount(source) {
    return app.wizard.jobs[source]?.overrides?.length || 0;
  }

  function confirmDiscard() {
    requestConfirm({
      title: 'Discard this draft?',
      message: 'The selected clips and configuration you have not created yet are lost.',
      confirmLabel: 'Discard draft',
      danger: true,
      onConfirm: () => discardWizard(),
    });
  }

  function create() {
    createFromWizard();
  }
</script>

<div class="content wizard">
  <header class="wizard-head">
    <div class="row">
      {#if app.wizard.step === 2}
        <button class="btn btn-ghost" onclick={() => wizardGoStep(1)}>
          <Icon name="arrowLeft" /> Back to clips
        </button>
      {:else}
        <button class="btn btn-ghost" onclick={leaveWizard}>
          <Icon name="arrowLeft" /> Back to queue
        </button>
      {/if}
      <ol class="steps" aria-label="Creation steps">
        <li class:active={app.wizard.step === 1}>
          <span class="step-num">1</span> Clips
        </li>
        <li class:active={app.wizard.step === 2}>
          <span class="step-num">2</span> Configure
        </li>
      </ol>
    </div>
    <div class="row">
      <button class="btn btn-ghost" onclick={confirmDiscard}>Discard draft</button>
      {#if app.wizard.step === 2}
        <button class="btn btn-primary" disabled={app.busy} onclick={create}>
          <Icon name="check" /> Create {selected.length} job{selected.length === 1 ? '' : 's'}
        </button>
      {/if}
    </div>
  </header>

  {#if app.wizard.step === 1}
    <section class="step-panel">
      <div class="section-head">
        <div>
          <h2>Select clips</h2>
          <p>Only clip selection lives here. Configuration is the next step.</p>
        </div>
        <div class="row">
          <button class="btn btn-ghost btn-sm" onclick={() => wizardSelectAll(app.sources.map((s) => s.name))}>
            Select all
          </button>
          <button class="btn btn-ghost btn-sm" onclick={wizardClearSelection}>Clear</button>
          <span class="mono faint">{selected.length} selected</span>
        </div>
      </div>

      {#if app.sources.length}
        <div class="clip-grid">
          {#each app.sources as source (source.name)}
            <label class="clip-card" class:selected={app.wizard.selected.includes(source.name)}>
              <input
                type="checkbox"
                aria-label={source.name}
                checked={app.wizard.selected.includes(source.name)}
                onchange={(event) => wizardToggleSource(source.name, event.currentTarget.checked)}
              />
              <span class="clip-thumb"><Icon name="video" /></span>
              <span class="clip-main">
                <b>{source.name}</b>
                <small class="faint">{formatBytes(source.size)}</small>
              </span>
            </label>
          {/each}
        </div>
      {:else}
        <p class="faint">No clips in your source folder yet.</p>
      {/if}

      <div class="transient">
        <div>
          <b>Add a clip from another folder</b>
          <p class="faint">Referenced in place; nothing is copied into the source folder.</p>
        </div>
        <div class="row">
          <input
            aria-label="Transient clip path"
            placeholder="D:\videos\clip.mp4"
            bind:value={extraPath}
            onkeydown={(event) => event.key === 'Enter' && addExtra()}
          />
          <button class="btn btn-secondary" onclick={addExtra}>
            <Icon name="plus" /> Add
          </button>
        </div>
        {#if app.wizard.extras.length}
          <ul class="extras">
            {#each app.wizard.extras as extra (extra.path)}
              <li>
                <span class="mono">{extra.name}</span>
                <small class="faint">{extra.path}</small>
                <button
                  class="btn btn-ghost btn-sm"
                  aria-label={`Remove ${extra.name}`}
                  onclick={() => wizardRemoveExtra(extra.path)}
                >Remove</button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <div class="step-actions">
        <button
          class="btn btn-primary"
          disabled={!selected.length}
          onclick={() => wizardGoStep(2)}
        >Next: Configure</button>
      </div>
    </section>
  {:else}
    {#if !spec}
      <p class="faint">Configuration form is loading…</p>
    {:else}
      <details class="batch-block" open>
        <summary>
          <b>Batch defaults</b>
          <small class="faint">Jobs inherit these unless they override them.</small>
        </summary>
        <p class="faint resolution">Resolution: job &gt; batch &gt; global default.</p>
        <ConfigForm sections={spec.sections} mode="batch" />
        {#each spec.platforms?.order || app.platforms as platform (platform)}
          <details class="platform-block">
            <summary>{platform}</summary>
            <ConfigForm
              sections={spec.platforms.sections}
              mode="batch"
              prefix={`platforms.${platform}.`}
            />
            <ConfigForm
              sections={[{
                id: `platforms.${platform}.options`,
                label: `${platform} options`,
                fields: spec.platforms.flat_fields[platform] || [],
              }]}
              mode="batch"
            />
          </details>
        {/each}
      </details>

      <div class="wizard-body">
        <aside class="rail" aria-label="Selected jobs">
          <h3>Jobs</h3>
          {#each selected as source (source)}
            <button
              class="rail-item"
              class:active={app.wizard.activeJob === source}
              onclick={() => wizardSetActiveJob(source)}
            >
              <span class="rail-name">{source}</span>
              <span class="badge" class:badge-info={overrideCount(source) > 0}>
                {overrideCount(source)}
              </span>
            </button>
          {/each}
          <button class="btn btn-ghost btn-sm" onclick={() => wizardGoStep(1)}>
            <Icon name="plus" /> Add or remove clips
          </button>
        </aside>

        <div class="detail">
          {#if jobError}
            <div class="job-error" role="alert">{app.wizard.activeJob}: {jobError}</div>
          {/if}

          <div class="job-config">
            <div class="job-head">
              <h2>{app.wizard.activeJob}</h2>
              <span class="faint">{activeJobConfig.overrides.length} override(s)</span>
            </div>

            <ConfigForm sections={spec.sections} mode="job" source={app.wizard.activeJob} />
          </div>

          {#each spec.platforms?.order || app.platforms as platform (platform)}
            <details class="platform-block">
              <summary>{platform}</summary>
              <ConfigForm
                sections={spec.platforms.sections}
                mode="job"
                source={app.wizard.activeJob}
                prefix={`platforms.${platform}.`}
              />
              <ConfigForm
                sections={[{
                  id: `platforms.${platform}.options`,
                  label: `${platform} options`,
                  fields: spec.platforms.flat_fields[platform] || [],
                }]}
                mode="job"
                source={app.wizard.activeJob}
              />
            </details>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
</div>

<style>
  .wizard-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-4);
    margin-bottom: var(--space-5);
    flex-wrap: wrap;
  }

  .steps {
    display: flex;
    gap: var(--space-4);
    list-style: none;
    margin: 0;
    padding: 0;
    color: var(--color-text-muted);
  }

  .steps li.active {
    color: var(--color-text);
    font-weight: 600;
  }

  .step-num {
    display: inline-flex;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    align-items: center;
    justify-content: center;
    background: var(--color-border);
    font-size: var(--text-xs);
  }

  .clip-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: var(--space-3);
  }

  .clip-card {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    cursor: pointer;
  }

  .clip-card.selected {
    border-color: var(--color-primary);
  }

  .clip-thumb {
    display: inline-flex;
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
  }

  .clip-main {
    display: grid;
  }

  .transient {
    margin-top: var(--space-5);
    padding: var(--space-4);
    border: 1px dashed var(--color-border);
    border-radius: var(--radius-md);
    display: grid;
    gap: var(--space-3);
  }

  .transient input {
    min-width: 280px;
  }

  .extras {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-2);
  }

  .extras li {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .step-actions {
    margin-top: var(--space-5);
    display: flex;
    justify-content: flex-end;
  }

  .wizard-body {
    display: grid;
    grid-template-columns: minmax(0, 220px) minmax(0, 1fr);
    gap: var(--space-5);
    align-items: start;
  }

  .rail {
    display: grid;
    gap: var(--space-2);
    position: sticky;
    top: var(--space-4);
  }

  .rail-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
    cursor: pointer;
    text-align: left;
  }

  .rail-item.active {
    border-color: var(--color-primary);
  }

  .rail-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .batch-block,
  .platform-block {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    margin-bottom: var(--space-4);
  }

  .resolution {
    margin: 0 0 var(--space-3);
    font-size: var(--text-xs);
  }

  .batch-block summary,
  .platform-block summary {
    cursor: pointer;
    display: flex;
    gap: var(--space-3);
    align-items: baseline;
  }

  .job-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: var(--space-2);
  }

  .job-error {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--color-danger) 12%, transparent);
    color: var(--color-danger);
    margin-bottom: var(--space-3);
  }

  @media (max-width: 860px) {
    .wizard-body {
      grid-template-columns: 1fr;
    }
  }
</style>
