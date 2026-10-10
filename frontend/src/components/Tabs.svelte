<script>
  /** Accessible tab strip. ``tabs`` is ``[{id, label, count?}]``. A ``count`` renders as a badge next to the label. */
  let { tabs, active, onSelect } = $props();
</script>

<div class="tabs" role="tablist">
  {#each tabs as tab (tab.id)}
    <button
      class="tab"
      role="tab"
      aria-selected={active === tab.id}
      onclick={() => onSelect(tab.id)}
    >{tab.label}{#if tab.count != null}<span class="tab-count">{tab.count}</span>{/if}</button>
  {/each}
</div>

<style>
  .tab-count {
    margin-left: var(--space-2);
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    color: var(--color-text-muted);
    background: var(--color-surface-hover);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-full);
    padding: 0 var(--space-2);
  }
</style>
