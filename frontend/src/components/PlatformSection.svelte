<script>
  import ConfigForm from './ConfigForm.svelte';
  import Icon from './Icon.svelte';
  import {
    batchValue,
    jobValue,
    setBatchField,
    setJobField,
  } from '../lib/store.svelte.js';
  import { platformLabel } from '../lib/format.js';

  /**
   * The generated forms' per-platform subtree (issue #259 D8): one
   * collapsible "Platform" node whose children are the platform rows, each
   * collapsed by default, with the platform-enable toggle visible on the
   * row itself. Upload participation is the per-platform ``upload.skip``
   * flag, inverted for the user-facing enable switch. The row is a manual
   * accordion button (not ``<details>``): a checkbox cannot live inside a
   * summary without breaking one of the two click behaviors.
   */
  let { spec, mode = 'batch', source = '' } = $props();

  const order = $derived(spec?.platforms?.order || []);
  let expanded = $state({});

  function skipPath(platform) {
    return `platforms.${platform}.upload.skip`;
  }

  function enabled(platform) {
    const skip = mode === 'batch'
      ? batchValue(skipPath(platform))
      : jobValue(source, skipPath(platform));
    return !skip; // an absent flag inherits "not skipped"
  }

  function write(platform, checked) {
    const path = skipPath(platform);
    // Explicit true/false: a drag back and forth must settle on parity
    // with the inherited value, so both states write real overrides.
    if (mode === 'batch') setBatchField(path, checked ? false : true);
    else setJobField(source, path, checked ? false : true);
  }

  function platformSections(platform) {
    const base = spec?.platforms?.sections || [];
    // The spec's flat per-platform options carry full paths
    // ("platforms.youtube.privacy_status"); ConfigForm re-prefixes them with
    // ``platforms.<platform>.``, so strip the platform prefix here.
    const flat = (spec?.platforms?.flat_fields?.[platform] || []).map(
      (field) => ({
        ...field,
        path: field.path.replace(
          new RegExp(`^platforms\\.${platform}\\.`), ''),
      }));
    if (!flat.length) return base;
    return [
      ...base,
      {
        id: `platforms.${platform}.options`,
        label: `${platformLabel(platform)} options`,
        fields: flat,
      },
    ];
  }
</script>

<details class="config-section platform-group" open>
  <summary class="config-summary">
    <span class="config-legend">Platform</span>
  </summary>
  <div class="platform-nodes">
    {#each order as platform (platform)}
      <div class="platform-node">
        <button
          type="button"
          class="platform-node-head"
          aria-expanded={Boolean(expanded[platform])}
          onclick={() => (expanded = { ...expanded, [platform]: !expanded[platform] })}
        >
          <span class="platform-name">{platformLabel(platform)}</span>
          {#if !enabled(platform)}
            <span class="badge badge-warning">skipped</span>
          {/if}
          <Icon
            name={expanded[platform] ? 'chevronDown' : 'chevronRight'}
            size={14}
          />
        </button>
        <label class="check" title="Upload through {platformLabel(platform)}">
          <input
            type="checkbox"
            aria-label={`${platformLabel(platform)} uploads enabled`}
            checked={enabled(platform)}
            onchange={(event) => write(platform, event.currentTarget.checked)}
          />
          <span>Enabled</span>
        </label>
      </div>
      {#if expanded[platform]}
        <div class="platform-body">
          <ConfigForm
            sections={platformSections(platform)}
            {mode}
            {source}
            prefix={`platforms.${platform}.`}
          />
        </div>
      {/if}
    {/each}
  </div>
</details>

<style>
  .platform-group {
    margin-top: var(--space-3);
  }

  .platform-nodes {
    display: grid;
    gap: var(--space-2);
    padding-top: var(--space-2);
  }

  .platform-node {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-1) var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
  }

  .platform-node-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex: 1;
    min-width: 0;
    padding: var(--space-2);
    text-align: left;
    cursor: pointer;
    color: inherit;
    background: none;
    border: none;
  }

  .platform-name {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    flex: 1;
  }

  .platform-node .check {
    flex-shrink: 0;
  }

  .platform-body {
    grid-column: 1 / -1;
    padding: var(--space-2) var(--space-3) var(--space-3);
    border-top: 1px solid var(--color-border);
  }
</style>
