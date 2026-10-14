# UX Autopilot report — 2026-10-13, continuation r5

## Result

Implemented the user's approval for AP-044 on
`ui/autopilot-20261013-r5`, based on clean starting HEAD
`ae07bac1340cf5488f338564f0c8d27f399b0cd1`. This is a focused primary-button
pressed-state improvement; AP-043 remains unchanged pending clarification.

## Fixed

- **AP-044 (P3, measured, approved):** primary buttons now use a distinct,
  tokenized pressed color without changing layout bounds. Red: the smoke test
  observed identical hover and pressed colors (`rgb(94, 234, 212)`). Green:
  Chromium, Firefox, and WebKit smoke tests pass. Evidence:
  `tests/qa/qa-out/accessibility/active-primary-button__375.png`.

## Validation

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `node tests/e2e/smoke.js` with `CLIPMORPH_BROWSER=chromium` — passed.
- `node tests/e2e/smoke.js` with `CLIPMORPH_BROWSER=firefox` — passed.
- `node tests/e2e/smoke.js` with `CLIPMORPH_BROWSER=webkit` — passed.
- `npm --prefix frontend run qa:ui` initially failed because its child process
  could not find Python on PATH. Rerun after activating `clipmorph` and setting
  `CLIPMORPH_PYTHON=C:\Users\bidab\miniconda3\envs\ClipMorph\python.exe` —
  passed: 19 states × 6 viewports = 114 combinations, axe enabled, 0 errors,
  and 2,354 expected seeded-thumbnail 404 warnings.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base ae07bac1340cf5488f338564f0c8d27f399b0cd1`
  — passed; no QA thresholds, states, or viewports were changed.
- `node .github/skills/ui-dev-qa/scripts/review-manifest.mjs --dir tests/qa/qa-out/accessibility --batch 40`
  — passed; selected both accessibility crops for its one review batch.
- `python scripts/check_docs.py` — to be run after this report is added.

## Review and remaining uncertainty

Visual review was not completed. The first reviewer dispatch received a
manifest that selected a different screenshot and declined to open it; the
manifest was corrected, but no second dispatch was made. The crop is preserved
for later review.

AP-043 is still open. In plain language, it concerns whether the keyboard-focus
outline is visibly painted around a focused button in a browser using WebKit
when forced-colors/high-contrast mode is active. The previous crop did not
show the ring, although computed styles reported one. No WebKit-specific code
change was made.

True screen-reader use, Windows High Contrast on a real Windows/browser
configuration, and live upload behavior were not tested in this focused
continuation. No upload was attempted.
