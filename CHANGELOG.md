# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added `clipmorph/platforms.py` as the single source of truth for the supported platform set, per-platform upload defaults, and `upload.platforms` include/exclude resolution; CLI, workflow, service, configuration, and web surfaces consume it.
- Added `scripts/check_docs.py` and CI documentation health checks for broken relative links, encoding mojibake, and duplicated doc passages.
- Added ruff (E9,F), typed mypy (0 issues across `clipmorph/`), and coverage reporting as CI gates, a `dev` package extra for the tooling, and CI runs on `dev` pushes.
- Added the authentication setup guide `docs/AUTHENTICATION.md` with step-by-step credential generation for every provider section of `auth.yaml`.

### Changed

- Resolve configuration sidecars by `general.source` instead of filename, allowing arbitrary `.yml`/`.yaml` names and distinct same-stem sources; duplicate sidecars for one source are rejected.
- Rewrote the README feature and configuration sections to the 0.5.0 layered-configuration and checkpoint model, listing the full `job`/`layout` command families; dry-run wording now matches what the implementation validates (source selection and configuration).
- Split `tests/test_cli.py` into focused modules named after the units they cover: `test_preflight.py`, `test_upload_platforms.py`, `test_oauth.py`, `test_service.py`, `test_job_manifest.py`, `test_transcription.py`, and `tests/test_platforms.py`.
- Extracted upload attempt execution into `clipmorph/upload_attempts.py`; upload attempts now record real per-platform start/completion timestamps instead of backfilling them.
- Documented the tagged GitHub repository as the current install channel for `clipmorph` and `clipmorph[web]`, noting PyPI publication as planned future work.
- Removed `clipmorph/batch.py`: multi-source fan-out lives in `JobService.create_jobs`, and no documentation now claims BatchProcessor participates in job creation.

### Fixed

- Fixed audit-grade wheel builds, upload pipeline, job manifest, and FFmpeg helper type findings surfaced by mypy (83 flagged issues resolved across cli, service, web, and platform adapters); web routes validate that `configuration` and `patch` payloads are objects before applying them.
- Repaired duplicated and interleaved corrupted passages in `docs/CONFIG_LAYERS.md`.
- Reimplemented the empty-platform-include regression against the current `submit_upload` contract (upload fan-out boundary), replacing the stale expected-failure harness pinned to the pre-0.5.0 API; `quality/test_functional.py` follows the current CLI surface.

## [0.5.0] - 2026-09-26

### Added

- Added per-job transcript, composition, and upload review checkpoints with revision checks, resumable state, immutable artifacts, and append-only upload history.
- Added dashboard controls for per-source job overrides, transcript timing and typography, composition review, and upload drafts.
- Added shared CLI and web API workflows for configuration validation, source fan-out, layout management, and job lifecycle operations.

### Changed

- **Breaking:** Replaced the flat configuration model with `app.yml` defaults and per-job overrides, finalized in each job's `job.yml`. Multi-source creation now creates independent jobs without persistent batch state.

### Fixed

- Corrected step-specific confirmation fallback and stacked caption panel padding.
- Reported duplicate per-source configuration records instead of silently ignoring them.

## [0.4.3] - 2026-09-25

### Fixed

- Fixed platform auth handling and default credential setup for upload flows.
- Fixed conversion option defaults and CLI/UI compatibility issues affecting local runs.
- Fixed empty upload defaults and data-directory manifest persistence for resumable jobs.
- Tightened the structure-policy validation so optional repo files no longer block valid checks.

## [0.4.2] - 2026-09-24

### Added

- Added separate CLI and UI executable variants for Windows, macOS, and Linux; the UI variant bundles the local dashboard and launches it through the default browser, while the CLI variant remains free of web assets and web-only dependencies.
- Added the `clipmorph-ui` launcher and the `clipmorph[web]` installation path for local dashboard use, while retaining `clipmorph web` for headless service startup.

### Fixed

- Fixed Python wheels omitting ClipMorph conversion, FFmpeg, and upload subpackages, which caused installed web and UI entry points to fail at runtime.
- Fixed frozen executable startup failures caused by excluding the `setuptools` runtime dependencies required by `pkg_resources`.

## [0.4.1] - 2026-09-24

### Added

- Functional local dashboard workflows for source-picker submission, dry-run validation, layouts, artifacts, uploads, retries, lifecycle controls, and platform credential health.
- Checked-in CLI-to-web parity matrix and differential configuration tests.
- UI-enabled package asset build while preserving the CLI-only installation path.

## [0.4.0] - 2026-09-24

### Added

- Source-bound job service with platform-aware data storage, versioned artifacts, persisted step state, cancellation, and FastAPI endpoints.
- Versioned transcript edit sessions with immutable originals, strict timing validation, per-word annotations, and reviewed-transcript rendering through the CLI and API.
- Composable crop and caption layout validation and rendering with fit, stretch, none, overlay, background, and timed caption support.
- Versioned platform capability policy with artifact validation, per-platform blockers, warnings, metadata transformations, and derived-artifact policy hooks.
- Svelte/Vite local dashboard with queue, job detail, destination status, configuration forms, advanced settings, and system theme support.
- Dashboard support for credential health, artifact management, asynchronous uploads, and per-platform retries.

## [0.3.0] - 2026-09-23

### Added

- Full YAML/JSON run configuration with CLI-over-config precedence.
- Centralized default values for YouTube, Instagram, and TikTok platform settings.
- Configurable transcription language, model, device, and compute settings with dry-run reporting of effective runtime values.
- Batch processing with deduplication and bounded concurrency controls.
- Preflight validation and `--dry-run` support.

### Changed

- Conversion now uses strict mode and reports explicit transcription degradation warnings.

### Fixed

- Per-platform upload failures now report meaningful exit statuses.

## [0.2.0] - 2026-09-23

### Security

- Added standards-compliant TikTok PKCE and OAuth state validation.
- Redacted access and refresh tokens from logs and interactive output.

### Fixed

- Kept the `init` subcommand and `--help` startup paths dependency-free.
- Used job-isolated Instagram staging objects with signed URLs and safe cleanup.
- Streamed TikTok uploads with bounded memory use and retry-safe file reopening.
- Isolated subtitle artifacts and converted output names by job.
- Persisted source-hashed job manifests with artifact and per-platform state.

## [0.1.2] - 2026-09-23

### Fixed

- Avoided FFmpeg setup for CLI help and configuration initialization commands.

## [0.1.1] - 2026-09-23

### Fixed

- Corrected packaged dependency handling and release-build compatibility.

## [0.1.0] - 2026-02-21

### Changed

- Updated the initial automated build and release workflow.

[unreleased]: https://github.com/A-Baji/ClipMorph/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/A-Baji/ClipMorph/compare/v0.4.3...v0.5.0
[0.4.3]: https://github.com/A-Baji/ClipMorph/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/A-Baji/ClipMorph/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/A-Baji/ClipMorph/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/A-Baji/ClipMorph/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/A-Baji/ClipMorph/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/A-Baji/ClipMorph/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/A-Baji/ClipMorph/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/A-Baji/ClipMorph/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/A-Baji/ClipMorph/releases/tag/v0.1.0
