# ClipMorph Agent Guide

## Project

ClipMorph is a Python 3.11+ CLI that converts gaming videos to vertical short-form content and uploads results to YouTube, Instagram, TikTok, and Twitter/X. The package entry point is `clipmorph.__main__:main`, exposed as the `clipmorph` command by `pyproject.toml`.

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
python -m clipmorph --init --config-path <temporary-path>/clipmorph.yaml
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir <temporary-path>/wheel
```

Install runtime dependencies when needed with:

```text
python -m pip install -r requirements.txt
```

The dependency set includes large media and ML packages. Prefer focused unit tests and lazy imports when a change does not require a real conversion or upload.

## Change rules

- Maintain a single source of truth for each rule, configuration value, workflow, and piece of project knowledge. Reference the authoritative location instead of copying it into parallel docs, configs, or implementations; when duplication is unavoidable, generate it or add a check that detects drift.
- Preserve the CLI contract and documented YAML/JSON configuration shape. Add or update focused tests when changing parsing, defaults, validation, or initialization behavior.
- Keep media processing behind the conversion pipeline and keep platform API behavior inside the relevant upload platform module. Do not duplicate orchestration in platform implementations.
- Treat preflight as the boundary before conversion or upload. New input, geometry, output, or credential requirements should be validated there when possible.
- Preserve resumability: job manifests must retain source identity, artifact state, status, and per-platform results. A successful platform must remain distinguishable from a partial failure.
- Keep heavy imports lazy where the `--help` and `--init` paths do not need them.
- Do not perform live uploads or require real credentials in tests. Mock network clients and platform initialization, and use temporary directories for files and manifests.
- Do not hand-edit generated or local runtime output. Video, audio, subtitle, conversion, upload, build, and package artifacts are local state unless a release workflow explicitly packages them.
- Keep bundled FFmpeg paths and executable permissions platform-specific. Changes to packaging data must be checked against the wheel and release workflows.
- Never commit credentials, `.env` files, OAuth tokens, media files, or generated build output. Follow `.gitignore` and inspect `git status` before finishing.

## Verification expectations

For Python or test changes, run the focused tests first, then the full unittest command and compile check when practical. For CLI or packaging changes, also run the help/init smoke tests and wheel build. Keep test cases deterministic and avoid changing unrelated behavior.

A release version is stored in `clipmorph/__version__.py`. Do not change it as part of ordinary feature work. Releases are run through the manually dispatched `Build and Release` workflow described in `docs/RELEASE.md`; the workflow updates the version, builds platform artifacts, and creates the tag only after builds succeed.

## Harness maintenance

Keep repository guidance itself a single source of truth: update the narrowest existing artifact rather than creating overlapping instructions, and link to authoritative documentation instead of restating it. When a recurring agent failure or repository rule is discovered, update this guide only after confirming it from code, tests, CI, or history. Prefer an executable test or CI check over prose when a rule can be enforced mechanically. Record substantial, user-visible recurring failures under `docs/failures/` with their root cause and detection method; do not create failure notes for ordinary one-off issues.
