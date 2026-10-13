# UI autopilot findings — 2026-10-13

Base: `a1b3c799f08e59ce32cf57e1837380ff7935f9c6`  
Branch: `ui/autopilot-20261013`

## Gate and review scope

- Baseline: 16 states × 5 viewports = 80 combinations and 715 unit tests.
- Baseline UI gate warnings: 1,628 expected seeded-thumbnail 404s.
- Final gate: 17 states × 5 viewports = 85 combinations; 255 screenshots captured.
- Final gate result: 85 combinations, 0 errors, axe enabled. The 1,758 warnings were all expected seeded-thumbnail 404s.
- The new `running-card-spinner` state failed its ready check at all five viewports before fixture correction: startup reconciliation had changed the seeded running fixture to failed before capture. The corrected fixture passes at all five.
- Re-review selection: 59 manifest-selected screenshots from states sharing the changed fixture scenario, followed by 12 selected detail-view screenshots after AP-025.

## Findings and triage

| ID | Severity | Evidence type | Finding | Triage |
| --- | --- | --- | --- | --- |
| AP-001 | P1 | measured | The expanded Failed grid appeared to show multiple columns at 375px. Its measured grid is 343px wide with one 343px column and no page overflow. | Not confirmed; no change. |
| AP-002 | P1 | measured | The mobile Settings Save button appeared hidden by the sticky header. At 375×812, the topbar ends at y=85 and Save is at y=117–152. | Not confirmed; no change. |
| AP-003 | P1 | measured | The New modal appeared clipped on mobile. It fits the viewport, scrolls internally, and retains a 40.8px bottom gap at maximum scroll with the large fixture. | Not confirmed; no change. |
| AP-015 | P1 | measured | The transient path appeared truncated on mobile. The input is empty; the visible path is placeholder text, not entered content. | Not confirmed; no change. |
| AP-022 | P1 | measured | QA's `running` fixture was reconciled to `failed` before the UI state could capture its spinner, leaving that state untested. | Fixed in the QA fixture seeding; the new state passes at all five viewports. Evidence: `evidence/AP-022-before.png` and `evidence/AP-022-after.png`. |
| AP-023 | P1 | measured | An upload-review job with every platform skipped still exposes Upload. Invoking it sends an empty platform selection and returns the backend error “upload platforms are empty or unsupported.” | User approved disabling Upload when no platforms are selected; implementation remains a separate follow-up. |
| AP-024 | P2 | measured | When all ten bounded status polls fail and EventSource is unavailable, the card remains Running with its spinner after the polling window ends. Reverting to review could enable a duplicate approval while the server may still be processing. | User approved showing the last known status, or the expected next status when known (for example, Running after review approval); implementation remains a separate follow-up. |
| AP-025 | P2 | measured | The detail header's space before the middle-dot separator was wider than the space after it. | Fixed by separating the dot and update text into flex items. The browser smoke test now asserts the two gaps differ by no more than 1 CSS pixel. Evidence: `evidence/AP-025-before.png` and `evidence/AP-025-after.png`. |
| AP-026 | P2 | visual-only | A teal blur shows through the sticky header in scrolled mobile captures; whether this is intentional translucency or distracting content bleed is unclear. | User proposed moving Save into the header to remove the separate row; implementation remains a separate follow-up. Screens: `tests/qa/qa-out/layouts__375___topbar.png` and `tests/qa/qa-out/settings__375___content.png`. |
| AP-027 | P2 | visual-only | The Rendered clip card appears to have substantial empty space below the player. | User approved a fixed 9:16 player frame with `contain` to preserve the full video; implementation remains a separate follow-up. Screenshot: `tests/qa/qa-out/review-conversion__1920.png`. |
| AP-028 | P2 | visual-only | A short vertical stub appeared beside the Accept composition action row, and review actions were not consistently positioned between stages. | Fixed per user approval: remove the group divider; keep the secondary and primary buttons paired at the right of the top-of-panel toolbar on transcript, conversion, and upload review, with the secondary button first. Keep variant/context controls separate on the left. The conversion pair is vertically aligned to the Render variant select within 2 CSS pixels. |
| AP-029 | P2 | visual-only | A small dash appears in the native video control bar in the conversion review; it may be a cursor or browser-control artifact. | User rejected a fix, identifying it as a likely loading-circle artifact. Screens: `tests/qa/qa-out/review-conversion__1920.png` and `tests/qa/qa-out/review-conversion__375___review_player.png`. |
| AP-030 | P2 | measured | The Strict section appeared clipped at the bottom of the conversion review. The detail modal has `scrollHeight=1606` and `clientHeight=992`; at maximum scroll (614px), the last composition block ends at y=987, above the modal bottom at y=1037. | Not confirmed; the content is reachable by scrolling. |

## Job-card interaction and accessibility probes

- Mocked approval failure displayed the API error in `role=alert` and kept the Approve action available.
- Mocked successful approval followed by a `completed` server response cleared the spinner.
- The processing indicator exposed `role=status` and the accessible name “Processing Status fixture: running”.
- Keyboard Tab navigation reached the native Approve button, which has an accessible name.
- No live uploads or credentials were used.

## Independent visual re-review

The first re-review covered 40 screenshots and found one P2 candidate for AP-026; 39 had no confirmed defect. The second covered 19 screenshots: its P1 observation of a backdrop seam was measured and confirmed as a full-page capture artifact, matching the previously rechecked AP-003. The AP-025 spacing concern was fixed; card spacing and Settings observations overlapped user-approved findings and were not reopened.

The final re-review covered 12 selected detail-view screenshots. The header spacing looked balanced after AP-025. The reviewer repeated the full-page backdrop seam observation; it is not visible in the browser viewport: at 1920×1080 the scrim is fixed at y=0 with height 1080, while the underlying document is 1804px tall. The screenshot extends below the viewport. The modal-bottom observation was also measured and dropped as AP-030. Remaining new P2 candidates are AP-027–AP-029. No confirmed P0 or P1 remains.

Do not re-raise AP-014/AP-020 or re-litigate approved AP-007–AP-013, AP-016–AP-019, and AP-021.

## AP-028 approved follow-up

The user clarified that review actions should have the same placement across review gates. The shared top-of-panel toolbar keeps contextual controls on the left and pairs the secondary action before the primary action at the right across transcript, conversion, and upload review. The composition divider was removed. Browser smoke assertions verify same-row button pairing and right-edge alignment at desktop and 375px widths; the conversion action group is also centered against the Render variant select within 2 CSS pixels.

The UI gate was extended with an upload-review state so all three surfaces are captured; the final follow-up run covered 18 states × 5 viewports = 90 combinations with 0 errors. Its 1,856 warnings were expected seeded-thumbnail 404s. The initial vertical-alignment smoke assertion failed at a 7px offset; after the CSS adjustment the <=2px assertion passed. The full 715-test Python suite passed after updating the source-structure assertion for the new grouped-action markup. `gate-guard.mjs` passed after each fix.

The refreshed reviewer pass confirmed the conversion action group is centered with the Render variant control. It repeated the backdrop seam and modal-bottom observations; these were previously measured as a full-page screenshot artifact and reachable scroll content (AP-030), respectively, and are not new findings.
