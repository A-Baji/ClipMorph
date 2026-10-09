<script>
  import Card from '../components/Card.svelte';
  import Field from '../components/Field.svelte';
  import Icon from '../components/Icon.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import { app, createLayout, deleteLayout, requestConfirm } from '../lib/store.svelte.js';

  /** Reusable conversion presets. The core form is short; geometry is advanced. */
  let form = $state({
    name: 'Vertical highlight',
    crop: false,
    crop_x: 0,
    crop_y: 0,
    crop_width: 320,
    crop_height: 240,
    sizing: 'fit',
    composition: 'overlay',
    placement: 'top',
    renderer: 'overlay',
    caption: true,
    caption_text: '',
  });

  function buildLayout() {
    const layout = {};
    if (form.crop) {
      layout.crop = {
        enabled: true,
        source: {
          x: Number(form.crop_x),
          y: Number(form.crop_y),
          width: Number(form.crop_width),
          height: Number(form.crop_height),
        },
        sizing: {
          mode: form.sizing,
          ...(form.sizing === 'native' ? {} : { dimensions: { width: 640, height: 360 } }),
        },
        composition: { mode: form.composition, placement: form.placement },
      };
    }
    const item = { text: form.caption_text || 'ClipMorph' };
    layout.captions =
      form.renderer === 'overlay'
        ? { overlay: { items: form.caption ? [{ ...item, placement: 'center' }] : [] } }
        : {
            stacked: {
              placement: form.placement,
              panel: { color: 'black' },
              padding: { left: 32, top: 20 },
              items: form.caption ? [item] : [],
            },
          };
    return layout;
  }

  function save() {
    createLayout(form.name, buildLayout());
  }

  function confirmDelete(layout) {
    requestConfirm({
      title: 'Delete this layout?',
      message: 'Jobs already created keep their materialized layout; only the preset is removed.',
      confirmLabel: 'Delete layout',
      danger: true,
      onConfirm: () => deleteLayout(layout.id),
    });
  }
</script>

<div class="content">
  <div class="section-head">
    <div>
      <h2>Layouts</h2>
      <p>Reusable conversion presets you can attach to any job.</p>
    </div>
    <button class="btn btn-primary" onclick={save}>Save layout</button>
  </div>

  <div class="columns">
    <Card title="New preset">
      <div class="stack">
        <Field label="Preset name">
          <input bind:value={form.name} />
        </Field>
        <Field label="Caption renderer">
          <select bind:value={form.renderer}>
            <option value="overlay">Overlay</option>
            <option value="stacked">Stacked</option>
          </select>
        </Field>
        <Field label="Placement">
          <select bind:value={form.placement}>
            <option value="top">Top</option>
            <option value="center">Center</option>
            <option value="bottom">Bottom</option>
          </select>
        </Field>
        <label class="check">
          <input type="checkbox" bind:checked={form.caption} /> Add a caption item
        </label>
        {#if form.caption}
          <Field label="Caption text">
            <input bind:value={form.caption_text} placeholder="ClipMorph" />
          </Field>
        {/if}

        <details class="advanced">
          <summary>Source crop &amp; sizing</summary>
          <div class="advanced-body">
            <label class="check">
              <input type="checkbox" bind:checked={form.crop} /> Enable source crop
            </label>
            {#if form.crop}
              <div class="grid-2">
                <Field label="X"><input type="number" min="0" bind:value={form.crop_x} /></Field>
                <Field label="Y"><input type="number" min="0" bind:value={form.crop_y} /></Field>
                <Field label="Width"><input type="number" min="0" bind:value={form.crop_width} /></Field>
                <Field label="Height"><input type="number" min="0" bind:value={form.crop_height} /></Field>
              </div>
              <div class="grid-2">
                <Field label="Sizing">
                  <select bind:value={form.sizing}>
                    <option value="fit">Fit</option>
                    <option value="stretch">Stretch</option>
                    <option value="native">Native</option>
                  </select>
                </Field>
                <Field label="Composition">
                  <select bind:value={form.composition}>
                    <option value="overlay">Overlay</option>
                    <option value="stacked">Stacked</option>
                  </select>
                </Field>
              </div>
            {/if}
          </div>
        </details>
      </div>
    </Card>

    <Card title="Saved presets">
      {#if app.layouts.length}
        <div class="layout-list">
          {#each app.layouts as layout (layout.id)}
            <div class="list-row">
              <span class="job-thumb"><Icon name="layers" /></span>
              <div class="grow">
                <b>{layout.name}</b>
                <small>{layout.id}</small>
              </div>
              <button
                class="btn btn-danger btn-icon"
                aria-label="Delete layout"
                onclick={() => confirmDelete(layout)}
              ><Icon name="trash" /></button>
            </div>
          {/each}
        </div>
      {:else}
        <EmptyState
          icon="layers"
          title="No presets yet"
          message="Save your first layout and it becomes available when creating a job."
        />
      {/if}
    </Card>
  </div>
</div>

<style>
  .columns {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--space-8);
    align-items: start;
  }

  @media (max-width: 860px) {
    .columns {
      grid-template-columns: 1fr;
    }
  }
</style>
