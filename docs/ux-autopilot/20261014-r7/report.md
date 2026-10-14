# UI QA report — 2026-10-14, continuation r7

## Result

Completed the large-text Settings reflow continuation on
`ui/autopilot-20261014`, starting from
`920e6a99cbe08195954440a6386c4eb6b019bb67`; the starting worktree was clean.
Five measured Settings defects were fixed (AP-053–057), each with a
before/after screenshot pair in [`evidence/`](./evidence/). No upload was
attempted.
The fixes and this dated report are committed locally in one commit; nothing
was pushed and no pull request was opened.

Confidence in the depth of this automated/browser QA: **93/100**. The complete
configured UI matrix passed in Chromium, Firefox, and WebKit, and focused E2E
checks exercised the changed Settings behavior and the existing workflow
smoke cases. This is not 100%: the matrix is finite and fixture-driven; it
does not establish behavior with real production data, a real service outage,
screen readers, native browser zoom, or native OS high-contrast settings.
AP-058–060 remain visual-only design decisions.

## Coverage

- Recomputed baseline: 20 states × 6 viewports = 120 combinations per browser.
  Viewports: 1920×1080, 1366×768, 1024×768, 375×812, 812×375, and 320×812.
- States cover the board, long content, large board and expanded columns,
  wizard, transcript/conversion/upload review, no-platform upload, empty
  states, Settings, Layouts, offline feedback, and mobile navigation.
- Final full UI matrices: Chromium 120/120, Firefox 120/120, WebKit 120/120.
  Axe was enabled in each; all three reported zero gate errors. Chromium had
  2,323 and WebKit 1,973 expected seeded-thumbnail 404 warnings; Firefox had
  none. No thresholds, states, viewports, or allowlists were changed.
- E2E smoke passed in Chromium, Firefox, and WebKit. It covered the changed
  Settings reflow at 320px and simulated 200% root text, keyboard approval,
  poll exhaustion/duplicate-approval protection, no-platform upload
  disabling, forced-colors focus emulation, active-state feedback, offline
  retry/recovery, event-stream reconnect, and review flows. This is browser
  automation, not assistive-technology testing.
- Long/untrusted text and a 55-card board were included in the seeded matrix.
  Reduced-motion and forced-colors browser emulation were exercised. Native
  browser zoom and native OS accessibility settings were out of scope.
- Reviewer calibration passed 6/6 earlier in this continuation. Three
  reviewer dispatches inspected 96 selected Chromium screenshots; two
  targeted post-fix reviews covered the Settings changes. Screenshots were
  not opened by the builder.

## Validation

Commands below were run from the repository root. Python/QA commands used the
`clipmorph` Conda environment.

- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors and 0 warnings.
- `npm --prefix frontend run qa:ui` — passed in Chromium: 120/120, axe enabled,
  0 errors, 2,323 expected seeded-thumbnail 404 warnings.
- `node "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-matrix-browser.cjs" firefox "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r7\qa-firefox-final-opaque-header"`
  — passed, 120/120, axe enabled, 0 errors and 0 warnings.
- `node "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r6\qa-matrix-browser.cjs" webkit "C:\Users\bidab\.copilot\session-state\09c766f7-72cd-47fd-b52c-892f42c40d8c\files\20261014-r7\qa-webkit-final-opaque-header"`
  — passed, 120/120, axe enabled, 0 errors, 1,973 expected seeded-thumbnail
  404 warnings. The temporary runner and browser matrix outputs remain
  outside the repository.
- `$env:CLIPMORPH_BROWSER='chromium'; node tests/e2e/smoke.js` — passed.
- `$env:CLIPMORPH_BROWSER='firefox'; node tests/e2e/smoke.js` — passed.
- `$env:CLIPMORPH_BROWSER='webkit'; node tests/e2e/smoke.js` — passed.
- `python -m unittest discover -s tests -v` — passed, 718 tests.
- `python -m compileall -q clipmorph` — passed.
- `python scripts/check_docs.py` — passed.
- `python scripts/check_structure.py` — failed on the pre-existing root-level
  `qa-out` directory. It was left untouched to avoid deleting unrelated local
  QA output.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base 920e6a99cbe08195954440a6386c4eb6b019bb67`
  — passed after fixes; no thresholds, states, viewports, or allowlists were
  loosened.

## Not verified

- No live upload was attempted; no supplied app/auth configuration or real
  credentials were read.
- Screen-reader or other assistive-technology use and native OS accessibility
  settings were not tested.
- Browser forced-colors and reduced-motion settings were emulated, not tested
  through native OS settings. The 200% text check is a root-font simulation,
  not native browser zoom.
- Real production data, live SSE/network failure behavior, exhaustive color
  contrast, and every possible viewport/content combination remain outside
  this evidence.
