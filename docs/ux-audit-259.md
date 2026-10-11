# UX audit #259 — Phase 0 (before-state, committed)

Phase 0 of issue #259: a defect-class sweep across every reachable dashboard
surface, recorded against the *before* state of `dev` at commit `29fe226`
(audit-only change; `frontend/src/**` and `clipmorph/**` were not touched).
Phase 1–2 implement the approved A–F items; Phase 3 re-runs this sweep and
pairs every committed before-shot below with an after-shot.

This audit never overrides an approved A–F decision. Surfaces mandated by the
issue (the empty-Completed prompt, the four-column board, etc.) are recorded as
specified under the matching A–F item, not as findings.

## Evidence

Full sweep run (30 PNGs, three viewports × state surfaces, all fixtures):
`C:\Users\bidab\AppData\Local\Temp\ux259-before\` — cited below by filename.
The run is uncommitted; Phase 3 diff-pairs against it, and per issue 0.4 the
full run should be uploaded as a CI artifact. It is reproducible with the
committed tool:

```text
python tests/e2e/capture.py --out <dir> --label before
```

Only the ten PNGs that back a finding or an A–F before-record are committed
under [docs/ux-audit-259/evidence/](ux-audit-259/evidence/); every row of the tables below
links to its copy there. DOM/keyboard checks were driven separately (numbers
inline in this document), and add two supplemental desktop captures from the
same commit (`before-modal-review-tab-desktop.png`,
`before-modal-publish-desktop.png`) that the sweep script did not produce.

## Defect-class sweep (issue 0.3)

| Defect class | Result | Findings |
| --- | --- | --- |
| Terminology drift | 3 findings | U1, U2, U3 (+ approved A1 before-record) |
| Structure disappears when empty | finding: approved B2 only | (recorded under B2) |
| Dead space / double scrollbars | 3 findings | U4, U5, U6 (+ approved B3 before-state) |
| Redundant or leaked states | 2 findings | U7, U8 |
| Disorganized composition / spacing | 2 findings | U9 (+ approved C4, E11 before-states) |
| Missing visual context | approved C5 only | (recorded under C5) |
| Form affordances and control types | approved D6/D7 | (recorded under D6/D7; no extra defect class instance) |
| Progressive disclosure | 2 findings | U10, U11 (+ approved D8/D9 before-states) |
| Master/detail navigation | approved D10 only | (recorded under D10) |
| Post-action behavior | 1 finding | U12 |
| Button hierarchy | 3 findings | U13, U14 (+ approved E16) |
| Raw data shown to users | 3 findings | U15, U16, U17 (+ approved E22, F15) |
| Baseline a11y and feedback | 2 findings | U18, U19 (see keyboard section for PASS evidence) |

PASS results worth recording: token-based WCAG AA contrast is reachable everywhere
sampled — computed at commit `29fe226` from `tokens.css`: body text on
surface 15.4:1, muted 7.1:1, faint 5.4:1, primary-button text on the teal
accent 7.7:1, danger 6.6:1, warning 10.4:1 (all ≥ 4.5:1). Destructive actions
(Cancel/Delete/Reset) gate through the shared `ConfirmDialog`. Status is never
color-only. `:focus-visible` produces a visible two-ring outline everywhere.

## Keyboard + a11y findings (issue 0.2.3, Playwright DOM checks)

Keyboard-only behavior was driven at the desktop and laptop viewports against
the `states` fixture. Recorded facts:

- **U18 (P1, a11y + dead class): modal focus is not trapped and the background
  scroll lock is missing.** With the job-detail modal open, page scrollHeight
  stays at 3215 px (client 1080/768) — the board behind keeps scrolling while
  the modal (`overflow-y: auto`), whose own content is 1056 px tall, scrolls
  independently: two scroll systems live at once. `inert` count on `<body>` is
  0 and Tab escapes the modal after the header buttons, landing on background
  board cards and column headers (`Tab` sequence recorded: modal header →
  board cards → `Scheduled 1` → card actions → `Completed 3`). Esc does close
  the modal; Enter performs no default action. Evidence:
  [before-modal-review-small.png](ux-audit-259/evidence/before-modal-review-small.png)
  (weak scrim, background content bleeding behind the modal). **Triage: Fix
  here** — JobDetailModal + one scroll-lock/trap on open, two components.
- **U19 (P3, a11y): icon-only buttons have accessible names but no tooltip.**
  Zero icon-only buttons failed the accessible-name scan (run at all three
  viewports). No `title` attribute is set on any of them (e.g.
  `ArtifactRow.svelte:77-81`, `JobDetailView.svelte:143`), so the required
  *tooltip* half of "name + tooltip" is unequipped system-wide. The values
  mandated by C4 (card quick actions) and F21 (artifact row icons) are covered
  by their approved items; the remaining strays (modal back arrow, error
  dismiss) belong to a finishing pass. **Triage: Follow-up issue** (app-wide
  tooltip pass; several components)
- PASS: icon-button accessible names (0 unnamed at all viewports);
  `:focus-visible` ring visible (`styles.css:57`, computed `box-shadow`
  two-ring 2px bg + 4px teal); the dialog is `role="dialog" aria-modal="true"`;
  destructive confirms route through `ConfirmDialog` (`aria-labelledby`).

## Findings registry (sweep defects not already governed by A–F)

Severity P1 blocks orientation/data correctness, P2 is significant usability,
P3 is polish.

- **U1 (P2, terminology): wizard back-link copy drifts between steps.** Step 1
  says "Back to queue"; step 2 says "Back to Clips" (capitalized differently,
  referencing a different object). Repro: wizard → clips step header vs
  configure step header. Evidence:
  [before-wizard-configure-desktop.png](ux-audit-259/evidence/before-wizard-configure-desktop.png).
  **Triage: Fix here** — WizardView single label (rides the A1 copy pass).
- **U2 (P2, terminology): "New batch" copy entry is dead and conflicting.**
  `App.svelte:22-24` carries `PAGE.wizard = { title: 'New batch', subtitle:
  'Pick clips, then configure…' }`, but the wizard branch (`app.view ===
  'wizard'`) never renders the Topbar, so the string ships unreferenced while
  the wizard header shows nothing named "batch". Repro: grep + visuals.
  **Triage: Fix here** — delete or fold into the A1 rename (one file).
- **U3 (P2, terminology — maintainer decision): every non-wizard view renders
  two page headers with divergent copy.** Topbar title+subtitle ("Settings /
  Workspace paths, credentials, and defaults.") is immediately followed by the
  view's own h2+subtitle ("Settings / Workspace paths, credentials, and the
  defaults every new job starts from."), on Queue, Metrics, Layouts and
  Settings alike. Fixing = picking which header survives on each view — an IA
  question. Evidence:
  [before-settings-desktop.png](ux-audit-259/evidence/before-settings-desktop.png)
  (Settings; Queue and Metrics are identical in pattern — full-run
  `before-metrics-desktop.png`, `before-board-states-desktop.png`).
  **Triage: Maintainer decision** (copy meaning / IA; list under "Open
  questions"; do not ship with the numbered items).
- **U4 (P2, dead space): the board columns are fixed at 180 px so the content
  area strands 460–540 px of empty background at wide viewports.** Measured at
  1920×1080: `.column` computed `width/minWidth: 180px, maxWidth: none`; six
  180px columns ≈ 1147 px inside a ~1656 px main area; the dead band is
  visible in every full-width capture. This is exactly B3's board half (the
  columns never share the full width), and B3 is the approved fix — recorded
  there. The *residual* defect beyond the board: the whole shell caps its
  content around 1116 px (Settings, Metrics and Layouts span the same
  263→1380 band at 1920), leaving the asymmetric right void on every view.
  Evidence:
  [before-board-states-laptop.png](ux-audit-259/evidence/before-board-states-laptop.png)
  (at 1366×768 the Failed column is half clipped by the same cap),
  [before-settings-desktop.png](ux-audit-259/evidence/before-settings-desktop.png).
  **Triage: Fix here** — one styles.css width rule, no state, same class as
  B3.
- **U5 (P2, dead space, covered by U18's modal fix):** the modal itself is
  inset with a near-invisible scrim; background content is readable through
  the top band (see
  [before-modal-review-small.png](ux-audit-259/evidence/before-modal-review-small.png)).
  Same root cause as U18's scroll/trap work. **Triage: Fix here** (with U18).
- **U6 (P3, dead space): the modal wastes its right half on desktop** — on the
  Review tab the Composition card ends at ~62% of modal width; Overview's
  Platform card likewise; nothing explains the void. Evidence:
  [before-modal-review-tab-desktop.png](ux-audit-259/evidence/before-modal-review-tab-desktop.png).
  **Triage: Follow-up issue** (modal width utilization; polish).
- **U7 (P2, redundant states): Overview pipeline rows repeat each checkpoint's
  status twice** — the row's muted subtext and the right-hand badge print the
  same value ("Transcript / awaiting review" + `awaiting review` badge;
  Conversion + `pending` ×2; Upload + `pending` ×2). Evidence:
  [before-modal-review-desktop.png](ux-audit-259/evidence/before-modal-review-desktop.png).
  **Triage: Fix here** — JobDetailView pipeline row render (one component).
- **U8 (P3, redundant copy): the sidebar badge zero-pads to two digits** —
  `Sidebar.svelte:36` `padStart(2, '0')` renders an empty workspace's count as
  "00" (visible in
  [before-board-empty-desktop.png](ux-audit-259/evidence/before-board-empty-desktop.png)).
  The same component is renamed in B20 anyway. **Triage: Fix here** (with
  B20's sidebar rename).
- **U9 (P3, composition): unbounded wrapping for long titles/filenames
  outside the card fix.** At column width 180 px the fixture's long title
  reflows to 3+ lines and the hyphenated filename to many more (no
  `text-overflow`/ellipsis anywhere on card text; computed
  `white-space: normal, word-break/overflow-wrap: normal`). C4 specifies
  single-line truncation for *cards*; unchanged surfaces are the artifact row
  and modal header (the full ~120-char filename renders untruncated in
  [before-modal-review-desktop.png](ux-audit-259/evidence/before-modal-review-desktop.png)).
  **Triage: Follow-up issue** (shared truncation utility for modal/artifact
  surfaces; >2 components).
- **U10 (P2, progressive disclosure): generated form sections render flat
  fieldsets** — General/Conversion/Subtitles/Upload print as non-collapsible
  `<fieldset>` blocks in the batch pane (D8's collapsible "Platform" grouping
  is the approved fix for platform subtrees; the top-level sections'
  flatness is not). Evidence:
  [before-wizard-configure-desktop.png](ux-audit-259/evidence/before-wizard-configure-desktop.png).
  **Triage: Fix here** — ConfigForm section-collapsible wrapper that D8 needs
  anyway; the batch-level sections reuse the same node.
- **U11 (P3, progressive disclosure): per-platform config in the batch block
  renders with no grouping node at all** — WizardView F2 renders
  `spec.platforms.sections` as sibling fieldsets with no "Platform"
  container grouping them.
  Covered by the D8 build; recorded under D8. No separate triage.
- **U12 (P3, post-action behavior): the Cancel confirmation copy overstates
  the action's scope.** The confirm dialog promises a board-level sweep
  (`'Queued and running work is aborted. Scheduled attempts are cancelled.'`,
  QueueView:74 / JobDetailView:110) although a job card's Cancel aborts one
  job. Repro: Cancel on a single card. **Triage: Fix here** —
  scope-accurate copy for the card action (one component, rides with the
  copy pass).
- **U13 (P2, button hierarchy): mixed affordances within one action row.**
  Board cards pair text-link buttons ("Run", "Cancel") with a lone icon
  button (trash) at unrelated sizes/
  heights ([before-board-states-desktop.png](ux-audit-259/evidence/before-board-states-desktop.png));
  artifact rows pair text links ("Preview", "Download") with pencil and trash
  icons ([before-modal-review-desktop.png](ux-audit-259/evidence/before-modal-review-desktop.png)).
  C4 fixes the card row and F21 the artifact row. The class instance outside
  those rows: "Probe" credential buttons render as naked text links while the
  app uses ghost/primary buttons elsewhere. **Triage: Fix here** (Settings
  Probe → ghost button; one component) — card/artifact rows are C4/F21, not
  this audit's.
- **U14 (P3, button hierarchy): gate-accept styling is not uniform.** In
  [before-modal-review-tab-desktop.png](ux-audit-259/evidence/before-modal-review-tab-desktop.png),
  "Accept transcript" is a filled teal primary while "Accept composition" is a
  muted secondary button (confounded: it is disabled in this state).
  E16 is the approved fix and its Phase 3 computed-style assertion covers
  this; recorded under E16.
- **U15 (P2, raw data): board-card status checkpoints show raw enum keys.**
  Chips print un-humanized `awaiting_review`, `created`, `pending`,
  `conversion`, `upload` while the same keys render humanized elsewhere
  ("Awaiting review" column header, "partial failure" on some card chips).
  The humanizer exists (`format.js:97`) and is simply not applied on card
  chips. Evidence:
  [before-board-states-desktop.png](ux-audit-259/evidence/before-board-states-desktop.png)
  (Queued column chips), full-run `before-board-large-desktop.png`.
  **Triage: Fix here** — QueueView card chip render (one component).
- **U16 (P2, raw data): Upload-history rows fall back to the raw attempt id**
  (`AttemptRow.svelte:20` prints `attempt.attempt_id` when no snapshot title
  exists). Same defect family as F15's raw hash evidence. **Triage: Fix
  here** — AttemptRow fallback label (one component; e.g. localized time +
  platform instead of an id).
- **U17 (P3, raw-data endpoint sweep PASS):** beyond the approved E22/F15
  leaks above and the two findings U15/U16, the grep pass found no further
  user-visible raw JSON, hashes, ISO stamps or absolute paths at 29fe226 (the
  two `JSON.stringify` calls in store.svelte.js persist the wizard draft, they
  do not render). Timestamps localize everywhere ("Oct 10, 2026, 02:54 PM").
  Counted as PASS for the class outside the recorded items.
- **U18** see keyboard section above (modal trap/scroll; Fix here).
- **U19** see keyboard section above (tooltip pass; Follow-up issue).

## Copy pass (issue 0.2.4) — terminology variants observed

One variant list for the same object, by surface:

- Topbar / document flow title: **"Your edit queue"** (App.svelte:18) —
  superseded by A1's "Your Clip Queue"; also used as the *default* fallback
  subtitle for unknown views.
- Queue board page heading: **"Queue"** h2 (QueueView.svelte:101) with its own
  subtitle "Every job by pipeline status. Click a card for its full detail."
- Sidebar item: **"Queue"** (Sidebar.svelte:9) with WIP count — renamed to
  "Jobs" by B20.
- Empty state heading: **"Your queue is empty"** / sub "Create your first job
  to see it move across the board." (QueueView.svelte:117) — replaced by B2.
- Wizard step 1 header link: **"Back to queue"**; step 2: **"Back to Clips"**
  (U1).
- Wizard rail label: **"Jobs"** (WizardView.svelte:202) for the same
  object the sidebar calls Queue and the board calls Queue (folded into B20's
  vocabulary).
- Unused Topbar entry: **"New batch"** (App.svelte:22, never rendered — U2).
- Artifact/platform vocabulary on Layouts: "Save layout" button vs
  "New preset"/"Saved presets" cards vs "layout preset" field elsewhere —
  layout/preset mixed (P3, noted; no item governs it; fold into the copy
  pass).
- Status strings: humanized in headers ("Awaiting review", "partial failure"),
  raw on card chips ("awaiting_review", "created") — U15.
- Board-page subtitle "Select clips and upload — everything else has a
  sensible default." (App.svelte:19) describes the wizard's job while sitting
  above the board; the board's own subtitle says something different (fact
  sheet for the double-header decision U3).

## Code pass (issue 0.2.5) — raw-data leaks in templates

Greps over `frontend/src/**` at 29fe226:

1. `JobDetailView.svelte:69` — `JSON.stringify(job.configuration?.conversion?
   .layout …)` rendered as the "Job layout JSON" textarea (E22's approved
   leak; visible in
   [evidence](ux-audit-259/evidence/before-modal-review-tab-desktop.png)).
2. `JobDetailView.svelte:373` — `· group {summary.group_id}` prints the raw
   12-hex group id in the per-platform summary (F15's approved leak; captured
   in [evidence](ux-audit-259/evidence/before-modal-publish-desktop.png), every platform
   row).
3. `ConfigForm.svelte:49` — object/array values stringified into the field
   value (the "Inline layout" free-text object field; removed by D7).
4. `AttemptRow.svelte:20` — raw `attempt_id` fallback (U16).
5. `Sidebar.svelte:36` — cosmetically padded count (U8).
6. `format.js:55/70` — timestamps localize through `toLocaleString` (page
   renders "Oct 10, 2026, 02:54 PM"): PASS, no ISO leaks found on screen.
7. No absolute paths, UUIDs or other hashes are rendered outside the above.

## A–F before-records (all 24 items)

Every item's before-state is recorded from the committed evidence plus the
full sweep; where the fix behavior itself is the item, the note says what
Phase 3 must pair against. Evidence filenames not expanded here are
`C:\Users\bidab\AppData\Local\Temp\ux259-before\{name}` and produced by the
committed capture tool cited at the top of this document.

| Item | Spec'd change (approved) | Before-state recorded | Evidence |
| --- | --- | --- | --- |
| A1 | "Your edit queue" → "Your Clip Queue" everywhere + remaining empty states | Topbar shows "Your edit queue" with wizard-flavored subtitle; no empty-state for Completed/clip-grid/Metrics/Layouts beyond Queue's own | [board empty](ux-audit-259/evidence/before-board-empty-desktop.png), [board states](ux-audit-259/evidence/before-board-states-desktop.png) |
| B2 | Board columns always render with "No jobs" placeholders; per-board EmptyState removed; fresh workspace hint lives inside the queue column only | Empty board is fully replaced by an EmptyState icon+heading+line; zero columns visible (`before-board-empty-{desktop,laptop,small}.png`, all viewports) | [link](ux-audit-259/evidence/before-board-empty-desktop.png) |
| B3 | Board fills content width; fluid columns; internal scroll only; no page-level horizontal scroll at any viewport | Six fixed 180 px columns (computed `width/minWidth 180, maxWidth none`) end in 460–540 px of dead background at 1920; board scrolls internally (`overflow-x auto`, scrollW 1147 vs clientW 1116) and page scrollHeight 3215/4228 vertical; no page-level horizontal scrollbar exists anywhere (measured all viewports) — the width fill and gap are the approved deltas. At 1024 columns wrap onto two rows inside the 728 px band and scroll both axes internally | [laptop](ux-audit-259/evidence/before-board-states-laptop.png) |
| B12 | No separate Queued column; queued jobs render under Running with "queued N" sub-badge, never after a gate accept | "Queued" is its own column (count 5/18 in fixtures), Running shows 0; auto-advance not shown on the board | [board states](ux-audit-259/evidence/before-board-states-desktop.png) |
| B19 | Completed cards never render progress bars; per-attempt progress cleared on completion | Completed cards show a green `completed` badge stacked over leftover status chips (`upload`) + trash icon (no progress rows in these fixtures; the leak's board variant is the chip stack) — Phase 3 asserts no bars | [board states](ux-audit-259/evidence/before-board-states-desktop.png) |
| B20 | Jobs tab = sub-tabs Completed (default) + Queue; board only 4 columns; sidebar "Queue"→"Jobs"; count badge moves to the Queue sub-tab; New (+) above both sub-tabs; landing rules | Six-column board, no sub-tabs, single top "New" button; sidebar carries "Queue 21"; Completed is an internal column; landing routes set nothing | [board states](ux-audit-259/evidence/before-board-states-desktop.png), [empty](ux-audit-259/evidence/before-board-empty-desktop.png) |
| C4 | Card composition: thumbnail left; title, status+checkpoint badges; single-line muted filename; compact icon quick actions with tooltips+aria; 8px rhythm | Cards: logo-icon circle left, title right, chip stack below, mono filename, mixed "Run/Cancel" text links + lone trash icon, uneven gaps | [board states](ux-audit-259/evidence/before-board-states-desktop.png) |
| C5 | Real video thumbnails on clip-grid and board cards (FFmpeg poster endpoint); generic icon as fallback only | Clip grid cards and board cards show checkbox + generic video icon + filename + byte size; no image anywhere in the flow | [clips](ux-audit-259/evidence/before-wizard-clips-desktop.png) |
| D6 | Checkbox immediately left of its visible label in one association row (label clickable); text/number/select under their label with consistent gap | Labels and controls sit in separate grid rows; checkboxes render detached from their label (centered vertically, far right); no `<label for>`, no wrapping label, `aria-label` only (code: ConfigForm.svelte renders label span + bare input); Layouts' hand-written form proves the app's own checkbox row is capable of adjacency ("Add a caption item") | [configure](ux-audit-259/evidence/before-wizard-configure-desktop.png) |
| D7 | Enums → dropdowns (layout preset from /api/v1/layouts, caption renderer, transcription model/device/compute, platform privacy/category); "Inline layout" removed; free text only for title/description/tags | form-spec types: `conversion.layout_id: string` (text input, no preset dropdown), `transcription_{model,device,compute_type}: string` (all text), only `renderer`/`schedule.mode` are `enum` (the "Caption renderer" select works); "Inline layout" object textarea present in the batch block; Title is a text input, description textarea, tags string_list — as allowed | [configure](ux-audit-259/evidence/before-wizard-configure-desktop.png) |
| D8 | All per-platform config under one "Platform" collapsible section; nodes per platform; platform toggles at Platform level | Platforms render as flat sibling fieldsets with no grouping node and none collapsed; platform-enable toggles sit inside each fieldset | [configure](ux-audit-259/evidence/before-wizard-configure-desktop.png) |
| D9 | Per-job config hidden by default; when a job is selected its sections start collapsed; batch may start expanded | Batch defaults block is `<details open>` (expanded — allowed); no per-job form exists at all (jobs render in the rail but no per-job pane) — the batch block occupies the full width above the rail | [configure](ux-audit-259/evidence/before-wizard-configure-desktop.png) |
| D10 | Right-hand master-detail rail (Batch, clip1.mp4, …), Batch default on multi-clip start, batch created only for >1 clip; never two config forms | A rail exists (`aria-label="Selected jobs"`) listing the clips (DOM: a-very-long-source-f…, checkpoint-awaiting_review…), but the batch block renders as a separate full-width expanded form alongside the rail (two competing configuration surfaces visible at once); batch pane has no selection semantics | [configure](ux-audit-259/evidence/before-wizard-configure-desktop.png) |
| D24 | Debounced dry-run validation live while editing; partial create removes created clips; rail/reselection/landing rules | Debounced `validateJobs` on edit exists in store (store.svelte.js:487/512) and the dry-run endpoint is live (`POST /api/v1/jobs/validate`, web.py:263); inline per-job summaries were not observable during the audit run and partial-create semantics do not exist (single bulk `createJobs`, no clip-removal/landing behavior) — implement-to-spec scope | [configure](ux-audit-259/evidence/before-wizard-configure-desktop.png) |
| E11 | Modal action bars get standard gaps; no element touches another | Review action row ("Save transcript revision" + "Accept transcript") shows gap but sits inside the header band with the tabs; the maintainer's zero-gap screenshot is the segment-toolbar header state, which the `states` fixture cannot reproduce (its awaiting-review job has no pending transcript revision to open the editor with — recorded as a fixture limitation) | [review tab](ux-audit-259/evidence/before-modal-review-tab-desktop.png) |
| E13 | Accept closes the job modal after success | `acceptCheckpoint` (store.svelte.js:672) awaits the accept call then only notifies ("transcript review accepted"); no modal close; modal stays open (behavior runtime; Phase 3 pairs) | [review tab](ux-audit-259/evidence/before-modal-review-tab-desktop.png) |
| E14 | After gate accept the board shows Running; no queued passthrough; store test with mocked poll sequence | No accept→resume path exists in store (accept only + refresh); board pre-accept state has the job in Awaiting review; passthrough is currently the transition expectation — verify/rebuild in Phase 1-2 | [board states](ux-audit-259/evidence/before-board-states-desktop.png) |
| E16 | One accent treatment for all gate-accept primaries; secondary/risky keep muted/danger styles | "Accept transcript" is filled teal; "Accept composition" renders muted gray (transport-disabled in the captured state) | [review tab](ux-audit-259/evidence/before-modal-review-tab-desktop.png) |
| E17 | Review tab shows only the current gate; conversion review mounts a media player on the artifact preview URL | Review tab renders the Transcript gate panel AND full Composition editor simultaneously; no media player anywhere on either tab | [review tab](ux-audit-259/evidence/before-modal-review-tab-desktop.png) |
| E22 | Composition data renders as labeled readable sections; no raw JSON anywhere | "Job layout JSON" prints a raw JSON object (captions/overlay/items) in a textarea; nothing labeled/segment | [review tab](ux-audit-259/evidence/before-modal-review-tab-desktop.png) |
| F15 | Group dropdown labeled by platform lists ("All variants" + per-group platforms) with one-line hint; raw hashes never render | Publish summary prints "· group e961ea6bb1e4" on every platform row; Review tab exposes the raw "All groups" select whose options are 12-hex ids | [publish](ux-audit-259/evidence/before-modal-publish-desktop.png), [review tab](ux-audit-259/evidence/before-modal-review-tab-desktop.png) |
| F18 | Instagram polls on the uniform 5 s interval (shared adapter default; derived pacing moves with it) | `instagram.py:35 API_POLL_INTERVAL = 60` (vs tiktok 3, twitter 5, youtube 2); no UI surface; Phase 1 unifies via Python unit tests | no UI evidence — backend item |
| F21 | Artifact row "Download" → "Open folder" (localhost-only reveal endpoint, guarded paths; raw download stays in row menu; icon-only buttons get aria-labels + tooltips) | Artifact row renders "Preview" "Download" text links + pencil (rename) and trash (delete) icon-only buttons: aria-labels present, no tooltips; no open-folder affordance | [modal review / artifacts](ux-audit-259/evidence/before-modal-review-desktop.png) |
| F23 | Scheduled-attempt cancel reachable from scheduled cards (endpoint landed in #257) | Scheduled card shows the "Cancel attempt" action (wired through `cancelScheduledAttempt` → `DELETE /jobs/{id}/scheduled/{attempt_id}`), endpoint + contract test landed in #257 — verify-pass for the "if it did not land" branch | [board states](ux-audit-259/evidence/before-board-states-desktop.png) |

## Triage summary

| Triage | Findings / items |
| --- | --- |
| Fix here (small, no new decision) | U1, U2, U4, U5, U7, U8, U10, U12, U13 (Probe button only), U15, U16, U18 |
| Follow-up issue (valid but large / P2-P3 polish) | U6, U9, U19 |
| Maintainer decision (IA / copy meaning) | U3 (which page header survives; fold the A1 copy work) |
| Approved-item before-record only (not findings) | B2, B3, B12, B19, B20, C4, C5, D6, D7, D8, D9, D10, E11, E22, F15 (and E13/E14/F18/F23/F21/E16/D24 as recorded states) |

Proposed follow-up issues to file after Phase 2 merge (not filed in this
audit):

1. **"Add visible tooltips (title) to the remaining icon-only buttons"
   (U19)** — modal back, error-dismiss and any icon control outside the C4/F21
   surfaces; plus an aria-label/title parity lint.
2. **"Shared truncation/ellipsis utility for long titles and filenames"
   (U9)** — modal header, artifact rows, publish summary rows.
3. **"Use the modal's full width for detail content" (U6)** — Overview/Review
   tab widths.

Open questions for the maintainer (from the audit; do not act without a
decision): U3 (pick the surviving header per view), and whether the "00"
sidebar badge should become "0" (U8 assumes yes, riding B20's rename).

## Coverage notes / limitations

- The wizard's *step-1 empty state* (zero clips found) and the *50-jobs
  wizard* state were not separately captured: the sweep's `states` fixture
  has 21 clips (fine coverage) and `empty` targets the board. Phase 3's D10
  assertions cover the single-clip-rail case programmatically.
- E11's segment-toolbar header state is not reproducible with the current
  `states` fixture (no pending transcript revision on the captured job); its
  before-state therefore rests on the maintainer's review screenshot
  description plus the modal action-row capture.
- Runtime gate-accept behaviors (E13/E14) are recorded as code-path facts;
  their observable before/after pairs come in Phase 3 per the verification
  map (mocked poll + board screenshots).
- Metrics/Layouts/Settings were audited at desktop only (full run contains all
  three viewports for each; no further defects were expected from the
  narrower viewports for these simple stacks, and the small-viewport variants
  exist in the uncommitted run for Phase 3's diff).
- The "00"-style sidebar badge is cosmetic; it is listed under U8 to avoid
  duplicating the count-badge rules in B20.

---

# Phase 3 — Re-audit (after-state, committed)

Phase 3 re-ran the Phase 0 sweep method against the same fixtures at the
completed Phase 1–2 state (`dev` at `b90b634`, tree clean; no frontend or
backend source was touched by the re-audit). Every Phase 0 "Fix here" finding
gets a resolved/not-resolved verdict on its own before/after pair below.

## Runs and re-pinned evidence

```text
python tests/e2e/verify_phase2c.py   # 32 passed, 0 failed (E11/E13/E14/E16/E17/E22/D24/U18/D10)
node tests/e2e/e14-store-poll.mjs    # E14 mocked-poll store test OK (queued never renders)
node tests/e2e/smoke.js              # fixtures -> board -> create flow OK
python -m unittest discover -s tests # 710 tests OK (incl. C5 thumbnails, F18 polling,
                                     #      F21/F23/D24 endpoints, E14 accept-resume, B19 state clear)
npm --prefix frontend run check      # svelte-check: 0 errors, 0 warnings
python -m compileall -q clipmorph    # OK
```

Screenshot runs: before `C:\Users\bidab\AppData\Local\Temp\ux259-before\` (30
PNGs, at commit `29fe226`), after `C:\Users\bidab\AppData\Local\Temp\ux259-after\`
(39 PNGs, at `b90b634`) — both regenerable with
`python tests/e2e/capture.py --out <dir> --label <before|after>` and both full
runs belong in CI artifacts, not the repo. Committed evidence below covers one
pair per verdict.

A Phase 3 DOM drive (three viewports, `states` + `empty` fixtures) re-verified
the browser facts inline: 41/42 script checks passed (the one miss is below).
Key numbers: page-level `scrollWidth > clientWidth` is **false at 1920/1366/
1024**; `.board` scrolls internally below 1400 px (`overflow-x: auto`, scrollW
1134/792 vs clientW, no scroll at 1920 where content width is 1688 px — U4's
1116 px cap is gone); the empty board renders four columns with four "No jobs"
rows; completed cards/artifact pages show **zero** `.progress` elements; card
chips are humanized (0 raw enum keys); the F15 group picker renders `["All
variants", "YouTube + Instagram + TikTok + Twitter / X + Facebook"]` with no
12-hex options; 11/11 checkboxes sit inside their wrapping label with 7 enum
selects and no "Inline layout" field; the selected job's pane opens with 0
expanded sections and collapsed platform nodes; exactly one `.config-pane` is
mounted with Batch active by default.

## Acceptance-criteria walkthrough

- Full-width four-column board inside the Queue sub-tab: yes — Running /
  Awaiting review / Scheduled / Failed fill the content area at 1920, with the
  container's internal horizontal scroll below 1400 px ([after-board-states-desktop](ux-audit-259/evidence/after-board-states-desktop.png), [after-board-states-laptop](ux-audit-259/evidence/after-board-states-laptop.png)).
- Completed sub-tab as the default archive list with the empty prompt when
  empty: yes — fresh workspaces land on Completed and show "Nothing completed
  yet — start with **New**" ([after-jobs-completed-desktop](ux-audit-259/evidence/after-jobs-completed-desktop.png)); row fields (title, source, completed
  time, Open folder + delete) in [after-jobs-completed-states-desktop](ux-audit-259/evidence/after-jobs-completed-states-desktop.png).
- Thumbnails in the clip grid and cards: yes — the FFmpeg poster endpoint
  (unit-tested generation, on-disk cache keyed by source identity, cache
  headers) feeds the Thumbnail component; a real clip renders its poster frame
  ([after-c5-board-card-thumbnail-desktop](ux-audit-259/evidence/after-c5-board-card-thumbnail-desktop.png)), and the synthetic 39-byte fixture clips show the
  generic icon fallback only ([after-wizard-clips-desktop](ux-audit-259/evidence/after-wizard-clips-desktop.png)).
- Card composition per C4: thumbnail left, title strong, status + checkpoint
  badges, single-line muted filename, one bottom row of compact icon actions
  with tooltips + accessible names ([after-board-states-desktop](ux-audit-259/evidence/after-board-states-desktop.png)).
- Form rows with adjacent checkboxes and dropdowns where enums exist: yes —
  checkboxes inside their wrapping label (11/11), 7 enum selects, no "Inline
  layout" field, sections collapsible under summaries, all per-platform blocks
  inside one collapsed Platform node ([after-wizard-configure-desktop](ux-audit-259/evidence/after-wizard-configure-desktop.png), [after-d8-platform-node-desktop](ux-audit-259/evidence/after-d8-platform-node-desktop.png)).
- No raw JSON anywhere: review-surface text contains no `{` (verify_phase2c on
  both gates); composition renders as labeled blocks; "Job layout JSON" and the
  "· group <hex>" leaks are gone from the built UI.
- Right-hand rail with Batch default (multi-clip start), sections collapsed:
  yes — rail order Batch + clips, Batch active on entry, exactly one config
  pane, and the selected job's sections all start collapsed.
- Accept → Running with the modal closing and no queued passthrough: yes —
  endpoint (`202`, resumed immediately, status `running`), store-level mocked
  poll ("queued, queued, running" sequence never renders queued, badge cannot
  count it), and Playwright route-mocked observation.
- Uniform accept styling: both accept primaries carry `btn btn-primary`
  (verify_phase2c class assertions); secondaries and danger actions stay
  muted/danger.
- Human group labels: verified (no 12-hex option or `· group <hex>` renders).
- "Open folder": works on the Completed archive rows — see the F21 row below
  for the artifact-row gap.
- Partial-created clips removed with the defined reselection behavior:
  verified (created clip leaves the rail, invalid stays, second Create never
  duplicates, last-clip create lands on Queue, discard lands on Completed).
- Completed cards free of progress bars: zero `.progress` elements archive- and
  board-side; the per-attempt state clear is pinned by tests/test_service.py.
- No page-level horizontal scrollbar at any tested viewport: measured false at
  1920/1366/1024 board-side and with the modal open at 1024.
- Phase 0 "Fix here" findings resolved on their own evidence pairs: all 12
  (U16 on code evidence; see the fix-here table) — the only A–F gap is F21.

## A–F verdict table (all 24 map items)

| Item | Verdict | Basis |
| --- | --- | --- |
| A1 | PASS | DOM: body contains "Your Clip Queue", no "Your edit queue"; every empty state carries a prompt ([after-board-states-desktop](ux-audit-259/evidence/after-board-states-desktop.png), [after-metrics-desktop](ux-audit-259/evidence/after-metrics-desktop.png)) |
| B2 | PASS | DOM (`empty` fixture): four columns with "No jobs"; the old full-board empty state is gone ([after-board-empty-desktop](ux-audit-259/evidence/after-board-empty-desktop.png)) |
| B3 | PASS | DOM at 1920/1366/1024: page-level scrollWidth > clientWidth false everywhere; board scrolls internally below the break, no internal scroll at 1920 ([after-board-states-laptop](ux-audit-259/evidence/after-board-states-laptop.png), [after-board-states-small](ux-audit-259/evidence/after-board-states-small.png)) |
| B12 | PASS | DOM: columns are exactly Running/Awaiting review/Scheduled/Failed; queued jobs render under Running with a "queued 5" sub-badge; the sub-badge counts the store's shared PRERUN_STATUSES (e14-store-poll + JobsView) |
| B19 | PASS | DOM: zero `.progress` elements; the completed render-out branch exists (JobsView:185-186); the per-attempt state clear is unit-tested (tests/test_service.py:839) ([after-jobs-completed-states-desktop](ux-audit-259/evidence/after-jobs-completed-states-desktop.png)) |
| B20 | PASS | DOM + capture: default sub-tab Completed; last-clip create lands on Queue, discard lands on Completed (verify_phase2c); archive row fields; empty prompt; sidebar "Jobs"; count badge on the Queue sub-tab ([after-jobs-completed-desktop](ux-audit-259/evidence/after-jobs-completed-desktop.png)) |
| C4 | PASS | Screenshot pair + DOM (thumbnail, title, badges, truncated single-line source, one icon action row with titles/aria) ([after-board-states-desktop](ux-audit-259/evidence/after-board-states-desktop.png) vs [before-board-states-desktop](ux-audit-259/evidence/before-board-states-desktop.png)) |
| C5 | PASS | Endpoint unit tests (generate-once + cache headers + content-hash key + missing/illegal rejections, test_web.py:243-347) and the real poster frame capture ([after-c5-board-card-thumbnail-desktop](ux-audit-259/evidence/after-c5-board-card-thumbnail-desktop.png)); fallback-only icon in the fresh run ([after-wizard-clips-desktop](ux-audit-259/evidence/after-wizard-clips-desktop.png) vs [before-wizard-clips-desktop](ux-audit-259/evidence/before-wizard-clips-desktop.png)) |
| D6 | PASS | Generator unit tests (checkbox inside its wrapping label, `for`-association, one control column) + DOM 11/11 + visible pair ([after-wizard-configure-desktop](ux-audit-259/evidence/after-wizard-configure-desktop.png) vs [before-wizard-configure-desktop](ux-audit-259/evidence/before-wizard-configure-desktop.png)) |
| D7 | PASS | Generator unit tests (free text exactly title/description/tags; "Inline layout" never renders; enum fields map to selects) + DOM (7 selects, no Inline layout) |
| D8 | PASS | Platform-section unit tests (one grouping node, platform rows collapsed by default with the enable toggle) + DOM (`.platform-group` present, 0 open) ([after-d8-platform-node-desktop](ux-audit-259/evidence/after-d8-platform-node-desktop.png)) |
| D9 | PASS | DOM: the selected job's pane opens with 0 expanded sections and 0 open platform nodes |
| D10 | PASS | DOM: rail lists Batch first + active on entry, exactly one `.config-pane`; the batch-persists-when-selection-drops rule is exercised by verify_phase2c's partial-create flow; single-clip-start (no Batch entry) is code-branch-verified only (no fixture) |
| D24 | PASS |Dry-run endpoint unit tests (test_web.py validate) + verify_phase2c: 12 live-validation/partial-create/reselection/landing checks PASS |
| E11 | PASS | Shared action-bar gap is unit-tested (test_form_rendering) and visible in the modal pair ([after-modal-review-desktop](ux-audit-259/evidence/after-modal-review-desktop.png) vs [before-modal-review-tab-desktop](ux-audit-259/evidence/before-modal-review-tab-desktop.png)) |
| E13 | PASS | verify_phase2c: modal closed after the accept call succeeded; e14-store-poll: `selectedJobId` cleared; non-completing conversion accept intentionally keeps the modal open (multi-group rule) |
| E14 | PASS | Endpoint: status `running` after gate accept (test_web.py:945) + e14-store-poll.mjs OK ("poll-iteration-start: running" through the mocked queued/queued/running sequence) + verify_phase2c board sampling |
| E16 | PASS | verify_phase2c computed class checks: both accept primaries carry `btn btn-primary`; secondary/danger kept for the rest |
| E17 | PASS | verify_phase2c: transcript gate renders the editor and no accept-composition/video; conversion gate renders Accept composition + a `<video.review-player>` on the artifact preview URL; no transcript editor |
| E22 | PASS | verify_phase2c: no `{` in the modal's text on either gate; labeled `.composition-block` sections; the U17 code-grep class result re-run clean; built UI drops the "Job layout JSON" textarea |
| F15 | PASS | DOM: variants select renders "All variants" + platform-list labels, zero 12-hex options; `· group <hex>` absent from review/publish surfaces |
| F18 | PASS | Unit tests (tests/test_platform_instagram.py:179-217): shared `API_POLL_INTERVAL = 5` default inherited by Instagram/Twitter, TikTok 3 / YouTube 2 unchanged, derived pacing scales with the constant |
| F21 | **PARTIAL** | Endpoint verified (reveal route on guarded artifact paths, Windows-only documented follow-up, test_web.py:349-393 + CLI_WEB_PARITY) and the Completed archive rows expose "Open folder" ([after-jobs-completed-states-desktop](ux-audit-259/evidence/after-jobs-completed-states-desktop.png)); **the modal artifact row — F21's named surface — still renders "Preview | Download | ✏ | 🗑" with no Open-folder affordance and no row menu** (see finding R1) |
| F23 | PASS | Endpoint + contract tests landed in #257 (test_web.py scheduled-attempt cancel) and verified shipping through mock-HTTP; DOM: scheduled cards expose the calendar-X "Cancel attempt" affordance and route it through the confirm dialog |

## Fix-here findings — resolved/not-resolved on before/after pairs

| Finding | Verdict | Evidence pair |
| --- | --- | --- |
| U1 (wizard back-link drift) | **RESOLVED** | "Back to clips" (configure) and "Back to jobs" (clips) share one vocabulary and name their real targets — DOM-verified both steps ([after-wizard-configure-desktop](ux-audit-259/evidence/after-wizard-configure-desktop.png) vs [before-wizard-configure-desktop](ux-audit-259/evidence/before-wizard-configure-desktop.png)) |
| U2 (dead "New batch" copy) | **RESOLVED** | No such string ships (grep clean); the wizard header names nothing "batch" |
| U4 (1116 px shell cap) | **RESOLVED** | Content width 1688 at 1920 (was ~1116); Settings/Layouts/Metrics span the full band ([after-settings-desktop](ux-audit-259/evidence/after-settings-desktop.png) vs [before-settings-desktop](ux-audit-259/evidence/before-settings-desktop.png)) |
| U5 (weak scrim) | **RESOLVED** | Dimmed, opaque scrim; background unreadable behind the dialog ([after-modal-review-small](ux-audit-259/evidence/after-modal-review-small.png) vs [before-modal-review-small](ux-audit-259/evidence/before-modal-review-small.png)); scroll-lock facts under U18; [after-u5-modal-scrim-desktop](ux-audit-259/evidence/after-u5-modal-scrim-desktop.png) |
| U7 (pipeline status printed twice) | **RESOLVED** | Rows show one muted subtext or one badge, not both ([after-modal-review-desktop](ux-audit-259/evidence/after-modal-review-desktop.png) vs [before-modal-review-desktop](ux-audit-259/evidence/before-modal-review-desktop.png)) |
| U8 (zero-padded "00" badge) | **RESOLVED** | No `00` anywhere in DOM text; an empty workspace renders no badge at all ([after-board-empty-desktop](ux-audit-259/evidence/after-board-empty-desktop.png) vs [before-board-empty-desktop](ux-audit-259/evidence/before-board-empty-desktop.png)) |
| U10 (flat non-collapsible sections) | **RESOLVED** | 8 collapsible `summary.config-summary` sections (General/Conversion/Subtitles/Upload/Content + platform nodes) ([after-wizard-configure-desktop](ux-audit-259/evidence/after-wizard-configure-desktop.png)) |
| U12 (Cancel copy overstates scope) | **RESOLVED** | Card Cancel dialog says "Running and queued work **for this job** is aborted…" (DOM) |
| U13 (Probe as naked text link) | **RESOLVED** | Probe/Re-probe render as bordered secondary buttons in the app's control family ([after-settings-desktop](ux-audit-259/evidence/after-settings-desktop.png)) |
| U15 (raw enum chips) | **RESOLVED** | 0 raw enum keys in card badge DOM (humanizer applied on card chips) ([after-board-states-desktop](ux-audit-259/evidence/after-board-states-desktop.png)) |
| U16 (raw attempt-id fallback) | **RESOLVED (code-verified)** | AttemptRow falls back to "Attempt · <localized time>", never the id; the fixture renders no upload-attempt rows, so the DOM check could not exercise it — noted as the one fixture limitation |
| U18 (no modal focus trap / scroll lock) | **RESOLVED** | verify_phase2c U18 block (6 checks): scroll locked both containers, wheel barrier, 12 Tab steps + Shift+Tab inside the dialog, Esc closes and unlocks (pair under U5 above) |

Follow-up findings remain follow-ups, unchanged: **U6** (modal width
utilization) and **U19** (tooltip pass — the C4/F21 icon rows now carry
`title` attributes, but the modal back arrow, error-dismiss and the sidebar
menu toggle still have names without tooltips). **U3** (two page headers,
maintainer decision) no longer reproduces: the implementation removed the
per-view `h2` and kept the Topbar header, resolving the drift in favor of the
Topbar — recorded here for the maintainer to confirm ([after-settings-desktop](ux-audit-259/evidence/after-settings-desktop.png) vs
[before-settings-desktop](ux-audit-259/evidence/before-settings-desktop.png)).

## New findings from the re-audit

- **R1 (P2, F21 gap on its named surface): the JobDetail modal's artifact row
  still shows "Preview | Download" with pencil/trash icons and no "Open
  folder" affordance.** F21's before-evidence is exactly this row; the
  approved change ("Download" → "Open folder", raw download in the row menu)
  landed only as an "Open folder" button on the new Completed archive rows,
  which reveals the *current* artifact — not the row F21 named, and not the
  per-artifact reveal the Phase 1 endpoint (`POST
  /jobs/{id}/artifacts/{artifact_id}/open-folder`) supports. Repro: open any
  job with an artifact → Overview tab → Artifacts card ([after-modal-review-desktop](ux-audit-259/evidence/after-modal-review-desktop.png), row bottom right).
  Fix is small and in-scope for F21: an "Open folder" button on the artifact
  row wired to `api.openFolder(jobId, artifact.id)` (already exists in
  `api.js`), with Download moved into the row's overflow/secondary affordance.
- **R2 (P3 polish, fold into U9): the detail modal scrolls horizontally
  inside itself at 1024×768** (`.detail-modal` scrollWidth 1572 vs client 940,
  `overflow-x: auto`; the two cards stay side by side instead of stacking).
  The page never overflows (checked), so B3 holds; the modal just does not
  adapt its grid below ~1100 px. This is U9's truncation/responsiveness
  follow-up territory, not a B3 regression.

## Remaining gap list

1. **F21's artifact-row half (R1)** — smallest open item; it complements the
   landed endpoint instead of new backend work.
2. **Follow-up issues to file (unchanged from Phase 0):** U19 tooltip pass,
   U9 shared truncation/responsiveness utility (now also covering R2), U6
   modal width utilization.
3. **Maintainer confirmation:** U3 was resolved in-implementation (Topbar
   header survives, per-view `h2` removed) — confirm the choice, and confirm
   the single-clip-start batch rule's quota of tests if desired.

---

*Phase 0 audit produced 2026-10-10 against `dev` at 29fe226. Phase 3 re-audit
completed 2026-10-10 against `dev` at b90b634 (branch state: clean at both
ends). Committed evidence lives in
[docs/ux-audit-259/evidence/](ux-audit-259/evidence/); the complete 30-PNG
(before) and 39-PNG (after) runs are the uncommitted sets cited at the top of
each phase and belong in CI artifacts.*

