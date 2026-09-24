# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

- Kept `--init` and `--help` startup paths dependency-free.
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

[unreleased]: https://github.com/A-Baji/ClipMorph/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/A-Baji/ClipMorph/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/A-Baji/ClipMorph/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/A-Baji/ClipMorph/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/A-Baji/ClipMorph/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/A-Baji/ClipMorph/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/A-Baji/ClipMorph/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/A-Baji/ClipMorph/releases/tag/v0.1.0
