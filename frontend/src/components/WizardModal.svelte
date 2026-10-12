<script>
  import WizardView from '../views/WizardView.svelte';
  import { app, leaveWizard } from '../lib/store.svelte.js';

  /**
   * The new-jobs overlay (issue #261 item 3): the wizard pops up as a modal
   * over the Jobs board instead of replacing the view. It reuses the detail
   * modal's U18 chrome — scroll lock, focus trap on open/return, barrier
   * wheel — with a wider dialog body for the two-step wizard. Closing the
   * popup *preserves* the draft (the header's Discard draft is the explicit
   * destructive action), so a stray click outside never loses work.
   */

  let modal = $state(null);
  let focused = $state(false);
  let returnFocus = null;

  function onKeydown(event) {
    if (event.key === 'Escape') {
      leaveWizard();
      return;
    }
    trapFocus(event);
  }

  function barrierWheel(event) {
    // U18: nothing behind the dialog scrolls.
    event.preventDefault();
  }

  function focusableElements() {
    if (!modal) return [];
    return [...modal.querySelectorAll(
      'button, [href], input, select, textarea, summary, video[controls], [tabindex]:not([tabindex="-1"])',
    )].filter((element) => !element.disabled && element.offsetParent !== null);
  }

  function trapFocus(event) {
    if (event.key !== 'Tab' || !app.wizard.active) return;
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
    if (!app.wizard.active) {
      focused = false;
      return;
    }
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

{#if app.wizard.active}
  <div
    class="wizard-scrim"
    role="presentation"
    onwheel={barrierWheel}
    onclick={leaveWizard}
  ></div>
  <div
    class="wizard-modal"
    role="dialog"
    aria-modal="true"
    aria-label="New jobs"
    tabindex="-1"
    bind:this={modal}
  >
    <WizardView />
  </div>
{/if}

<style>
  /* U5-style scrim: the token wash plus a blur plates the board behind the
     dialog. */
  .wizard-scrim {
    position: fixed;
    inset: 0;
    background: var(--color-scrim);
    backdrop-filter: blur(6px);
    z-index: 40;
  }

  .wizard-modal {
    position: fixed;
    z-index: 41;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: min(1150px, 94vw);
    max-height: 90vh;
    overflow-y: auto;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg, var(--radius-md));
    box-shadow: var(--shadow-lg, 0 24px 64px rgb(0 0 0 / 0.45));
    padding: var(--space-6);
  }
</style>
