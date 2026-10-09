<script>
  import { onMount } from 'svelte';
  import Sidebar from './components/Sidebar.svelte';
  import Topbar from './components/Topbar.svelte';
  import Notice from './components/Notice.svelte';
  import ErrorAlert from './components/ErrorAlert.svelte';
  import ConfirmDialog from './components/ConfirmDialog.svelte';
  import QueueView from './views/QueueView.svelte';
  import JobDetailView from './views/JobDetailView.svelte';
  import MetricsView from './views/MetricsView.svelte';
  import LayoutsView from './views/LayoutsView.svelte';
  import SettingsView from './views/SettingsView.svelte';
  import { app, loadWorkspace } from './lib/store.svelte.js';

  const PAGE = {
    queue: {
      title: 'Your edit queue',
      subtitle: 'Select clips and upload — everything else has a sensible default.',
    },
    metrics: { title: 'Metrics', subtitle: 'Cross-job comparison of published clips.' },
    layouts: { title: 'Layouts', subtitle: 'Reusable conversion presets.' },
    settings: { title: 'Settings', subtitle: 'Workspace paths, credentials, and defaults.' },
  };

  const page = $derived(PAGE[app.view] || PAGE.queue);

  onMount(() => {
    loadWorkspace();
  });
</script>

<svelte:head>
  <title>ClipMorph / Studio</title>
  <link rel="icon" href="data:," />
</svelte:head>

<div class="shell">
  <Sidebar />

  <main class="main">
    {#if app.view === 'job'}
      <div class="alert-slot">
        <Notice />
        <ErrorAlert />
      </div>
      <JobDetailView />
    {:else}
      <Topbar title={page.title} subtitle={page.subtitle}>
        {#if !app.online}
          <span class="badge badge-danger">offline</span>
        {/if}
      </Topbar>
      <div class="alert-slot">
        <Notice />
        <ErrorAlert />
      </div>
      {#if !app.ready}
        <div class="content"><p class="faint">Loading workspace…</p></div>
      {:else if app.view === 'metrics'}
        <MetricsView />
      {:else if app.view === 'layouts'}
        <LayoutsView />
      {:else if app.view === 'settings'}
        <SettingsView />
      {:else}
        <QueueView />
      {/if}
    {/if}
  </main>
</div>

<ConfirmDialog />

<style>
  .alert-slot {
    width: 100%;
    max-width: 1180px;
    padding: var(--space-6) var(--space-8) 0;
  }

  @media (max-width: 860px) {
    .alert-slot {
      padding: var(--space-4) var(--space-5) 0;
    }
  }
</style>
