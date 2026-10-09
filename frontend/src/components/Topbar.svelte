<script>
  import Icon from './Icon.svelte';
  import { app } from '../lib/store.svelte.js';

  /** Page header: title, subtitle, and an action slot. */
  let { title, subtitle = '', children } = $props();
</script>

<header class="topbar">
  <button
    class="btn btn-ghost btn-icon menu-toggle"
    aria-label="Open navigation"
    onclick={() => (app.mobileNav = true)}
  ><Icon name="menu" /></button>
  <div class="topbar-title">
    <h1>{title}</h1>
    {#if subtitle}<p>{subtitle}</p>{/if}
  </div>
  <div class="topbar-actions">{@render children()}</div>
</header>
