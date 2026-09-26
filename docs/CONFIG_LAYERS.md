# Layered configuration design

This is the target design for a two-source configuration model:
**global defaults → job overrides**, where job overrides deep-merge over the
persistent defaults. Global job defaults live in `app.yml`. A `job.yml`
contains one job-level configuration object using the declared schema. Multi-job
creation is a grouping and execution concern, not a configuration tier; there is
no separate `batch.yml` or backend batch configuration tier. This replaces the
current flat, single-file config model
described informally in
`clipmorph/cli.py` and `docs/CLI_WEB_PARITY.md`.

## Goals

- One schema shape reused for global defaults and per-job overrides.
  A user can set `upload.content.title` in `app.yml`, then override it for
  an individual job.
- `layouts` remain a **global-only named registry** in `app.yml`
  (`GET/POST /layouts`). Records are `{id, name, layout}`; validate and save
  them through the shared layout validator. Tiers reference a layout by id;
  they don't compose the registry itself.
- Preserve CLI/Web parity: the CLI and web surfaces use the same `job` CRUD
  operations, per-job override records, and two-source merge.
- Preserve resumability: job manifests keep enough information to show the
  effective (merged) configuration a job ran with.

## App configuration

`app.yml` contains application/workspace settings and the persistent global
defaults for job configuration. `source_dir` and `output_dir` are app-level
paths and are not part of the job configuration merge.
`job_defaults` uses the same job-config shape shown below:

```yaml
source_dir: sources
output_dir: output
job_defaults:
  general:
    source: null
    no_confirm: false
    clean: false
  conversion: {}
  upload: {}
layouts: []
```

When multiple jobs are created together, the UI may present a shared override
form initialized from `app.yml:job_defaults`. Changed fields are copied into
each selected job's override object. The effective configuration for each job
is resolved as:

```text
merge(app.yml:job_defaults, job_overrides)
```

## Job configuration shape

```yaml
general:
  source: null                  # per-job root-level filename relative to app.yml:source_dir; null in app defaults
  no_confirm: false
  clean: false                   # null-able per section below; this is the top-level default
conversion:
  layout_id: <uuid | null>      # reference into the global layouts registry
  layout: {...}                 # optional inline overrides over layout_id; inline layout is valid without an id
  skip: false                   # skip conversion and upload the input video directly
  strict: false                 # fail on configured optional conversion/transcription errors
  no_confirm: null              # null = fall back to general.no_confirm; true/false overrides it for this step only
  clean: null                   # null = fall back to general.clean; deletes the converted clip (and subtitle artifact, unless overridden below)
  subtitles:
    skip: false                   # skip transcription and subtitle generation entirely
    renderer: overlay             # overlay | stacked; selects conversion.layout.captions.overlay or .stacked
    no_confirm: null             # null = fall back to conversion.no_confirm (which falls back to general.no_confirm)
    clean: null                  # null = fall back to conversion.clean; deletes just the subtitle/transcript artifact
    transcription_language: en
    transcription_model: tiny
    transcription_device: cpu
    transcription_compute_type: int8
upload:
  skip: false                    # skip all uploads
  no_confirm: null              # null = fall back to general.no_confirm; true/false overrides it for this step only
  schedule:                     # stub for #100, shape TBD when scheduling lands
    publish_at: null
    timezone: null
  content:
    title: ''
    description: ''
    tags: []
  platforms:
    include: []                  # only upload to these platforms (empty = all)
    exclude: []                  # exclude these platforms from an otherwise-included set
    youtube: {...}
    instagram: {...}
    tiktok: {...}
    twitter: {...}
```

`content` and `platforms` nest under `upload` — both are exclusively
upload-time concerns (what gets published and where), so there's no reason
for them to sit at the top level next to `general`/`conversion`.

`upload_to`/`skip` (the platform allowlist/denylist) move under
`upload.platforms` and are renamed `include`/`exclude` — they select which
platforms participate, exactly the concern `upload.platforms` already owns,
and `include`/`exclude` says what they do without needing the CLI's
original flag names as context.

`no_conversion` (renamed `conversion.skip`) moves from `general` into
`conversion` — it's the direct parallel of `upload.skip` (skip this
pipeline stage entirely), not a cross-cutting setting like
`general.no_confirm`/`general.clean`, which apply regardless of whether
conversion or upload run.

