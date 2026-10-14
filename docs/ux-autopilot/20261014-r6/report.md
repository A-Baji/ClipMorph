# UI QA report — 2026-10-14, continuation r6

## Result

Completed the cross-browser audit and an approved-fixes pass on
`ui/autopilot-20261014`, starting from
`9b79a922e3862ceb882e3618b5c4d5485dae2b9e`. AP-045, AP-046, and AP-047 were
approved and fixed with focused regressions; AP-043 was not reproduced as a
defect, and AP-044 remains approved and passes regression checks. The
independent post-fix visual review surfaced AP-048–052. AP-048, AP-049,
AP-051, and AP-052 were approved and fixed; AP-050 was rejected and remains
unchanged. A corrected six-image independent visual review found no
remaining actionable defects in these changes.

The approved AP-048–052 implementation continuation began at
`a1ff64b16fd4d3a0cc9aced0354bb85c0e3e6dc4` on the same branch. Gate integrity
was checked against the full-round baseline SHA above.

## Coverage

- Recomputed baseline after adding a dedicated mobile-navigation offline
  capture state: 20 configured states × 6 viewports = 120 combinations in the
  latest Chromium gate. Viewports: 1920×1080, 1366×768, 1024×768, 375×812,
  812×375, and 320×812. Earlier cross-browser matrices passed 19 × 6 in
  Chromium, Firefox, and WebKit; the added capture-only state was rerun in the
  Chromium gate.
- The states covered the board and failed/running/large-board variants; long
  content; the new-job wizard; transcript, upload, and conversion review;
  empty board/expanded column/Metrics; Settings; Layouts; offline/error
  feedback; reduced-motion and forced-colors emulation. Axe ran at the
  configured 1366px viewport. The keyboard approval and mobile-nav flows were
  exercised in smoke tests.
- Reviewer calibration passed 6/6. Eight earlier UI-reviewer dispatches
  covered 290 selected screenshots, and the approved-fixes review examined
  15 images. Two focused post-fix reviews covered 11 images total; the first
  revealed that the open navigation obscured the mobile topbar crop. Separate
  closed-navigation and open-navigation states were captured and the corrected
  six-image review found no actionable defects. Screenshots were not opened
  by the assistant. No fallback reviewer was used.
- The browser smoke suite passed in Chromium, Firefox, and WebKit. It exercised
  keyboard approval semantics, poll exhaustion and duplicate-approval
  protection, no-platform upload disabling, forced-colors focus visibility,
  pressed-button feedback, AP-031 load-error/retry, a 750ms delayed jobs
  response, two transient status-request failures, and a simulated event-stream
  disconnect/reconnect.
- After AP-045–047 were fixed, Chromium, Firefox, and WebKit smoke runs passed
  new checks for orphan-free final lines in both empty states and for offline
  feedback plus retry/recovery.
- Approved-fix regressions now verify one retry action only, compact button
  width, refreshed jobs requests after the retry succeeds, visible 320px
  sidebar-footer bounds, and no topbar subtitle/badge overlap.
- **TDD evidence:** pre-fix E2E assertions reproduced the raw fetch-error
  message and an orphaned empty-state final word; the new retry regression
  also failed because the offline page exposed a second Retry button (actual
  count 1, expected 0). Following the fixes, the regression checks passed in
  Chromium, Firefox, and WebKit.
- Smoke assertions measured the 9:16 mobile conversion preview within 0.015
  of its target ratio at 375px and kept Settings Save inside the 375px header.
  Chromium-only CDP large-text coverage set standard/fixed fonts to 32px/26px
  at 320px and asserted that Settings did not overflow horizontally.
- 718 Python unit tests passed; this is supporting application coverage, not
  a claim of 718 UI tests.

## Revalidated and new findings

- **AP-043:** the forced-colors keyboard focus ring is visible in all three
  engines; no regression reproduced.
- **AP-044:** approved pressed-state feedback remains distinct from hover and
  does not shift button bounds; all three browser smoke runs passed.
- **AP-045 / AP-046 (P2, measured):** one-word trailing lines in the Metrics
  and Layouts empty states at 320×812 were reproduced in all three engines;
  approved copy and balanced wrapping remove the one-word endings.
- **AP-047 (P3, measured):** the offline alert now replaces known browser
  fetch errors with connection guidance and a Retry connection action. A
  successful retry clears the alert.
- **AP-048 (P1, approved/fixed):** the retry is now primary-styled and
  content-sized; at 1920px the measured width is 142.1px against a 1,624px
  alert. Evidence: `tests/qa/qa-out/offline__1920___alert_slot.png`.
- **AP-049 (P2, approved/fixed):** removed the redundant Jobs-board Retry;
  the remaining Retry connection reloads workspace endpoints, including
  jobs. Evidence: `tests/qa/qa-out/offline__1920___alert_slot.png`.
- **AP-050 (P2, rejected):** offline empty-state wording left unchanged.
- **AP-051 (P2, approved/fixed):** added a distinct mobile-navigation
  offline capture state so the footer screenshot includes the drawer.
  Evidence: `tests/qa/qa-out/offline-mobile-navigation__320.png` and
  `tests/qa/qa-out/offline-mobile-navigation__320___sidebar.png`.
