# ClipMorph Agent Guide

## Project

ClipMorph is a Python 3.11+ CLI that converts gaming videos to vertical short-form content and uploads results to YouTube, Instagram, TikTok, and Twitter/X. The package entry point is `clipmorph.__main__:main`, exposed as the `clipmorph` command by `pyproject.toml`.

The repository workflow uses `dev` as the working and integration branch. All completed work flows from `dev` to `main` through the repository's approved merge process; do not develop directly on `main`.

## Repository map

- `clipmorph/cli.py`: argument parsing, config loading, defaults, and CLI initialization.
- `clipmorph/__main__.py`: top-level workflow orchestration and lazy loading of heavy processing dependencies.
- `clipmorph/preflight.py`: input, output, media, and credential validation before work starts.
- `clipmorph/conversion_pipeline/`: transcription, subtitle generation, editing, and video conversion.
- `clipmorph/upload_pipeline/`: upload coordination and platform-specific integrations.
- `clipmorph/job.py`: resumable job manifests, source identity, artifact state, and per-platform status.
- `clipmorph/ffmpeg/`: bundled platform-specific FFmpeg and FFprobe binaries.
- `tests/`: standard-library `unittest` coverage for CLI behavior, preflight checks, uploads, OAuth helpers, artifacts, and job state.
- `.github/workflows/tests.yml`: the authoritative CI test and package smoke-test sequence.
- `.github/workflows/release.yml` and `docs/RELEASE.md`: versioning, PyInstaller builds, and release procedure.

## Development commands

Run these from the repository root with Python 3.11 or newer:

```text
python -m unittest discover -s tests -v
python -m compileall -q clipmorph
python scripts/check_structure.py
python scripts/check_docs.py
python -m ruff check --select E9,F clipmorph scripts tests quality  # pip install -e ".[dev]"
python -m mypy --ignore-missing-imports clipmorph                   # pip install -e ".[dev]"
python -m clipmorph --help
python -m clipmorph init --config-path <temporary-path>/clipmorph.yaml
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir <temporary-path>/wheel
```

Install runtime dependencies when needed with:

```text
python -m pip install -r requirements.txt
```

The dependency set includes large media and ML packages. Prefer focused unit tests and lazy imports when a change does not require a real conversion or upload.

## Change rules

- Maintain a single source of truth for each rule, configuration value, workflow, and piece of project knowledge. Reference the authoritative location instead of copying it into parallel docs, configs, or implementations; when duplication is unavoidable, generate it or add a check that detects drift.
- Make and publish normal changes on `dev`; merge `dev` into `main` only through the repository's approved merge process.
- Before opening a PR, identify every GitHub issue fully resolved by the PR and include a closing keyword (`Closes #N`, `Fixes #N`, or `Resolves #N`) for each in the PR description. If an issue is only partially addressed, include `Refs #N` without a closing keyword and state the remaining work. Do not rely on comments, labels, or commit messages to close issues.
- Feature-work PRs default to auto-merge after opening (merge-commit method), unless the user asks for manual gating.
- Do not preserve backward compatibility for internal formats, ever: job manifest schemas, config file shapes, layout/job/batch JSON, and internal APIs may change freely. Prefer clean breaking changes over migration shims, versioned dual-read paths, or legacy-format fallbacks. Update the CLI, web API, docs, and tests to match the new shape in the same change instead of keeping old-format handling around.
- Keep the CLI parser, config loader, and documented YAML/JSON configuration shape internally consistent with each other; update all three together when the shape changes rather than preserving an old shape for compatibility.
- Keep media processing behind the conversion pipeline and keep platform API behavior inside the relevant upload platform module. Do not duplicate orchestration in platform implementations.
- Treat preflight as the boundary before conversion or upload. New input, geometry, output, or credential requirements should be validated there when possible.
- Job manifests must retain source identity, artifact state, status, and per-platform results so a successful platform remains distinguishable from a partial failure. This does not require preserving old manifest schema versions.
- Keep heavy imports lazy where the `--help` and `init` subcommand paths do not need them.
- Do not perform live uploads or require real credentials in tests. Mock network clients and platform initialization, and use temporary directories for files and manifests.
- Do not hand-edit generated or local runtime output. Video, audio, subtitle, conversion, upload, build, and package artifacts are local state unless a release workflow explicitly packages them.
- Keep bundled FFmpeg paths and executable permissions platform-specific. Changes to packaging data must be checked against the wheel and release workflows.
- Never commit credentials, `.env` files, OAuth tokens, media files, or generated build output. Follow `.gitignore` and inspect `git status` before finishing.