The old `no_conversion`/`no_subs`/`no_upload` names stutter once nested
under their own section (`conversion.no_conversion`,
`conversion.subtitles.no_subs`, `upload.no_upload`) and are inconsistent
with each other. They're renamed to a shared generic `skip: false` at each
level. `disabled` was considered first, but `skip` reads more naturally
here ("skip conversion", "skip subtitles", "skip upload") and only became
available once the platform allowlist/denylist moved to
`upload.platforms.include`/`exclude`. `general.no_confirm` keeps its name
since it isn't nested under a section named after what it disables.

`conversion.no_confirm` and `upload.no_confirm` let a step opt out of (or
back into) confirmation prompts independently of the global default. This
is a **section-level fallback**, not the tier merge: within one already-merged
configuration, `effective_no_confirm(step) = step.no_confirm if step.no_confirm
is not None else general.no_confirm`. `general.no_confirm` remains the only
boolean with a concrete default (`false`); the section-level fields default
to `null`/unset so they don't silently shadow the global setting.

`clean` becomes composable the same way. `general.clean` is the top-level
default: when true it deletes every generated artifact for the job (the
converted clip, the subtitle/transcript artifact) once the job's steps
finish — it never deletes the job manifest/history itself, so a cleaned-up
job remains visible and users can still delete it explicitly later.
`conversion.clean` overrides that default for the converted clip (and,
transitively, the subtitle artifact); `conversion.subtitles.clean` overrides
just the subtitle/transcript artifact, ignoring whatever `conversion.clean`
says about it. The fallback chain mirrors `no_confirm`:
`conversion.subtitles.clean` → `conversion.clean` → `general.clean`.
`upload` has no `clean` of its own — uploads don't produce a local artifact
of their own beyond the conversion output and remote platform state, which
isn't something this config deletes.

`conversion.subtitles` groups everything about whether/how the transcript
track is generated (`skip`, `transcription_language`,
`transcription_model`, `transcription_device`, `transcription_compute_type`)
separately from the rest of `conversion`, since none of it applies once
`skip` is set. Its `no_confirm` extends the same fallback chain one level
further: `conversion.subtitles.no_confirm` → `conversion.no_confirm` →
`general.no_confirm`. This is distinct from `conversion.layout.captions`, which controls
placement and typography of rendered caption content —
`conversion.subtitles` controls whether and how transcript content is
generated in the first place.

`conversion.no_cam` / `conversion.camera` (`cam_x`/`cam_y`/`cam_width`/
`cam_height`) are dropped, not deprecated-with-a-fallback — per repo
convention there's no compatibility shim. The camera feed was always just a
fixed crop of the source video; that's exactly what `layout.crop` already
models, so a camera overlay is now expressed as a crop layout instead of a
parallel set of `conversion` fields. Converting the old defaults
(`cam_x=1420, cam_y=790, cam_width=480, cam_height=270`) to the new shape is
`crop: {enabled: true, source: {x: 1420, y: 790, width: 480, height: 270}, sizing: {mode: fit}, composition: {mode: overlay, placement: top}}`.
The conversion pipeline's current camera compositing
(`edit.py::_process_camera_feed`/`_process_main_clip`/`_blur_background`,
a fixed top/bottom stack) and its generic crop overlay
(`edit.py::_apply_layout`, a picture-in-picture overlay) are two different
ffmpeg filter graphs today — reconciling them into one implementation is
follow-up conversion-pipeline work, not part of this config-shape change.

`layouts:` (the named registry) exists only in `app.yml` at the global app
level and is not part of the job configuration merge — it is a lookup table
`conversion.layout_id` resolves against.

## Layout object shape

Both an `app.yml` layouts registry entry's `layout` field and an inline
`conversion.layout` use the same shape, validated by
`clipmorph.layout.validate_layout`:

