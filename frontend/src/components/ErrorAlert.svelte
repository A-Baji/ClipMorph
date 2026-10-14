<script>
  import Icon from './Icon.svelte';
  import {
    app,
    clearErrors,
    CONNECTION_ERROR_MESSAGE,
    loadWorkspace,
  } from '../lib/store.svelte.js';

  let retrying = $state(false);

  async function retryConnection() {
    if (retrying) return;
    retrying = true;
    try {
      await loadWorkspace();
      if (app.online) clearErrors();
    } finally {
      retrying = false;
    }
  }
</script>

{#if app.errors.length}
  <div class="alert" role="alert">
    <Icon name="alert" />
    <div class="alert-body">
      {#each app.errors as error}<div>{error}</div>{/each}
      {#if !app.online && app.errors.includes(CONNECTION_ERROR_MESSAGE)}
        <button
          class="btn btn-secondary"
          disabled={retrying}
          onclick={retryConnection}
        >{retrying ? 'Retrying…' : 'Retry connection'}</button>
      {/if}
    </div>
    <button
      class="btn btn-ghost btn-icon"
      aria-label="Dismiss errors"
      onclick={clearErrors}
    ><Icon name="x" /></button>
  </div>
{/if}

<style>
  .alert-body {
    flex: 1;
    min-width: 0;
    display: grid;
    gap: var(--space-2);
  }
</style>
