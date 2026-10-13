# UI round report — 2026-10-13

## Result

Completed on `ui/autopilot-20261013`; stop condition: three review passes. Two round commits; nothing pushed and no PR opened.

## Fixed

- **AP-022 — measured:** The QA fixture now restores the running job after startup reconciliation, and the new spinner state passes at all five viewports. Evidence: [before](./evidence/AP-022-before.png), [after](./evidence/AP-022-after.png).
- **AP-025 — measured:** The detail-header separator now has balanced spacing; the smoke test asserts the gaps differ by no more than 1 CSS pixel. Red: the new assertion failed because the separator was not a distinct item. Green: the updated UI passes. Evidence: [before](./evidence/AP-025-before.png), [after](./evidence/AP-025-after.png).

AP-022's added QA state failed its ready check at all five viewports before the fixture correction; the final gate passes it at all five.

## Deferred for your decision

- **AP-023 — P1, measured:** An upload-review job with all platforms skipped still offers Upload, then receives the empty-platform error. Decide whether to suppress/disable it or allow platform selection.
- **AP-024 — P2, measured:** If all ten status polls fail and EventSource is unavailable, the spinner remains Running. Safe recovery must avoid falsely permitting duplicate approval.
- **AP-026 — P2, visual-only:** Teal content may show through the scrolled mobile sticky header. Screenshots: `tests/qa/qa-out/layouts__375___topbar.png`, `tests/qa/qa-out/settings__375___content.png`.
- **AP-027 — P2, visual-only:** The Rendered clip card appears to leave substantial space below its player. Screenshot: `tests/qa/qa-out/review-conversion__1920.png`.
- **AP-028/AP-029 — P2, visual-only:** The Accept composition row has an unexplained vertical stub, and a small dash appears in native video controls. Screenshots: `tests/qa/qa-out/review-conversion__1920.png`, `tests/qa/qa-out/review-conversion__375___review_player.png`.

Previously unconfirmed AP-001, AP-002, AP-003, and AP-015 were re-measured and not confirmed. The repeated modal-backdrop seam was a full-page screenshot artifact: the fixed scrim covers the 1920×1080 viewport while the underlying document is 1804px tall. The conversion modal's final composition block is reachable by scrolling.

## Validation

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `npm --prefix frontend run qa:ui` — passed, 85 state/viewport combinations, 0 gate errors, axe enabled. All 1,758 warnings were expected seeded-thumbnail 404s.
- `python -m unittest discover -s tests -v` in the activated `clipmorph` Conda environment — passed, 715 tests.
- `python -m compileall -q clipmorph tests\qa` — passed.
- `python scripts/check_structure.py` — passed.
- `python scripts/check_docs.py` — passed.
- `node tests/e2e/smoke.js` in the activated `clipmorph` Conda environment — passed, including the new metadata-spacing assertion.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base a1b3c799f08e59ce32cf57e1837380ff7935f9c6` — passed after each fix.

The first smoke invocation without Conda could not find Python; the activated-environment run above passed.

## Reviewer and gate integrity

The independent `ui-reviewer` passed its canary (6/6). Five visual-review dispatches covered the initial manifest, the 59 changed-state screenshots, and the 12 changed detail-view screenshots. No confirmed P0/P1 remains. The QA config adds one state; no viewport, threshold, or allowlist was removed or loosened, and no allowlist entry was added.

## Not verified

No live uploads or credentials; no production SSE/status-outage truthfulness; dark-mode contrast; full keyboard journeys or actual screen-reader speech. The specific Approve focus path and spinner role/name were checked.
