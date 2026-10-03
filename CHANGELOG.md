# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Breaking:** `auth.yaml` schema version `2` stores the shared Meta app and Page token once under a new `meta:` section (`FACEBOOK_*` environment keys), so the facebook and instagram adapters resolve one credential block instead of duplicated sections; `instagram:` keeps only its `GCS_*`/`GCP_*` hosting fields, `auth set facebook`/`auth set instagram` prompt the shared fields and route them into `meta:`, and a `facebook:` section or a Meta field inside `instagram:` is refused with the actionable version error instead of migrated. Adapters, preflight, probes, and the credentials routes are unchanged (they read the same environment keys).
- `clipmorph job resume` and `clipmorph job review` are removed; `clipmorph job run ID [--yes] [--json]` is the only pipeline-running command. At a review gate it shows the checkpoint content and prompts `[y] accept, [e] edit, [q] stop` (an edit object is a YAML/JSON file path; a conversion accept addresses every awaiting group), so one interactive command reaches the landed status; `--yes` accepts every gate and submits the upload attempts immediately; a future `schedule.publish_at` still defers. Non-terminal input requires a TTY or `--yes`, and the command reports the landed manifest and exits `1` when the run failed. Web endpoints are unchanged.
- `clipmorph job create` now only creates the resource: without `--yes` no pipeline runs and the rows report the creation outcome (`created`). With `--yes` — equivalent to `general.no_confirm = true` on every created job — the pipeline runs during the command, auto-accepts each review gate it reaches (including submitting the upload attempts instead of parking at the upload review gate; a future `schedule.publish_at` still defers to its timer), and the rows report the final status landed; the command exits `1` when a created job failed. Previously every creation ran transcription and a synchronous failure was hidden behind `Job created`. A `created` job is actionable through `job run`.
- Parallel CLI uploads now report into ONE combined progress bar instead of one bar per adapter, which previously overwrote each other. The bar's total is 100% per platform the submission will upload, its postfix lists every platform's own percent under the canonical platform title, and each platform's final outcome is logged (a silent console between errors previously looked hung). The bar belongs to the submission instead of to one artifact binding, so a per-platform upload option (a different privacy level, a different content kind) or a separate vertical no longer splits a run into several bars. The submission declares all of its platforms before the first binding runs, so the total and the description never change while the bar is on screen: a binding that runs later shows `0%` instead of the bar reaching 100%, pausing, and then widening as a new platform appeared, and a platform that never uploads stays at `0%` rather than the bar claiming an upload that did not happen. A caller-supplied progress callback no longer suppresses CLI progress: it only records percents, so the job's live-progress recorder and the CLI bar are fed from the same hook. Both bars pass tqdm's `disable=None` and size themselves to the terminal rather than to a fixed 100 columns (a wide postfix was clipped, hiding the last platform's percent), so a server log or redirected output shows progress only through the callback and keeps its records in the log stream. Per-platform outcomes and adapter messages print through the bar instead of being overwritten by its redraws, the adapters' interpolated upload/processing updates reach the bar through the shared progress sink, so the bar keeps moving during the long upload instead of freezing at the last step boundary, and an adapter whose early step completed before its bar opened still completes to 100% instead of announcing completion over a bar frozen short of it.

### Added

