# ClipMorph dashboard design system — "Calm Slate"

This document is the design source of truth for the Svelte dashboard under
`frontend/`. It records the approved design system, the candidate set it was
chosen from, the information architecture (IA)/shell, and how each view maps
onto it. The token values themselves live in **one** place:
[`src/tokens.css`](src/tokens.css). Views and components reference semantic or
component tokens only; a hardcoded color, spacing, radius, or font in a view is
a bug.

Written for the full front-end rewrite in issue #248 (`dev`).

## Product law (why the UI looks the way it does)

The app is, at its core, an uploading tool. A user who does not care about deep
customization should be able to **select clips and upload**. Complexity emerges
only when a user deliberately goes deeper — clicking a job opens that job's
detail — and even a deep view is simplified to exactly what that view needs.
Every screen starts from "what is the one job of this view?". Cognitive load is
the enemy; the previous UI failed on *unintuitive*, *confusing*, and *tacky*.

## Process: three candidates, one approved

Per issue #248, 2–3 candidate systems were generated for a local prosumer video
tool, then one was chosen.

| Candidate | Direction | Palette | Type | Why it was / wasn't chosen |
| --- | --- | --- | --- | --- |
| **Calm Slate** *(approved)* | Calm, modern, dark working surface | Deep desaturated slate, one teal accent | Inter + JetBrains Mono | Reads as a professional tool, not a toy; one accent keeps focus on clips and status; dark surface is kind to long sessions and to video thumbnails. |
| Soft UI (light indigo) | Rounded, airy, light | Off-white + soft indigo, heavy radii/shadows | Inter | Friendly but low-contrast and soft for a status-heavy tool; large soft shadows reduce scannability of dense job/attempt tables. |
| Swiss monochrome | Editorial, high-contrast | Near-black on white, one red | Grotesk + mono | Striking and clean, but austere; no room for the semantic status colors a pipeline tool relies on, and light surfaces glare next to dark video. |

**Decision:** Calm Slate. It keeps the status-heavy views scannable, gives the
five platforms and six job states distinct-but-calm color, and stays visually
quiet so the clips are the loudest thing on screen. The design is **dark-only**
by deliberate choice — no light theme is maintained.

## Calm Slate

### Principles

1. **One job per view.** Each surface answers a single question and hides the rest behind `Advanced`/`details`.
2. **Depth is deliberate.** The default surface is the upload flow; job detail is exactly one click away.
3. **Calm over dense.** Hairline borders and generous spacing instead of boxes-in-boxes.
4. **Tokens or nothing.** Color, type, space, radius, motion all come from `tokens.css`.
5. **Status is legible.** State is shown with a small, consistent badge + dot language, never color alone.

### Color

Three-layer tokens: **primitive → semantic → component**. Views consume the
semantic/component layers.

- **Primitives** (`--slate-*`, `--teal-*`, status colors) are raw values.
- **Semantic** (`--color-bg`, `--color-surface`, `--color-text`, `--color-primary`, `--color-success`, …) name the *purpose*.
- **Component** (`--button-*`, `--input-*`, `--card-*`, `--nav-item-*`, `--focus-ring`) wire a control to semantics.

The palette is a deep slate ramp with a single teal accent and a small status
set:

| Role | Token | Value |
| --- | --- | --- |
| App background | `--color-bg` | `--slate-950` `#0b0f14` |
| Card surface | `--color-surface` | `--slate-900` `#10151c` |
| Raised surface | `--color-surface-raised` | `--slate-850` `#151b24` |
| Hover / active surface | `--color-surface-hover` | `--slate-800` `#1b232e` |
| Border | `--color-border` | `rgba(231,236,242,0.10)` |
| Text | `--color-text` | `--slate-100` `#e7ecf2` |
| Muted text | `--color-text-muted` | `--slate-300` `#93a2b5` |
| Faint text | `--color-text-faint` | `--slate-350` `#7c8da3` |
| Accent / primary | `--color-primary` | `--teal-400` `#2dd4bf` |
| Success | `--color-success` | `--green-400` `#4ade80` |
| Warning | `--color-warning` | `--amber-400` `#f5b856` |
| Danger | `--color-danger` | `--red-400` `#f87171` |
| Info | `--color-info` | `--blue-400` `#60a5fa` |

`--slate-350` exists specifically so faint text (hints, timestamps,
placeholders) clears WCAG AA on card surfaces; `--slate-400` remains for
non-text uses such as status dots.

### Typography

- **UI:** Inter (400/500/600/700), falling back to the system stack.
- **Machine values:** JetBrains Mono (400/500) via `.mono` for ids, hashes, byte sizes, timestamps, JSON and numeric table cells.
- Scale: `--text-2xs` 11px … `--text-3xl` 30px; body `--text-base` 14px.

### Spacing, radii, elevation, motion

