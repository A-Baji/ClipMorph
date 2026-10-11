<script>
  import Icon from './Icon.svelte';
  import { api } from '../lib/api.js';
  import {
    selectedJob,
    renameArtifact,
    deleteArtifact,
    requestConfirm,
    notify,
    report,
  } from '../lib/store.svelte.js';
  import { formatBytes } from '../lib/format.js';

  /** One artifact revision with preview/download and inline rename. */
  let { artifact } = $props();

  let editing = $state(false);
  let draftName = $state('');
  let menuOpen = $state(false);

  const jobId = $derived(selectedJob()?.job_id || '');
  const isSource = $derived(artifact.kind === 'source');

  function beginRename() {
    draftName = artifact.display_name || '';
    editing = true;
  }

  function commitRename() {
    const name = draftName.trim();
    editing = false;
    if (name && name !== artifact.display_name) renameArtifact(artifact, name);
  }

  function confirmDelete() {
    requestConfirm({
      title: 'Delete this artifact?',
      message: 'The local bytes are moved to trash. Upload history keeps its reference.',
      confirmLabel: 'Delete',
      danger: true,
      onConfirm: () => deleteArtifact(artifact),
    });
  }

  /** F21: reveal the artifact file in its OS folder via the localhost endpoint. */
  async function revealInFolder() {
    try {
      await api.openFolder(jobId, artifact.id);
      notify('Folder opened');
    } catch (error) {
      report(error);
    }
  }

  // F21: raw download keeps its home in the artifact row's menu (it is no
  // longer a bare row link). The popover closes on outside click (the fixed
  // backdrop), on Escape, and when the menu item is chosen.
  function toggleMenu() {
    menuOpen = !menuOpen;
  }
</script>

<div class="list-row">
  <span class="job-thumb"><Icon name={isSource ? 'video' : 'layers'} /></span>
  <div class="grow">
    {#if editing}
      <input
        class="artifact-name-input"
        aria-label="Artifact display name"
        value={draftName}
        oninput={(event) => (draftName = event.currentTarget.value)}
        onkeydown={(event) => {
          if (event.key === 'Enter') commitRename();
          if (event.key === 'Escape') editing = false;
        }}
      />
    {:else}
      <b class="artifact-label">
        <span class="truncate">{artifact.display_name || artifact.kind} · r{artifact.revision}</span>
      </b>
      <small>
        {artifact.state} · {artifact.kind}
        {#if artifact.bytes !== undefined} · {formatBytes(artifact.bytes)}{/if}
      </small>
    {/if}
  </div>

  {#if editing}
    <button class="btn btn-primary btn-sm" onclick={commitRename}>Save</button>
    <button class="btn btn-ghost btn-sm" onclick={() => (editing = false)}>Cancel</button>
  {:else}
    <a
      class="btn btn-ghost btn-sm"
      href={api.previewUrl(jobId, artifact.id)}
      target="_blank"
      rel="noreferrer"
    >Preview</a>
    <!-- F21: "Download" becomes "Open folder"; the raw download moves into the
         row's "more" menu. The localhost-only endpoint reveals the file. -->
    <button
      class="btn btn-ghost btn-sm"
      title="Reveal the artifact file in its folder"
      aria-label={`Open the folder of ${artifact.display_name || artifact.kind}`}
      onclick={revealInFolder}
    >
      Open folder
    </button>
    <div class="more">
      <button
        class="btn btn-ghost btn-icon"
        title="Artifact actions"
        aria-label="Artifact actions"
        aria-expanded={menuOpen}
        onclick={toggleMenu}
        onkeydown={(event) => {
          if (event.key === 'Escape') menuOpen = false;
        }}
      >
        <Icon name="more" />
      </button>
      {#if menuOpen}
        <button class="menu-backdrop" tabindex="-1" aria-hidden="true" onclick={() => (menuOpen = false)}></button>
        <div class="menu" role="menu" aria-label="Artifact actions">
          <a
            class="menu-item"
            role="menuitem"
            href={api.downloadUrl(jobId, artifact.id)}
            onclick={() => (menuOpen = false)}
          >
            <Icon name="download" size={14} /> Download
          </a>
        </div>
      {/if}
    </div>
    <button
      class="btn btn-ghost btn-icon"
      title="Rename artifact"
      aria-label="Rename artifact"
      onclick={beginRename}
    >
      <Icon name="pencil" />
    </button>
    {#if !isSource}
      <button
        class="btn btn-danger btn-icon"
        title="Delete artifact"
        aria-label="Delete artifact"
        onclick={confirmDelete}
      >
        <Icon name="trash" />
      </button>
    {/if}
  {/if}
</div>

<style>
  .artifact-name-input {
    padding: var(--space-1) var(--space-2);
  }

  /* U9: the shared one-line truncation for artifact names. */
  .artifact-label {
    display: flex;
    min-width: 0;
  }

  /* F21: the "more" menu holds the raw download. */
  .more {
    position: relative;
    display: inline-flex;
  }

  .more .menu-backdrop {
    position: fixed;
    inset: 0;
    z-index: 30;
    background: transparent;
    border: none;
    padding: 0;
  }

  .more .menu {
    position: absolute;
    right: 0;
    top: calc(100% + var(--space-1));
    z-index: 31;
    min-width: 9.5rem;
    padding: var(--space-1);
    background: var(--color-surface-raised);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
  }

  .menu-item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    text-decoration: none;
  }

  .menu-item:hover {
    background: var(--color-surface-hover);
    color: var(--color-text);
  }
</style>
