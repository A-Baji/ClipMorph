<script>
  import Icon from './Icon.svelte';
  import SelfConfigForm from './ConfigForm.svelte';
  import {
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
   * Recursive renderer for the generated configuration-form spec (issue #257).
   * Every control is tri-state: inherit batch / inherit global default /
   * custom. ``mode`` is "batch" for the shared block and "job" for a job's
   * detail form; ``prefix`` namespaces per-platform paths.
   */
  let { sections = [], mode = 'job', source = '', prefix = '', depth = 0 } = $props();

  function fullPath(field) {
    return prefix ? `${prefix}${field.path}` : field.path;
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
    if (type === 'object') {
      try {
        return write(path, raw.trim() ? JSON.parse(raw) : {});
      } catch {
        return; // keep typing until the JSON is valid
      }
    }
    return write(path, raw);
  }
</script>

{#each sections as section (section.id)}
  <fieldset class="config-section depth-{depth}">
    <legend>{section.label}</legend>
    <div class="config-fields">
      {#each section.fields as field (field.path)}
        {@const path = fullPath(field)}
        {@const value = resolved(path)}
        {@const overridden = hasOverride(path)}
        {#if field.protected}
          <!-- Transcription keys drive the one shared transcript session; the
               schema rejects a per-platform override, so it is not offered. -->
        {:else}
        <div class="config-field" class:overridden>
          <div class="config-label">
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
            </span>
          </div>
          <div class="config-control">
            {#if field.type === 'boolean'}
              <input
                type="checkbox"
                aria-label={field.label}
                checked={Boolean(value)}
                onchange={(event) => onInput(path, 'boolean', event.currentTarget.checked)}
              />
            {:else if field.type === 'enum'}
              <select
                aria-label={field.label}
                value={display(value)}
                onchange={(event) => onInput(path, 'string', event.currentTarget.value)}
              >
                <option value="">inherit</option>
                {#each field.options || [] as option (option)}
                  <option value={option}>{option}</option>
                {/each}
              </select>
            {:else if field.type === 'text'}
              <textarea
                aria-label={field.label}
                rows="2"
                value={display(value)}
                oninput={(event) => onInput(path, 'string', event.currentTarget.value)}
              ></textarea>
            {:else if field.type === 'object'}
              <textarea
                aria-label={field.label}
                rows="3"
                spellcheck="false"
                value={display(value)}
                oninput={(event) => onInput(path, 'object', event.currentTarget.value)}
              ></textarea>
            {:else}
              <input
                aria-label={field.label}
                type={field.type === 'integer' || field.type === 'number' ? 'number' : 'text'}
                value={display(value)}
                oninput={(event) => onInput(path, field.type, event.currentTarget.value)}
              />
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
          </div>
          {#if field.hint}<small class="field-hint">{field.hint}</small>{/if}
        </div>
        {/if}
      {/each}
    </div>
    {#if section.sections}
      <SelfConfigForm sections={section.sections} {mode} {source} {prefix} depth={depth + 1} />
    {/if}
  </fieldset>
{/each}

<style>
  .config-section {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    margin: 0 0 var(--space-3);
    background: var(--color-surface);
  }

  .config-section legend {
    font-size: var(--text-xs);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--color-text-muted);
    padding: 0 var(--space-2);
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

  .config-label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }

  .badges {
    display: inline-flex;
    gap: var(--space-1);
  }

  .config-control {
    display: flex;
    align-items: center;
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
