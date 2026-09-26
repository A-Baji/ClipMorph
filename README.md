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

### Local dashboard

Install the optional web dependencies from the tagged GitHub repository with `python -m pip install "clipmorph[web] @ git+https://github.com/A-Baji/ClipMorph.git@vX.Y.Z"`,
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
- Dry runs: validate source selection, config, layout, and media without creating jobs
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

- **Intelligent Video Processing**
  - Automatic audio transcription with speaker diarization
  - Profanity detection and censoring (audio muting + subtitle filtering)
  - Multi-speaker subtitle overlays with color coding
  - Camera feed extraction and placement
  - Vertical format optimization (9:16 aspect ratio)
  - Blurred background support

- **Multi-Platform Upload**
  - Parallel uploads to YouTube, Instagram, TikTok, and Twitter
  - Platform-specific parameter mapping
  - Progress tracking with detailed status updates
  - Automatic retry logic with exponential backoff

- **Flexible Configuration**
  - Command-line arguments
  - YAML/JSON config files
  - Environment variable support

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Credits

- Created by Adib Baji
- Uses Whisper for transcription
- Uses PyAnnote for speaker diarization
- FFmpeg for video processing

## Release

Developer release instructions and troubleshooting are in [docs/RELEASE.md](docs/RELEASE.md).