<script>
  import JobDetailView from '../views/JobDetailView.svelte';
  import { app, closeJob } from '../lib/store.svelte.js';

  /** The one detail surface: the full JobDetailView content in a modal (#257). */

  function onKeydown(event) {
    if (event.key === 'Escape') closeJob();
  }
</script>

<svelte:window on:keydown={onKeydown} />

{#if app.selectedJobId}
  <div class="detail-scrim" role="presentation" onclick={closeJob}></div>
  <div class="detail-modal" role="dialog" aria-modal="true" aria-label="Job detail">
    <JobDetailView />
  </div>
{/if}

<style>
  .detail-scrim {
    position: fixed;
    inset: 0;
    background: var(--color-scrim);
    z-index: 40;
  }

  .detail-modal {
    position: fixed;
    z-index: 41;
    inset: 4vh 4vw;
    overflow: auto;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg);
  }

  @media (max-width: 700px) {
    .detail-modal {
      inset: 0;
      border-radius: 0;
    }
  }
</style>
