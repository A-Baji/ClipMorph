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

## Verification expectations

For Python or test changes, run the focused tests first, then the full unittest command and compile check when practical. For CLI or packaging changes, also run the help/init smoke tests and wheel build. Keep test cases deterministic and avoid changing unrelated behavior.

The release version is stored in `[project].version` in `pyproject.toml`. Update it and the matching changelog section in a commit merged to `main` before dispatching the `Build and Release` workflow. The workflow reads that committed version, builds the same commit, and creates its version tag only after all builds succeed; see `docs/RELEASE.md`.

## Harness maintenance

Keep repository guidance itself a single source of truth: update the narrowest existing artifact rather than creating overlapping instructions, and link to authoritative documentation instead of restating it. When a recurring agent failure or repository rule is discovered, update this guide only after confirming it from code, tests, CI, or history. Prefer an executable test or CI check over prose when a rule can be enforced mechanically. Record substantial, user-visible recurring failures under `docs/failures/` with their root cause and detection method; do not create failure notes for ordinary one-off issues.
