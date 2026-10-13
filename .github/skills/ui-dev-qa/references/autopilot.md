# Autopilot mode: hands-off UI refinement

Goal: audit, fix, and re-audit a UI with no human input. The human reads one final
report. Everything below is a rule, not a suggestion; the policy exists so you never
need to ask. `<skill>` means the installed skill folder (for example
`.github/skills/ui-dev-qa`). Run scripts from the folder where `playwright` is installed.

## Hard rules

- Never call Ask User and never wait for a reply. If you cannot continue, change nothing
  further and end with a message that starts with `BLOCKED:` (what failed, what you
  checked, options A and B).
- Work on a new branch `ui/autopilot-<YYYYMMDD>`. Never push, open PRs, or file issues.
  Never commit to `dev` or `main`.
- Scope: frontend source, styles, and `tests/qa` config and fixtures. No backend, API,
  schema, dependency, or CI changes. Never hand-edit built assets; run the build.
- Never open screenshots yourself. Only the reviewer subagent opens images.
- Never loosen the gate. After every fix run
  `node <skill>/scripts/gate-guard.mjs --base <start-sha>`; if it fails, undo the change.
- No live uploads or real credentials; mocks and temp dirs only.

## Phase 0: preflight

1. List the skill's files and confirm `SKILL.md`, `scripts/` (qa-ui, canary, review-manifest,
   gate-guard), `canary/canary.html`, and both references exist. If not: `BLOCKED:`.
2. `git status` must be clean. Create the branch and record the start SHA in
   `docs/ux-autopilot/<date>/base-sha.txt`.
3. Run the project's build, `qa:ui`, and tests once as a baseline. If they are already
   failing for reasons unrelated to UI polish, record that and continue only if `qa:ui`
   itself can run; otherwise `BLOCKED:`.
4. Calibrate the reviewer (no human involved):
   `node <skill>/scripts/canary.mjs shoot --out qa-out/canary`, dispatch the `ui-reviewer`
   subagent on those two images with the rubric, save its table to `qa-out/canary/review.md`,
   then `node <skill>/scripts/canary.mjs score qa-out/canary/review.md`.
   - PASS: use `ui-reviewer` for the run.
   - FAIL: repeat with `ui-reviewer-fallback` if that agent exists.
   - Both fail or no reviewer available: continue in measured-only mode. Visual review is
     then listed as "not run" in the report. Do not review images yourself.

## Phase 1: audit pass

1. Run `qa:ui` and save the report. Group warnings by check; fix noise sources in config
   (with a written `reason`) so real warnings are visible.
2. `node <skill>/scripts/review-manifest.mjs --dir <qa-out> --batch 40`.
3. Dispatch the reviewer once per manifest batch (at most 3 per pass). Each reviewer writes
   its table to `<qa-out>/review-<n>.md` using `references/review-rubric.md`.
4. Merge gate output and reviewer tables into `docs/ux-autopilot/<date>/findings.md`.
   One finding per root cause (merge duplicates across viewports). IDs: AP-001, AP-002...
   Label each finding `measured` or `visual-only`.

## Phase 2: automatic triage (replaces the human)

| Finding | Action |
|---|---|
| Gate ERROR | Fix now |
| Visual-only P0/P1 | Measure it first (bounding boxes or computed styles with a throwaway Playwright snippet). If measurement confirms, or it appears in 2+ images of the same surface, fix now. Otherwise list as "unconfirmed" |
| P2 | Fix now only if it shares a root cause with a fixed item, or touches at most 2 files. Otherwise follow-up list |
| P3 | Follow-up list |
| Changes navigation, layout structure, copy meaning, or removes a feature | "Decisions for the human" list. Never implement |
| Needs backend/API/dependency change | Follow-up list |

Cap: at most 15 root causes fixed per pass. The rest go to the follow-up list.

## Phase 3: fix loop

For each root cause to fix:

1. Failing check first when the gate can express it: add or extend a QA state so the gate or
   a unit test fails. If the gate cannot detect it, say so in the finding.
2. Smallest change, built from design tokens and existing components.
3. Rebuild, run `qa:ui` and the project's tests, then `gate-guard.mjs`.
4. Green: commit with `ui(AP-00X): <summary>`.
   Red or guard failure: undo that change (`git reset --hard` to the previous commit), mark
   the finding `fix failed` with the reason, and move on.

## Phase 4: re-audit

Re-run `qa:ui`, rebuild the manifest, and dispatch the reviewer only on states whose files
changed. Merge new findings into `findings.md` and triage them with the same table.

## Stop conditions (stop at the first that applies)

1. `qa:ui` exits 0 and the reviewer reports no P0 or P1 on two consecutive passes.
2. Three passes have run.
3. A pass fixed nothing and found nothing new.
4. The same finding failed to fix twice.

## Final report: `docs/ux-autopilot/<date>/report.md`

Commit it with the findings file. It is the only thing the human reads, so keep it short:

- Result: stop condition reached, branch name, commit count, final `qa:ui` and test results.
- Fixed: ID, one line, before and after evidence paths (copy one before/after crop pair per
  fixed item into `docs/ux-autopilot/<date>/evidence/`).
- Deferred: follow-up list and unconfirmed list, each with severity.
- **Human attention needed** (at most 5 bullets): items from the decisions list, any
  `BLOCKED:` conditions, any `fix failed` items.
- Not verified: live SSE/status truthfulness, keyboard flows beyond the focus check, dark-mode
  contrast, and anything run in measured-only mode.
- Gate integrity: allowlist entries added (with reasons) and the `gate-guard` result.
- Reviewer: which agent ran, canary score, number of dispatches.
