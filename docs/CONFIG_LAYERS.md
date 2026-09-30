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
paths and are not part of the job configuration merge. `config_version`,
`retention`, and the `layouts` registry are likewise app-level and never merge
into a job. `job_defaults` uses the same job-config shape shown below:

```yaml
config_version: 1
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
retention:
  artifacts:
    max_age_days: null
    max_bytes: null
  backups:
    keep_n: null
storage:
  backend: local
```

`config_version` is a stamp of the app-configuration schema shape, maintained
in `clipmorph/configuration.py:APP_CONFIG_VERSION` and bumped in the same
commit as any breaking `app.yml` change. It is deliberately independent of the
job manifest `schema_version` in `clipmorph/job.py`; the two are never
unified. Loading rejects a file whose stamp is missing or different *before*
any other field is inspected, so an outdated file produces one actionable
error instead of a validation cascade. `clipmorph init` run beside an existing
`app.yml` regenerates a current template to copy settings into; the CLI never
rewrites an existing `app.yml` in place.

`storage.backend` selects the artifact storage backend and is app-level, never
part of the job configuration merge. Phase 1 accepts only `local`; any other
value is rejected as `unknown storage backend` (web `PUT /configuration`
answers `422 invalid_configuration`). `clipmorph.storage.make_storage` is the
single place that builds the backend, and `JobService` grabs it once at
construction.

`output_dir` doubles as the artifact root: every manifest artifact record
stores a storage reference `{backend, key}` instead of a local `path`, and the
`key` is always relative to that root (`<job_id>/<artifact_name>.mp4`). A file
outside the root — the source artifact in `source_dir` — keys with the
relative path that reaches it (`../sources/clip.mp4`), so one root resolves
every key on the `local` backend and the same key is the object key a remote
backend would use. `clipmorph.storage.storage_key_for` is the only place that
derives a key from a file and the root. The `signed_url` contract is
explicitly unsupported for the `local` backend: local preview and download
stream the registered bytes.

`retention` bounds what a long-lived workspace accumulates. Every knob
defaults to `null`, which makes retention a no-op until a policy is set:

- `retention.artifacts.max_age_days` prunes non-source artifacts in the
  `superseded` state once they are older than this, aged from `superseded_at`
  (falling back to `created_at`).
- `retention.artifacts.max_bytes` caps the total bytes recorded for a job's
  artifacts, evicting the oldest obsolete revisions first until the job is
  under the cap.
- `retention.backups.keep_n` caps rotated `<file>.backup[n]` copies of
  credential files; it defaults to 5 when unset or when `app.yml` cannot be
  read (credentials may be persisted before a valid `app.yml` exists).

`current` and `stale` artifacts are never auto-pruned, so a rerender target
always survives; a pruned artifact keeps its manifest entry with a `deleted`
tombstone, and its bytes go to the system trash rather than being unlinked.
Pruning recycles through the configured storage backend's `remove(key)`; a
backend failure is recorded as a manifest warning, never an error, because
cleanup cannot fail a job. Enforcement runs automatically after a job's run
completes and is also
available on demand as `clipmorph job artifacts prune ID` and
`POST /api/v1/jobs/{id}/artifacts/prune`. Both return `{"pruned": [...],
"bytes_freed": N}`; the no-policy case returns `{"pruned": []}` without
touching the manifest.

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
  schedule:
    publish_at: null              # ISO-8601 instant; a future value defers the upload instead of running it now
    timezone: null
    mode: null                    # local | platform; null = local. "platform" asks the platform to hold the publication
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

`upload.schedule.mode` decides **who holds** a future publication: `local`
(the default, and the value an absent `mode` reads as) keeps ClipMorph's
in-process timer, `platform` uploads at submission time and asks the platform
to hold the publication itself. It is inert without a deferred upload — no
`publish_at`, or one that is not in the future, uploads immediately whatever
`mode` says. It is one string for the whole job, not a per-platform map:
platform eligibility is not a configuration question, so a submission whose
selected platforms cannot hold the publication is refused outright rather
than partially honoured:

```text
upload.schedule.mode platform is not enabled for: <platforms>
See quality/research/scheduling_probe.py — run it with sandbox tokens, then
flip `SUPPORTED_NATIVE_SCHEDULING` in clipmorph/platforms.py.
```

