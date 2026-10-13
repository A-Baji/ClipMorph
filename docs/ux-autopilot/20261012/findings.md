# UI autopilot findings

Base: `2e4bd8c995570868c0b44e43a734e729e8973633`  
Scope: 16 configured states × 5 viewports. The gate ran 80 state/viewport combinations and captured 240 images; the manifest selected 80 for visual review and skipped 160.

## Gate

- **measured — PASS:** 0 errors across all 80 combinations; axe was enabled.
- **measured — warning noise:** 1,626 warnings, all `thumbnail 404 (seeded fixture fallback, expected)`. The QA runner emits these for intentionally synthetic fixture thumbnails; no other warning category appeared. The current UI-QA config has no supported control for this console-warning path, so no ineffective allowlist entry was added.
- **measured — gate integrity:** no UI-QA states, viewports, thresholds, or allowlist entries changed. `gate-guard.mjs` passed; the original base commit has no UI-QA config, so the guard reported that config comparison was unavailable.
- The final `qa:ui` process exited 0 and reported 0 gate errors. Windows logged a non-fatal Proactor `ConnectionResetError [WinError 10054]` during harness shutdown.

## Findings and triage

| ID | Severity | Evidence type | Finding | Triage |
| --- | --- | --- | --- | --- |
| AP-001 | P1 | measured | The expanded Failed grid appeared to have three cards per row at 375px. Browser measurement showed a 343px grid with one 343px column, one card per row, and no page overflow. | Not confirmed; no change. |
| AP-002 | P1 | measured | The mobile Settings Save button appeared hidden behind the sticky header. At 375×812, the topbar ends at y=85 and Save is at y=117–152; it is outside and below the header. | Not confirmed; no change. |
| AP-003 | P1 | measured | The New modal appeared clipped, its first Configure chip overlapped by the sticky header, and the page below appeared undimmed. At 375×812 the modal fits within y=41–771, scrolls internally, and the chip is below the header. At 1920×1080 the fixed scrim bounds exactly match the viewport. The modal's scroll height is 1,101px against a 970px client height; at maximum scroll the final action remains inside the modal with a 57px gap. | Capture/scroll-position artifacts; not confirmed, no change. |
| AP-004 | P1 | measured | Clip filenames appeared to overflow their tiles. The first measurement missed two unbreakable underscore-containing labels; the final reviewer found horizontal overflow of 139px in 128px labels. | Fixed with `overflow-wrap: anywhere`; all 21 labels now fit their boxes and retain their full `title`. |
| AP-005 | P2 | measured | Long filenames initially created 232.5px clip tiles beside ordinary 78–85.5px tiles at 1920px; truncated job titles lacked hover disclosure. | Fixed with two-line clip-name clamping, full-name titles, and job-title hover disclosure. A later review exposed the separate AP-004 unbreakable-word overflow, now also fixed. Evidence: `evidence/AP-005-before.png`, `evidence/AP-005-after.png`, `evidence/AP-005-overflow-before.png`, and `evidence/AP-005-overflow-after.png`. |
| AP-006 | P1 | measured | At 375×812 the New modal's content had `scrollWidth=330` vs `clientWidth=303`; the 280px transient-path input forced the wizard wider than the modal, with a clip tile extending 2.5px beyond the modal edge. | Fixed with a narrow-screen input minimum of 0 and a flexing input; the wizard content now measures 303px by 303px and the wrapped action row remains right-aligned. Evidence: `evidence/AP-006-before.png` and `evidence/AP-006-after.png`. |
| AP-007 | P2 | visual-only | Job-card action rows appear inconsistently inset relative to thumbnails/titles; some expanded cards appear tight at the lower edge. | Follow-up: low-confidence spacing observations; no single demonstrated shared cause. |
| AP-008 | P2 | visual-only | Compact board empty columns use a short “No jobs” label while an expanded empty stage uses a full icon/title/body state. | Follow-up: compact-vs-expanded treatment may be intentional; defer consistency decision. |
| AP-009 | P2 | visual-only | Several captures show fixture titles/status words and platform labels that look like raw data. The reviewed names are explicitly seeded test fixtures; the implementation humanizes platform names. | Follow-up: no production-data defect established; changing user-visible naming is outside this polish pass. |
| AP-010 | P2 | visual-only | Settings/Layout captures show blank bands, uneven card heights, and a Save action separated from its form. | Follow-up: structural page-spacing changes are broader than a two-file polish fix. |
| AP-011 | P2 | visual-only | Offline alert text/close control and the mobile topbar pill appear vertically crowded or misaligned. | Follow-up: no measurable overlap/error was reported by the gate; defer absent a confirmed defect. |
| AP-012 | P2 | visual-only | Review and Configure captures show small helper text, uneven nested-control alignment, unclear empty media/placeholder regions, and a low-contrast subtitle under “Select clips.” | Follow-up: includes fixture/media ambiguity and potential information-hierarchy changes. |
| AP-013 | P2 | visual-only | Metrics empty-state captures show a large blank region and small platform filter chips. | Follow-up: no published metrics is an intentional seeded empty state; defer chart/layout changes. |
| AP-014 | P1 | measured | At 375px, the wizard header wraps into three rows; the discard action is alone on the final row. After AP-006, the header is 270.5px wide and 151.8px tall, with the action aligned to the right. | Confirmed visual concern, but reducing the row count requires changing responsive header layout structure. Human decision; no structural change made. |
| AP-015 | P1 | measured | The transient path looked clipped at 375px. Browser measurement showed the input value is empty; the visible `D:\videos\clip.mp4` text is the placeholder in a 136px input. | Not an entered-path truncation defect; no change. |
| AP-016 | P2 | visual-only | The “0 selected” count uses monospace while nearby controls use sans-serif; the selection controls also appear small and low-contrast. | Follow-up; no measured accessibility failure or interaction issue. |
| AP-017 | P2 | visual-only | The active step-number badge appears too dark to distinguish from the background. | Follow-up; requires a contrast/design-token decision. |
| AP-018 | P2 | visual-only | “Discard draft” looks similar to the “Back to jobs” navigation action. | Follow-up; destructive-action styling decision. |
| AP-019 | P2 | visual-only | Checkbox and thumbnail positions appear to vary slightly between clip tiles. | Follow-up; small alignment polish, not measured as overflow or overlap. |
| AP-020 | P2 | visual-only | The mobile step badge appears to touch the left edge of its crop; the reviewer could not distinguish crop framing from container alignment. | Unconfirmed crop-boundary observation; no change. |

## Final re-review and stop condition

The third and final reviewer pass covered five `new-modal-clips` screenshots and reported five P1 and six P2 observations. AP-004 was confirmed and fixed; AP-014 is confirmed but requires a human decision about responsive header structure. AP-003 and AP-015 were measured and not confirmed as defects. The remaining P2 observations are recorded above. The three-pass limit was reached; no fourth visual review was run after the AP-004 overflow correction.