- Added composable per-platform job configuration overrides: `platforms` is now a top-level job-configuration section (sibling of `general`/`conversion`/`upload`) whose entries carry `general`/`conversion`/`upload` override sections that deep-merge over the job's effective configuration, plus that platform's flat adapter options. Platform participation is `platforms.<p>.upload.skip` (an absent entry means the platform participates); the `upload.platforms.include`/`exclude` lists are removed. Platforms are grouped by the SHA-256 digest of their effective `conversion` section, the conversion checkpoint gains per-group sub-checkpoints keyed by that digest, and the pipeline renders once per group, so changing one platform's override stales only that group's artifact. A group whose effective `conversion` is skipped is born `skipped`, binds the `"source"` artifact revision for the platforms in it, and never renders; a per-platform `conversion.layout_id` is materialized against the layout registry during resolution, so an unregistered id is rejected up front rather than at render time. Per-platform `conversion.subtitles.transcription_*` overrides are rejected because the job shares one transcript session. Upload draft payload is now `{upload, platforms}`, and checkpoint accept/render plus `job render` accept an optional group. Editing a platform's override re-derives the group list against the stored one, a render loop whose platforms all moved onto already-rendered groups still completes instead of stranding the stage, and retention never prunes an artifact a live conversion group still binds. Manifest schema bumped once, to `4`; the breaking `app.yml` change (the removal of `upload.platforms`) bumps `config_version` to `2` in the same change, so an existing `app.yml` fails with the actionable stamp error instead of an `Unknown upload field(s)` cascade.
- Added `clipmorph/platforms.py` as the single source of truth for the supported platform set, per-platform upload defaults, and upload participation resolution; CLI, workflow, service, configuration, and web surfaces consume it.
- Added `scripts/check_docs.py` and CI documentation health checks for broken relative links, encoding mojibake, and duplicated doc passages.
- Added ruff (E9,F), typed mypy (0 issues across `clipmorph/`), and coverage reporting as CI gates, a `dev` package extra for the tooling, and a workflow concurrency group that cancels superseded runs.
- Added the authentication setup guide `docs/AUTHENTICATION.md` with step-by-step credential generation for every provider section of `auth.yaml`.
- Added the platform extension guide `docs/PLATFORM_EXTENSION_GUIDE.md`, which lists every touchpoint a new platform has to reach, and the `PlatformCoverageDriftTests` drift suite in `tests/test_platforms.py` that fails when a platform is missing from any of them.
- Added `clipmorph doctor [--json] [--source PATH]`, a read-only environment health check (FFmpeg/FFprobe binaries, app.yml, source/output directories, layouts, fonts, credentials, transcription device, artifact storage backend, and optional source media) that prints a text report by default and exits `0` when no check failed (warnings and `unavailable` allowed) or `1` when at least one failed.
- Added `clipmorph auth status --probe [PLATFORM ...]`, an opt-in per-platform credential health probe that makes one read-only call per platform and prints a masked verdict as JSON (exit `1` when any probe fails), plus a per-platform **Probe** button in the dashboard Settings view backed by `POST /api/v1/credentials/{platform}/probe`.
- Added `clipmorph/storage.py` with the `ArtifactStorage` protocol (`stage`, `store`, `open`, `remove`, `signed_url`, `exists`, `health`) and the phase-1 `local` backend rooted at `app.yml:output_dir`, selected through the new validated `app.yml` `storage.backend` block (web `PUT /configuration` accepts it; unknown values are rejected as `unknown storage backend`).
- Added `upload.schedule.mode` (`local` | `platform`, defaulting to `local`) to the app/job configuration schema: `platform` uploads at submission time and asks the platform to hold the future publication, gated per platform by the new `clipmorph/platforms.py::SUPPORTED_NATIVE_SCHEDULING` registry, which ships disabled until the maintainer's `quality/research/scheduling_probe.py` sandbox probe passes. A platform-scheduled attempt records `scheduled_via: platform`, stays `scheduled` while the platform holds the post, and is reported with its publish instant and post URL.
- Added per-attempt scheduled-upload cancellation through `clipmorph job cancel-scheduled ID ATTEMPT_ID` and `DELETE /api/v1/jobs/{id}/scheduled/{attempt_id}`, plus the opt-in adapter hook `BaseUploadPipeline.cancel_scheduled_post` (YouTube deletes the held private post) so cancelling or superseding a platform-scheduled publication actually removes it. The YouTube adapter also accepts `scheduled_publish_at`/`notify_subscribers` on `videos.insert`; an unscheduled insert is unchanged.
- Added AI-assisted platform metadata and caption suggestions: `clipmorph/suggest.py` provides a deterministic `template` provider (the always-works default, built on `clipmorph/policy.py` composition and caption limits) and an opt-in `hugging_face` provider (the OpenAI-compatible Inference Providers router, `temperature: 0`, no new dependency), selected by the new `upload.suggestions.provider`/`model` config. `clipmorph job suggest ID [--platform --provider --force]`, `job accept-suggestions ID [--platform]`, `POST /api/v1/jobs/{id}/checkpoints/upload/suggest`, and `POST /api/v1/jobs/{id}/checkpoints/upload/suggestions/accept` generate per-platform drafts into `upload.suggestions` and copy accepted rows into `upload.content` through the existing review gate — suggestions are draft-level and never auto-publish. A maintainer-only `quality/research/ai_suggest_probe.py` validates the HF provider with live tokens.
- Added the optional `meta.config_id` credential (`FACEBOOK_CONFIG_ID`) for Facebook Login for Business apps: when it is set, the Meta login dialog is invoked with the app's Configuration ID instead of a `scope` list (FL4B permissions come from the Configuration, and Meta grants no permissions when the requested set is not the configured one); non-FL4B apps leave it empty and the scope-based dialog is unchanged. See [AUTHENTICATION.md](docs/AUTHENTICATION.md).