- Spacing is a 4px-based scale `--space-1`(4) … `--space-12`(48).
- Radii: `--radius-sm` 6 → `--radius-full` 999; cards use `--radius-lg`, controls `--radius-md`.
- Two shadows only: `--shadow-sm` (controls) and `--shadow-md` (overlays).
- Motion: `--duration-fast` 140ms / `--duration-base` 200ms with `--ease-standard`; disabled under `prefers-reduced-motion: reduce`.

## IA / shell

The shell is a persistent **sidebar** (workspace nav) + **main** column with a
per-view topbar. Navigation is deliberately shallow:

```
Queue  ← default surface: select clips → upload; the job list is on the same page
  └─ Job detail (opened by clicking a job card; not a nav item)
       Overview · Review · Publish · Metrics
Metrics
Layouts
Settings
```

- **Default surface = the upload flow.** The old separate "New Job" page is folded into the top of **Queue**: pick clips (or upload a file), optionally add a title/tags/description and pick platforms, then *Create & upload*. Everything else sits in a collapsed **Advanced options** disclosure.
- **Queue** shows the upload form and the job list side by side (stacked under ~980px). A status filter keeps the list scannable.
- **Job detail is exactly one deliberate step:** click a job card → detail opens at **Overview**, with four tabs. It shows only that job: pipeline checkpoints, per-platform status, artifacts, transcript/composition review, upload draft/suggestions/attempts, and engagement.
- **Settings** and **Layouts** are scannable in one glance; advanced knobs (global job defaults, crop/sizing) are collapsed in `details` by default.
- Below ~860px the sidebar becomes an off-canvas drawer behind a menu button; the drawer keeps `aria-label="Primary navigation"` so the model is unchanged on mobile.

## Per-view implementation

| View | One job | Key surface |
| --- | --- | --- |
| **Queue** | Select clips and upload | Upload-a-clip input; source list with per-source overrides; shared title/tags/description; platform chips; collapsed advanced options; *Validate* or *Create & upload*; status-filtered job list. |
| **Job detail · Overview** | Where is this job? | Checkpoint rows (transcript/conversion/upload) with accept/retry, per-platform participation + latest result, artifact list with preview/download/rename/delete. Header carries Resume/Cancel/Delete (confirmed). |
| **Job detail · Review** | Fix the transcript and composition | Segment editors (timing, text, collapsed typography) + *Save transcript revision* / *Accept transcript*; job layout JSON + save/render/accept. |
| **Job detail · Publish** | Get it out the door | Upload draft (title/description/tags/schedule/platforms), per-platform summary, AI suggestions (generate/regenerate/apply all/clear/edit), append-only attempt history with status/platform/since filters and retry. |
| **Job detail · Metrics** | How is it doing? | First→latest per post, delta vs first snapshot, *Pull fresh data*, link to the post. |
| **Metrics** | Compare across jobs | Cross-job table with platform filter and deltas. |
| **Layouts** | Manage presets | Short preset form (name, renderer, placement, caption) with collapsed crop/sizing; saved-preset list with delete (confirmed). |
| **Settings** | Configure the workspace | Source/output paths; credential status + probe; collapsed global job defaults. |

## Accessibility & responsiveness

- **WCAG AA contrast** for text and UI on the surfaces they appear on. Representative pairs (measured against the actual tokens):

  | Foreground | Background | Ratio |
  | --- | --- | --- |
  | `--color-text` | `--color-bg` | ≈16.3:1 |
  | `--color-text-muted` | `--color-surface` | ≈7.2:1 |
  | `--color-text-faint` | `--color-surface` | ≈5.5:1 |
  | `--color-primary` | `--color-bg` | ≈10.4:1 |
  | `--color-danger` | `--color-bg` | ≈7.0:1 |
  | `--color-on-primary` | `--color-primary` | ≈10.4:1 |

- **Keyboard-navigable:** native `button`/`input`/`select`/`a` controls, tabs use `role="tab"` with `aria-selected`, nav uses a labelled landmark, and `:focus-visible` paints a two-ring token focus (`--focus-ring`) that is never removed.
- **Status is not color-only:** every state also carries text.
- **Responsive to ~360px:** `body { min-width: 320px }`; grids collapse to one column, the sidebar becomes a drawer, and filter rows stack.
- **Reduced motion** disables transitions/animations.

## Capability parity

No capability reachable in the old `App.svelte` is missing. Job create/validate
(single + bulk) with per-source overrides, upload source, job resume/cancel/
delete, checkpoint accept (+ retry), render, transcript get/save, composition
patch, upload-draft get/save, suggestions (generate/accept/accept-all/clear/edit/
save-edits), submit/retry upload with status/platform/since filters, artifacts
preview/download/rename/delete, metrics get/pull/compare, layouts create/delete,
settings save, credential probe, and the live upload-progress event stream are
all reachable. The rewrite adds checkpoint retry and a consistent confirm
dialog, and invents no API routes.