## Feature scope gate

Recurring failure mode: simple ideas grow into over-built implementations until the app becomes too complex to use. The rules below apply established anti-over-engineering standards to this repository; see the grounding note at the end of this section.

When planning any new feature or new user-visible behavior, treat this as a hard gate:

1. State the user-visible outcome in one sentence, then present the smallest design that delivers it: which existing pipeline stages it touches, any CLI or config surface it adds, and the tests that verify it. "Good enough" is judged against the outcome, and simplicity is the art of maximizing the amount of work not done (Agile Manifesto principle 10).

2. Prefer existing machinery and conventions — pipeline stages, config keys, preflight checks, job manifests, docs. Adding a new module, directory, config layer, abstraction, dependency, or manifest/config field requires a per-item justification against the minimal alternative. Speculative future-proofing ("we might need it later") is not a justification: YAGNI says build for what is needed now and keep the code easy to change instead (Fowler). Do not introduce an abstraction before its third concrete occurrence (the Rule of Three, Don Roberts via Fowler's Refactoring). When two designs both work, include the subtractive option in the comparison; people systematically overlook it (Adams, Converse, Hales, and Klotz 2021, Nature).

3. Stop and get explicit user approval of that minimal design before writing implementation code. An issue whose body already records the approved minimal design (an implementation guide reviewed by the maintainer) satisfies this step — cite the issue and proceed, but stop for anything the guide does not settle that crosses steps 1–4's bar.

4. When the user asks for more, treat it as a scope proposal: state its complexity cost, offer the minimal alternative, and get a decision before building it. Treat the effort as fixed and the scope as the variable ("fixed time, variable scope", Shape Up): shrink the scope rather than inflating the effort. Actively reel the user in instead of silently complying.

5. Mid-implementation expansion repeats step 4; if extra machinery becomes genuinely unavoidable, stop and get approval for the expanded design before continuing.

YAGNI governs speculative flexibility, not code health: refactoring, tests, and tooling that keep the code easy to change are always in scope. Bug fixes, test-only work, and internal cleanups do not need this gate.

Grounding: [Agile Manifesto principle 10](https://agilemanifesto.org/principles.html) (simplicity as "maximizing the amount of work not done"); Fowler, [Yagni](https://martinfowler.com/bliki/Yagni.html) (four costs of presumptive features; origin: Extreme Programming); the [Rule of Three](https://en.wikipedia.org/wiki/Rule_of_three_%28computer_programming%29) (Don Roberts, via Fowler's *Refactoring*); Basecamp, ["Set Boundaries"](https://basecamp.com/shapeup/1.2-chapter-03) in *Shape Up* (appetite, fixed time, variable scope); Adams, Converse, Hales, and Klotz, [People systematically overlook subtractive changes](https://doi.org/10.1038/s41586-021-03380-y), Nature 592:258-261 (2021).

## Verification expectations

For Python or test changes, run the focused tests first, then the full unittest command and compile check when practical. For CLI or packaging changes, also run the help/init smoke tests and wheel build. Keep test cases deterministic and avoid changing unrelated behavior.

The release version is stored in `[project].version` in `pyproject.toml`. Update it and the matching changelog section in a commit merged to `main` before dispatching the `Build and Release` workflow. The workflow reads that committed version, builds the same commit, and creates its version tag only after all builds succeed; see `docs/RELEASE.md`.

## Harness maintenance

Keep repository guidance itself a single source of truth: update the narrowest existing artifact rather than creating overlapping instructions, and link to authoritative documentation instead of restating it. When a recurring agent failure or repository rule is discovered, update this guide only after confirming it from code, tests, CI, or history. Prefer an executable test or CI check over prose when a rule can be enforced mechanically. Record substantial, user-visible recurring failures under `docs/failures/` with their root cause and detection method; do not create failure notes for ordinary one-off issues.
