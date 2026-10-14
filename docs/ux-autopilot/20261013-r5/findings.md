# UI finding — 2026-10-13, continuation r5

Starting branch: `ui/autopilot-20261013-r4`; starting worktree was clean.
Base SHA: `ae07bac1340cf5488f338564f0c8d27f399b0cd1` (see `base-sha.txt`).
Working branch: `ui/autopilot-20261013-r5`.

## AP-044 — P3, measured; approved and fixed

The primary button's held-down state previously had the same background color
as its hover state. The user approved adding clearer, informative interaction
feedback. The theme now defines `--color-primary-active` using the existing
teal palette and wires it through `--button-primary-bg-active`; enabled primary
buttons use that token while pressed. The existing background transition
provides the change without moving the control.

The Playwright regression test waits for the hover and press transitions,
asserts that the pressed background differs from hover, and checks that the
button's x/y/width/height stay within 0.5 CSS pixels of their pre-press bounds.
It failed before the CSS change with hover and pressed both
`rgb(94, 234, 212)`. It passed after the change in Chromium, Firefox, and
WebKit.

Evidence crop:
`tests/qa/qa-out/accessibility/active-primary-button__375.png`. The matching
review manifest includes this crop, but visual review was not completed: the
first reviewer dispatch encountered a manifest mismatch and declined to open
an unrelated image. No second dispatch was made.

## AP-043 — P2, visual-only; clarification pending

"WebKit forced-colors focus ring" means the visible outline around the
currently keyboard-focused control when a browser uses Windows High Contrast
or an equivalent forced-colors setting, specifically in a browser using the
WebKit engine. The code reports a 2px system-color outline, but a reviewer
could not see it in a small WebKit crop. This does not yet establish that the
outline is missing in a normal viewport. The user said the term was unclear;
no implementation change was approved or made.

Evidence remains
`tests/qa/qa-out/accessibility/forced-colors-focus-webkit-control.png` and
`tests/qa/qa-out/accessibility/forced-colors-focus-webkit__375.png`.
