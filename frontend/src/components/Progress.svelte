<script>
  /** Determinate progress bar. */
  let { value = 0, small = false, label = '' } = $props();

  const pct = $derived(Math.max(0, Math.min(100, Number(value) || 0)));
</script>

<div
  class="progress"
  class:progress-sm={small}
  role="progressbar"
  aria-valuenow={pct}
  aria-valuemin="0"
  aria-valuemax="100"
  aria-label={label || undefined}
>
  <span style="width:{pct}%"></span>
</div>
