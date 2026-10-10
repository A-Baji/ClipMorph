<script>
  import Icon from './Icon.svelte';
  import { app, setView } from '../lib/store.svelte.js';

  /** Primary navigation. Queue is the default surface; job detail is nested. */
  let { onNavigate } = $props();

  const items = [
    { id: 'queue', label: 'Queue', icon: 'queue' },
    { id: 'metrics', label: 'Metrics', icon: 'chart' },
    { id: 'layouts', label: 'Layouts', icon: 'layers' },
    { id: 'settings', label: 'Settings', icon: 'sliders' },
  ];
</script>

<aside class="sidebar" class:open={app.mobileNav}>
  <div class="brand">
    <div class="brand-mark">CM</div>
    <div class="brand-text">
      <strong>ClipMorph</strong>
      <span>local workspace</span>
    </div>
  </div>

  <nav class="nav-group" aria-label="Primary navigation">
    <span class="nav-label">Workspace</span>
    {#each items as item (item.id)}
      <button
        class="nav-item"
        class:active={app.view === item.id || (app.view === 'wizard' && item.id === 'queue')}
        onclick={() => { setView(item.id); onNavigate?.(); }}
      >
        <Icon name={item.icon} />
        <span>{item.label}</span>
        {#if item.id === 'queue'}
          <span class="count">{app.jobs.length.toString().padStart(2, '0')}</span>
        {/if}
      </button>
    {/each}
  </nav>

  <div class="sidebar-foot">
    <div class="service-row" class:offline={!app.online}>
      <span class="dot"></span>
      {app.online ? 'Local service connected' : 'Local service offline'}
    </div>
  </div>
</aside>

{#if app.mobileNav}
  <button
    class="sidebar-scrim"
    aria-label="Close navigation"
    onclick={() => (app.mobileNav = false)}
  ></button>
{/if}
