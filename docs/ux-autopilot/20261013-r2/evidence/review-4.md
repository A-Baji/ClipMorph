# UI review 4: Per-platform summary (config badge + subline)

Scope: five screenshots in this folder. Thumbnail fallbacks excluded per user.
Verified by viewing each image in this turn. No DOM or pixel measurements were taken.

| file | location in image | what is wrong | P0/P1/P2 |
|---|---|---|---|
| review-upload__1920.png | Modal bottom edge, about y=1072, under the AI suggestions card | The modal ends directly under the Generate suggestions / Regenerate / Apply all / Clear row. The card's bottom edge and padding are not visible. Possible clipping by a fixed modal height. Can't tell whether this is a scroll container or real overflow without measuring. | P2 (can't tell) |
| review-upload__1366.png | Modal bottom edge, about y=815, through the Platforms label | The modal clips the Platforms row. The label is cut off and the checkboxes are not visible. Can't tell whether the modal body scrolls. | P2 (can't tell) |
| review-upload__1366.png | Per-platform summary rows, sublines | Sublines wrap to two lines ("uploads the rendered / vertical"). The config badge stays on one line and right-aligned. Row heights grow. Wrapping is consistent across rows. Can't tell whether this is intended. | P2 (can't tell) |
| review-upload__1024.png | Modal bottom edge, about y=815, through the Platforms row | Same clipping as 1366. The Platforms row is outside the visible modal area. Can't tell whether the body scrolls. | P2 (can't tell) |
| review-upload__1024.png | Per-platform summary rows, sublines | Same two-line subline wrap as 1366. Consistent across rows. | P2 (can't tell) |
| review-upload__375.png | Header meta row, below "Status fixture: completed" | "updated Oct 13, 2026, 03:27 PM" wraps to its own line. A dangling "·" separator is left at the end of the "status-completed.mp4 ·" line. | P2 |
| review-upload__375.png | Upload draft card, hint text at about y=960–978 | "Leave empty to upload now. A future time defers every selected platform." is cut off at the modal's visible bottom. The second line is partly hidden. Can't tell whether this is scroll clipping. | P2 (can't tell) |
| review-upload__375.png | Per-platform summary | Not visible in this viewport. Can't tell whether stacked placement is intended. | P2 (can't tell) |
| review-upload-no-platforms__1920.png | Helper text "Choose at least one platform to enable upload.", about y=351 | The helper text sits between the Save draft / Submit upload row and the Title label. It pushes Title down. The gap above the Title label (about y=382) looks tighter than the other field gaps. | P2 |
| review-upload-no-platforms__1920.png | Submit upload button, about x=878, y=320 | The button renders in the same full-opacity teal style as the enabled state. The image alone does not show whether it is disabled. Needs a DOM check of the `disabled` attribute or aria state. | P1 (can't tell) |
| review-upload-no-platforms__1920.png | Per-platform summary, all five rows | All five platforms are still listed even though none are selected in the Platforms row. Can't tell whether the summary should reflect only selected platforms. | P2 (can't tell) |

Screens reviewed: 5. Screens with no defects: 0 confirmed. Every screen has at least one item above, and several are marked "can't tell" pending measurement.

Not flagged: the config badge on all rows reads `config e961ea6bb1e4` (12 hex characters, correct format). The same id appears on all five rows. Can't tell whether that is correct, since the config is shared, or a keying bug.
