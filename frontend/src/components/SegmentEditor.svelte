<script>
  import { updateSegment, updateSegmentTypography } from '../lib/store.svelte.js';

  /** One transcript segment: timing, text, and collapsed text styling. */
  let { segment, index } = $props();

  const n = $derived(index + 1);

  /** Issue #261 item 15: caption color is a bounded palette, not free text.
      "" = Automatic: the renderer falls back to the caption-scale default. */
  const COLORS = [
    'white', 'black', 'yellow', 'orange', 'red',
    'pink', 'purple', 'blue', 'cyan', 'green', 'gray',
  ];
</script>

<div class="segment">
  <div class="segment-head">
    <span class="eyebrow">Segment {n}</span>
    <span class="mono">{segment.start}s → {segment.end}s</span>
  </div>

  <div class="segment-times">
    <label class="field">
      <span>Start</span>
      <input
        aria-label="Segment {n} start time"
        type="number"
        min="0"
        step="0.01"
        value={segment.start}
        oninput={(event) => updateSegment(segment, 'start', Number(event.currentTarget.value))}
      />
    </label>
    <label class="field">
      <span>End</span>
      <input
        aria-label="Segment {n} end time"
        type="number"
        min="0"
        step="0.01"
        value={segment.end}
        oninput={(event) => updateSegment(segment, 'end', Number(event.currentTarget.value))}
      />
    </label>
  </div>

  <label class="field">
    <span>Transcript</span>
    <textarea
      aria-label="Transcript segment {n}"
      value={segment.text}
      oninput={(event) => updateSegment(segment, 'text', event.currentTarget.value)}
    ></textarea>
  </label>

  <details class="advanced segment-typography">
    <summary>Text styling</summary>
    <div class="advanced-body">
      <div class="grid-2">
        <label class="field">
          <span>Font size</span>
          <!-- Issue #261 item 14: the field's default is the caption-scale
               size (64); the placeholder shows it, an explicit value
               overrides it, and clearing it returns to Automatic. -->
          <input
            aria-label="Segment {n} font size"
            type="number"
            min="1"
            placeholder="64"
            title="Captions render at the default size (64) until a value is set here"
            value={segment.typography?.size ?? ''}
            oninput={(event) => updateSegmentTypography(segment, 'size', event.currentTarget.value)}
          />
        </label>
        <label class="field">
          <span>Color</span>
          <!-- Issue #261 item 15: a dropdown over the named palette; a
               transcript revision value outside the palette still shows. -->
          <select
            aria-label="Segment {n} color"
            value={segment.typography?.color ?? ''}
            onchange={(event) => updateSegmentTypography(segment, 'color', event.currentTarget.value)}
          >
            <option value="">Automatic</option>
            {#each COLORS as color (color)}
              <option value={color}>{color}</option>
            {/each}
            {#if segment.typography?.color && !COLORS.includes(segment.typography.color)}
              <option value={segment.typography.color}>{segment.typography.color}</option>
            {/if}
          </select>
        </label>
      </div>
      <div class="row">
        {#each ['bold', 'italic', 'underline'] as style (style)}
          <label class="check">
            <input
              aria-label="Segment {n} {style}"
              type="checkbox"
              checked={Boolean(segment.typography?.[style])}
              onchange={(event) => updateSegmentTypography(segment, style, event.currentTarget.checked)}
            />
            {style}
          </label>
        {/each}
      </div>
    </div>
  </details>
</div>
