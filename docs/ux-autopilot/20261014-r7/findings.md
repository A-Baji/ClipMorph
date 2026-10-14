# UI findings — 2026-10-14, continuation r7

Starting branch: `ui/autopilot-20261014`

Starting HEAD: `920e6a99cbe08195954440a6386c4eb6b019bb67`

Baseline: 20 QA states × 6 viewports = 120 combinations per browser. The
Python suite contains 718 tests.

## Fixed findings

### AP-053 — P2, measured; fixed

At 320×812 with simulated 200% root text, the Settings grid extended to
327.8px and the document to 328px. The regression failed before the fix.
Allowing grid children to shrink with `min-width: 0` keeps the page within the
320px viewport.

Before/after:

- `evidence/AP-053-before.png`
- `evidence/AP-053-after.png`

The final geometry assertion passed in Chromium, Firefox, and WebKit. This
simulates root-font scaling; it is not native browser zoom.

### AP-054 — P1, measured; fixed

At 320×812 and simulated 200% root text, the Settings heading and Save
app.yml action overlapped. The heading occupied x=72–228.4px while the action
occupied x=88–302.1px. The small-screen topbar now uses a two-column grid,
with title content beside the menu and actions below it.

Before/after:

- `evidence/AP-054-before.png`
- `evidence/AP-054-after.png`

The E2E regression passed at 320px in all three browser engines.

### AP-055 — P2, measured; fixed

At 320×812 and simulated 200% root text, all five credential Probe buttons
extended to x=310.8px while the Credentials card ended at x=304px. Min-width
constraints on the Settings grid, credential rows, and flexible name column
now keep the buttons inside the card.

Before/after:

- `evidence/AP-055-before.png`
- `evidence/AP-055-after.png`

The E2E bounds assertion passed in Chromium, Firefox, and WebKit.

### AP-056 — P2, measured; fixed

The first mobile header adjustment removed the title/action overlap but
collapsed the Settings subtitle to four lines at 320px. A failing regression
captured that result. The final grid gives the title/subtitle the available
column width and the E2E assertion now limits the normal-size subtitle to two
lines.

Before/after:

- `evidence/AP-056-before.png`
- `evidence/AP-056-after.png`

The assertion passed in Chromium, Firefox, and WebKit.

### AP-057 — P1, measured; fixed

The mobile sticky header background had a measured alpha of 0.8784, allowing
underlying page content to show through while scrolling. It is now opaque at
the small-screen breakpoint. An independent post-fix review confirmed the
header no longer shows content through its background.

Before/after:

- `evidence/AP-057-before.png`
- `evidence/AP-057-after.png`

The background-alpha regression passed in Chromium, Firefox, and WebKit.

## Reviewer triage

An independent reviewer inspected 96 screenshots selected from the full
Chromium run in three batches, then re-reviewed the changed Settings surface.
The final re-review covered three mobile Settings images and confirmed the
sticky-header see-through issue was gone.

Other observations were checked against rendered behavior and existing intent:

- The platform-mark/name gap is 12px in the credential row. The initials are
  decorative (`aria-hidden`); contrast calculated from their foreground and
  composited background colors is 7.70:1 (YouTube), 5.26:1 (Instagram),
  9.01:1 (TikTok), and 5.56:1 (Twitter/Facebook). The reported zero-gap and
  low-contrast defects were not reproduced.
- “Submit upload” is disabled when there are no selected platforms; the
  existing E2E check confirms the native disabled state.
- The per-platform “config” identifier is an intentional render-variant group
  ID with a title explaining its purpose. It is not a credential or token.
- Fixture titles deliberately contain status-like phrases and are ellipsized;
  the full title remains available in the card's title attribute. The title
  text is not the job status.
- The full-page modal/scrim edges and the wizard's dark horizontal band were
  visual-only observations and were not confirmed as clipped interactive
  content. The dialog itself has an overflow-scrolling container; no gate
  errors or page overflow were reported.

## Visual-only follow-ups — decisions recorded

These are design preferences rather than reproduced functional defects. They
were not changed without a maintainer decision.

- **AP-058 — P2, visual-only:** At 320px, “Twitter / X” and “not configured”
  wrap within credential rows, producing uneven row heights. Evidence:
  `tests/qa/qa-out/settings__320___content.png` and
  `tests/qa/qa-out/accessibility/settings-root-font-200-320-after-chromium.png`.
  **Outcome: not substantiated; no change.** The user did not observe wrapping
  and initially could not locate the cited screenshot. Both files were
  verified present in the repository, but this visual-only observation was
  not approved for change.
- **AP-059 — P2, visual-only:** With large root text, the menu icon and
  Settings title do not appear vertically centered, and the Save action uses
  its own row. Evidence:
  `tests/qa/qa-out/accessibility/settings-root-font-200-320-after-chromium.png`.
  **Outcome: rejected.** Keep the current responsive header arrangement.
- **AP-060 — P2, visual-only:** At desktop width the Paths card has unused
  vertical space beside the Credentials card. Evidence:
  `tests/qa/qa-out/settings__1920___content.png`.
  **Outcome: rejected.** Keep the equal-height paired cards.

No assistive technology, native OS accessibility settings, or live upload was
used in this continuation.
