# Dashboard UX audit â€” round 4 opening pass

**Status: ready for triage.** Four visual findings below; none implemented.

## Coverage and evidence

The committed UI gate was extended to cover these additional states:

- `failed-status-mix`: expanded Failed column with failed, cancelled, and
  partial-failure fixtures.
- `long-content`: long source filename and title.
- `large-board` and `large-failed-grid`: the 55-additional-job fixture and its
  expanded Failed grid.
- `settings` and `layouts`: the two previously unphotographed workspace
  surfaces.
- `offline`: the application with its `/api/v1/` fetches rejected in the QA
  browser context.

Coverage ran at **1920x1080, 1366x768, 1024x768, 375x812, and 812x375**:
16 states Ã— 5 viewports = 80 state/viewport captures. The gate generated 240
PNGs (full-page and component crops) under the gitignored
`tests/qa/qa-out/`. Examples:

- `tests/qa/qa-out/large-board__375.png`
- `tests/qa/qa-out/long-content__1366__article_card.png`
- `tests/qa/qa-out/offline__375__alert_slot.png`
- `tests/qa/qa-out/report.md`

`report.md` records **0 errors**. Its 1,613 warnings are all the expected
seed-fixture thumbnail 404 fallback; the gate documents and handles these
synthetic-media failures. The screenshots remain local and are not committed;
there are no before/after pairs in this opening pass.

The offline scenario is a QA-only simulation; no application code, credentials,
or live uploads were used. The QA runner suppresses no unexpected network
errors: it makes only the fixture's API `fetch` calls reject so the app renders
its ordinary offline/error state.

## Automated gates

All commands ran on `dev` with
`CLIPMORPH_PYTHON=C:\Users\bidab\miniconda3\envs\ClipMorph\python.exe`.

| Command | Result |
|---|---|
| `npm --prefix frontend run qa:ui` | PASS, exit 0; 80 state/viewport pairs |
| `python tests/e2e/verify_board.py` | PASS; 27 passed, 0 failed |
| `python tests/e2e/verify_phase2c.py` | PASS; 32 passed, 0 failed |
| `node tests/e2e/smoke.js` | PASS; fixtures â†’ board â†’ create flow |
| `python -m unittest discover -s tests` | PASS; `Ran 714 tests`; `OK` |

The initial run of the newly extended gate exposed config-only mobile navigation
and offline-fixture reporting issues. The QA actions and offline simulation
were corrected; the final gate run above is green. This was test-harness
iteration, not a dashboard defect.

## UI/UX guidance searches performed

Searches used the local `ui-ux-pro-max` dataset before any visual judgments.

| Concern | Search and result | Applicability |
|---|---|---|
| Modal keyboard focus | `keyboard focus modal` â€” UX `Focus States`, High | Applicable to the wizard and detail modals; screenshot review is still needed. |
| Offline/error state | `offline service error state` â€” generic error-message and form-error results; narrower `offline network failure reconnect` â€” no match | No verified offline-specific result; do not infer a defect from the generic form advice. |
| Long filenames | `long filename truncation` â€” `Truncation` and `Long Token Wrapping` | Applicable to the long-content fixture; pixels were not adjudicated. |
| Dark-mode contrast | `dark mode contrast dashboard` â€” Dark Mode style with a 4.5:1 contrast requirement; narrower `dark theme text contrast WCAG` returned generic palettes | Use the skill Quick Reference threshold of 4.5:1 for normal text; no contrast measurement was performed. |
| Icon-only affordances | `icon button accessible label tooltip` â€” `icon-context-accessibility` | Applicable to interactive icons; automated evidence is in the gate report, visual/tool-tip behavior remains unreviewed. |
| Spacing and reflow | `dashboard spacing rhythm` â€” `Text Reflow and Spacing` plus mobile touch spacing | Reflow guidance applies; no visual spacing judgment was made. |
| Live status | `live status update stale dashboard`; narrower `streaming data status freshness` returned unrelated guidance | No verified domain match; whether displayed statuses stay current requires a separate functional review. |

## Independent visual review

The specified `opencode-go/glm-5.3-flash` is unavailable in this harness, so the
review ran as three general-purpose subagents on the harness default model
(three screenshot batches: board states; modals/review; secondary surfaces),
given only the PNGs and an inline rubric (the skill's `review-rubric.md` is not
present in this checkout). They did not read source. Keyboard focus trap, Esc,
and dynamic focus are not verifiable from stills (the e2e U18 checks cover them).
Static-image findings are unverified against code; confidence is the reviewer's.

## Triage

| ID | Sev | Evidence | Finding | Proposed bucket |
|---|---|---|---|---|
| UX4-001 | P2 | `board__375.png`, `large-board__375.png`, `long-content__375.png`, `board__812.png`, `empty-board__375.png`, `empty-board__812.png` | At 375/812px the six-column board is clipped at the right edge (Transcribe cut off; only a sliver of the next column at 812) with no visible scroll cue. | needs my decision (scroll-snap/cue vs. one-stage-at-a-time layout) |
| UX4-002 | P2 | `review-conversion__1024___detail_modal_composition_block.png`, `review-conversion__1366___detail_modal_composition_block.png` | Conversion Config labels ("Strict validation", "Clean conversion files", "Caption renderer", "Skip conversion confirmations") truncate with ellipses in the review composition block. | fix here |
| UX4-003 | P2 | `offline__375.png` | Offline alert shows only the raw browser error "Failed to fetch"; no plain-language cause or next step. Violates the humanized-labels rule. | fix here |
| UX4-004 | P3 | `empty-metrics__1920.png`, `empty-metrics__375.png` | Large blank gap between the Metrics header and the filters/empty panel. | follow-up |

Not covered / unverified: live-status (SSE) truthfulness, focus order, dark-mode
contrast (no dark theme measured), hit-target sizes beyond axe. No issues filed;
no application code changed.
