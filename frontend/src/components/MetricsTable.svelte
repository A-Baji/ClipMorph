<script>
  import PlatformMark from './PlatformMark.svelte';
  import { formatDelta } from '../lib/format.js';

  /** Cross-job metrics comparison table. */
  let { rows } = $props();

  function deltaClass(delta) {
    if (delta > 0) return 'delta-up';
    if (delta < 0) return 'delta-down';
    return '';
  }
</script>

<div class="metric-table-wrap">
  <table class="metric-table">
    <thead>
      <tr>
        <th>platform</th>
        <th>title</th>
        <th>duration</th>
        <th>layout</th>
        <th>views</th>
        <th>likes</th>
        <th>comments</th>
        <th>views Δ</th>
        <th>likes Δ</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row (row.platform + row.platform_post_id)}
        <tr>
          <td>
            <span class="row">
              <PlatformMark platform={row.platform} size={18} />
              {row.platform}
            </span>
          </td>
          <td class="truncate" title={row.title}>{row.title || '—'}</td>
          <td>{row.duration_bucket || '—'}</td>
          <td>{row.layout_id || '—'}</td>
          {#if row.unavailable}
            <td colspan="5" class="faint">unavailable: {row.unavailable_reason}</td>
          {:else}
            <td class="num">{row.views ?? '—'}</td>
            <td class="num">{row.likes ?? '—'}</td>
            <td class="num">{row.comments ?? '—'}</td>
            <td class="num {deltaClass(row.views_delta)}">{formatDelta(row.views_delta)}</td>
            <td class="num {deltaClass(row.likes_delta)}">{formatDelta(row.likes_delta)}</td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>
</div>