The gate is `clipmorph/platforms.py::SUPPORTED_NATIVE_SCHEDULING`, one entry
per supported platform, and every entry ships `false` because a platform is
only marked capable after the maintainer's sandbox probe has observed a full
schedule → inspect → cancel cycle on the real API. `docs/PLATFORM_CAPABILITIES.md`
carries the per-platform probe status next to the parameter each adapter sends,
and the two change in the same commit. The strict error is deliberate: silently
falling back to ClipMorph's own timer would publish at a different time than the
one the user asked for and record the wrong `scheduled_via` history.

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
An explicit `font_file` selects that exact face; to use bold or italic with a
custom font, point it to the corresponding styled font file.

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
config-directory sidecar, then a source-directory sidecar, then
`app.yml:job_defaults`. Each immediate `.yml` or `.yaml` sidecar is one job
configuration object and must declare its root-level `general.source`. The
filename is not semantic; sidecars are matched by the exact source filename in
that field. Thus `clip.mp4` and `clip.mov` are distinct keys even though they
share a stem. Each directory may contain at most one sidecar for a given
`general.source`; duplicates are rejected as ambiguous. Explicit records
override matching sidecars but do not change selection: every supported
root-level clip is still processed. If no override source is provided, every
job uses only `app.yml:job_defaults`.

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

## Web Job API

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
  "schema_version": 3,
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
a `storage` reference (`{backend, key}` with the key relative to `output_dir`,
never a local path), SHA-256, conversion configuration hash,
transcript revision (when used), creation timestamp, and state. The manifest's
`current_artifact_id` points to the latest render; it may point to a stale
artifact while a rerender is required. A rerender never overwrites an existing
artifact. The previous artifact is marked `superseded`; configuration edits
before rerender mark it `stale`. Both remain on disk by default. Only explicit
artifact deletion removes the bytes, and deletion leaves an audit tombstone
and all upload references intact.

Each upload attempt is append-only and records attempt id, platform, artifact
id and SHA-256, the upload-content/platform/schedule configuration snapshot and
hash, a content hash for dedup, start/completion timestamps, outcome, and
safe response/error details. A completed attempt's `result` also carries
`progress_percent`, the last observed live upload percent; live percents are
runtime state and are never rewritten into a terminal record. An attempt is
never rewritten to point at a newer artifact or new content. Partial platform
success remains visible per attempt and platform. Remote uploads are historical
results; local edits never silently update or delete them.

Attempt statuses are `pending`, `scheduled`, `running`, `published`, `failed`,
and `cancelled`. A scheduled attempt waits on a future `publish_at`; when the
timer fires it moves to `running`, then to a terminal state. A successful
upload records `platform_post_id`, `platform_url`, and `published_at` in its
result. A `cancelled` attempt is a scheduled upload aborted before its timer
fired. The submission-side dedup guard rejects a new submission when the same
platform already holds an active (`pending`, `scheduled`, or `running`)
attempt for the same artifact bytes and content hash.

A deferred attempt records who owns its publication in `scheduled_via`
(`local` or `platform`), written when the attempt is created and never
back-filled by a loader. `local` attempts behave as above: an in-process timer
fires the upload and the attempt ends `published` or `failed`. `platform`
attempts are uploaded at submission time — the upload lands while the platform
holds the future publication — and the attempt therefore *stays* `scheduled`
after a successful worker pass, with `platform_post_id`, `platform_url`,
`scheduled_publish_at`, and a message recording that the platform holds it.
Recording `published` here would claim a visibility only the platform can
confirm; the flip happens when the platform publishes. The upload checkpoint
still reaches a terminal state after that pass, because restart
reconciliation would otherwise treat the checkpoint as interrupted work and
re-upload content the platform already holds. A platform-scheduled attempt
holds no local timer, so it is excluded from re-arm and from the
"still waiting on a future instant" test; a crash in the gap between the
platform accepting the upload and the attempt recording it is healed from
platform state on the next service construction (below).

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

### Restart Reconciliation

A process that dies mid-step leaves a `running` checkpoint with no thread behind
it, so the manifest alone cannot be trusted to describe live work. On
construction the service scans `jobs/*/job.yml` once and reconciles each manifest
whose recorded status is `running`: the in-flight checkpoint is marked `failed`
with `{"code": "interrupted_by_restart", "retryable": true}` and the job returns
to a state where `resume` or a checkpoint retry is actionable, instead of
appearing permanently stuck. A `queued` manifest is left alone — all-pending
checkpoints are not evidence of a crash — and a `running` job whose checkpoints
have all gone terminal has only its drifted status re-derived.

