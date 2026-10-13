# UI round report — 2026-10-13 (second full pass)

## Result

Stopped after the first audit pass plus one fix re-audit: one actionable new item (AP-032), approved and fixed. Branch `ui/autopilot-20261013`, base `a75ba9e`. Nothing pushed; no PR.

## Fixed

- **AP-032 — measured:** upload-review platform summary rows no longer clip their text; the repeated sentence became a `config <id>` badge. Red then green via the smoke test. After: [evidence/AP-032-after.png](./evidence/AP-032-after.png). No before image retained.

- **AP-033 - measured:** double-click on card Approve sent two accept requests; now one. Red then green (smoke).
- **AP-034 - measured, approved:** focus returns to the card's Open button after Approve (was BODY). Red then green (smoke).

## Baseline and validation

- Baseline: 95 combinations (19 states × 5 viewports), 0 errors; 718 tests.
- `npm --prefix frontend run build` — passed.
- `npm --prefix frontend run check` — passed, 0 errors/warnings (baseline run).
- `npm --prefix frontend run qa:ui` — passed after the fix, 0 errors (all 95 combinations; warnings were seeded-thumbnail 404s).
- `python -m unittest discover -s tests` — OK, 718 tests (before and after).
- `python -m compileall -q clipmorph tests\qa`, `python scripts/check_structure.py`, `python scripts/check_docs.py` — passed.
- `node tests/e2e/smoke.js` — failed first on the new assertion (clipped 20px), then passed.
- `node .github/skills/ui-dev-qa/scripts/gate-guard.mjs --base a75ba9ed6258b86f69fe5f3683c8de43e8387f19` — OK after the fix.

## Pending decisions

- **AP-035 (P2, measured):** nowrap the `0 override(s)` hint (`tests/qa/qa-out/new-modal-configure__1920.png`). User asked if text would be cut off; answer: no, with `flex-shrink:0` the heading shrinks instead. Awaiting approval.

## Deferred

See [findings.md](./findings.md): P2 visual-only follow-ups (configure-modal "override(s)" wrapping, Settings/layout polish).

## Human attention needed

- **AP-031 (P1, measured), still undecided:** (A) replace the "No jobs" columns with a load-error state and retry, or (B) keep empty columns plus the banner. Evidence: `docs/ux-autopilot/20261013/evidence/AP-031.png`.

## Not verified

Live uploads/credentials; SSE/status truthfulness; dark-mode contrast; real screen-reader output; full keyboard journeys. The reviewer's screenshot-only items marked "can't tell" were triaged from code and smoke assertions rather than measured individually. First-audit reviewer tables and canary files were overwritten by the rerun of `qa:ui` and are summarized in findings.md. The canary review table was condensed by me before scoring; it scored 5/6 (C3 missed), above the 4 needed.

## Reviewer and gate integrity

`ui-reviewer`, canary 5/6 (PASS). Four dispatches in total (three batch reviews and one re-audit of the changed upload-review screens). No threshold, state, or viewport was changed, and no allowlist entry was added; gate-guard passed.

Extended pass: no further reviewer dispatches were made (total remains four); the extra depth came from Playwright measurements. Post-fix: build, check (0 errors), qa:ui (exit 0), 718 unittest OK, smoke, gate-guard OK.
