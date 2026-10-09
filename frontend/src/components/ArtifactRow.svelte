<script>
  import Icon from './Icon.svelte';
  import { api } from '../lib/api.js';
  import {
    selectedJob,
    renameArtifact,
    deleteArtifact,
    requestConfirm,
  } from '../lib/store.svelte.js';
  import { formatBytes } from '../lib/format.js';

  /** One artifact revision with preview/download and inline rename. */
  let { artifact } = $props();

  let editing = $state(false);
  let draftName = $state('');

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
      <b>{artifact.display_name || artifact.kind} · r{artifact.revision}</b>
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
    <a class="btn btn-ghost btn-sm" href={api.downloadUrl(jobId, artifact.id)}>Download</a>
    <button class="btn btn-ghost btn-icon" aria-label="Rename artifact" onclick={beginRename}>
      <Icon name="pencil" />
    </button>
    {#if !isSource}
      <button class="btn btn-danger btn-icon" aria-label="Delete artifact" onclick={confirmDelete}>
        <Icon name="trash" />
      </button>
    {/if}
  {/if}
</div>

<style>
  .artifact-name-input {
    padding: var(--space-1) var(--space-2);
  }
</style>
