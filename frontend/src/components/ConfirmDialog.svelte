<script>
  import { app, settleConfirm } from '../lib/store.svelte.js';

  /** Single app-level confirmation dialog. Escape cancels. */
  function onKeydown(event) {
    if (event.key === 'Escape' && app.confirm) settleConfirm(false);
  }

  function onScrimClick(event) {
    if (event.target === event.currentTarget) settleConfirm(false);
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if app.confirm}
  <div class="scrim" role="presentation" onclick={onScrimClick}>
    <div
      class="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      tabindex="-1"
    >
      <h3 id="confirm-title">{app.confirm.title}</h3>
      {#if app.confirm.message}<p>{app.confirm.message}</p>{/if}
      <div class="modal-actions">
        <button class="btn btn-ghost" onclick={() => settleConfirm(false)}>Cancel</button>
        <button
          class="btn {app.confirm.danger ? 'btn-danger' : 'btn-primary'}"
          onclick={() => settleConfirm(true)}
        >{app.confirm.confirmLabel || 'Confirm'}</button>
      </div>
    </div>
  </div>
{/if}
