# UI round report — 2026-10-13

## Result

The initial round and AP-028 review-action follow-up are recorded above. The user then approved AP-023, AP-024, AP-026's Settings action, and AP-027. Those changes are implemented and validated on `ui/autopilot-20261013`, with follow-up base `3d1c4fd`. This final follow-up is committed locally; nothing has been pushed and no PR is open.

## Fixed

- **AP-022 — measured:** The QA fixture now restores the running job after startup reconciliation, and the new spinner state passes at all five viewports. Evidence: [before](./evidence/AP-022-before.png), [after](./evidence/AP-022-after.png).
- **AP-025 — measured:** The detail-header separator now has balanced spacing; the smoke test asserts the gaps differ by no more than 1 CSS pixel. Red: the new assertion failed because the separator was not a distinct item. Green: the updated UI passes. Evidence: [before](./evidence/AP-025-before.png), [after](./evidence/AP-025-after.png).
- **AP-023 — measured:** Empty or unsupported upload targets now disable upload actions and are guarded at the store entry points; the UI explains why. Evidence: [after](./evidence/AP-023-after.png).
- **AP-024 — measured:** Exhausted status polling no longer leaves an indefinite spinner; it shows “Status unconfirmed” and retains the duplicate-approval guard until an authoritative refresh.
- **AP-026 — measured:** Settings Save is registered in the Topbar and is single-line at mobile width. Evidence: [after](./evidence/AP-026-after.png).
- **AP-027 — measured:** Conversion preview is constrained to a capped 9:16 frame with `object-fit: contain`. Evidence: [after](./evidence/AP-027-after.png).

AP-022's added QA state failed its ready check at all five viewports before the fixture correction; the final gate passes it at all five.

## Deferred for your decision

- **AP-031 — P1, measured:** When API loading fails, the Offline badge and “Failed to fetch” alert appear while all six board columns say “No jobs.” See [evidence](./evidence/AP-031.png). Decide whether to replace the empty-board copy with a load-error state and retry action, or retain the current empty columns with the global error banner. No copy/state change was made without approval.
- **AP-026 — P2, visual-only, unconfirmed:** Teal content may show through the scrolled mobile sticky header. Screenshots: `tests/qa/qa-out/layouts__375___topbar.png`, `tests/qa/qa-out/settings__375___content.png`.
- Other new P2 suggestions from the final reviewer batches are visual-only and remain outside the approved scope; see `tests/qa/qa-out/review-1.md` through `review-3.md`. AP-029 remains rejected and was not revisited.

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

The independent `ui-reviewer` passed its canary (6/6). The initial round used five review dispatches; the approved follow-up used six dispatches across two three-batch passes, with 95 selected screenshots in the final pass. AP-031 is the one newly confirmed P1 and needs a product decision. No P0 was found. Across the round, no viewport or threshold was removed or loosened, and no allowlist entry was added.

## Not verified

No live uploads or credentials; production SSE/status-outage truthfulness; dark-mode contrast; full keyboard journeys or actual screen-reader speech. The specific Approve focus path and spinner role/name were checked. The transient AP-024 “Status unconfirmed” visual state was covered by the mocked E14 harness but was not captured in the screenshot gate. Previous-round before screenshots for AP-023/026/027 were not retained when `qa-out` was regenerated; no before evidence is claimed.

## Follow-up: AP-028 shared review actions

After the round, the user approved consistent review-action placement across transcript, conversion, and upload review: contextual controls remain on the left, while the secondary/primary button pair stays together at the right of the top-of-panel toolbar, in that order. The composition divider was removed. The QA fixture and gate now include an upload-review state. A refreshed visual pass initially found a 7px vertical offset between conversion actions and the Render variant control; after adjustment, the browser assertion passes at <=2px and the reviewer confirmed the alignment.

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `npm --prefix frontend run qa:ui` — passed, 90 state/viewport combinations, 0 errors. All 1,856 warnings were expected seeded-thumbnail 404s.
- `node tests/e2e/smoke.js` in the activated `clipmorph` Conda environment — passed; all three review surfaces keep secondary and primary actions together at the toolbar's right edge at desktop and 375px, with the conversion pair within 2px of the selector's vertical center.
- `python -m unittest discover -s tests -v` in the activated `clipmorph` Conda environment — passed, 715 tests. The source-structure regression assertion was updated to match the new review-action grouping.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base a1b3c799f08e59ce32cf57e1837380ff7935f9c6` — passed.

The reviewer repeated the known full-page backdrop seam and modal-bottom visibility observations. The former is a full-page screenshot artifact; the latter remains reachable by scrolling (AP-030). Neither was reopened.

## Approved follow-up: AP-023, AP-024, AP-026, AP-027

Follow-up base: `3d1c4fd`. Final validation for this follow-up:

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `npm --prefix frontend run qa:ui` — passed 19 states × 5 viewports = 95 combinations with axe enabled and 0 gate errors; 1,934 expected seeded-thumbnail 404 warnings.
- `python -m unittest discover -s tests -v` in activated `clipmorph` Conda — passed, 718 tests.
- `python -m compileall -q clipmorph tests\qa` — passed.
- `python scripts/check_structure.py` and `python scripts/check_docs.py` in activated `clipmorph` Conda — passed.
- `node tests/e2e/e14-store-poll.mjs` and `node tests/e2e/smoke.js` — passed.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base 3d1c4fd` — passed.
- Final independent review batches: `tests/qa/qa-out/review-1.md` through `review-3.md`; six follow-up dispatches across two three-batch passes.

The empty-platform regression first failed because an unsupported configured platform counted as a target; restricting target detection to supported platforms made it pass. The mobile Settings assertion first failed at 51.6px height; the final button is one line and at most 44px. The empty-upload hint spacing first measured 0px; the final layout assertion passes. Full run details and AP-031's decision options are in [findings](./findings.md).