A `running` upload checkpoint whose every `scheduled` attempt waits on a
future `publish_at` is deliberately left alone — that is a deferral waiting on a
timer, not a stall, and reconciliation would otherwise cancel a schedule the
restart was supposed to keep. A past-due `scheduled` attempt is healed as an
interrupted failure, never published unattended. A platform-scheduled attempt
is the one exception to both rules: it is not waiting on this process, so a
`running` upload checkpoint holding only such attempts is interrupted work. If
a platform-scheduled attempt with no recorded result is attached to that
checkpoint, reconciliation first settles it from platform state through the
adapter's existing-post lookup — a post that is there completes the attempt as
`published` with its id and URL, and no post marks it `failed` with a retryable
`platform_schedule_unconfirmed` note, so the user's ordinary retry is both the
re-upload and the refresh. The healed count is logged at startup. The
checkpoint itself then fails as interrupted work, because that worker pass
really did not finish; the attempt row is the source of truth for what the
platform holds, so a job never reads as published on the strength of a post
ClipMorph merely believes is out there. Reconciliation runs before the re-arm
scan, so genuinely scheduled local attempts get their timers back.

The manifest is the only input: no attempt is resumed automatically, and no
remote upload is repeated without an explicit user action. Because
reconciliation reads on-disk state, two concurrent instances pointed at the same
data directory can mark each other's live jobs failed at the exact moment they
cross; the checkpoint review flow remains the user-facing guard against that
race. A manifest that cannot be parsed is logged and skipped, never rewritten.

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
| Cancel one scheduled attempt | `DELETE /api/v1/jobs/{id}/scheduled/{attempt_id}` | `202` with the cancelled attempt; `404` for an unknown attempt, `422` when it is not `scheduled`. A local attempt is disarmed and its surviving batch members re-armed; a platform-scheduled attempt is deleted on the platform first, and a refusal leaves it `scheduled` with a `platform_cancel_failed` note |

Mutations accept an expected checkpoint/configuration revision and return
`409 Conflict` on concurrent edits or illegal transitions. Validation failures
return `422`; missing jobs or revisions return `404`. The CLI exposes the same
operations and reports the same checkpoint names, revisions, invalidation
reasons, and per-platform outcomes. Batch-form values are expanded into
individual job override objects before either caller invokes the shared
configuration resolver.

## Open items intentionally left unspecified

- `upload.schedule.publish_at` is implemented as a deferral: a submission whose
  snapshot carries a future instant arms an in-process timer and leaves the
  attempts `scheduled` with `scheduled_publish_at` set, instead of uploading
  immediately. A timestamp in the past, a value within one second of now, or a
  missing value uploads immediately, and a targeted retry always uploads
  immediately regardless of the snapshot. The schedule belongs to the accepted
  submission, not to the draft: editing or discarding the draft, or rerendering
  the conversion, cancels the timer and unmarks those attempts, so the next
  submission is the only thing that re-arms an upload. See
  [CLI_WEB_PARITY.md](CLI_WEB_PARITY.md) for the per-route contract.
- The `upload.schedule` model now includes the full attempt lifecycle:
  `pending → scheduled → running → published|failed|cancelled` attempt states,
  a derived `scheduled` job-status bucket, submission-side dedup guard,
  platform-side existing-post detection, and filterable history. A past-due
  `scheduled` attempt at service startup is healed as an interrupted failure,
  never published unattended.
- `upload.schedule.mode: platform` uploads at submission time and lets the
  platform hold the future publication. It is inert without a future
  `publish_at`, is refused outright (before any attempt exists) for a platform
  the registry has not blessed, and ships disabled for every platform until the
  maintainer's sandbox probe runs. A successful attempt stays `scheduled`
  because the platform still holds the post; the strictness is the point, since
  a silent fallback to the local timer would publish at a time the user did not
  choose. See [PLATFORM_CAPABILITIES.md](PLATFORM_CAPABILITIES.md) for the
  per-platform probe status and
  [CLI_WEB_PARITY.md](CLI_WEB_PARITY.md) for the cancel surface.
- Whether multi-job groups ever become save-able presets later is deferred;
  today they are ephemeral execution groups.

## Implementation Boundaries

The shared resolver and app.yml persistence live in `clipmorph/configuration.py`.
Per-source fan-out, checkpoint transitions, transcript revision persistence,
artifact history, and upload attempts are owned by `clipmorph/service.py` and
`clipmorph/job.py`. `clipmorph/cli.py` and `clipmorph/web.py` are command/route
adapters over those shared operations. The conversion renderer consumes
`conversion.layout`; it does not expose a parallel camera-feed configuration.

The API/CLI route syntax and focused test matrix are maintained in
[CLI_WEB_PARITY.md](CLI_WEB_PARITY.md). There is no persisted batch tier or
group manifest.
