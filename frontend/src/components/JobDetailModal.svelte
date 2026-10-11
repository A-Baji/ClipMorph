<script>
  import JobDetailView from '../views/JobDetailView.svelte';
  import { app, closeJob } from '../lib/store.svelte.js';

  /** The one detail surface: the full JobDetailView content in a modal (#257).

      U18 (#259): while the modal is open the background scroll is locked
      (the board cannot scroll behind it) and Tab is trapped inside the
      dialog — it can never escape onto the background cards. Focus moves
      into the dialog on open and returns to its trigger on close. */

  let modal = $state(null);
  let focused = $state(false);
  let returnFocus = null;

  function onKeydown(event) {
    if (event.key === 'Escape') {
      closeJob();
      return;
    }
    trapFocus(event);
  }

  /** U18: nothing behind the dialog ever scrolls — wheel input on the
      barrier is stopped instead of chaining into the root scroller. */
  function barrierWheel(event) {
    event.preventDefault();
  }

  function focusableElements() {
    if (!modal) return [];
    return [...modal.querySelectorAll(
      'button, [href], input, select, textarea, summary, video[controls], [tabindex]:not([tabindex="-1"])',
    )].filter((element) => !element.disabled && element.offsetParent !== null);
  }

  function trapFocus(event) {
    if (event.key !== 'Tab' || !app.selectedJobId) return;
    // The shared ConfirmDialog stacks above the dialog; its focus cycle
    // belongs to the confirm step while it is open.
    if (app.confirm) return;
    const focusables = focusableElements();
    if (!focusables.length) {
      event.preventDefault();
      return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const current = document.activeElement;
    if (!modal?.contains(current)) {
      event.preventDefault();
      first.focus();
    } else if (event.shiftKey && current === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && current === last) {
      event.preventDefault();
      first.focus();
    }
  }

  $effect(() => {
    if (!app.selectedJobId) {
      focused = false;
      return;
    }
    // U18: the board behind the dialog must not scroll while it is open:
    // both the html (the page's scroll container) and body are locked, so
    // two scroll systems never live at once behind the dialog.
    const previousHtml = document.documentElement.style.overflow;
    const previousBody = document.body.style.overflow;
    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
    returnFocus = document.activeElement;
    focused = false;
    requestAnimationFrame(() => {
      if (!modal || focused) return;
      const focusables = focusableElements();
      (focusables[0] || modal).focus();
      focused = true;
    });
    return () => {
      document.documentElement.style.overflow = previousHtml;
      document.body.style.overflow = previousBody;
      if (returnFocus instanceof HTMLElement) returnFocus?.focus();
      returnFocus = null;
    };
  });
</script>

<svelte:window on:keydown={onKeydown} />

{#if app.selectedJobId}
  <div
    class="detail-scrim"
    role="presentation"
    onwheel={barrierWheel}
    onclick={closeJob}
  ></div>
  <div
    class="detail-modal"
    role="dialog"
    aria-modal="true"
    aria-label="Job detail"
    tabindex="-1"
    bind:this={modal}
  >
    <JobDetailView />
  </div>
{/if}

<style>
  /* U5: an unmistakable scrim — the token wash plus a blur plates the board
     behind the dialog instead of leaving it readable through the top band. */
  .detail-scrim {
    position: fixed;
    inset: 0;
    background: var(--color-scrim);
    backdrop-filter: blur(6px);
    z-index: 40;
  }

  .detail-modal {
    position: fixed;
    z-index: 41;
    inset: 4vh 4vw;
    overflow: auto;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg);
  }

  .detail-modal:focus {
    outline: none;
  }

  @media (max-width: 700px) {
    .detail-modal {
      inset: 0;
      border-radius: 0;
    }
  }
</style>
