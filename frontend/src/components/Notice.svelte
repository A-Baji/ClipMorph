<script>
  import { app } from '../lib/store.svelte.js';
</script>

{#if app.notice}
  <div class="notice" role="status">{app.notice}</div>
{/if}
