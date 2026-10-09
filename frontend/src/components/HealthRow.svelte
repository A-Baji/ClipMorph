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
    <button class="btn btn-ghost btn-sm" onclick={() => onProbe(platform)}>
      {probe ? 'Re-probe' : 'Probe'}
    </button>
  </div>
</div>

<style>
  .health-name {
    display: grid;
    gap: var(--space-1);
  }
</style>
