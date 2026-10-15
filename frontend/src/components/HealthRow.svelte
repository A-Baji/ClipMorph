<script>
  import PlatformMark from './PlatformMark.svelte';
  import { platformLabel } from '../lib/format.js';

  /** Credential status + probe row for the Settings view. */
  let { platform, configured, probe, onProbe } = $props();

  const tone = $derived(!probe ? '' : probe === 'ok' ? 'ok' : probe === 'unavailable' ? 'warn' : 'bad');
</script>

<div class="health-row">
  <PlatformMark {platform} />
  <div class="health-name">
    <b>{platformLabel(platform)}</b>
    <small class="faint">{configured ? 'configured' : 'not configured'}</small>
  </div>
  <div class="verdict">
    {#if probe}
      <span class="dot {tone}"></span>
      <small>{probe}</small>
    {/if}
    <!-- U13: the probe sits in the same quiet bordered control family as the
         app's other secondary actions, not as a naked text link. -->
    <button class="btn btn-secondary btn-sm" onclick={() => onProbe(platform)}>
      {probe ? 'Re-probe' : 'Probe'}
    </button>
  </div>
</div>

<style>
  .health-name {
    display: grid;
    gap: var(--space-1);
    min-width: 0;
    flex: 1 1 0;
  }
</style>
