# UI autopilot findings — 2026-10-13

Base: `a1b3c799f08e59ce32cf57e1837380ff7935f9c6`  
Branch: `ui/autopilot-20261013`

## Gate and review scope

- Baseline: 16 states × 5 viewports = 80 combinations and 715 unit tests.
- Baseline UI gate warnings: 1,628 expected seeded-thumbnail 404s.
- Previous gate after AP-022: 17 states × 5 viewports = 85 combinations; 255 screenshots captured.
- Previous gate result: 85 combinations, 0 errors, axe enabled. The 1,758 warnings were all expected seeded-thumbnail 404s.
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
| AP-023 | P1 | measured | An upload-review job with every platform skipped still exposes Upload. Invoking it sends an empty platform selection and returns the backend error “upload platforms are empty or unsupported.” | Fixed: disable the review and one-click upload actions when there are no supported targets, explain the empty selection, and guard both store entry points. The gate captures the empty-platform review state; browser smoke and helper regression tests cover it. |
| AP-024 | P2 | measured | When all ten bounded status polls fail and EventSource is unavailable, the card remains Running with its spinner after the polling window ends. Reverting to review could enable a duplicate approval while the server may still be processing. | Fixed: retain expected Running, replace the spinner with an accessible “Status unconfirmed” status, keep the resume guard active, and clear the marker on a successful authoritative refresh. The mocked E14 harness covers poll exhaustion and marker recovery. |
| AP-025 | P2 | measured | The detail header's space before the middle-dot separator was wider than the space after it. | Fixed by separating the dot and update text into flex items. The browser smoke test now asserts the two gaps differ by no more than 1 CSS pixel. Evidence: `evidence/AP-025-before.png` and `evidence/AP-025-after.png`. |
| AP-026 | P2 | visual-only | A teal blur shows through the sticky header in scrolled mobile captures; whether this is intentional translucency or distracting content bleed is unclear. | The approved Settings Save action is now in the Topbar, and a mobile smoke assertion ensures it remains a single-line action. The unrelated decorative blur remains unconfirmed. Screens: `tests/qa/qa-out/layouts__375___topbar.png` and `tests/qa/qa-out/settings__375___content.png`. |
| AP-027 | P2 | visual-only | The Rendered clip card appears to leave substantial space below the player. | Fixed: constrain the player to a 9:16 frame, cap its dimensions, and use `object-fit: contain`. The final review-conversion state is captured at desktop and mobile sizes. |
| AP-028 | P2 | visual-only | A short vertical stub appeared beside the Accept composition action row, and review actions were not consistently positioned between stages. | Fixed per user approval: remove the group divider; keep the secondary and primary buttons paired at the right of the top-of-panel toolbar on transcript, conversion, and upload review, with the secondary button first. Keep variant/context controls separate on the left. The conversion pair is vertically aligned to the Render variant select within 2 CSS pixels. |
| AP-029 | P2 | visual-only | A small dash appears in the native video control bar in the conversion review; it may be a cursor or browser-control artifact. | User rejected a fix, identifying it as a likely loading-circle artifact. Screens: `tests/qa/qa-out/review-conversion__1920.png` and `tests/qa/qa-out/review-conversion__375___review_player.png`. |
| AP-030 | P2 | measured | The Strict section appeared clipped at the bottom of the conversion review. The detail modal has `scrollHeight=1606` and `clientHeight=992`; at maximum scroll (614px), the last composition block ends at y=987, above the modal bottom at y=1037. | Not confirmed; the content is reachable by scrolling. |
| AP-031 | P1 | measured | When workspace loading fails, all six board columns still say “No jobs” while the Offline badge and “Failed to fetch” alert are visible. The board contains zero cards. | Decision for the human: either replace the empty-board copy with an explicit load-error state and retry action, or retain the current empty columns alongside the global error banner. No copy/state behavior change was made without approval. Evidence: `evidence/AP-031.png`. |

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

## Approved follow-up implementation and final re-audit

Follow-up base: `3d1c4fd` on `ui/autopilot-20261013`. The review manifest selected 95 screenshots across three batches; the independent reviewer found no P0 and one new P1 candidate (AP-031), which browser measurement confirmed. Three final review tables are preserved under `tests/qa/qa-out/review-1.md` through `review-3.md`.

- **AP-023 — fixed, measured:** Upload review disables Submit when no platform is selected, provides a status hint, and store/card actions reject jobs with no supported upload targets. Unsupported configured platform names are excluded. The `review-upload-no-platforms` state covers five viewports. Red/green: the helper regression failed on an unsupported configured platform before the supported-platform filter; smoke assertions failed with 0px hint spacing before the spacing fix; both now pass. Evidence: [after screenshot](./evidence/AP-023-after.png). The baseline screenshot was not retained when `qa-out` was regenerated.
- **AP-024 — fixed, measured:** After all ten bounded polls fail, expected Running remains visible with an accessible “Status unconfirmed” status instead of an indefinite spinner. The resume guard remains active to avoid duplicate approval and clears on a successful authoritative refresh. The E14 harness covers exhaustion and recovery. The transient unconfirmed badge itself was not captured in the screenshot gate.
- **AP-026 — approved action fixed, measured:** Settings Save is registered by SettingsView and rendered in the Topbar. The mobile smoke assertion requires a single-line action no taller than 44px. Red/green: before the nowrap rule, its height was 51.6px; the assertion now passes. The separate sticky-header blur remains an unconfirmed visual observation. Evidence: [after screenshot](./evidence/AP-026-after.png). The baseline screenshot was not retained when `qa-out` was regenerated.
- **AP-027 — fixed, measured:** The review video is constrained to a capped 9:16 frame and uses `object-fit: contain`; the final independent review confirmed the ratio. Evidence: [after screenshot](./evidence/AP-027-after.png). The baseline screenshot was not retained when `qa-out` was regenerated.

**AP-031 measurement:** In the browser with API fetches rejected, the Offline badge and `Failed to fetch` alert appear, but Pending, Transcribe, Convert, Upload, Complete, and Failed each show `0 No jobs`; no cards render. This is a confirmed state/copy mismatch, but the correction changes the meaning and hierarchy of an error state. It remains for a product decision rather than being changed in this approved follow-up.

**Final validation:** `npm --prefix frontend run build` and `npm --prefix frontend run check` passed (0 errors, 0 warnings); `npm --prefix frontend run qa:ui` passed 19 states × 5 viewports = 95 combinations with axe enabled and 0 gate errors (1,934 expected seeded-thumbnail 404 warnings); `python -m unittest discover -s tests -v` passed 718 tests; compileall, structure, docs, Playwright smoke, E14 mocked polling, and `gate-guard.mjs --base 3d1c4fd` passed.

**Review triage:** The disabled upload button’s state was confirmed by DOM measurement (`disabled=true`, opacity `0.5`), despite an initial visual-only concern. Mobile Settings Save wrapping and empty-upload spacing were measured and fixed. No confirmed P0 remains. AP-031 is the one decision requiring human attention; unrelated new P2 visual suggestions remain deferred and are recorded in the final batch review tables.
