<script>
  /** Surface container with an optional heading row and action slot. */
  let { title = '', description = '', flush = false, actions, children } = $props();
</script>

<section class="card" class:flush>
  {#if title || actions}
    <div class="card-head">
      <div>
        {#if title}<h3>{title}</h3>{/if}
        {#if description}<p class="card-sub">{description}</p>{/if}
      </div>
      {#if actions}<div class="row">{@render actions()}</div>{/if}
    </div>
  {/if}
  {@render children()}
</section>

<style>
  .card-sub {
    margin-top: var(--space-1);
    font-size: var(--text-xs);
    color: var(--color-text-muted);
  }
</style>
