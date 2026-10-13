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
| AP-023 | P1 | measured | An upload-review job with every platform skipped still exposes Upload. Invoking it sends an empty platform selection and returns the backend error “upload platforms are empty or unsupported.” | Deferred for a product decision: suppress/disable the action or provide platform selection. No behavior was assumed. |
| AP-024 | P2 | measured | When all ten bounded status polls fail and EventSource is unavailable, the card remains Running with its spinner after the polling window ends. Reverting to review could enable a duplicate approval while the server may still be processing. | Deferred for safe recovery semantics; do not infer terminal status from a transport failure. |
| AP-025 | P2 | measured | The detail header's space before the middle-dot separator was wider than the space after it. | Fixed by separating the dot and update text into flex items. The browser smoke test now asserts the two gaps differ by no more than 1 CSS pixel. Evidence: `evidence/AP-025-before.png` and `evidence/AP-025-after.png`. |
| AP-026 | P2 | visual-only | A teal blur shows through the sticky header in scrolled mobile captures; whether this is intentional translucency or distracting content bleed is unclear. | Deferred for human review: `tests/qa/qa-out/layouts__375___topbar.png` and `tests/qa/qa-out/settings__375___content.png`. |
| AP-027 | P2 | visual-only | The Rendered clip card appears to have substantial empty space below its player. | Deferred for human review: `tests/qa/qa-out/review-conversion__1920.png`. |
| AP-028 | P2 | visual-only | A short vertical stub appears to the left of the Accept composition action row; its purpose is unclear. | Deferred for human review: `tests/qa/qa-out/review-conversion__1920.png`. |
| AP-029 | P2 | visual-only | A small dash appears in the native video control bar in the conversion review; it may be a cursor or browser-control artifact. | Deferred for human review: `tests/qa/qa-out/review-conversion__1920.png` and `tests/qa/qa-out/review-conversion__375___review_player.png`. |
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
