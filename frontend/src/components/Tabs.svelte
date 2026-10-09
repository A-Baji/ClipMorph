<script>
  /** Accessible tab strip. ``tabs`` is ``[{id,label}]``. */
  let { tabs, active, onSelect } = $props();
</script>

<div class="tabs" role="tablist">
  {#each tabs as tab (tab.id)}
    <button
      class="tab"
      role="tab"
      aria-selected={active === tab.id}
      onclick={() => onSelect(tab.id)}
    >{tab.label}</button>
  {/each}
</div>
