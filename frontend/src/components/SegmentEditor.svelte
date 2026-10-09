<script>
  import { updateSegment, updateSegmentTypography } from '../lib/store.svelte.js';

  /** One transcript segment: timing, text, and collapsed text styling. */
  let { segment, index } = $props();

  const n = $derived(index + 1);
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
          <input
            aria-label="Segment {n} font size"
            type="number"
            min="1"
            value={segment.typography?.size ?? ''}
            oninput={(event) => updateSegmentTypography(segment, 'size', event.currentTarget.value)}
          />
        </label>
        <label class="field">
          <span>Color</span>
          <input
            aria-label="Segment {n} color"
            value={segment.typography?.color ?? ''}
            placeholder="Automatic"
            oninput={(event) => updateSegmentTypography(segment, 'color', event.currentTarget.value)}
          />
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
