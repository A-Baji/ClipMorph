<script>
  /** Label + control + optional hint. Wrapping the control keeps the label bound. */
  let { label, hint = '', children } = $props();
</script>

<label class="field">
  <span>{label}</span>
  {@render children()}
  {#if hint}<small class="field-hint">{hint}</small>{/if}
</label>
