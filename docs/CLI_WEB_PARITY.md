# CLI and Web Parity Contract

Normative parity contract and release gate. Configuration shape, merge rules,
layout schema, and derived values have one source of truth in
[CONFIG_LAYERS.md](CONFIG_LAYERS.md). CLI and API normalize into that contract,
share validation/workflow behavior, and persist equivalent per-source jobs.

There is no `/batches` route, `batch_id`, `batch.yml`, group manifest, or
backend batch configuration tier. Multi-source is transient UI/submission
grouping. Every job has one source and independent config, manifest, lifecycle,
artifacts, and platform results.

## Invariants

- `app.yml` owns `source_dir`, `output_dir`, `job_defaults`, and global
  `layouts`; credentials live separately in `auth.yaml`/environment.
- Effective config is `merge(app.yml:job_defaults, job_overrides)`. Derived
  values follow merge and explicit values win. Persist effective config to
  `jobs/<job_id>/job.yml`.
- Manifest provenance retains effective config and the global-default
  snapshot, not separate CLI/UI override patches. No legacy readers/migrations.
- `general.source` is a root-level filename under `source_dir`; reject
  traversal, separators, nested/outside-root paths. Persist normalized absolute
  source path and SHA-256 in the manifest. Discovery never recurses.
- Per-source priority is field-wise deep merge: explicit JSONL/YAML record,
  explicit config-dir sidecar, source-dir sidecar, app defaults. Sidecars are
  immediate `.yml`/`.yaml` job objects selected by exact `general.source`;
  filenames are not semantic and duplicate source keys in one directory are
  invalid. Objects merge; scalars/lists replace. CONFIG_LAYERS.md owns config
  semantics.
- Conversion artifacts are in `output_dir/<job_id>/`, registered in the
  manifest as a `{backend, key}` storage reference relative to that root
  (never a local `path`). Review sessions live in the job directory. Trash
  local files only; never delete remote posts.
- Artifact bytes are read through the configured storage backend
  (`app.yml:storage.backend`, phase 1 `local` only); `local_path` is a
  local-backend-only accessor behind `JobService.artifact_path`. Uploads always
  read a staged copy under `data_dir/staging`, released after the attempt.
- Use shared source/config/layout/transcript/preflight/platform validation;
  CLI and API use the same error fields/messages.

## CLI Contract

Global `--data-dir DIR` and `--app-config PATH` apply to all commands and are
accepted before the first command group and after a leaf command; they are not
accepted between a group and its subcommand. Default app config is
`<data-dir>/app.yml`. Help/init/config inspection/web startup keep media
imports lazy.

Commands that report records render a rich table for humans and print the
machine-readable JSON payload when `--json` is passed; colour is dropped
automatically when output is not a terminal. Every `[--json]` below reproduces
the previous JSON payload unchanged. Process statuses are `0` success, `1` a
source/runtime failure, `2` a usage or configuration failure, and `130` an
interruption.

