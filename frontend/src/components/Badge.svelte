<script>
  /** Status pill. ``tone`` is neutral|primary|success|warning|danger|info. */
  let { tone = 'neutral', children } = $props();
</script>

<span class="badge badge-{tone}">{@render children()}</span>
