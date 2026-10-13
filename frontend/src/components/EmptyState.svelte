<script>
  import Icon from './Icon.svelte';

  /** Centered placeholder for an empty collection. */
  let { icon = 'queue', title, message = '', compact = false, children } = $props();
</script>

<div class="empty" class:compact>
  <Icon name={icon} size={compact ? 20 : 28} />
  <strong>{title}</strong>
  {#if message}<p>{message}</p>{/if}
  {#if children}{@render children()}{/if}
</div>
