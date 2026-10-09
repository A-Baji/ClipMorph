<script>
  /**
   * Inline stroke icon (Lucide-style paths). Vector only; never an emoji.
   * Decorative by default; pass ``label`` to expose an accessible name.
   */
  let { name, size = 18, label = '', stroke = 1.75 } = $props();

  const paths = {
    upload: ['M12 15V3', 'M7 8l5-5 5 5', 'M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2'],
    queue: ['M22 12h-6l-2 3h-4l-2-3H2', 'M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z'],
    layers: ['m12 3 9 5-9 5-9-5 9-5z', 'm3 13 9 5 9-5'],
    sliders: ['M4 21v-7', 'M4 10V3', 'M12 21v-9', 'M12 8V3', 'M20 21v-5', 'M20 12V3', 'M1 14h6', 'M9 8h6', 'M17 16h6'],
    chart: ['M3 3v18h18', 'M18 17V9', 'M13 17V5', 'M8 17v-3'],
    plus: ['M12 5v14', 'M5 12h14'],
    check: ['M20 6 9 17l-5-5'],
    x: ['M18 6 6 18', 'M6 6l12 12'],
    trash: ['M3 6h18', 'M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2', 'M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6', 'M10 11v6', 'M14 11v6'],
    pencil: ['M17 3a2.83 2.83 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5Z'],
    refresh: ['M3 12a9 9 0 0 1 15-6.7L21 8', 'M21 3v5h-5', 'M21 12a9 9 0 0 1-15 6.7L3 16', 'M3 21v-5h5'],
    play: ['m6 3 14 9-14 9V3z'],
    external: ['M15 3h6v6', 'M10 14 21 3', 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'],
    chevronDown: ['m6 9 6 6 6-6'],
    chevronRight: ['m9 18 6-6-6-6'],
    arrowLeft: ['M19 12H5', 'm12 19-7-7 7-7'],
    alert: ['M12 9v4', 'M12 17h.01', 'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'],
    sparkles: ['M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z', 'M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z'],
    calendar: ['M8 2v4', 'M16 2v4', 'M3 10h18', 'M3 6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'],
    download: ['M12 3v12', 'm7 10 5 5 5-5', 'M5 21h14'],
    eye: ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z', 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z'],
    video: ['m22 8-6 4 6 4V8z', 'M2 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z'],
    menu: ['M3 6h18', 'M3 12h18', 'M3 18h18'],
    dot: ['M12 12h.01'],
  };
</script>

<svg
  class="icon"
  style="width:{size}px;height:{size}px"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={stroke}
  stroke-linecap="round"
  stroke-linejoin="round"
  role={label ? 'img' : undefined}
  aria-hidden={label ? undefined : 'true'}
>
  {#if label}<title>{label}</title>{/if}
  {#each paths[name] || paths.dot as d}
    <path {d} />
  {/each}
</svg>
