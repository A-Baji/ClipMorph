<script>
  import Icon from './Icon.svelte';

  /** Centered placeholder for an empty collection. */
  let { icon = 'queue', title, message = '', children } = $props();
</script>

<div class="empty">
  <Icon name={icon} size={28} />
  <strong>{title}</strong>
  {#if message}<p>{message}</p>{/if}
  {#if children}{@render children()}{/if}
</div>