- **AP-052 (P2, approved/fixed):** at the existing narrow-screen breakpoint,
  topbar children align to the top so the Offline badge no longer overlaps
  the subtitle. Evidence: `tests/qa/qa-out/offline__320___topbar.png`.
- The first review's low-contrast concern for the Offline badge was not
  reproduced when the topbar was captured with the drawer closed. The
  corrected review found the badge readable and reported no defect.
- A thin grey strip at the edge of the open-navigation full-page screenshot
  was judged possibly a scrollbar or capture artifact; it is unconfirmed and
  no code change was made. Evidence:
  `tests/qa/qa-out/offline-mobile-navigation__320.png`.
- **Not filed:** the possible Layouts sticky-header overlap remains
  unconfirmed from a still image and is not reported as a defect.
- Before/after screenshot evidence and implementation details are in
  [findings.md](./findings.md).

## Validation

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `npm --prefix frontend run qa:ui` — passed in Chromium: 120/120
  combinations, axe enabled, 0 errors; 2,321 expected seeded-thumbnail 404
  warnings. It ran in a PowerShell session with the documented `clipmorph`
  conda environment active and `CLIPMORPH_PYTHON` set to
  `C:\Users\bidab\miniconda3\envs\ClipMorph\python.exe`.
- `node "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-matrix-browser.cjs" firefox "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-firefox-r7"`
  — passed: 114/114 combinations, axe enabled, 0 errors and 0 warnings.
- `node "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-matrix-browser.cjs" webkit "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-webkit-r7"`
  — passed: 114/114 combinations, axe enabled, 0 errors; 1,978 expected
  seeded-thumbnail 404 warnings. The temporary browser-matrix bootstrap and
  output are outside the repository and were not committed.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; $env:CLIPMORPH_BROWSER='chromium'; node tests/e2e/smoke.js`
  — passed.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; $env:CLIPMORPH_BROWSER='firefox'; node tests/e2e/smoke.js`
  — passed.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; $env:CLIPMORPH_BROWSER='webkit'; node tests/e2e/smoke.js`
  — passed on retry after one fixture-selection timeout at the wizard
  “Next: Configure” step.
- A smoke attempt made after restoring generated web assets tested the older
  bundled UI and failed the new offline assertion with “Failed to fetch.”
  `npm --prefix frontend run build` regenerated the bundle; all three smoke
  commands above then passed against the current source. Generated bundle
  outputs were restored/removed afterward and are not included in the change.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; python -m unittest discover -s tests -v`
  — passed, 718 tests.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; python -m compileall -q clipmorph`
  — passed.
- `C:\Users\bidab\miniconda3\envs\ClipMorph\python.exe scripts/check_docs.py`
  — passed.
- `python tests/e2e/verify_board.py` — final rerun passed, 27 checks and 0
  failures. Its first run found the B2 empty-board test used the stale
  `.column-empty` selector; this was corrected to the current `.empty.compact`
  selector before the passing rerun.
- `C:\Users\bidab\miniconda3\envs\ClipMorph\python.exe scripts/check_structure.py`
  — failed because the repository-root
  `qa-out` directory is not allowed by the structure validator. It was left
  untouched; `tests/qa/qa-out` contains the preserved screenshot evidence.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base 9b79a922e3862ceb882e3618b5c4d5485dae2b9e`
  — passed; one offline mobile-navigation capture state was added; no
  viewports, thresholds, or allowlist entries were changed.

## Not verified

- No actual screen reader or other assistive technology was run. Automated
  axe and Playwright accessibility/keyboard checks are not substitutes for
  assistive-technology testing.
- A complete manual contrast audit across all text, control, and state-token
  combinations was not run; the 15.43:1 select measurement addresses only the
  specific reviewer concern.
- Forced-colors was browser-emulated; native Windows High Contrast was not
  tested. Native browser-chrome zoom and operating-system text scaling were
  not exercised. Large-font reflow was checked only in Chromium, only on
  Settings, and is not equivalent to testing every view at every zoom level.
- No upload was submitted, and the supplied media/config/auth files were not
  used. The one-upload authorization remains unused (0 submissions). No
  real-user credentials or live platform clients were exercised.
- Network delays, transient status failures, offline fetch failure/retry, and
  an event-stream disconnect/reconnect were simulated. Real outage behavior
  and live server status truthfulness were not verified.
- Arbitrary locales, bidi/control characters, every possible extreme filename,
  and all hardware/browser combinations were not exhaustively tested.

## Gate integrity and confidence

No QA viewport, threshold, or allowlist was changed. One capture-only state
was added, and the final `gate-guard` check passed. This audit does not justify
a 100% claim: prior cross-browser matrix results plus the latest 120 Chromium
combinations and end-to-end smoke checks are broad, but the untested native
assistive-technology, operating-system, zoom, live-service, and upload
conditions remain material. Calibrated confidence in the depth of this UI QA
pass: **92/100**. The three approved issues now have regression coverage, and
the offline error has a tested recovery path. Remaining native accessibility,
operating-system, zoom, real-service, and live-upload uncertainty keeps the
score well below 100.