| Command | Contract |
| --- | --- |
| `clipmorph --help`; `clipmorph init [--config-path PATH]` | Lightweight help; `-h` is accepted wherever `--help` is. init writes app.yml and adjacent auth.yaml, no media work. |
| `clipmorph web [--host HOST] [--port PORT]` | Start API/dashboard; global `--data-dir` and `--app-config` precede the command. |
| `clipmorph auth status [--json]`; `auth set PLATFORM`; `auth twitter` | Status only; secure prompt + auth.yaml update; existing Twitter/X OAuth flow. Never print secrets. |
| `clipmorph auth status --probe [PLATFORM ...]` | Opt-in network probe; one read-only call per platform, masked verdict as JSON. Never automatic (not from preflight, startup, or the bare status command). Exits 1 when any probe fails; `unavailable` rows neither fail nor block. |
| `clipmorph job create SOURCE [--job-configs FILE] [--config-dir DIR] [--dry-run] [--yes] [--json]` | SOURCE is a supported root-level file beneath `app.yml:source_dir` or that directory. Directory creation fans out over immediate files; JSONL is object-per-line, YAML is a list. Dry-run writes no job or manifest. |
| `clipmorph job list [--status STATUS] [--json]`; `job get ID [--json]` | List/show manifest, effective config, checkpoint, artifacts and platform results; redact secrets. |
| `clipmorph job update ID --patch FILE [--reopen] [--json]`; `job resume ID`; `job cancel ID --yes [--json]`; `job delete ID --yes` | Apply a validated per-job patch using the current config hash; persist finalized job.yml and apply #180 invalidation. Reopen completed work only with confirmation; source identity is immutable. |
| `clipmorph job review ID CHECKPOINT [--edits FILE] [--accept] [--group GID] [--json]`; `job render ID [--group GID]` | `--edits` supplies a complete transcript edit-session YAML/JSON object. Review acceptance uses the current manifest revision; `--group` accepts one conversion group and omitting it accepts every group awaiting review. Render creates a new immutable artifact for the whole job, or for one group with `--group`. |
| `clipmorph job upload ID [--platform PLATFORM] [--json]`; `job upload retry ID PLATFORM [--attempt-id ID]` | Submit the accepted upload draft or retry one failed attempt. Retries use frozen artifact/settings and upload immediately; historical use requires explicit ID and confirmation. PLATFORM is a supported id (`youtube`, `instagram`, `tiktok`, `twitter`, `facebook`) validated against `clipmorph/platforms.py::SUPPORTED_PLATFORMS`, which stays the single source of truth. |
| `clipmorph job uploads ID [--status S] [--platform P] [--since ISO] [--json]` | List a job's upload attempt history with optional status, platform, and since filters. Returns filtered attempts with result fields (`platform_post_id`, `platform_url`, `published_at`). |
| `clipmorph job metrics ID [--pull] [--dimensions] [--json]` | List a job's metric snapshots; `--pull` triggers a bounded pull from platforms first. Returns snapshot records with `captured_at`, `platform`, `metrics`, `unavailable`, `unavailable_reason`. `--dimensions` joins each record to its manifest dimensions (`duration_seconds`, `title`, `layout_id`, `subtitles_renderer`, `platform_overrides`). |
| `clipmorph job suggest ID [--platform P] [--provider NAME] [--force] [--json]` | Generate per-platform title/description/hashtag drafts for the upload review draft from the job's transcript. `--platform` limits generation (repeatable); `--provider` overrides `upload.suggestions.provider` for this call; `--force` regenerates past the content-hash dedup guard. Writes `upload.suggestions` and bumps the draft revision; nothing is published. |
| `clipmorph job accept-suggestions ID [--platform P] [--json]` | Copy chosen suggestion rows into `upload.content` (hashtags normalized to `content.tags`) and clear the accepted rows; omitting `--platform` accepts every available row. Goes through the existing review gate; nothing auto-publishes. |
| `clipmorph metrics compare [--platform P] [--limit N] [--json]` | Cross-job comparison over all jobs' stored snapshots. One row per published platform post with the join dimensions, latest metric values, and first → latest deltas. `--platform` filters to one supported platform; `--limit` bounds rows (1-500, default 100). Read-only; no pull is triggered. |
| `clipmorph job cancel-scheduled ID ATTEMPT_ID [--json]` | Cancel one scheduled upload attempt before its publication, whether it is `scheduled_via: local` or `platform`. A local attempt loses its batch timer and the surviving members of that group are re-armed; a platform-scheduled attempt is deleted on the platform first, so a platform refusal exits `2` and leaves the attempt `scheduled` with a `platform_cancel_failed` note. An unknown attempt id or an attempt that is not `scheduled` is refused. |
| `clipmorph job artifacts list ID [--json]`; `job artifacts preview ID ARTIFACT_ID`; `job artifacts download ID ARTIFACT_ID --destination PATH`; `job artifacts rename ID ARTIFACT_ID --name NAME`; `job artifacts delete ID ARTIFACT_ID --yes`; `job artifacts prune ID [--json]` | Operate on registered artifact IDs; rename changes display metadata only, delete recycles the bytes through the storage backend and retains a manifest tombstone. `prune` applies `app.yml:retention.artifacts` and prints `{pruned,bytes_freed}`. |
| `clipmorph layout list [--json]`; `layout create FILE [--json]`; `layout get ID [--json]`; `layout delete ID --yes` | CRUD validated global `{id,name,layout}` records; create reads YAML/JSON. |
| `clipmorph doctor [--json] [--source PATH]` | Read-only environment health check (FFmpeg/FFprobe binaries, app.yml, source/output directories, layouts, fonts, credentials, transcription device, artifact storage backend, and optional source media); text report by default, `--json` emits `{"checks":[{"id","status","detail"}]}` with status `ok\|warning\|failed\|unavailable`. The `artifacts_storage` check probes the configured backend (a `.<uuid>.probe` object written and recycled inside the artifact root) and reports `unavailable` when the backend cannot be built. CLI-only surface; no API route — an intentional CLI-only mechanic. Exit `0` when no check failed (warnings and `unavailable` allowed), `1` when at least one failed. |

