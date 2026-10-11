<script>
  import Icon from './Icon.svelte';
  import SelfConfigForm from './ConfigForm.svelte';
  import { controlDescriptor } from '../lib/form.js';
  import { toLocalInput, toUtcTimestamp } from '../lib/format.js';
  import {
    app,
    batchHasOverride,
    batchValue,
    clearBatchField,
    clearJobField,
    globalDefault,
    jobHasOverride,
    jobValue,
    setBatchField,
    setJobField,
  } from '../lib/store.svelte.js';

  /**
   * Recursive renderer for the generated configuration-form spec (issue
   * #257). Every control is tri-state: inherit batch / inherit global
   * default / custom. ``mode`` is "batch" for the shared block and "job"
   * for a job's detail form; ``prefix`` namespaces per-platform paths.
   *
   * Row anatomy (issue #259 D6, D7): boolean controls sit immediately left
   * of their visible label inside one wrapping ``<label>``; text, number and
   * select controls sit directly beneath their ``for``-associated label;
   * free text survives only for content title/description/tags; object
   * fields (the inline layout) never render — inline layout overrides live
   * in the Layouts editor. Sections render as collapsible ``<details>``
   * (D9/U10): batch sections may start expanded, per-job sections start
   * collapsed.
   */
  let {
    sections = [],
    mode = 'job',
    source = '',
    prefix = '',
    depth = 0,
    open = false,
  } = $props();

  const layouts = $derived(app.layouts || []);

  function fullPath(field) {
    return prefix ? `${prefix}${field.path}` : field.path;
  }

  /** Explicit label CONTROL association id (D6): ``for`` + ``id`` pair. */
  function fieldId(field) {
    return `cf-${mode}-${source || 'batch'}-${fullPath(field)}`
      .replace(/[^a-zA-Z0-9]+/g, '-');
  }

  function hasOverride(path) {
    return mode === 'batch' ? batchHasOverride(path) : jobHasOverride(source, path);
  }

  function resolved(path) {
    return mode === 'batch' ? batchValue(path) : jobValue(source, path);
  }

  function write(path, value) {
    if (mode === 'batch') setBatchField(path, value);
    else setJobField(source, path, value);
  }

  function reset(path) {
    if (mode === 'batch') clearBatchField(path);
    else clearJobField(source, path);
  }

  function display(value) {
    if (value === null || value === undefined) return '';
    if (Array.isArray(value)) return value.join(', ');
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function defaultDiffers(path) {
    const value = resolved(path);
    return JSON.stringify(value ?? null) !== JSON.stringify(globalDefault(path) ?? null);
  }

  function batchDiffers(path) {
    if (mode !== 'job' || !jobHasOverride(source, path)) return false;
    return JSON.stringify(jobValue(source, path) ?? null)
      !== JSON.stringify(batchValue(path) ?? null);
  }

  function onInput(path, type, raw) {
    if (type === 'boolean') return write(path, raw);
    if (type === 'integer') return write(path, raw === '' ? null : Number.parseInt(raw, 10));
    if (type === 'number') return write(path, raw === '' ? null : Number.parseFloat(raw));
    if (type === 'string_list') {
      return write(
        path,
        raw.split(',').map((item) => item.trim()).filter(Boolean),
      );
    }
    return write(path, raw);
  }
</script>

{#each sections as section (section.id)}
  <details class="config-section depth-{depth}" open={open}>
    <summary class="config-summary">
      <span class="config-legend">{section.label}</span>
    </summary>
    <div class="config-fields">
      {#each section.fields as field (field.path)}
        {@const control = controlDescriptor(field, layouts)}
        {@const path = fullPath(field)}
        {@const value = resolved(path)}
        {@const overridden = hasOverride(path)}
        {@const fid = fieldId(field)}
        {#if field.protected || control.kind === 'hidden'}
          <!-- Transcription keys drive the one shared transcript session; the
               schema rejects a per-platform override, so it is not offered.
               Object fields (the inline layout) are D7-removed: inline layout
               overrides belong to the Layouts editor. -->
        {:else if control.kind === 'checkbox'}
          <div class="config-field" class:overridden>
            <div class="config-label">
              <label class="check" for={fid}>
                <input
                  type="checkbox"
                  id={fid}
                  checked={Boolean(value)}
                  onchange={(event) => onInput(path, 'boolean', event.currentTarget.checked)}
                />
                <span>{field.label}</span>
              </label>
              <span class="badges">
                {#if defaultDiffers(path)}
                  <span class="badge badge-warning" title={`default: ${display(globalDefault(path))}`}>
                    ≠ default
                  </span>
                {/if}
                {#if batchDiffers(path)}
                  <span class="badge badge-info" title={`batch: ${display(batchValue(path))}`}>
                    ≠ batch
                  </span>
                {/if}
                {#if overridden}
                  <button
                    type="button"
                    class="btn btn-ghost btn-icon"
                    title="Reset to inherited value"
                    aria-label={`Reset ${field.label}`}
                    onclick={() => reset(path)}
                  >
                    <Icon name="refresh" size={14} />
                  </button>
                {/if}
              </span>
            </div>
            {#if field.hint}<small class="field-hint">{field.hint}</small>{/if}
          </div>
        {:else}
          <div class="config-field" class:overridden>
            <label class="config-label" for={fid}>
              <span>{field.label}</span>
              <span class="badges">
                {#if defaultDiffers(path)}
                  <span class="badge badge-warning" title={`default: ${display(globalDefault(path))}`}>
                    ≠ default
                  </span>
                {/if}
                {#if batchDiffers(path)}
                  <span class="badge badge-info" title={`batch: ${display(batchValue(path))}`}>
                    ≠ batch
                  </span>
                {/if}
                {#if overridden}
                  <button
                    type="button"
                    class="btn btn-ghost btn-icon"
                    title="Reset to inherited value"
                    aria-label={`Reset ${field.label}`}
                    onclick={() => reset(path)}
                  >
                    <Icon name="refresh" size={14} />
                  </button>
                {/if}
              </span>
            </label>
            <div class="config-control">
              {#if control.kind === 'select'}
                <select
                  id={fid}
                  value={value === null || value === undefined ? '' : String(value)}
                  onchange={(event) => onInput(path, 'string', event.currentTarget.value)}
                >
                  <option value="">inherit</option>
                  {#each control.options as option (option.value)}
                    <option value={option.value}>{option.label}</option>
                  {/each}
                </select>
              {:else if control.kind === 'datetime'}
                <input
                  id={fid}
                  type="datetime-local"
                  value={toLocalInput(value)}
                  oninput={(event) => onInput(path, 'datetime', toUtcTimestamp(event.currentTarget.value))}
                />
              {:else if control.kind === 'textarea'}
                <textarea
                  id={fid}
                  rows="2"
                  value={display(value)}
                  oninput={(event) => onInput(path, 'string', event.currentTarget.value)}
                ></textarea>
              {:else if control.kind === 'string_list'}
                <input
                  id={fid}
                  value={display(value)}
                  placeholder="tag one, tag two"
                  oninput={(event) => onInput(path, 'string_list', event.currentTarget.value)}
                />
              {:else if control.kind === 'number'}
                <input
                  id={fid}
                  type="number"
                  value={display(value)}
                  oninput={(event) => onInput(path, field.type, event.currentTarget.value)}
                />
              {:else}
                <input
                  id={fid}
                  type="text"
                  value={display(value)}
                  oninput={(event) => onInput(path, 'string', event.currentTarget.value)}
                />
              {/if}
            </div>
            {#if field.hint}<small class="field-hint">{field.hint}</small>{/if}
          </div>
        {/if}
      {/each}
    </div>
    {#if section.sections}
      <SelfConfigForm
        sections={section.sections}
        {mode}
        {source}
        {prefix}
        depth={depth + 1}
        {open}
      />
    {/if}
  </details>
{/each}

<style>
  .config-section {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    margin: 0 0 var(--space-3);
    background: var(--color-surface);
  }

  .config-summary {
    cursor: pointer;
    list-style: none;
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .config-summary::-webkit-details-marker {
    display: none;
  }

  .config-summary::before {
    content: '\203A';
    display: inline-block;
    transition: transform var(--duration-fast) var(--ease-standard);
    color: var(--color-text-faint);
  }

  .config-section[open] > .config-summary::before {
    transform: rotate(90deg);
  }

  .config-legend {
    font-size: var(--text-xs);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--color-text-muted);
  }

  .config-fields {
    display: grid;
    gap: var(--space-3);
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .config-field {
    display: grid;
    gap: var(--space-1);
    grid-template-columns: minmax(0, 1fr);
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    border: 1px solid transparent;
  }

  .config-field.overridden {
    border-color: var(--color-border);
    background: var(--color-surface-raised, var(--color-surface));
  }

  .config-label,
  .config-field .check {
    min-width: 0;
  }

  .config-label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }

  .config-label > .check {
    max-width: 100%;
  }

  .config-label > .check span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .badges {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    flex-shrink: 0;
  }

  .config-control {
    display: grid;
    gap: var(--space-2);
  }

  .config-control input,
  .config-control select,
  .config-control textarea {
    width: 100%;
  }

  @media (max-width: 700px) {
    .config-fields {
      grid-template-columns: 1fr;
    }
  }
</style>
