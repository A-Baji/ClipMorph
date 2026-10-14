# UI findings — 2026-10-13, continuation r4

Starting branch: `ui/autopilot-20261013`; starting worktree was clean.
Base SHA: `8473e6e706e914734a7b101cb18be4ec9ea9c2b1` (see `base-sha.txt`).
Working branch: `ui/autopilot-20261013-r4`.

## Coverage baseline

The checked-in baseline had 19 states × 5 viewports = 95 combinations. The
320×812 viewport was added without removing or changing any existing state or
viewport: the final matrix is 19 × 6 = 114 combinations. The Python suite ran
718 tests. `qa:ui` generated 342 screenshots; the final review manifest selected
95 for review in three batches (40, 40, and 15) and skipped 247. Axe was enabled
at 1366px. The gate reported zero errors and 2,343 warnings; every warning in
the generated report was an expected seeded-fixture thumbnail 404.

## Fixed

| ID | Severity | Evidence | Result |
|---|---|---|---|
| AP-040 | High | measured | Fixed forced-colors keyboard focus fallback; computed 2px solid system-color outline across Chromium, Firefox, and WebKit. |
| AP-041 | P2 | measured | Fixed Settings grid overflow at 320px with large text; measured right edge is 304px within the 320px viewport. |
| AP-042 | P1 | measured | Fixed collapsed off-canvas navigation receiving keyboard focus; first Tab now focuses the on-screen Open navigation button. |

### AP-040 — forced-colors focus

The red regression check found no visible focus fallback before the CSS change.
The fix supplies a system-color outline in forced-colors mode. Afterward all
three engines report forced-colors emulation active and a 2px solid computed
outline. Chromium and Firefox focused-control crops visibly show the ring.
The WebKit crop does not visibly show it, despite the computed outline; this
conflict is tracked separately as AP-043, not treated as a confirmed fix
regression.

Evidence: `tests/qa/qa-out/accessibility/forced-colors-focus-chromium-control.png`,
`tests/qa/qa-out/accessibility/forced-colors-focus-firefox-control.png`, and
`tests/qa/qa-out/accessibility/forced-colors-focus-webkit-control.png`.
The pre-fix assertion failure was preserved in the session's
`forced-colors-red-r4` output logs; a pre-fix screenshot was not captured.

### AP-041 — large-text Settings reflow

At 320px with a 32px root font and 26px fixed text, the previous Settings grid
overflowed horizontally by 7.796875px. The grid track sizing was corrected.
Afterward `documentWidth` is 320px and the Settings grid ends at x=304px.

Evidence: `tests/qa/qa-out/accessibility/settings-large-text-320.png`.
The pre-fix measurement is preserved in the session's `large-text-red-r4`
output logs; the original 320px QA baseline did not include this text-scaling
probe, so no pre-fix screenshot exists.

### AP-042 — mobile keyboard focus

Before the fix, the first Tab focused the off-canvas Jobs item at x=-216..-17.
The final fix hides only the collapsed `.nav-group` from keyboard navigation,
leaving the sidebar footer available for its existing QA crop. The first Tab
now focuses Open navigation at x=20..56, and Enter opens the menu so its Jobs
button is exposed to role queries.

Evidence: `tests/qa/qa-out/accessibility/mobile-navigation-first-focus-375.png`.
The red assertion and focused coordinates are in the final smoke-test history;
the pre-fix keyboard focus was not saved as a screenshot.

## Decisions requested

These are questions for the maintainer; no subjective change was made.

### AP-043 — P2, visual-only: WebKit forced-colors ring visibility

The visual reviewer could not see the focus ring in the WebKit focused-control
crop, while Chromium and Firefox crops show it. WebKit reports
`forced-colors: active` and a computed 2px solid system-color outline. The crop
may clip an outline painted outside the button bounds, so a browser-visible
failure is not yet confirmed.

**Q&A:** Do you approve a minimal WebKit-specific fallback for the forced-colors
focus indicator, or reject a code change until a viewport-level/manual check
confirms that WebKit actually fails to paint the computed outline?

Evidence: `tests/qa/qa-out/accessibility/forced-colors-focus-webkit-control.png`
and `tests/qa/qa-out/accessibility/forced-colors-focus-webkit__375.png`.

### AP-044 — P3, measured: primary-button pressed feedback

The primary button's measured `:active` and hover styles use the same
background (`rgb(94, 234, 212)`), opacity 1, and no transform or shadow. This
is a possible interaction-polish improvement, not a functional defect.

**Q&A:** Do you approve a distinct pressed-state treatment for the primary
button, or reject this polish item and keep the current feedback?

Evidence: `tests/qa/qa-out/accessibility/active-primary-button-375.png`.

## Triaged, not filed as defects

- The large-board state contains 55 cards. All 55 long titles are ellipsized
  within their cards and retain the full text in the `title` attribute; no
  overflow regression was measured.
- The 320px transient path field is narrow (about 87px), and the Settings
  subtitle wraps to several lines, but neither measured as overflowing. No
  behavior change was made.
- The long-content state and dense board were exercised. Arbitrary Unicode,
  bidi controls, and every possible extreme filename were not separately
  fuzzed.
- The WebKit forced-colors observation remains unconfirmed as described in
  AP-043; AP-040 is not reopened as a measured regression.