Map CLI controls to CONFIG_LAYERS.md: no-confirm -> `general.no_confirm`, clean
-> `general.clean`, no-conversion/no-subs/no-upload -> `conversion.skip`/
`conversion.subtitles.skip`/`upload.skip`, per-platform skip ->
`platforms.<p>.upload.skip`, content -> `upload.content`, platform
options -> `platforms.<platform>` (flat adapter options), layout preset/inline ->
`conversion.layout_id`/`conversion.layout`, crop/captions ->
`conversion.layout`, transcription/renderer -> `conversion.subtitles`, strict
-> `conversion.strict`. `output_dir` is app-level. Dry-run/resume/review/cancel/
render/artifact actions are not persistent config. Legacy flat invocation and
camera flags are replaced by job commands/layout crop. Never clean original
source when conversion is skipped.

## API Contract

Routes are rooted at `/api/v1`; job config uses the CLI schema. Sources are
root-level names under `source_dir`; validate before queueing.

| Method / route | Contract |
| --- | --- |
| `GET /health` | `200 {status:ok}`; no media imports. |
| `GET/PUT /configuration` | Get config + credential status; PUT replaces validated full app.yml atomically; no secret values. A missing or mismatched `config_version` is `422 invalid_configuration` and leaves the file untouched; an absent stamp is filled in on save. |
| `GET /credentials`; `PUT /credentials/{platform}` | Configured booleans only; PUT validates fields, saves auth.yaml, returns status only. |
| `POST /credentials/{platform}/probe` | Executes the single-platform probe from `clipmorph/auth_probe.py`; always `200` with the masked verdict in the body, never a provider-mapped error. |
| `GET/POST /sources` | List root-level supported files; multipart upload sanitizes basename, validates media, uniquifies collision, returns `201 {name,source}`. |
| `GET/POST /layouts`; `GET/PATCH/DELETE /layouts/{id}` | Validated `{id,name,layout}` in app.yml. Delete requires `confirm=true`; materialized jobs remain valid. |
| `GET /jobs?status=...`; `GET /jobs/{id}` | List/get source, status/checkpoint, timestamps, config, artifacts, platform results. Missing ID `404`. |
| `POST /jobs/validate` | Single `{source,configuration}` or bulk `{source_names,job_configs,overrides}`; `200 {valid,created,skipped,failed,effective_configurations,warnings}`, no writes; malformed request `422`. |
| `POST /jobs` | Single `{source,configuration}`; persist finalized job.yml/manifest and queue; `202 {job_id,job,status_url}`. |
| `POST /jobs/bulk` | `{source_names:null|[...],job_configs:[<job objects>],overrides:<job object>,config_dir?:PATH}`. Null selects all immediate source-root files; explicit names select only those. Direct job records key on `general.source`; shared overrides are copied per source before resolution. Return `{created,skipped,failed,summary,effective_configurations}`; no group ID. |
| `PATCH /jobs/{id}/configuration`; `DELETE /jobs/{id}?confirm=true` | PATCH accepts `{patch,expected_configuration_hash,reopen?}`, validates/applies to effective config, saves job.yml, applies #180; source immutable. Hash mismatch `409`, invalid patch `422`. DELETE trashes local data/output only. |
| `POST /jobs/{id}/resume`; `POST /jobs/{id}/cancel`; `POST /jobs/{id}/checkpoints/{stage}/retry`; `POST /jobs/{id}/render`; `GET /jobs/{id}/events` | Resume only executable work (`409` if review is required); cancel needs `{confirm:true}`; retry appends attempt history; render creates new artifact revision (`202`) for every conversion group, or for the single group named by the optional `group` body param, and discards a schedule the new artifact supersedes. SSE ends terminal. Each SSE event and the `GET /jobs/{id}` polling fallback carry `upload_progress` (`{platform: percent}`), the live per-platform upload percents; the field is an empty dict when no upload is in flight. |
| `GET/PUT /jobs/{id}/transcript` | GET returns the active source-bound session. PUT body includes `source_sha256`, `expected_revision`, optional `expected_checkpoint_revision`, duration and original/edited segments; it validates edits and saves a new immutable revision. Conflict `409`; invalid edits `422`. |
| `POST /jobs/{id}/checkpoints/transcript/accept`; `POST /jobs/{id}/checkpoints/conversion/accept` | Accept current review with expected checkpoint revision; stale input/illegal transition `409`. Optional `group` body param accepts one conversion group; omitted = all groups. State contract is [#180](https://github.com/A-Baji/ClipMorph/issues/180). |
| `GET/PUT/DELETE /jobs/{id}/checkpoints/upload` | GET returns `{upload,platforms,checkpoint}`; PUT body `{expected_revision,upload,platforms?,reopen?}` updates only the pending draft; DELETE query `expected_revision` resets it to frozen global defaults. Mutations do not change prior attempts. A draft change also discards a schedule armed by an earlier submission: its timers are cancelled and its pending attempts are unmarked, so only the next submission uploads. |
| `POST /jobs/{id}/checkpoints/upload/suggest` | Body `{platforms?, provider?, force?}`; generate per-platform `upload.suggestions` drafts for the pending upload review, degrading to the template provider with a `note` on provider failure. `202` with the updated `{upload, checkpoint}`; `404` unknown job, `409` before review. Never publishes. |
| `POST /jobs/{id}/checkpoints/upload/suggestions/accept` | Body `{platforms?}`; copy the chosen suggestion rows into `upload.content` and clear them (the `provider`/`model` selector survives). `202` with the updated `{upload, checkpoint}`; `404` unknown job, `422` for a platform with no suggestion, `409` before review. |
| `GET /jobs/{id}/uploads?status=&platform=&since=`; `POST /jobs/{id}/upload` | Read append-only history with optional status, platform, and since filters; submit pending draft after review against current artifact; accepted work `202 {job_id,attempts,scheduled,status_url,detection}`. A snapshot whose `upload.schedule.publish_at` is in the future returns `scheduled: true` and leaves the attempts `scheduled` for a later timer. Attempt statuses are `pending`, `scheduled`, `running`, `published`, `failed`, `cancelled`. A duplicate active submission returns `409`. Platform-side detection may mark attempts `published` without running a pipeline. A completed attempt's `result` carries `progress_percent`, the last observed live upload percent (not extrapolated); live percents are never rewritten into a terminal record. |
| `GET /jobs/{id}/metrics?include=dimensions`; `POST /jobs/{id}/metrics/pull` | Read-only list of metric snapshots; `POST` triggers a bounded pull (202) and returns `{job_id, snapshots, pulled}`. No GET-triggered network calls. `include=dimensions` joins each record to its manifest dimensions; any other `include` value is `422`. |
| `GET /metrics/comparison?platform=&limit=` | Cross-job comparison rows over all jobs' stored snapshots. One row per published platform post: latest snapshot per `(platform, platform_post_id)`, dimensions joined from the manifest, first → latest deltas. `platform` validates against `SUPPORTED_PLATFORMS_SET`; `limit` is an int 1-500 (default 100). Empty state is `[]` (200), never 404. |
| `POST /jobs/{id}/uploads/{platform}/retry` | Body names failed `attempt_id`; reuse frozen settings/artifact. Historical retry requires matching `artifact_id` and `confirm_historical_artifact:true`. A retry ignores any `publish_at` in the frozen snapshot and uploads immediately. |
| `DELETE /jobs/{id}/scheduled/{attempt_id}` | `202 {job_id,attempt_id,platform,scheduled_via,status}`; an unknown attempt id is `404`, an attempt that is not `scheduled` is `422`, and a platform that refuses to drop its held post is `422` with the attempt left `scheduled`. Only ever touches one attempt: a local disarm re-arms the surviving members of the cancelled attempt's timer group, and a platform-scheduled attempt is deleted through the adapter. |
| `GET /jobs/{id}/artifacts`; `GET /jobs/{id}/artifacts/{artifact_id}/preview`; `GET .../download` | List immutable revisions with their `{backend, key}` storage reference and no local path; stream registered bytes from the local backend; missing/deleted bytes or paths outside allowed roots return `404`, and a backend that owns no local bytes returns `409 storage_unavailable`. |
| `GET/PATCH/DELETE /jobs/{id}/artifacts/{artifact_id}` | PATCH body `{display_name}` changes display metadata only. DELETE requires `confirm=true`, recycles the bytes through the storage backend but retains a manifest tombstone/upload references; source artifacts cannot be deleted. |
| `POST /jobs/{id}/artifacts/prune` | Apply the `app.yml:retention.artifacts` policy; `202 {pruned,bytes_freed}`, `404` for a missing job, `409` when bytes could not be recycled (nothing is saved). Only superseded non-source artifacts are candidates; `current`/`stale` are never pruned. No policy set is a no-op. |

Explicit records override matching sidecars but never narrow all-source
discovery; only `source_names` filters API selection. Unknown record sources
fail without escaping root. `upload.schedule.publish_at` is implemented as an
in-process deferral with a full attempt lifecycle: attempts move through
`pending → scheduled → running → published|failed|cancelled`, the derived job
status gains a `scheduled` bucket, duplicate prevention combines a
submission-side guard with platform-side existing-post detection, and history
is filterable by status, platform, and since. #179 defines no scheduler API. An
armed schedule is owned by the accepted submission, not by the draft, so the
two ways of superseding it — a draft `PUT`/`DELETE` or a rerender — cancel the
timer and unmark its scheduled attempts. The next submission is the only thing
that re-arms an upload, and to abandon a schedule without uploading, cancel
the job (which aborts scheduled attempts to `cancelled`).

`upload.schedule.mode` selects who holds that publication, and every surface
reports it as `scheduled_via` on the submission response and the attempt:
`local` (the default) is the deferral above, and `platform` uploads at
submission time and lets the platform hold the future post. A platform-scheduled
attempt is created `scheduled` with its `scheduled_publish_at` and stays
`scheduled` after a successful upload, because only the platform knows when the
post becomes visible; its result carries `platform_post_id`, `platform_url`,
`scheduled_publish_at`, and a message saying the platform holds publication, and
the queue/history surfaces render that status with the publish instant and the
post URL. The mode is refused before any attempt exists for a platform the
registry has not blessed, and it ships disabled for every platform until the
maintainer's probe has run, so in a default build `mode: platform` reports the
registry's strict error.

Every service construction reconciles manifests left `running` by a process
that never returned, so both surfaces heal phantom queue entries on first
touch: the in-flight checkpoint becomes `failed` with
`{"code":"interrupted_by_restart","retryable":true}`. A `running` upload
checkpoint whose every `scheduled` attempt waits on a future `publish_at`
is left alone, and reconciliation runs before the re-arm scan restores those
timers. A past-due `scheduled` attempt is healed as an interrupted failure,
never published unattended. A platform-scheduled attempt is not waiting on this
process, so it never keeps a `running` upload checkpoint alive, and an attempt
stranded between the platform accepting the upload and the result being written
is settled from platform state first: a post that exists completes the attempt
as `published` with its id and URL (no re-upload), and no post marks it
`failed` with a retryable `platform_schedule_unconfirmed` note, which makes the
ordinary retry both the re-upload and the refresh. Nothing is resumed
automatically and no remote upload is repeated without an explicit user action.

### Response And Validation Boundaries

- Validation failures use `{error:{code,message}}`; `404` is a missing resource,
  `409` is a stale revision, illegal transition, immutable source, review gate,
  or unavailable/historical artifact conflict, and `422` is malformed input.
- Each bulk outcome carries `source`, `record_index`, `status`, `code`,
  `message`, `job_id`, and `status_url`; inapplicable values are null. The
  summary counts created, skipped, and failed records independently.
- CLI exits `0` for success/valid dry-run, `1` for a source/runtime failure,
  `2` for usage or configuration input errors, and `130` for interruption.
- Source validation occurs at `JobService.resolve_job`; root containment,
  extension, schema, layout, and title checks are shared by validation and
  creation. `job.yml` stores the effective normalized object; `manifest.json`
  stores source identity, the global-default snapshot, checkpoints, artifact
  revisions, safe errors, and append-only upload attempts.
- Focused implementation tests live in `tests/test_configuration.py`,
  `tests/test_platforms.py`, `tests/test_layout.py`,
  `tests/test_layout_rendering.py`, `tests/test_transcript.py`,
  `tests/test_transcription.py`, `tests/test_preflight.py`,
  `tests/test_upload_platforms.py`, `tests/test_policy_metadata.py`,
  `tests/test_oauth.py`,
  `tests/test_reconciliation.py`, `tests/test_retention.py`,
  `tests/test_service.py`, `tests/test_job_manifest.py`,
  `tests/test_storage.py`, `tests/test_doctor.py`,
  `tests/test_auth.py`, `tests/test_cli.py`, `tests/test_cli_surface.py`, and
  `tests/test_web.py`.

## Discovery and Results

- Scan immediate source_dir children only. JSONL is one object per nonblank
  line; YAML is a list. Records are job configs with unique root-level
  `general.source`; wrappers/batch fields are invalid.
- Sidecars are immediate `.yml`/`.yaml` files containing one job object with
  `general.source`; filenames do not map to source names. Duplicate sidecars
  for the same source in one directory are invalid. `clip.mp4` and `clip.mov`
  remain distinct sources despite sharing a stem.
- Read/encoding/JSON/YAML syntax errors reject atomically (CLI exit 2/API 422).
  Invalid individual records fail while valid records continue. Priority is
  explicit record > explicit config-dir sidecar > source sidecar > app defaults.
- Explicit records override matching sidecars while other supported root
  clips remain eligible. Preserve deterministic ordering. First resolved
  filename/hash wins; repeats skip as `duplicate_source`/`duplicate_content`.
  Upload name collisions are uniquified, never overwritten.
- Outcome schema: `{source,record_index,status,code,message,job_id,status_url}`;
  inapplicable fields are null; status is created/skipped/failed. Codes:
  `unsupported_extension`, `source_missing`, `source_outside_root`,
  `invalid_record`, `invalid_config`, `duplicate_source`, `duplicate_content`,
  `creation_failed`.
- Bulk response: `{created:[],skipped:[],failed:[],summary:{total,created,skipped,failed}}`.
  API returns 202 if any job queued, 200 for valid all-skip/failure, 422 for
  request errors. CLI exits 0 if no failures, 1 for any failed source, 2 for
  usage/config errors, 130 on user interruption.

## Persistence and Lifecycle

```text
<data_dir>/app.yml
<data_dir>/auth.yaml
<source_dir>/<root sources and optional .yml sidecars>
<data_dir>/jobs/<job_id>/manifest.json
<data_dir>/jobs/<job_id>/job.yml
<data_dir>/jobs/<job_id>/transcripts/revision-0001.json
<data_dir>/jobs/<job_id>/metrics/snapshots.jsonl
<output_dir>/<job_id>/<registered media artifacts>
<data_dir>/staging/<per-attempt upload copies, removed after the attempt>
```

Manifest stores schema version, ID, normalized source path/hash, effective
config, `configuration_sources.global_defaults` snapshot, status, steps/progress,
checkpoint revisions, artifact metadata/history, warnings/errors and append-only
upload attempts. Every artifact record carries a `storage` reference
(`{backend, key}`, key relative to `output_dir`) instead of a local `path`.
It never stores override patches. `job.yml` is finalized
after merge/normalization/derivation. Transcript sessions are immutable files
under `transcripts/`; conversion outputs are immutable revisions referenced by
artifact ID/hash in the manifest.

Transcript edits change text/timing/per-segment typography without mutating
reusable layouts; reviewed segments render via `conversion.subtitles.renderer`.
Composition edits change crop/caption/layout/placement and rerender. Both stale
the prior local conversion until replaced. Upload edits affect pending upload
only. Remote results stay historical and tied to their submitted artifact.
Checkpoint transition/invalidation specifics are assigned to #180.

API: 404 missing, 409 lifecycle/source conflict, 422 invalid input, 202 async
accepted. CLI: 0 success/valid dry-run, 1 runtime/per-source failure, 2
usage/config failure, 130 interruption. Both report canonical status/error,
checkpoint summary and artifact availability.

## Parity Matrix

Each row gives route/fields, visual control, shared validation, normalized
destination, manifest/artifact destination, CLI/API behavior and focused tests.
CONFIG_LAYERS.md remains authoritative for field meaning.

| CLI item | API route/request/response | Visual control | Validation | Normalized destination | Manifest/artifact | CLI/API behavior | Focused tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Help/startup/web | Health/startup | Service status | Lazy parser/config | App path/data-dir | app.yml/no job writes | CLI 0; API 200/422 | CLI lazy; web health |
| Init/config/defaults | GET/PUT configuration | Settings/defaults/layout | App schema/path/atomic save/`config_version` | App fields | app.yml/auth template | CLI 0/2; API 200/422 | CLI init; web config; version guard |
| Credentials | GET/PUT credentials; POST per-platform probe | Masked status/secure form/probe verdict | Field allowlist/auth loader | No job field | auth.yaml | Never echo; invalid 422; probe always 200 | Auth/web mask/update; probe masked |
| Source upload/select | GET/POST sources | Picker/list/multiselect | Basename/media/nonempty/collision/root | general.source | Source root/manifest identity | CLI 2; API 201/422 | Upload/list/collision |
| Single/multi create | POST jobs/jobs/bulk | New Job/source selection/shared overrides/results | Resolver/preflight/discovery/priority/dedup | One merged config per source | Per-source job.yml/manifest/output | CLI 0 or 1/2; API 202/200/422 | CLI/API differential; partial results |
| JSONL/YAML/sidecars | Bulk fields after normalization | Import/per-source config | Safe parse/schema/source | Priority chain + defaults | Final job.yml/no patch | Syntax CLI 2/API 422; row failure | Parse/priority/all-clips tests |
| Dry-run/strict | POST jobs/validate | Dry-run/strict controls | Resolver/preflight/layout/policy | conversion.strict; dry-run request-only | No writes | CLI 0/2; API 200/422 | Equal config/errors |
| Job list/get/update | GET/PATCH configuration | Queue/detail/config editor | Patch schema/hash/reopen/source immutable | Read/merge patch into effective config | Manifest hashes/checkpoints and job.yml | CLI 0/1/2; API 200/404/409/422 | CRUD/hash/reopen/immutability |
| Resume/cancel/delete | POST resume/cancel/stage retry; DELETE job | Queue actions/confirmation | Checkpoint state, cooperative cancellation, local cleanup | Config unchanged | Manifest transition; local trash; history retained | CLI 0/1/130; API 202/200/404/409 | Service/web transition and confirmation tests |
| Layout registry | GET/POST/PATCH/DELETE layouts | Layout editor/list/confirm | Registry/crop/caption/typography | app.yml/materialized job layout | app.yml/job.yml | CLI 2; API 201/200/404/422 | Layout CRUD/materialization |
| Conversion/output | Job create/update/render | Crop/caption/conversion | Preflight/layout validator | conversion.*; output_dir app-only | Step/job output | CLI 1; API 202/eventual error | Layout/render/preflight |
| Transcript review | GET/PUT transcript; POST transcript/accept | Text/timing/typography editor/accept | Hash/revision/timing/type/renderer | conversion.subtitles + selected captions | Immutable transcripts and conversion artifact revisions | CLI 2; API 409/422 | Transcript revision/renderer/rerender |
| Composition review | PATCH configuration; POST conversion/accept; POST render | Layout/preview/accept | Expected hash/checkpoint revision/layout/preflight | conversion.layout | job.yml; new immutable artifact, prior stale/superseded | CLI 1/2; API 409/202 | Stale artifact/history |
| Pre-upload review | GET/PUT/DELETE checkpoint upload | Content/platform review | Expected revision/platform policy/title/current artifact | Pending upload config only (`{upload, platforms}`) | Draft checkpoint; prior attempts unchanged | CLI 2; API 404/409/422 | Review gate/update/discard |
| AI suggestions | `job suggest ID [--platform --provider --force]`; `job accept-suggestions ID [--platform]`; POST checkpoint upload/suggest + /suggestions/accept | Generate/Regenerate/Apply/Apply-all/Clear suggestion cards with provider chip and note | Review gate; provider registry; platform caption limits from policy; content-hash dedup | `upload.suggestions` (provider/model selector + per-platform rows); accept writes `upload.content` | Draft-only; accept clears accepted rows; never auto-publishes | CLI 0/2; API 202/404/409/422 | `tests/test_suggest.py`; `tests/test_web.py`; `tests/test_cli.py` |
| Per-platform overrides | PATCH configuration; POST conversion/accept with `group`; POST render with `group` | Composition review edits; read-only per-platform upload summary | Per-platform section schemas, protected keys, group id derivation | `platforms.<p>.{general,conversion,upload}` over the job config | Per-group conversion checkpoint/artifact; one render per group | CLI 1/2; API 200/409/422 | Grouping/binding/grouped-staleness tests |
| Upload/retry/status | POST /upload; GET /uploads; POST per-platform retry | Submit/result/retry | Platform/credentials/review; attempt artifact and frozen config | upload fields/snapshot | Append-only attempt history | CLI 1; API 202/404/409/422 | Mocked upload/history/retry |
| Schedule deferral | POST /upload with `upload.schedule.publish_at`; draft PUT/DELETE | Future instant defers instead of uploading | Snapshot `publish_at` parse/future check; review gate | upload.schedule.publish_at | Attempts marked `scheduled`; timers re-armed on startup; superseding draft/rerender disarms them | CLI 1; API 202 | Service/web deferral, re-arm, disarm, immediate retry |
| Platform publish scheduling | POST /upload with `upload.schedule.mode: platform`; `job cancel-scheduled ID ATTEMPT_ID`; DELETE /jobs/{id}/scheduled/{attempt_id} | Scheduled attempt shows publish instant + post URL; attempt cancel action | Registry `SUPPORTED_NATIVE_SCHEDULING` gate; adapter `cancel_scheduled_post` | `scheduled_via`, per-platform `scheduled_publish_at` override | Attempts `scheduled` until the platform publishes; platform hold deleted on cancel/rerender | CLI 1/2; API 202/404/422 | Registry/config/adapter/service/web tests; probe script |
| Upload history/filters | `job uploads ID [--status --platform --since]`; GET /uploads?status=&platform=&since= | Filter chips on Uploads view | Status/platform/since filter validation | Read-only | Filtered attempt history with result fields | CLI 0/2; API 200/422 | Scheduling history filter tests |
| Dedup guard | POST /upload; POST /uploads/{platform}/retry | Submission blocked while active attempt exists | Same platform + artifact + content hash + active status | None | `409` on duplicate active attempt | CLI 2; API 409 | Service dedup guard tests |
| Platform-side detection | POST /upload (YouTube with read scope) | Existing post detected, upload skipped | `find_existing_post` hook per adapter | None | Attempt `published` with found id/url; `unavailable` note on scope failure | CLI 1; API 202 | Detection hook tests |
| Cancel scheduled | POST /jobs/{id}/cancel (job in `scheduled` status); `job cancel-scheduled ID ATTEMPT_ID`; DELETE /jobs/{id}/scheduled/{attempt_id} | Scheduled attempts aborted pre-firing; per-attempt cancel | Disarm timers + mark `cancelled`; platform hold deleted first | None | Attempts `cancelled`; job `cancelled` when nothing is left to publish | CLI 0/2; API 200/202/404/422 | Service cancel path tests |
| Artifact preview/download/rename/delete | GET/PATCH/DELETE artifact by ID plus preview/download | Table/preview/download/display-name/trash | Registered immutable ID, safe metadata, availability, confirmation | Display metadata or artifact availability only | Manifest revisions/tombstones with `storage` refs; bytes recycled through the backend; upload references retained | CLI 1/2; API 200/400/404/409 | Bytes/headers/containment/rename/delete |
| Artifact storage backend | `app.yml:storage.backend`; doctor `artifacts_storage` | Settings backend selector; doctor report | Unknown backend `422`; backend health probe | None (app-level) | Every artifact keyed relative to `output_dir` | CLI 1; API 422 | `tests/test_storage.py`; `tests/test_doctor.py` |
| Retention/prune | `job artifacts prune ID`; POST /jobs/{id}/artifacts/prune | Apply app-level retention policy | superseded + non-source only; `current`/`stale` protected | None (app-level, not part of the job merge) | Tombstoned manifest entries; bytes to trash | CLI 0/1; API 202/404 | `tests/test_retention.py`; CLI/web cases |
| Restart reconciliation | Implicit on every service construction | Queue self-healing | Recorded `running` status; unreadable manifests skipped | None | `interrupted_by_restart` checkpoint failure | CLI 0/1; API n/a | `tests/test_reconciliation.py` |
| Events/progress/errors | GET job events SSE | Queue progress/checkpoint/errors | Shared status serializer | No config change | Manifest progress/status/errors | Same error fields; terminal SSE; `upload_progress` is live/in-memory only (empty when idle) | Event/status parity |
| Metrics comparison | `metrics compare [--platform --limit]`; GET /metrics/comparison; `job metrics --dimensions`; GET /jobs/{id}/metrics?include=dimensions | Metrics view cross-job table + platform filter chips; job-detail per-post delta cards | Platform against `SUPPORTED_PLATFORMS_SET`; limit 1-500; `include=dimensions` only | Read-only over stored snapshots | None (local snapshots) | CLI 0/2; API 200/422 | `tests/test_metrics.py`; `tests/test_web.py`; `tests/test_cli.py` |

## Differential Test Plan

Compare effective config, validation messages/warnings, result codes, status,
checkpoint gate, artifact availability and platform history. Use temporary
roots and mock FFmpeg/transcription/uploads/credentials; no live credentials
or network calls.

| Slice | Cases and focused home |
| --- | --- |
| Resolver/provenance | Deep merge; scalar/list replace; priority; post-merge derivation; defaults snapshot/no patch; job.yml round-trip. New resolver and CLI/web tests. |
| Source/parser | Root-only, unsupported/missing/empty/nested/traversal/symlink, duplicates/order, malformed atomicity, invalid-row continuation, explicit record does not filter clips. Focused source/parser tests. |
| Create/validation | CLI/API equality, one job/source, dry-run no writes, partial successes, stable results/shared overrides. CLI/web/service tests. |
| App/auth/layout | Init/lazy startup, path resolution/replacement, registry, masking/env precedence/auth-only writes, preset+inline override. CLI/auth/layout/web tests. |
| Conversion/review | Crop/placement/captions/typography/renderer/strict; transcript hash/roundtrip; invalidation/rerender. Layout/render/transcript/web tests. |
| Checkpoint/upload | Review gates, content/platform updates, partial result, one-platform retry, historical result, future `publish_at` deferral, schedule disarm on draft change/rerender, and immediate retry. Service/web/upload; checkpoint tests under #180. |
| Lifecycle/artifacts | CRUD/status, immutable source, confirm, cancel/resume/events, preview/download containment, rename/recycle/pointers/no remote deletion, storage-reference keys and staged upload copies, retention prune and restart reconciliation. Service/web/CLI/storage tests. |
| Frontend | Source/results, masked settings, layouts, review checkpoints, `publish_at` field and scheduled-attempt badge, progress/errors, desktop/mobile. Extend `test_e2e_dashboard.py`. |

Do not introduce legacy configuration/manifest readers or duplicate validation paths; preserve lazy media imports.

This document specifies the work; production implementation is tracked by #179.

