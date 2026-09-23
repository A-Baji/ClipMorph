# Changelog

## 0.2.0 - Unreleased

### Added

- Full YAML/JSON run configuration with CLI-over-config precedence.
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
