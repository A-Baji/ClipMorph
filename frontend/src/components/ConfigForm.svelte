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
    wizardFieldError,
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
   * collapsed. Dry-run validation errors that name a field's config path
   * also render inline under that field (D24).
   */
  let {
    sections = [],
    mode = 'job',
    source = '',
    prefix = '',
    depth = 0,
    /* Issue #261 item 7: every config section is expanded by default — the
       collapse-by-default decision (D9) is walked back. */
    open = true,
  } = $props();

  const layouts = $derived(app.layouts || []);

  /** D24: the inline error for one field, mapped from its config path. */
  function fieldError(path) {
    return wizardFieldError(source, path, mode === 'job');
  }

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

  /**
   * Issue #261 item 11: selects never offer a generic "inherit" entry — the
   * reset button is the one tri-state mechanism, and the select shows the
   * resolved value. A schema-null field (unset schedule timezone) renders one
   * domain-labeled unset option so the empty state stays readable; a config
   * value outside the curated options still shows truthfully.
   */
  const UNSET_LABELS = {
    'upload.schedule.timezone': 'Platform default',
  };

  function unsetLabel(path) {
    return UNSET_LABELS[path] || 'Not set';
  }

  function valueOutsideOptions(control, value) {
    return (
      value !== null && value !== undefined && value !== '' &&
      !control.options.some((option) => String(option.value) === String(value))
    );
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
          <div class="config-field" class:overridden class:invalid={fieldError(path)}>
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
            {#if fieldError(path)}
              <small class="field-error" role="alert">{fieldError(path)}</small>
            {/if}
          </div>
        {:else}
          <div class="config-field" class:overridden class:invalid={fieldError(path)}>
            <div class="config-label">
              <label for={fid}><span>{field.label}</span></label>
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
            <div class="config-control">
              {#if control.kind === 'select'}
                <select
                  id={fid}
                  value={value === null || value === undefined ? '' : String(value)}
                  onchange={(event) => {
                    // Issue #261 item 11: choosing an unset option writes
                    // null (the reset button remains the tri-state
                    // mechanism); any other choice writes the real value.
                    const next = event.currentTarget.value;
                    onInput(path, 'string', next === '' ? null : next);
                  }}
                >
                  {#if value === null || value === undefined || value === ''}
                    <option value="">{unsetLabel(fullPath(field))}</option>
                  {/if}
                  {#each control.options as option (option.value)}
                    <option value={option.value}>{option.label}</option>
                  {/each}
                  {#if valueOutsideOptions(control, value)}
                    <option value={String(value)}>{String(value)}</option>
                  {/if}
                </select>
              {:else if control.kind === 'datetime'}
                <!-- Issue #261 item 12: the whole field is the click target —
                     a click anywhere calls showPicker, not just the tiny
                     calendar glyph. -->
                <input
                  id={fid}
                  type="datetime-local"
                  value={toLocalInput(value)}
                  onclick={(event) => event.currentTarget.showPicker?.()}
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
            {#if fieldError(path)}
              <small class="field-error" role="alert">{fieldError(path)}</small>
            {/if}
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
