# Changelog

## 0.4.0

### Added

- Source-bound job service foundation with platform-aware data storage, versioned artifacts, persisted step state, cancellation, and FastAPI endpoints.
- Versioned transcript edit sessions with immutable originals, strict timing validation, per-word annotations, and reviewed-transcript rendering through the CLI and API.
- Composable crop/caption layout validation and rendering with fit, stretch, none, overlay, background, and timed caption support.
- Versioned platform capability policy with artifact validation, per-platform blockers, warnings, metadata transformations, and derived-artifact policy hooks.
- Svelte/Vite local dashboard shell with queue, job detail, destination status, configuration forms, advanced settings, and system theme support.
- Dashboard API parity slices for masked credential health, artifact management, asynchronous uploads, and per-platform retries.

### Validation

- Required CI checks passed for the merged implementation PRs.
- Dashboard visual review completed at 375px, 768px, and 1280px viewports.

### Scope note

- Issues #34, #98, #99, and #104 remain open for their remaining full-acceptance work; this release contains the completed implementation increments merged during the 0.3.1 cycle.

## 0.3.0

### Added

- Full YAML/JSON run configuration with CLI-over-config precedence.
- Centralized default values for YouTube, Instagram, and TikTok platform settings.
- Configurable transcription language/model/device/compute settings and dry-run reporting of effective runtime values.
- Batch processing entry point with deduplication and bounded concurrency controls.
- Preflight validation and `--dry-run` support.
- Strict conversion mode and explicit transcription degradation warnings.
- Per-platform upload failure reporting with meaningful exit statuses.

### Security

- Standards-compliant TikTok PKCE and OAuth state validation.
- Redacted access and refresh tokens from logs and interactive output.

### Fixed

- Dependency-free `--init` and `--help` startup paths.
- Job-isolated Instagram staging objects with signed URLs and safe cleanup.
- Streaming TikTok uploads with bounded memory usage and retry-safe file reopening.
- Job-scoped subtitle artifacts and collision-resistant converted output names.
- Persistent source-hashed job manifests with artifact and per-platform state.
- Automated unittest, compilation, CLI, and package-install checks in CI.

## 0.2.0 - Unreleased

### Added

- Full YAML/JSON run configuration with CLI-over-config precedence.
- Centralized default values for YouTube, Instagram, and TikTok platform settings.
- Configurable transcription language/model/device/compute settings and dry-run reporting of effective runtime values.
- Batch processing entry point with deduplication and bounded concurrency controls.
- Preflight validation and `--dry-run` support.
- Strict conversion mode and explicit transcription degradation warnings.
- Per-platform upload failure reporting with meaningful exit statuses.

### Security

- Standards-compliant TikTok PKCE and OAuth state validation.
- Redacted access and refresh tokens from logs and interactive output.

### Fixed

- Dependency-free `--init` and `--help` startup paths.
- Job-isolated Instagram staging objects with signed URLs and safe cleanup.
- Streaming TikTok uploads with bounded memory usage and retry-safe file reopening.
- Job-scoped subtitle artifacts and collision-resistant converted output names.
- Persistent source-hashed job manifests with artifact and per-platform state.
- Automated unittest, compilation, CLI, and package-install checks in CI.