```yaml
crop:
  enabled: false
  source: {x: 0, y: 0, width: 0, height: 0}   # required when enabled; must fit inside the source video
  sizing:
    mode: fit          # fit | stretch | native; controls crop scaling only
    dimensions: {width: 0, height: 0}   # required for fit and stretch
  composition:
    mode: overlay      # overlay | stacked
    placement: top     # overlay: region or {x, y}; stacked: region or {y}
captions:
  overlay:
    items:              # flexible text layers; items may overlap in time and placement
      - placement: center      # named region, or {x: 540, y: 960} for pixels
        dimensions: {width: 0, height: 0}     # optional; omitted = text-measured
        text: "..."
        range: [0, 2.5]   # optional; [start, end] seconds when timed
        typography:       # optional; item-specific
          size: 64
          color: null       # null = pipeline-selected; explicit color overrides it
          font_file: null
          outline_color: black
          bold: true
          italic: false
          underline: false
  stacked:
    placement: top      # named region, or {y: 960}; x is always canvas-centered
    dimensions: {width: 0, height: 0}     # optional; omitted = largest-item dimensions
    panel:               # fixed panel styling
      color: black
      padding:           # fixed text padding within the panel
        left: 64
        top: 48
    items:              # text content that changes within the fixed layout
      - text: "..."
        range: [0, 2.5]   # optional for one item; [start, end] seconds when timed
        typography:       # item-specific text styling
          size: 64
          color: null       # null = pipeline-selected; explicit color overrides it
          font_file: null
          outline_color: black
          bold: true
          italic: false
          underline: false
```

Crop sizing and composition are independent. `fit` preserves the source
aspect ratio inside the declared dimensions, `stretch` forces the declared
dimensions, and `native` retains the cropped source dimensions. `overlay`
places the result over the existing canvas at the selected region without
participating in layout flow. `stacked` places the result into the composed
layout stack at the selected region or vertical center coordinate, so
`top`, `center`, and `bottom` are valid for both modes and every sizing mode.

Overlay elements use a scalar-or-object `placement`: a named region such as
`top`, `center`, or `bottom`, or an object such as `{x: 540, y: 960}`.
Coordinate objects represent the element's center point in output pixels,
measured from the top-left of the target canvas. The target canvas is 1080x1920
by default. A named region is resolved to the equivalent center coordinate
using the target canvas and the element's resolved dimensions. Stacked crops
and stacked captions may use either a named region or a `{y: ...}` coordinate;
an `x` coordinate is not accepted for either stacked element type. Their `x`
is always the horizontal center of the target canvas because stacked
composition is centered horizontally.

Caption dimensions follow a deterministic authority rule. When overlay item
dimensions are omitted, they are measured from the rendered text,
item-specific typography, and any applicable padding. When stacked dimensions
are omitted, the shared panel is sized to contain the largest rendered stacked
item plus its padding, so the panel remains stable while text changes. When
dimensions are explicitly provided, they are authoritative; text that cannot
fit is a validation error rather than silently shrinking typography or
clipping text.

Caption behavior is separated into two collections. `overlay.items` draws
flexible text layers directly over the current video layer; overlay items may
overlap in time and may use independent placement. `stacked.items` composes
panel-and-text content using the one shared layout declared under `stacked`.
Stacked items define only text and timing; they cannot override the panel's
placement, dimensions, padding, or styling. Typography remains
item-specific because it styles the text rather than the physical panel. A
single stacked item may omit `range`, which means it applies for the full media
duration. Multiple stacked items must use non-overlapping ranges so the fixed
panel has one active text value at a time.

Generated subtitles use the same rendering concepts and auto-fill the
collection selected by `conversion.subtitles.renderer`:
`overlay` targets `conversion.layout.captions.overlay.items`, while `stacked`
targets `conversion.layout.captions.stacked.items`. The selector is explicit; the implementation must
not infer a renderer from whichever collection happens to be present. The
selected caption renderer, placement, panel geometry, and typography remain
in `conversion.layout.captions`; generated transcript segments provide the item text and
timing. Omitted stacked dimensions are measured from the largest rendered
item, while explicit dimensions are authoritative and must contain every
rendered item. The selected collection must exist when stacked-specific
settings are required; otherwise validation fails.

