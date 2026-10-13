# UI round report — 2026-10-12

## Result

Completed on branch `ui/autopilot-20261012`. Stop condition: the three-pass reviewer limit was reached. The round comprises five commits, including this documentation cleanup.

## Fixed

- **AP-005:** Clip names are clamped to two lines, long unbroken names wrap inside tiles, and full clip/job titles are available through `title`. Evidence: [before](./evidence/AP-005-before.png), [after](./evidence/AP-005-after.png), [overflow before](./evidence/AP-005-overflow-before.png), [overflow after](./evidence/AP-005-overflow-after.png).
- **AP-006:** The transient path input now shrinks on narrow screens, keeping the wizard content within the mobile modal; the wrapped action group stays aligned to the right. Evidence: [before](./evidence/AP-006-before.png), [after](./evidence/AP-006-after.png).

## Validation

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `npm --prefix frontend run qa:ui` — passed, all 80 state/viewport combinations, 0 gate errors. The 1,626 warnings were expected seeded-thumbnail 404s.
- `python -m unittest discover -s tests -v` in the activated `clipmorph` Conda environment — passed, 714 tests.
- `python scripts/check_docs.py` — passed.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base 2e4bd8c995570868c0b44e3a734e729e8973633` — passed. The base commit has no UI-QA config, so the guard noted that config comparison was unavailable.
- Browser regression probes failed before each fix and passed after: mobile modal `scrollWidth` changed from 330px vs 303px available to 303px vs 303px; both previously overflowing desktop clip labels now fit, with full titles preserved.

## Deferred and human attention

- **P1 — AP-014:** At 375px, the wizard header wraps into three rows. Reducing the row count requires a responsive layout-structure decision; no structural change was made.
- **P2 — AP-007–AP-013, AP-016–AP-020:** Card spacing/alignment, empty-state consistency, fixture-data presentation, settings spacing, helper-text legibility, metrics emptiness, selection toolbar styling, step-badge contrast, and destructive-action styling remain follow-ups. See [findings](./findings.md).
- The final reviewer pass reported five P1 and six P2 observations. AP-004 was confirmed and fixed; AP-014 remains for human review. The backdrop and modal-bottom concerns were scroll/capture artifacts, and the mobile path text was an empty input's placeholder.

## Not verified

- No live SSE/status-truthfulness checks, real uploads, or credential-backed flows.
- Keyboard flows beyond the UI gate's focus check and dark-mode contrast were not separately verified.
- The third review pass was the maximum allowed; the AP-004 overflow correction was measured and passed the gate, but did not receive a fourth visual review.
- The final UI-gate process exited 0 with 0 reported gate errors; Windows also logged a non-fatal Proactor socket-reset during harness shutdown.

## Gate integrity

No UI-QA states, viewports, thresholds, or allowlist entries were changed. `gate-guard.mjs` passed; no allowlist entries were added.
