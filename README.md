# ClipMorph

A powerful CLI tool for converting gaming videos into short-form content and automatically uploading to YouTube Shorts, Instagram Reels, TikTok, and Twitter/X.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

## First run

```bash
clipmorph init
clipmorph job create sources/video.mp4 --dry-run
clipmorph job create sources/video.mp4
clipmorph web
```

`app.yml` defaults to the ClipMorph data directory. Configure `source_dir`,
`output_dir`, `job_defaults`, and named layouts there. Job configuration is
resolved from `app.yml:job_defaults` plus one per-job override object; finalized
jobs live in `jobs/<job_id>/job.yml` with state in `manifest.json`. A source must
be an immediate file under `source_dir`.

## Commands

- `clipmorph init [--config-path PATH]` — write `app.yml` and an adjacent `auth.yaml` template.
- `clipmorph web [--host HOST] [--port PORT]` — start the local API and dashboard.
- `clipmorph auth status|set PLATFORM|twitter` — credential status, prompt-based updates, and the X OAuth flow.
- `clipmorph layout list|create CONFIG|get ID|delete ID` — manage the global layout registry.
- `clipmorph job create SOURCE [--job-configs FILE] [--config-dir DIR] [--dry-run]` — create jobs from one source file or fan out over `source_dir`; per-source records are JSONL/YAML job objects.
- `clipmorph job list|get ID|update ID --patch FILE [--reopen]|delete ID --yes|resume ID|cancel ID --yes` — inspect and manage the job lifecycle.
- `clipmorph job review ID {transcript|conversion|upload} [--edits FILE] [--accept]` — checkpoint review gates.
- `clipmorph job render ID` — create a new immutable artifact revision from the accepted composition.
- `clipmorph job upload ID [--platform NAME]`, `clipmorph job upload retry ID PLATFORM [--attempt-id ID]` — submit the accepted draft or retry a failed attempt.
- `clipmorph job artifacts list|preview|download|rename|delete ...` — manage registered artifact revisions.

A directory `job create` scans the root of `app.yml:source_dir` only; unsupported or missing sources are skipped and reported per source, while valid jobs still proceed (no group manifest is persisted). The web API exposes the same lifecycle at `/api/v1/`; see `docs/CLI_WEB_PARITY.md` for the contract.
### Local dashboard

Install the optional web dependencies from the tagged GitHub repository with `python -m pip install "clipmorph[web] @ git+https://github.com/A-Baji/ClipMorph.git@vX.Y.Z"` (the base package and its `web` extra are currently distributed from tagged GitHub releases; PyPI publication is planned but not yet available),
then run `clipmorph web`. The service binds to `127.0.0.1:8000` and serves the
local dashboard plus `/api/v1/` without authentication. Jobs, credentials,
artifacts, captions, and upload state remain on the local machine. Stop the
service with `Ctrl+C`.

## Authentication and secrets

Running `clipmorph init` creates both `app.yml` and an adjacent `auth.yaml`.
Use `--data-dir <path>` to choose a custom local data directory, or
`--app-config <path>` to select an app configuration file. See
[Authentication Setup](docs/AUTHENTICATION.md) for instructions on obtaining
every value and filling in the provider sections. For example:

```yaml
youtube:
  client_id: "..."
  client_secret: "..."
  refresh_token: "..."
tiktok:
  client_key: "..."
  client_secret: "..."
  refresh_token: "..."
```

ClipMorph loads credentials from `auth.yaml` for both the CLI and web service.
Existing environment variables, including values from `.env`, take precedence.
Keep both files private and do not commit secrets to source control.

Environment variables remain supported for platform and model credentials.

Common variables include:

- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`
- `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `FACEBOOK_PAGE_ID`, `FACEBOOK_ACCESS_TOKEN`
- `GCS_BUCKET_NAME`, `GCP_PRIVATE_KEY_ID`, `GCP_PRIVATE_KEY`, `GCP_CLIENT_EMAIL`, `GCP_CLIENT_ID`, `GCP_PROJECT_ID`
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_ACCESS_TOKEN`, `TIKTOK_REFRESH_TOKEN`, `TIKTOK_OPEN_ID`
- `TWITTER_CLIENT_ID`, `TWITTER_CLIENT_SECRET`, `TWITTER_OAUTH2_ACCESS_TOKEN`, `TWITTER_OAUTH2_REFRESH_TOKEN`, `TWITTER_OAUTH2_EXPIRES_AT`
- `HUGGING_FACE_ACCESS_TOKEN`

For X publishing, configure the OAuth 2.0 Client ID and Client Secret in
`auth.yaml`, then run `clipmorph auth twitter`. The command opens the X consent
page, uses the registered callback `http://localhost:8765/callback`, and stores
the user access and refresh tokens. The requested scopes are `tweet.read`,
`tweet.write`, `users.read`, `media.write`, and `offline.access`.

## Configuration precedence

ClipMorph deep-merges `app.yml:job_defaults` with one per-job configuration
object. Dictionaries merge recursively; lists and scalars in the job object
replace their defaults. Multi-source inputs may provide a direct job object in
JSONL/YAML or a `.yml`/`.yaml` sidecar with `general.source`; the sidecar
filename is arbitrary. See
[Layered configuration](docs/CONFIG_LAYERS.md) for the schema and resolution
rules.

## Supported media and workflow constraints

- Input formats: commonly MP4/MOV/MKV/AVI/WebM files
- Preferred output target: vertical 9:16 content with validated crop geometry
- Uploads: support partial failures without dropping platform state in the job manifest
- Dry runs: validate source selection and configuration without creating jobs
- Retry handling: pipeline retries and partial-failure reporting are available for uploads
- Cleanup: use `--clean` to remove generated artifacts after a successful run

## Troubleshooting

### FFmpeg problems

- Ensure FFmpeg and FFprobe are available in the project runtime path.
- Re-run with `--dry-run` to validate the source file and output directory before conversion.

### Transcription problems

- Reduce model demand with `--transcription-model` and `--transcription-device cpu`.
- Use the `--transcription-language auto` or a specific language code as needed.
- If a requested GPU device is unavailable, ClipMorph falls back to CPU automatically.

### OAuth and upload problems

- Confirm the relevant env vars are set for the target platform.
- Re-check the platform scopes and refresh tokens.
- Use dry runs and partial-failure summaries to inspect what was blocked and what succeeded.

## Features

- **Layered job configuration**
  - `app.yml` global defaults with per-job override objects deep-merged on top
  - Finalized effective `job.yml` persisted per job, with resumable manifest state
  - Sidecar `general.source` matching with arbitrary YAML filenames; no batch tier

- **Review checkpoints**
  - Transcript review: edit generated segment text, timing, and per-segment typography before render
  - Composition review: crop, captions, and layout materialization with immutable artifact revisions
  - Upload review: pending draft with append-only per-platform attempt history and targeted retries

- **Intelligent video processing**
  - Automatic audio transcription with speaker diarization
  - Profanity detection and censoring (audio muting + subtitle filtering)
  - Multi-speaker subtitle overlays with color coding
  - Vertical format optimization (9:16) with composable crop/caption layouts
  - Blurred background support

- **Multi-platform upload**
  - Parallel uploads to YouTube, Instagram, TikTok, and Twitter
  - Centralized platform capability policy with blockers, warnings, and metadata transforms
  - Platform-specific parameter mapping and duration/size guards
  - Automatic retry with backoff plus per-platform retries bound to the failed attempt

- **Local dashboard**
  - `clipmorph web` serving a FastAPI dashboard at `127.0.0.1:8000`
  - Queue, job detail, layouts, captions, uploads, and credential-health views
  - Same shared JobService lifecycle as the CLI

- **Flexible configuration**
  - `app.yml` layered config with CLI/Web/API parity (see `docs/CONFIG_LAYERS.md`)
  - Environment variable support with `auth.yaml` credential precedence

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Credits

- Created by Adib Baji
- Uses Whisper for transcription
- Uses PyAnnote for speaker diarization
- FFmpeg for video processing

## Release

Developer release instructions and troubleshooting are in [docs/RELEASE.md](docs/RELEASE.md).