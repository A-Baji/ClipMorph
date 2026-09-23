# Changelog

## 0.2.0 - Unreleased

### Added

- Full YAML/JSON run configuration with CLI-over-config precedence.
- Preflight validation and `--dry-run` support.
- Per-platform upload failure reporting with meaningful exit statuses.

### Security

- Standards-compliant TikTok PKCE and OAuth state validation.
- Redacted access and refresh tokens from logs and interactive output.

### Fixed

- Dependency-free `--init` and `--help` startup paths.
- Job-isolated Instagram staging objects with signed URLs and safe cleanup.
