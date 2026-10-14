# UX Autopilot report — 2026-10-13, continuation r4

## Result

Completed on `ui/autopilot-20261013-r4`, based on verified starting HEAD
`8473e6e706e914734a7b101cb18be4ec9ea9c2b1` (starting branch
`ui/autopilot-20261013`, clean worktree). The final matrix passed: 19 states × 6
viewports = 114 combinations, axe enabled, 0 errors, and 2,343 expected
seeded-thumbnail 404 warnings. Python tests: 718 passed. No push or PR.

## Fixed

- **AP-040, High, measured:** forced-colors keyboard focus fallback. Computed
  2px system-color outline in Chromium, Firefox, and WebKit; Chromium and
  Firefox crops visibly show it. WebKit visual visibility remains a question
  (AP-043).
- **AP-041, P2, measured:** 320px Settings grid reflows under large text; its
  right edge is 304px, with no document overflow.
- **AP-042, P1, measured:** the first mobile Tab no longer focuses the
  off-canvas Jobs link; it focuses the visible menu control instead.

Regression tests were red before the three fixes and green afterward. The
before/after limitations and evidence paths are recorded in
[findings.md](./findings.md).

## Coverage actually exercised

- All board, empty/error, wizard, Settings, Layouts, Metrics, transcript review,
  conversion review, upload review, and no-supported-target states in the 19
  state matrix, at 1920×1080, 1366×768, 1024×768, 812×375, 375×812, and
  320×812.
- Long-content and 55-card dense-board fixtures; review action placement,
  9:16 conversion preview, Settings Save, poll exhaustion, status-unconfirmed
  state, spinner clearing, and duplicate-approval protection.
- Slow initial loading, transient status-request failures, a dropped/closed
  aggregate SSE response followed by successful reconnect, and no-target upload
  disabling.
- Keyboard focus and Space activation of the named approval button; mobile
  first-Tab navigation; automated role/name queries and axe. This was not a
  real screen-reader test.
- Chromium, Firefox, and WebKit smoke runs. Forced-colors emulation was checked
  in all three. Large-text reflow was measured at a fixed 320px viewport with a
  32px root font; reduced motion was enabled for keyboard navigation checks.
- AP-031's load-error/Retry state and AP-039's wrapping conversion labels were
  rechecked with the final smoke and UI matrix.

## Human attention needed

- **AP-043 (P2, visual-only):** decide whether to authorize a WebKit-specific
  forced-colors focus-ring fallback or require viewport-level confirmation
  first. Evidence: `tests/qa/qa-out/accessibility/forced-colors-focus-webkit-control.png`.
- **AP-044 (P3, measured):** decide whether to add distinct primary-button
  pressed feedback. Evidence:
  `tests/qa/qa-out/accessibility/active-primary-button-375.png`.

No changes were made for either decision item.

## Validation

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `npm --prefix frontend run qa:ui` — passed, 19 states × 6 viewports = 114
  combinations, 0 gate errors; 342 screenshots generated, 95 selected for
  review and 247 skipped. All 2,343 warnings were expected seeded-thumbnail
  404s.
- `node .github/skills/ui-dev-qa/scripts/review-manifest.mjs --dir tests/qa/qa-out --batch 40`
  — passed; three batches (40, 40, 15).
- `node tests/e2e/smoke.js` with `CLIPMORPH_BROWSER` set to `chromium`,
  `firefox`, and `webkit` — passed in all three engines.
- `python -m unittest discover -s tests -v` — passed, 718 tests in 56.300s.
- `python -m compileall -q clipmorph` — passed.
- `python scripts/check_docs.py` — passed after these records were added.
- `python scripts/check_structure.py` — failed because the pre-existing
  repository-root `qa-out` entry is not an allowed top-level source directory.
  It was preserved and not removed.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base 8473e6e706e914734a7b101cb18be4ec9ea9c2b1`
  — passed after the final UI/test changes. No threshold, state, or existing
  viewport was removed; no allowlist entry was added.
- `python -m clipmorph job create --dry-run
  'C:\Users\bidab\AppData\Local\ClipMorph\ClipMorph\sources\test-1.mp4'
  --data-dir 'C:\Users\bidab\AppData\Local\ClipMorph\ClipMorph'` — passed;
  one source validated. No job/manifest was written.

## Reviewer and stop condition

The `ui-reviewer` canary scored 6/6 and passed; the fallback reviewer was not
used. The final pass used three reviewer dispatches, within the three-dispatch
cap. The exact cumulative dispatch count across earlier passes is unavailable
because prior reviewer tables were overwritten by subsequent QA output. The
three-pass stop condition was reached.

## Not verified

- No live upload was attempted. The local configuration has public visibility,
  but the configured platform/account and intended audience could not be
  established safely; the one-upload authorization was not consumed. No
  credentials were printed or changed.
- True browser-chrome zoom was not verified; headless Ctrl+Shift+= did not
  change the viewport. Large-text coverage used a fixed viewport and explicit
  font scaling instead.
- No real screen reader or other assistive technology was run. Automated
  accessibility-tree queries and axe are not substitutes.
- Full keyboard-only journeys through every workflow, every possible long or
  untrusted filename, arbitrary Unicode/bidi input, every intermittent network
  failure pattern, and long-duration SSE recovery were not exhaustively tested.
- WebKit forced-colors ring painting is visually ambiguous in the captured
  crop, despite the measured computed outline.

## Calibrated confidence

**8/10.** Confidence is high for the tested responsive matrix, seeded workflow
states, regressions, and three-engine smoke behavior. A 100% claim is not
justified because real assistive technology, true browser zoom, real upload
target/account behavior, all possible untrusted text, and the WebKit
forced-colors paint discrepancy remain unverified.
