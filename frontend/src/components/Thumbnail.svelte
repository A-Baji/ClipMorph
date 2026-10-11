<script>
  import Icon from './Icon.svelte';
  import { api } from '../lib/api.js';

  /**
   * Real video poster frame for a source clip (issue #259 C5): the Phase 1
   * thumbnail endpoint's disk-cached frame. The generic video icon is the
   * load/error fallback only — it never sits next to a rendered image.
   */
  let { name = '', size = 44, alt = '' } = $props();

  let state = $state('loading'); // loading | loaded | error

  const iconSize = $derived(Math.round(size * 0.45));
</script>

<span class="thumb" style="width:{size}px;height:{size}px">
  {#if !name || state !== 'loaded'}
    <Icon name="video" size={iconSize} />
  {/if}
  {#if name && state !== 'error'}
    <img
      src={api.thumbnailUrl(name)}
      {alt}
      loading="lazy"
      onload={() => (state = 'loaded')}
      onerror={() => (state = 'error')}
    />
  {/if}
</span>

<style>
  .thumb {
    position: relative;
    flex-shrink: 0;
    display: grid;
    place-items: center;
    border-radius: var(--radius-sm);
    background: var(--color-surface-hover);
    color: var(--color-text-muted);
    overflow: hidden;
  }

  .thumb img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: inherit;
  }
</style>