When `conversion.subtitles.no_confirm` is `false`, conversion pauses after
transcription and opens a transcript review step before rendering. The review
session may edit each generated segment's text and timing and may attach a
partial per-segment `typography` override. The selected caption renderer,
placement, panel geometry, and other track-level settings remain in
`conversion.layout.captions` and provide defaults for every generated item. When
`conversion.subtitles.no_confirm` is `true`, the generated transcript is
accepted with those defaults without pausing for review. Segment edits are
stored in the versioned transcript edit session and persisted with the job,
not in the reusable layout definition.

All caption and subtitle typography objects use the same keys: `size`,
`color`, `font_file`, `outline_color`, `bold`, `italic`, and `underline`. A
`null` `color` delegates
to the conversion pipeline's automatic color selection; declaring an explicit
color overrides that selection. Placement, panel geometry, padding, and
spacing remain renderer-specific layout settings.

Generated subtitle items and authored caption items share the same renderer
collections. Generated items are appended after authored items, preserving
authored order. After named or pixel placement and automatic dimensions are
resolved, overlapping stacked items are invalid; the configuration must not
rely on implicit z-order or panel reflow. Overlay items may overlap according
to their normal overlay rules.

`crop` and `captions` are each optional; an empty `{}` layout is valid (no
crop, no captions). `conversion.subtitles` controls
whether and how transcript content is generated, while generated content is
rendered through `captions`. When `conversion.layout_id` is set, resolve its
registry layout first and deep-merge optional `conversion.layout` overrides on
top. Without an id, `conversion.layout` is the inline layout. Persist both the
selected `layout_id` and fully materialized `layout` in the effective job.

## Merge semantics

- Deep-merge dictionaries key by key.
- Scalars and lists are fully replaced by the lower tier's value (no
  concatenation) — matches the existing "only set if the destination
  attribute is absent" behavior in `cli._apply_config_defaults`, generalized
  to two sources instead of the former flat CLI/config layering.
- Order of precedence: job overrides win over global defaults. Applied as
  `merge(app.yml:job_defaults, job_overrides)`.
- `conversion.layout_id` resolves the app registry first, then
  `conversion.layout` deep-merges over the resolved preset. The effective
  configuration stores the fully materialized layout; `layout_id` alone is
  sufficient to select a preset, while an inline layout provides overrides.
- Missing optional values resolve to the least expensive valid behavior:
  transcription uses `tiny`/`cpu`/`int8`, captions default to the overlay
  renderer, and unspecified styling delegates to pipeline defaults.
