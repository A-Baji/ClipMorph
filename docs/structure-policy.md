# Structure policy

This repository’s structure is intentionally derived from the project’s actual architecture, not from a generic Python layout.

## Canonical areas

- `clipmorph/` is the source of truth for the CLI, runtime config, validation, media processing, and upload orchestration.
  - `clipmorph/__main__.py` is the package entry point and top-level workflow coordinator.
  - `clipmorph/cli.py` owns CLI parsing, defaults, and config template generation.
  - `clipmorph/preflight.py` performs input, output, media, and credential validation before execution.
  - `clipmorph/conversion_pipeline/` contains conversion and media-processing logic.
  - `clipmorph/upload_pipeline/` contains upload orchestration and platform-specific behavior.
  - `clipmorph/ffmpeg/` holds bundled FFmpeg/FFprobe assets and runtime helpers.
  - `clipmorph/resources/` and `clipmorph/web_assets/` store packaged runtime assets.
- `tests/` contains the project’s automated unittest coverage and should remain the home for verification code.
- `docs/` contains project documentation, operating guidance, release flow, and architecture notes.
- `quality/` contains the committed Quality Playbook system: requirements, contracts, functional and regression tests, review protocols, audit findings, and reproducible validation evidence.
- `frontend/` contains the optional local browser dashboard and its build configuration. It is a separate app from the Python package and should not absorb Python runtime responsibilities.
- Root-level files such as `README.md`, `pyproject.toml`, `requirements.txt`, `AGENTS.md`, and `LICENSE` define package metadata, user-facing documentation, and repo conventions.
- Local data directories such as `input/`, `output/`, and `uploads/` are runtime working folders for examples and generated assets, not source-code locations.
- `build/` and `clipmorph.egg-info/` are generated packaging artifacts and should be considered build state, not canonical source.

## Placement rules

- New production code belongs under `clipmorph/` unless it is specifically a frontend asset or repository documentation.
- Keep platform-specific upload logic inside `clipmorph/upload_pipeline/` rather than creating new top-level modules.
- Keep conversion work inside `clipmorph/conversion_pipeline/` and supporting FFmpeg helpers under `clipmorph/ffmpeg/`.
- Keep the CLI contract and config logic in `clipmorph/cli.py` and `clipmorph/__main__.py` instead of scattering workflow logic across the repo.
- Keep tests in `tests/` and name them after the feature or module under test.
- Add documentation under `docs/` when a behavior is user-facing or operationally relevant.
- Keep durable quality artifacts under `quality/`; do not move them into `tests/` or `docs/` because they are consumed as a connected playbook rather than as ordinary application tests or user documentation.
- Avoid creating new top-level directories for ordinary source code. If new runtime data directories are needed, prefer existing local data locations or user-specified paths rather than introducing additional repo-root buckets.

## Dependency and architecture constraints

- The Python package remains the runtime boundary. Frontend code under `frontend/` is an adjacent app, not a parallel implementation of the CLI.
- The conversion pipeline and upload pipeline remain internal modules of the package; they should not become root-level services.
- Source code should not be edited inside generated packaging directories or local runtime-output directories unless the work is intentionally part of a release or a developer-local workflow.
- `quality/` is a committed project-quality boundary, but machine-local audit checkpoints under `docs/audit/` and temporary quality-run output should remain ignored unless intentionally promoted into durable evidence.
- Structural changes are justified only when they map to a real architectural boundary, reduce actual coupling, or reflect existing project conventions.

## Validation

The repository runs a deterministic structural check with:

```bash
python scripts/check_structure.py
```

This validator enforces the project’s mechanical rules for allowed top-level directories and canonical source locations. CI also runs the same validation as part of the normal test workflow.

## Allowed exceptions

- Hidden development metadata directories such as `.github/`, `.agents/`, `.claude/`, `.venv/`, and `.git/` are allowed for tooling and local development.
- Root-level local state such as `.env`, `.gitignore`, `.gitattributes`, and certificate/private-key files may exist for workspace configuration or local credentials, but they are not source modules and should remain out of ordinary code changes.
- Local runtime folders such as `input/`, `output/`, and `uploads/` may exist as working directories for the app’s current execution context.
- Generated build outputs may appear in `build/` or `clipmorph.egg-info/` while packaging or working locally, but they are not source-of-truth locations.