### Changed

- **Breaking:** job manifest `schema_version` is now `3` and every artifact record stores a `{backend, key}` storage reference relative to `output_dir` instead of a local `path`; older manifests are rejected on load (no migration path). Conversion outputs, CLI and web artifact routes, retention pruning, and upload submission/retry all resolve bytes through the configured backend.
- Uploads now read a per-attempt staged copy under `data_dir/staging`, released in a `finally` block after the attempt; a staging failure fails the attempts like an upload failure and records a `staging_failed` manifest error, while a retention recycle failure is recorded as a manifest warning and never fails a job.
- Moved every per-platform upload metadata rule out of `clipmorph/upload_pipeline/__init__.py` into `clipmorph/policy.py`: `build_platform_metadata` now composes `upload.content` into the fields each adapter sends, bounded by the `CAPABILITY_MATRIX` character limits, and the duplicated per-adapter limits and the inlined composition helper are gone. `POLICY_VERSION` was bumped and `docs/PLATFORM_CAPABILITIES.md` documents the rule set; per-platform upload defaults stay in `clipmorph/platforms.py`.
- Migrated the CLI from argparse to typer/click: every command, flag, argument, and process status (`0`, `1`, `2`, `130`) is unchanged, `--data-dir`/`--app-config` are now also accepted after the subcommand, and each subcommand gained its own `--help`.
- `auth status`, `job create|list|get|update|cancel|review|upload`, `job artifacts list|prune`, and `layout list|create|get` now print a rich table instead of JSON; pass the new `--json` flag to get the previous payload unchanged. Colour is dropped automatically when output is not a terminal, and characters the redirected terminal cannot encode are printed as escapes instead of failing the command.
- Resolve configuration sidecars by `general.source` instead of filename, allowing arbitrary `.yml`/`.yaml` names and distinct same-stem sources; duplicate sidecars for one source are rejected.
- Rewrote the README feature and configuration sections to the 0.5.0 layered-configuration and checkpoint model, listing the full `job`/`layout` command families; dry-run wording now matches what the implementation validates (source selection and configuration).
- Split `tests/test_cli.py` into focused modules named after the units they cover: `test_preflight.py`, `test_upload_platforms.py`, `test_oauth.py`, `test_service.py`, `test_job_manifest.py`, `test_transcription.py`, and `tests/test_platforms.py`.
- Extracted upload attempt execution into `clipmorph/upload_attempts.py`; upload attempts now record real per-platform start/completion timestamps instead of backfilling them.
- Documented the tagged GitHub repository as the current install channel for `clipmorph` and `clipmorph[web]`, noting PyPI publication as planned future work.
- Removed `clipmorph/batch.py`: multi-source fan-out lives in `JobService.create_jobs`, and no documentation now claims BatchProcessor participates in job creation.
- Persisted Twitter OAuth tokens to the active auth file: `authorize_twitter` and `refresh_twitter_access_token` no longer fall back to the default data directory when called without one, so a job configured against a custom workspace writes its rotated tokens to the auth file that job loaded instead of one it never reads.
- Rendered captions through an ffmpeg `drawtext` textfile instead of an inline filter argument: a caption containing a character `drawtext` treats specially (a colon, backslash, quote, or comma) broke the filtergraph and the render failed or silently emitted a mangled caption; captions are now written to a file and passed as `textfile=`, so ffmpeg reads the literal text.