- Section-level fallbacks (`conversion.subtitles.no_confirm` →
   Section-level fallbacks (`conversion.subtitles.no_confirm` →
  `conversion.no_confirm` → `general.no_confirm`; `upload.no_confirm` →
  `general.no_confirm`; `conversion.subtitles.clean` → `conversion.clean` →
  `general.clean`) are resolved *after* the two sources are merged, against
  the single effective configuration — they are not part of the tier-merge
  algorithm itself.

## Derived Values

Derived values are resolved after merging global defaults and job overrides.
An explicit value always wins over a derived value:

- `general.source` is populated from the selected root-level source filename
  when a directory is created as a job source.
- `upload.content.title` defaults to the source filename stem when empty or
  unset. The extension is removed and the remaining name is used as-is unless
  the user provides an explicit title.
- `conversion.layout_id` is materialized through `app.yml:layouts`; an inline
  `conversion.layout` deep-merges over that preset. The effective job retains
  both the original `layout_id` and the fully materialized `layout`.
- Named placements resolve to pixel centers using the target canvas and
  resolved dimensions.
- Omitted caption and stacked-panel dimensions resolve from rendered text,
  typography, and padding.
- Generated transcript segments populate the selected caption renderer after
  transcription and review.

Runtime identifiers, normalized absolute source paths, artifact paths, and
checkpoint state belong to the job manifest rather than the reusable job
configuration.

## Resolution Pipeline

Each job is resolved in this order:

1. Load `app.yml:job_defaults`.
2. Load the per-job override object from `job.yml`, JSONL/YAML input, a
  sidecar, or the UI/API request.
3. Normalize and validate `general.source` against `app.yml:source_dir`.
4. Deep-merge global defaults with the per-job override object.
5. Derive missing values on the merged effective configuration.
6. Materialize layout presets and resolve placement and dimensions.
7. Persist the effective job configuration and manifest.

Derived values do not mutate `app.yml:job_defaults` or the original override
object. Interactive checkpoint edits update the effective job configuration,
job provenance, and the persisted job record.

## Where each tier lives

| Tier | Storage | Lifetime |
| --- | --- | --- |
| Global defaults | `app.yml` global job defaults + layouts registry | Persistent, user-edited defaults |
| Multi-job context | In-memory selected-clip run configuration | Ephemeral UI/API/CLI grouping; not a merged schema tier |
| Job | Finalized `job.yml` inside the job directory, or the equivalent in-memory UI/API request body | Persisted with that job's manifest |

`app.yml` stores application/workspace settings such as the source directory
and output directory, plus the persistent global job defaults. When a user
starts a multi-job creation request, the UI/API copies changed fields from the
defaults into each selected job's override object. The multi-job context is
intentionally **not** a saved/named preset like layouts — it is scoped to one
creation request and discarded once jobs are created.

## CLI Job Commands

The CLI exposes CRUD operations under `job`; the create operation accepts one
source file or a source directory and may create one or many jobs:

```bash
clipmorph job create <source.mp4>
clipmorph job create <source-dir>
clipmorph job create <source-dir> --job-configs jobs.jsonl
```

The same service contract is used by the web API. A source directory is scanned
only at its root; unsupported or missing sources are skipped and reported. No
nested traversal is performed. Explicit override records take precedence over
the default configuration directory. When no explicit override record exists,
the command synthesizes one job configuration per supported clip and
auto-populates `general.source` with that clip's filename before merging
`app.yml:job_defaults`.

Each JSONL/YAML record is itself a job configuration object. Its
`general.source` value is a root-level filename relative to
`app.yml:source_dir`; it must not contain directory separators. YAML uses the
same job configuration shape as a list:

```jsonl
{"general":{"source":"clip1.mp4"},"upload":{"content":{"title":"Clip 1"}}}
{"general":{"source":"clip2.mp4"},"upload":{"content":{"title":"Clip 2"}}}
```

The equivalent YAML input is:

```yaml
- general:
    source: clip1.mp4
  upload:
    content:
      title: Clip 1
- general:
    source: clip2.mp4
  upload:
    content:
      title: Clip 2
```

`general.source` is resolved during input normalization and copied to the
manifest's normalized `source_path`; it remains in the final job configuration
for traceability. It is not treated as a behavioral merge setting. The global
default must keep it `null`, and every created job must resolve it to an
existing supported file under the configured source directory.

Configuration input priority is explicit per-job JSONL/YAML, then an explicit
config directory containing `clip.mp4.yml` sidecars, then `clip.mp4.yml`
sidecars in `app.yml:source_dir`. Explicit records override matching files but
do not change selection: every supported root-level clip is still processed.
If no override source is provided, every job uses only
`app.yml:job_defaults`.

Single-job and multi-job creation use the same `job` service and merge
`app.yml:job_defaults` with each record. `job list`, `job
get`, `job update`, `job delete`, and `job resume` operate on the resulting
job manifests.

There is no separate `batch.yml`. Multi-job creation is a grouping context;
batch-form edits are copied into each selected job's override object before the
same two-source merge runs. Generated caption items are not a new top-level job
configuration section; they are materialized at runtime inside the selected
`conversion.layout.captions` renderer and persisted through the transcript edit
session when reviewed.

`clipmorph/batch.py` (`BatchProcessor`) will support multi-job creation by
iterating root-level clips, applying per-job overrides, skipping invalid
sources, and reusing its existing hashing/dedup and bounded concurrency
behavior instead of being replaced outright.

## Web Job API

and does not create a group manifest. Shared UI fields are copied into each
`docs/CLI_WEB_PARITY.md` is authoritative for HTTP routes and request/response
shapes. Single-source creation is `POST /api/v1/jobs`; multi-source creation is
`POST /api/v1/jobs/bulk`, an ephemeral fan-out that creates independent jobs.
Its request carries `source_names`, direct job-schema `job_configs`, and
optional shared `overrides`. No group identifier, batch configuration tier, or
group manifest is persisted. Explicit records override matching sidecars but
do not narrow default root-level discovery.

For each source, both surfaces resolve `merge(app.yml:job_defaults,
job_overrides)`, validate it, persist finalized effective `job.yml`, and create
one manifest. The bulk response reports created/skipped/failed outcomes per
source; successful jobs are not rolled back because another source fails.
Job edits update only that job's effective config, never `app.yml`; changed app
defaults affect future jobs only. Updates use the checkpoint/config hash and
reopen rules below. Resume never silently re-merges newer app defaults.

## Job Manifest And Checkpoints

The manifest is the source of truth for lifecycle and audit state; `job.yml`
is the source of truth for the job's current effective configuration. Bump the
manifest schema for this contract. No migration or dual-read path is needed.
Persist timestamps as UTC ISO-8601 values, hashes as lowercase SHA-256 hex, and
errors without credentials or secret values.

```json
{
  "schema_version": 2,
  "status": "awaiting_review",
  "current_checkpoint": "transcript",
  "current_configuration_hash": "<sha256 of canonical effective job.yml>",
  "configuration": {"general": {"source": "clip.mp4"}, "conversion": {}, "upload": {}},
  "configuration_sources": {"global_defaults": {"general": {}, "conversion": {}, "upload": {}}},
  "checkpoints": {
    "transcript": {
      "status": "awaiting_review",
      "revision": 1,
      "configuration_hash": "<sha256 of transcription dependency projection>",
      "artifact_hash": "<sha256 of transcript session file>",
      "session": {"revision": 1, "path": "transcripts/revision-0001.json"},
      "created_at": "<UTC timestamp>",
      "started_at": "<UTC timestamp>",
      "updated_at": "<UTC timestamp>",
      "completed_at": null,
      "invalidation_reason": null,
      "error": null
    },
    "conversion": {"status": "pending", "revision": 0},
    "upload": {"status": "pending", "revision": 0}
  },
  "current_artifact_id": null,
  "artifacts": {},
  "upload_attempts": []
}
```

Each checkpoint record has `status`, monotonic `revision`, dependency
`configuration_hash`, nullable `artifact_hash`, `created_at`, `started_at`,
`updated_at`, nullable `completed_at`, nullable `invalidation_reason`, and
nullable structured `error`. `error` contains a stable code, safe message,
occurrence timestamp, attempt id, and retryable flag. Stage-local fields such
as transcript-session reference, conversion-artifact reference, or per-platform
results are persisted alongside these common fields. `current_configuration_hash`
hashes the entire canonical effective job configuration; each checkpoint's
`configuration_hash` hashes only the normalized inputs that determine that
stage's output. `current_checkpoint` is the earliest required stage that is
pending, stale, failed, or awaiting review; it is null when all required stages
are complete. Top-level `status` is derived as `created`, `queued`, `running`,
`awaiting_review`, `partial_failure`, `failed`, `cancelled`, or `completed`; it
is not an independent source of truth.

Checkpoint statuses are `pending`, `running`, `awaiting_review`, `completed`,
`partial_failure`, `skipped`, `failed`, `cancelled`, and `stale`.
`partial_failure` is valid only for upload, where per-platform attempt results
remain individually visible and successful platforms are not repeated by a
targeted retry. Legal flow is:

| Checkpoint | Legal progression |
| --- | --- |
| Transcript | `pending → running → awaiting_review → completed` |
| Conversion | `pending → running → awaiting_review → completed` |
| Upload | `pending → awaiting_review → running → completed` or `partial_failure`; a targeted retry returns it to `running` and appends results |
| Retry/edit | `failed` or `cancelled → pending`; changed inputs make a completed checkpoint `stale → pending` |
| Optional stage | `pending → skipped`; a configuration change may make it required again |

An invalid transition returns a conflict and does not change the manifest.
Transcript and conversion checkpoints stop for review after producing their
candidate outputs. The upload checkpoint stops for review after conversion is
accepted and before any remote upload. Accepting a review completes that
checkpoint and makes the next required checkpoint actionable. `job resume`
continues execution only; it does not accept or bypass a review. It returns a
review-required result when the next checkpoint is awaiting review. Overall
`completed` means every required checkpoint for the current effective
configuration is completed; skipped optional stages do not block completion.

### Transcript Session And Effective Configuration

Store each transcript session in the job directory as an immutable revision,
for example `transcripts/revision-0001.json`. It contains the source hash,
media duration, original generated segments, edited segments, and stable
segment ids. Each edited segment may carry its own typography override. The
manifest links the active session revision and its file hash. Saving a review
creates a new session revision; it never overwrites the original or a prior
accepted review. The session file is canonical for transcript text, timing,
and per-segment typography.

On transcript acceptance, generated segments are materialized into the
explicitly selected `conversion.layout.captions.overlay.items` or
`conversion.layout.captions.stacked.items`. Generated items carry an internal
`transcript_segment_id` marker. Re-materialization replaces only items carrying
that marker and preserves authored items and their order. The transcript
session remains authoritative; the generated items in effective `job.yml` are
a derived copy for rendering. The selected renderer is never inferred from
which collection happens to exist.

Behavioral checkpoint edits update only that job's finalized effective
`job.yml`, its configuration hash, and the relevant manifest checkpoint. They
do not mutate `app.yml` or re-save a reusable layout preset. A transcript edit
updates the session revision and regenerates the marked items in `job.yml`; a
composition or upload-review edit updates its corresponding effective config
fields. Writes use temporary files and atomic replacement; the manifest points
at the new revision only after the referenced files are durable.

### Artifact And Upload History

Every successful render creates a new immutable conversion revision and a
unique artifact id. A manifest artifact entry contains its id, revision, kind,
relative or normalized path, SHA-256, conversion configuration hash,
transcript revision (when used), creation timestamp, and state. The manifest's
`current_artifact_id` points to the latest render; it may point to a stale
artifact while a rerender is required. A rerender never overwrites an existing
artifact. The previous artifact is marked `superseded`; configuration edits
before rerender mark it `stale`. Both remain on disk by default. Only explicit
artifact deletion removes local bytes, and deletion leaves an audit tombstone
and all upload references intact.

Each upload attempt is append-only and records attempt id, platform, artifact
id and SHA-256, the upload-content/platform/schedule configuration snapshot and
hash, start/completion timestamps, outcome, and safe response/error details.
An attempt is never rewritten to point at a newer artifact or new content.
Partial platform success remains visible per attempt and platform. Remote
uploads are historical results; local edits never silently update or delete
them.

### Invalidation And Retry Rules

Checkpoint input hashes are derived from these dependencies:

| Change | Invalidated state | Retained history |
| --- | --- | --- |
| Transcript text, timing, segment typography, transcript generation settings, or source identity | Transcript and downstream conversion/upload work; converted artifact becomes stale | Prior transcript sessions, artifacts, and upload attempts |
| Crop, captions/layout, subtitle/rendering, or composition settings | Conversion and pending upload work; converted artifact becomes stale | Prior artifacts and upload attempts |
| Title, description, tags, schedule, or platform options | Upload draft/current upload checkpoint only; conversion remains valid | All prior upload attempts and remote results |
| No dependency hash changes | Nothing | All state unchanged |

Source identity is fixed for a job; changing the source requires creating a new
job. Editing `app.yml` defaults does not change an existing job. `job update`
applies a validated deep-merge patch to that job's effective configuration
(lists replace), recomputes the affected hashes, and marks the earliest changed
checkpoint stale with a structured reason. It marks downstream work pending
only when that work can be repeated from the new inputs. Upload-only edits do
not discard a valid conversion artifact.

After transcription failure, retry transcription with current transcript
settings; preserve prior failed-attempt details and any prior transcript
revision. After conversion failure, retry from the latest accepted transcript
and current composition config; create a new artifact only on success. After
upload failure, retrying an attempt uses that attempt's exact artifact and
frozen upload settings and appends a new attempt record. To use edited upload
settings, create a new upload submission from the upload review checkpoint.
Retry is limited to failed platforms unless the user explicitly selects more.

Upload retry names the failed `attempt_id` and reuses that attempt's artifact
and frozen upload settings. If its artifact is no longer current, the retry
must also provide the matching `artifact_id` and
`confirm_historical_artifact: true`. A new submission targeting an older
artifact requires the same explicit id and confirmation. A missing or locally
deleted artifact cannot be uploaded.
Failed transcription/conversion attempts are retryable after returning to
`pending`; retries never delete prior transcript sessions or artifact files.

A completed job can be reopened only through an explicit review/edit or update
with confirmation (`--reopen` in non-interactive CLI use, or `reopen: true` in
the API). Only the affected checkpoint and its downstream dependencies reopen.
Previously successful remote uploads remain immutable history, even when a new
artifact or upload attempt is created.

### CLI And Web Checkpoint Contract

CLI review, accept, update, retry, artifact, upload, and resume operations use
the same `JobService` transitions as the web API. The web contract is:

| Operation | Route | Contract |
| --- | --- | --- |
| Read job/checkpoints | `GET /api/v1/jobs/{id}` | Return aggregate status, all checkpoint revisions, active transcript session, artifact pointers, and upload history references |
| Update job config | `PATCH /api/v1/jobs/{id}/configuration` | Accept a patch, `expected_configuration_hash`, and optional `reopen`; validate and update only that job's `job.yml` |
| Read/save transcript | `GET/PUT /api/v1/jobs/{id}/transcript` | Validate source hash and expected transcript revision; save a new immutable session revision and invalidate conversion when accepted edits change |
| Accept transcript/conversion review | `POST /api/v1/jobs/{id}/checkpoints/{transcript\|conversion}/accept` | Require the current checkpoint revision; return conflict on stale review input |
| Review/update upload draft | `GET/PUT/DELETE /api/v1/jobs/{id}/checkpoints/upload` | Update or discard only the pending draft; never modify prior upload attempts |
| Resume/retry | `POST /api/v1/jobs/{id}/resume`; `POST /api/v1/jobs/{id}/checkpoints/{stage}/retry` | Resume earliest executable checkpoint; return conflict if review is required; retries append attempt/error history |
| Artifacts | `GET/PATCH/DELETE /api/v1/jobs/{id}/artifacts/{artifact_id}` | Patch display metadata only; delete local bytes after confirmation and retain a tombstone |
| Upload history/start/retry | `GET /api/v1/jobs/{id}/uploads`; `POST /api/v1/jobs/{id}/upload`; `POST /api/v1/jobs/{id}/uploads/{platform}/retry` | Retry requires `attempt_id`; if its artifact is no longer current, require matching `artifact_id` and `confirm_historical_artifact: true` |

Mutations accept an expected checkpoint/configuration revision and return
`409 Conflict` on concurrent edits or illegal transitions. Validation failures
return `422`; missing jobs or revisions return `404`. The CLI exposes the same
operations and reports the same checkpoint names, revisions, invalidation
reasons, and per-platform outcomes. Batch-form values are expanded into
individual job override objects before either caller invokes the shared
configuration resolver.

## Open items intentionally left unspecified

- Full `upload.schedule` shape, queued/published/failed/canceled states, and
  history are out of scope here — tracked in
  [A-Baji/ClipMorph#100](https://github.com/A-Baji/ClipMorph/issues/100).
  Only the field's *location* (composable, under `upload`) is decided now.
- Whether multi-job groups ever become save-able presets later is deferred;
  today they are ephemeral execution groups.

## Implementation phases (once this design is approved)

1. Extract a shared `merge_configuration(global, job)` helper (new
   `clipmorph/config.py` or added to `cli.py`) and unit tests.
2. Add CLI `job` CRUD commands plus JSONL/YAML per-job override parsing,
  repurposing `clipmorph/batch.py` for multi-source creation.
3. Align the web `job` CRUD API with the CLI and expand UI form changes into
  per-job overrides before using the shared two-source merge helper.
4. Bump `JobManifest` schema and add `configuration_sources`.
5. Remove `no_cam`/`camera`/`cam_*` from the CLI parser, `cli.py` config
   flattening, `workflow.py`, `preflight.py`, and `edit.py`'s constructor;
   route camera use through `layout.crop` instead. Extend
   `clipmorph.layout.validate_layout` to validate the new `subtitles`
   object. Reconcile `edit.py`'s fixed camera-stack pipeline with the
   generic `_apply_layout` crop/caption/subtitles pipeline into one
   implementation.
6. Update `docs/CLI_WEB_PARITY.md` and frontend batch/layout UI to expose
   batch vs. per-clip fields and the new `subtitles` styling controls.
