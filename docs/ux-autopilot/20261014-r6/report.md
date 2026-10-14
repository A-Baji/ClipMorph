# UI QA report — 2026-10-14, continuation r6

## Result

Completed one full cross-browser UI audit pass on `ui/autopilot-20261014`,
starting from `9b79a922e3862ceb882e3618b5c4d5485dae2b9e`. No source changes
were made. AP-043 was rechecked and not reproduced as a defect; AP-044 remains
approved and passes regression checks. Three new user-facing copy/layout
decisions are recorded in [findings.md](./findings.md) as AP-045–AP-047 and
were not implemented without approval.

## Coverage

- Recomputed baseline: 19 configured states × 6 viewports = 114 combinations
  per browser. Viewports: 1920×1080, 1366×768, 1024×768, 375×812, 812×375,
  and 320×812. Chromium, Firefox, and WebKit each passed all 114 combinations
  (342 total).
- The states covered the board and failed/running/large-board variants; long
  content; the new-job wizard; transcript, upload, and conversion review;
  empty board/expanded column/Metrics; Settings; Layouts; offline/error
  feedback; reduced-motion and forced-colors emulation. Axe ran at the
  configured 1366px viewport. The keyboard approval and mobile-nav flows were
  exercised in smoke tests.
- Reviewer calibration passed 6/6. Eight UI-reviewer dispatches covered 290
  selected screenshots in batches; screenshots were not opened by the
  assistant. No fallback reviewer was used.
- The browser smoke suite passed in Chromium, Firefox, and WebKit. It exercised
  keyboard approval semantics, poll exhaustion and duplicate-approval
  protection, no-platform upload disabling, forced-colors focus visibility,
  pressed-button feedback, AP-031 load-error/retry, a 750ms delayed jobs
  response, two transient status-request failures, and a simulated event-stream
  disconnect/reconnect.
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
  and Layouts empty states at 320×812, reproduced in all three engines.
- **AP-047 (P3, measured):** the simulated offline `role="alert"` exposes the
  raw text “Failed to fetch”. The page has other offline explanation, but the
  alert itself is not actionable.
- Evidence paths and approval questions are in
  [findings.md](./findings.md). No subjective copy/layout change was made.

## Validation

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `npm --prefix frontend run qa:ui` — passed in Chromium: 114/114
  combinations, axe enabled, 0 errors; 2,339 expected seeded-thumbnail 404
  warnings. It ran in a PowerShell session with the documented `clipmorph`
  conda environment active and `CLIPMORPH_PYTHON` set to
  `C:\Users\bidab\miniconda3\envs\ClipMorph\python.exe`.
- `node "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-matrix-browser.cjs" firefox "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-firefox"`
  — passed: 114/114 combinations, 0 errors and 0 warnings; run with the same
  Python environment.
- `node "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-matrix-browser.cjs" webkit "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-webkit"`
  — passed: 114/114 combinations, 0 errors; 1,985 expected seeded-thumbnail
  404 warnings. The temporary browser-matrix bootstrap and output are outside
  the repository and were not committed.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; $env:CLIPMORPH_BROWSER='chromium'; node tests/e2e/smoke.js`
  — passed.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; $env:CLIPMORPH_BROWSER='firefox'; node tests/e2e/smoke.js`
  — passed.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; $env:CLIPMORPH_BROWSER='webkit'; node tests/e2e/smoke.js`
  — passed.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; python -m unittest discover -s tests -v`
  — passed, 718 tests.
- `(& "$env:USERPROFILE\miniconda3\Scripts\conda.exe" shell.powershell hook) | Out-String | Invoke-Expression; conda activate clipmorph; python -m compileall -q clipmorph`
  — passed.
- `C:\Users\bidab\miniconda3\envs\ClipMorph\python.exe scripts/check_docs.py`
  — passed.
- `C:\Users\bidab\miniconda3\envs\ClipMorph\python.exe scripts/check_structure.py`
  — failed because the repository-root
  `qa-out` directory is not allowed by the structure validator. It was left
  untouched; `tests/qa/qa-out` contains the preserved screenshot evidence.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base 9b79a922e3862ceb882e3618b5c4d5485dae2b9e`
  — passed; no states, viewports, thresholds, or allowlist entries were
  changed.

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
- Network delays, transient status failures, offline fetch failure, and an
  event-stream disconnect/reconnect were simulated. Real outage behavior and
  live server status truthfulness were not verified.
- Arbitrary locales, bidi/control characters, every possible extreme filename,
  and all hardware/browser combinations were not exhaustively tested.

## Gate integrity and confidence

No QA state, viewport, threshold, or allowlist was changed. The final
`gate-guard` check passed. This audit does not justify a 100% claim: its 342 browser-matrix
combinations and end-to-end smoke checks are broad, but the untested native
assistive-technology, operating-system, zoom, live-service, and upload
conditions remain material. Calibrated confidence in the depth of this UI QA
pass: **91/100**.
