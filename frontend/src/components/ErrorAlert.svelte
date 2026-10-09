<script>
  import Icon from './Icon.svelte';
  import { app, clearErrors } from '../lib/store.svelte.js';
</script>

{#if app.errors.length}
  <div class="alert" role="alert">
    <Icon name="alert" />
    <div class="alert-body">
      {#each app.errors as error}<div>{error}</div>{/each}
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
  }
</style>
