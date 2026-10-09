<script>
  import Badge from './Badge.svelte';
  import { app, editSuggestion, acceptSuggestion, saveSuggestionEdits } from '../lib/store.svelte.js';

  /** Editable AI suggestion row for one platform. */
  let { row } = $props();

  const platform = $derived(row.platform);
  const edit = $derived(app.publish.suggestionEdits[platform]);
  const title = $derived(edit?.title ?? row.title ?? '');
  const description = $derived(edit?.description ?? row.description ?? '');
  const hashtags = $derived(edit?.hashtags ?? (row.hashtags || []).join(', '));
</script>

<div class="suggestion">
  <div class="suggestion-head">
    <b>{platform}</b>
    <Badge tone="primary">{row.provider}{row.model ? ` · ${row.model}` : ''}</Badge>
  </div>
  {#if row.note}<small class="faint">{row.note}</small>{/if}

  <label class="field">
    <span>Title</span>
    <input
      aria-label="{platform} suggestion title"
      value={title}
      oninput={(event) => editSuggestion(row, 'title', event.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span>Description</span>
    <textarea
      aria-label="{platform} suggestion description"
      rows="2"
      value={description}
      oninput={(event) => editSuggestion(row, 'description', event.currentTarget.value)}
    ></textarea>
  </label>
  <label class="field">
    <span>Hashtags</span>
    <input
      aria-label="{platform} suggestion hashtags"
      value={hashtags}
      oninput={(event) => editSuggestion(row, 'hashtags', event.currentTarget.value)}
    />
  </label>

  <div class="row">
    <button class="btn btn-secondary btn-sm" onclick={() => saveSuggestionEdits(platform)}>Save edits</button>
    <button class="btn btn-primary btn-sm" onclick={() => acceptSuggestion(platform)}>Apply</button>
  </div>
</div>