### Fixed

- Fixed an empty-string environment entry shadowing a configured `auth.yaml` value: the shared credential export treats an empty environment entry as unset, so a pre-set blank no longer hides a real file value (a non-empty environment value keeps precedence; rotated refresh tokens still replace a stale environment value).
- Fixed `clipmorph auth status` (without `--probe`) and `clipmorph doctor`'s credentials check reporting only pre-set environment values: the persisted `auth.yaml` was never loaded, so file-configured credentials reported `no`/`warning` and the dashboards understated the workspace's real configuration. Both surfaces now load the workspace auth file first.
- Fixed the Twitter upload sending a stale OAuth2 access token when the stored `oauth2_expires_at` is empty or unreadable: the freshness guard treated `0` as valid and skipped the at-upload refresh, answering `401 Unauthorized` at `media/upload/initialize` while a valid refresh token was persisted. An absent access token with a stored refresh token now refreshes first instead of raising. With the fixed at-upload refresh and its interactive fallback, the upload authorizes itself end to end.
- Fixed TikTok uploads never reaching an upload call: the OAuth token exchange failed with "Code verifier or code challenge is invalid" because the PKCE verifier used the full punctuation-bearing unreserved alphabet; it now generates alphanumeric verifiers, which TikTok's token endpoint accepts.
- Fixed transcription models returning numpy timestamps (`np.float64`) that passed the JSON transcript-session write (they subclass `float`) but crashed the manifest's YAML dump with `cannot represent an object` after a clean transcription; `create_edit_session` now coerces every scalar to native Python types at the session boundary.
- Fixed `job create` failing the transcript stage right after a clean transcription on Windows and CUDA machines in two steps: (1) Whisper alignment and diarization loaded on CUDA from an import-time device constant regardless of the configured `transcription_device`, crashing alignment with a CPU-input/CUDA-weights mismatch, and (2) the workflow's nested `JobService` construction (transcript session save) ran startup reconciliation against the job its own thread was running, marking the running transcript `interrupted_by_restart` and failing the save with `stale checkpoint revision`. The alignment/diarization device now follows the resolved pipeline device, and in-process service constructions skip the restart-boundary scans via `JobService(..., reconcile=False)`.
- Fixed facebook uploads answering 403 (#200) on a Page Reels publish after the stored Page token rotted: the Meta user access token is finite-lived (roughly 60 days) while the derived Page token was documented and kept as though it never expired, so a stored Page token silently rotted. Each adapter now derives the Page token from the user token at publish time (`GET /v23.0/{page_id}?fields=access_token`), uses that derived token for the upload, never stores it, and `auth status --probe facebook` probes the derivation alongside the `/me/accounts` listing.
- Fixed TikTok running a second token grant immediately behind an interactive authorization: the authorization-code exchange already returns an access token, but `_refresh_access_token` read the missing refresh token as "no tokens yet" and re-requested one, which could consume the refresh token the first grant had just issued. The interactive flow is factored into `_authorize_interactively`, which returns its token pair, and the refresh path uses it directly.
- Fixed upload adapters entering a parallel attempt with no OAuth session only on Twitter: `_prepare_interactive_authentication` authenticated YouTube and refreshed TikTok, but not Twitter, so the platform reached its worker thread unauthenticated and failed there, silently dropped from the run. Every adapter now renews its credentials at attempt time and the failure is logged, with a drift test keeping the per-adapter renewal honest as new platforms land.
- Fixed every conversion resume silently stalling at `conversion stale`: the conversion-group sync was applied in memory and then overwritten by the reload right after it, and because saving the transcript session materializes captions into `conversion.layout`, the stored group set always differed from the derived one on the first conversion run. The sync is now persisted before the reload, and a `running` group a failed render left behind is re-armed as `pending` for the retry — this process has not executed the group yet, so it cannot have left it genuinely running.
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
