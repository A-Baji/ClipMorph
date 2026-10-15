# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] - 2026-10-14

### Added

- Added inline job configuration overrides, per-platform settings, and separate app/auth template regeneration.
- Added `clipmorph doctor` and opt-in credential checks with `clipmorph auth status --probe`.
- Added configurable artifact storage, platform-scheduled uploads, and per-attempt schedule cancellation.
- Added optional AI-assisted metadata and caption suggestions, plus Facebook Login for Business configuration.
- Added a native Windows desktop app.

### Changed

- **Breaking:** Job operations now use `job create|list|get|update|delete|run` plus `job artifacts`. Standalone resume, review, render, upload, metrics, suggestion, and scheduled-cancellation commands were removed.
- `job create` now creates jobs without running them by default. Use `job run` for interactive review and pipeline execution; `--yes` runs and accepts each review step automatically.
- **Breaking:** The auth schema now stores shared Meta credentials under `meta:`. Instagram Reels use Meta resumable uploads instead of Google Cloud staging; the old GCS/GCP credentials are no longer used.
- **Breaking:** Job manifest schema version 3 stores artifact references through the configured storage backend.
- Redesigned the dashboard job board and wizard, added live job updates, and made conversion settings editable with a re-render before approval.
- Improved dashboard accessibility, error recovery, and layouts on narrow or zoomed screens.
- Parallel uploads now share a progress display and show per-platform outcomes; CLI status and job details use clearer tables.

### Fixed

- Fixed credential checks to use configured auth-file values and prevent empty environment variables from overriding them.
- Fixed OAuth and upload failures affecting Facebook, TikTok, and Twitter, including stale tokens, duplicate authentication, and Twitter token persistence.
- Fixed transcription failures after clean transcripts on Windows/CUDA and handling of numeric timestamps in transcript data.
- Fixed conversion jobs getting stuck after checkpoint synchronization.
- Fixed captions containing special characters that could break FFmpeg rendering.

## [0.5.0] - 2026-09-26

### Added

- Added resumable job checkpoints for transcript, composition, and upload review.
- Added dashboard editing for per-source settings, transcripts, composition, and upload drafts.
- Added shared CLI and dashboard workflows for configuration validation, layouts, multi-source jobs, and job management.

### Changed

- **Breaking:** Replaced flat configuration with shared `app.yml` defaults and per-job overrides saved in each job's `job.yml`. Multi-source submissions now create independent jobs.

### Fixed

- Fixed confirmation handling and caption panel spacing.
- Reported duplicate per-source configuration records instead of ignoring them.

## [0.4.3] - 2026-09-25

### Fixed

- Fixed platform credential defaults, conversion settings, and CLI/dashboard behavior.
- Fixed empty upload defaults and persistence of resumable job manifests.

## [0.4.2] - 2026-09-24

### Added

- Added separate CLI and dashboard executables for Windows, macOS, and Linux, plus the `clipmorph-ui` launcher and `clipmorph[web]` install extra.

### Fixed

- Fixed missing conversion, FFmpeg, and upload packages in wheels and startup failures in frozen executables.

## [0.4.1] - 2026-09-24

### Added

- Added dashboard workflows for source selection, dry runs, layouts, artifacts, uploads, retries, job controls, and credential health.
- Added dashboard assets to UI packages without changing the CLI-only installation path.

## [0.4.0] - 2026-09-24

### Added

- Added resumable jobs and a local API for job status, artifacts, and per-platform uploads.
- Added transcript editing and review, including word-level annotations.
- Added configurable crop and caption layouts.
- Added a local dashboard for jobs, settings, credentials, artifacts, uploads, and retries.
- Added platform capability checks for upload requirements and metadata.

## [0.3.0] - 2026-09-23

### Added

- Added YAML/JSON configuration, CLI overrides, and configurable transcription settings.
- Added batch processing with deduplication, preflight validation, and dry runs.
- Added default upload settings for YouTube, Instagram, and TikTok.

### Changed

- Conversion now reports transcription degradation instead of silently continuing.

### Fixed

- Fixed per-platform upload failures reporting incorrect exit statuses.

## [0.2.0] - 2026-09-23

### Security

- Added TikTok PKCE and OAuth state validation.
- Redacted access and refresh tokens from logs and interactive output.

### Fixed

- Kept `init` and `--help` usable without loading conversion dependencies.
- Isolated Instagram staging, TikTok upload streams, and per-job media artifacts.
- Persisted source-specific job manifests with artifact and per-platform status.

## [0.1.2] - 2026-09-23

### Fixed

- Avoided FFmpeg setup for CLI help and configuration initialization.

## [0.1.1] - 2026-09-23

### Fixed

- Fixed runtime dependency packaging.

[unreleased]: https://github.com/A-Baji/ClipMorph/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/A-Baji/ClipMorph/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/A-Baji/ClipMorph/compare/v0.4.3...v0.5.0
[0.4.3]: https://github.com/A-Baji/ClipMorph/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/A-Baji/ClipMorph/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/A-Baji/ClipMorph/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/A-Baji/ClipMorph/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/A-Baji/ClipMorph/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/A-Baji/ClipMorph/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/A-Baji/ClipMorph/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/A-Baji/ClipMorph/compare/v0.1.0...v0.1.1
