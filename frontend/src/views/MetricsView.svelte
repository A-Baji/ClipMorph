<script>
  import Card from '../components/Card.svelte';
  import MetricsTable from '../components/MetricsTable.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import PlatformMark from '../components/PlatformMark.svelte';
  import { app, loadMetrics } from '../lib/store.svelte.js';
  import { platformLabel } from '../lib/format.js';

  /** Cross-job comparison over stored snapshots. */
  function choose(platform) {
    app.metricFilterPlatform = app.metricFilterPlatform === platform ? '' : platform;
    loadMetrics();
  }
</script>

<div class="content">
  <!-- U3: the Topbar renders the page's single header; the filter chips
       belong to the table below it. -->
  <div class="section-head">
    <div class="chips">
      {#each app.platforms as platform (platform)}
        <button
          class="chip"
          class:active={app.metricFilterPlatform === platform}
          aria-pressed={app.metricFilterPlatform === platform}
          onclick={() => choose(platform)}
        >
          <PlatformMark platform={platform} size={16} />
          {platformLabel(platform)}
        </button>
      {/each}
    </div>
  </div>

  <Card flush>
    {#if app.metricsComparison.length}
      <MetricsTable rows={app.metricsComparison} />
    {:else}
      <EmptyState
        icon="chart"
        title="No metrics yet"
        message="Open a clip to view its metrics."
      />
    {/if}
  </Card>
</div>
