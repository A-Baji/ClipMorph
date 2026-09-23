# Project Instructions

## Overview

ClipMorph is a Python app + CLI that converts long-form screen-recording videos (camera feed + spoken audio) into vertical short-form videos — camera overlay and Whisper-transcribed subtitles burned in with FFmpeg — then uploads the result in parallel to YouTube, Instagram, TikTok, and Twitter. FFmpeg binaries are vendored per-OS under `clipmorph/ffmpeg/` (tracked with Git LFS), so no system FFmpeg install is needed.

## Stack

- Python ≥ 3.11, setuptools (`pyproject.toml`); console script `clipmorph` → `clipmorph.__main__:main`
- Runtime dependencies resolved dynamically from `requirements.txt`
- Uploads: `clipmorph/upload_pipeline/` — `UploadPipeline` runs platforms concurrently (`ThreadPoolExecutor`); `platforms/base.py` provides retry/progress; one module per platform in `platforms/`
- CI: GitHub Actions only — `tag.yml` (release flow) and `build_and_release.yml` (PyInstaller, 3-OS matrix)

## Build / Run

```
pip install .                            # install (bundles FFmpeg + fonts, provides `clipmorph`)
clipmorph --init                         # writes clipmorph.yaml template (--config-path for custom location)
clipmorph input.mp4 --title "My video"   # full pipeline: convert, confirm, upload
```

Key flags (from `cli.py`): `--no-upload` (also drops the `--title` requirement), `--upload-to` / `--skip` (choices: youtube, instagram, tiktok, twitter), `--no-cam`, `--cam-x/y/width/height` (defaults 1420/790/480/270), `--no-subs`, `--output-dir` (default `output/`), `--no-confirm`/`-y`, `--clean`/`-c` (delete output after upload), `--no-conversion`, `--tags` (comma-separated).

Config sources: `--config` (YAML/JSON file), `--platform-overrides` (JSON string); platform params flatten as `{platform}_{param}` (e.g. `youtube_category`, `tiktok_privacy_level`). Credentials come from `.env` mirroring the variable names in `template.env` (per-platform `GOOGLE_*`, `FACEBOOK_*`, `TIKTOK_*`, `TWITTER_*`, `GCS_*` for temporary Instagram video hosting, `HUGGING_FACE_ACCESS_TOKEN`).

## Testing

No test suite, linter, or type checker is tracked. CI contains only the two release/build workflows — there is no local verification command beyond running the CLI itself.

## Project Structure

```
clipmorph/
  __main__.py           # console-script entry
  cli.py                # argparse, config template, platform-override flattening
  ffmpeg/{windows,mac,linux}/   # vendored FFmpeg binaries (Git LFS)
  resources/fonts/roboto/       # bundled subtitle font
  upload_pipeline/
    __init__.py         # UploadPipeline, per-platform content mapping
    platforms/          # base.py + youtube.py, instagram.py, tiktok.py, twitter.py
template.env            # credential variable names for .env
example-config.json     # example config file
docs/RELEASE.md         # release procedure
.github/workflows/      # tag.yml, build_and_release.yml
```

## Conventions

- Version single source of truth: `clipmorph/__version__.py` (read dynamically by `pyproject.toml`); the release workflow rewrites it — do not hand-edit
- Platform parameters are named `{platform}_{param}` in every layer (CLI flattening, config keys)
- Platform name strings are lowercase and must match `--upload-to`/`--skip` choices, the upload mapping, and config blocks
- Per-platform upload failure is isolated (warned, does not abort other platforms) by design of `UploadPipeline`

## Boundaries

- `.env` and platform credential files are never committed; `template.env` is the unsecret reference only
- `clipmorph/ffmpeg/*` are LFS-tracked vendored binaries and part of the shipped package — do not re-vendor or hand-edit them
- Releases come only from GitHub Actions (`tag.yml` → `build_and_release.yml`); there is no local PyInstaller or release command

## Generated Files

Local, non-committed artifacts: `output/` (default `--output-dir`), `clipmorph.yaml` (plus `clipmorph.yaml.backup` made when `--init` regenerates it), `.venv/`, `build/`, `clipmorph.egg-info/`.

## References

- `docs/RELEASE.md` — release procedure: `gh workflow run tag.yml --ref main -f version=X.Y.Z [-f allow_existing_tag=true]`
- `clipmorph/upload_pipeline/__init__.py` — smart content mapping and failure isolation behavior
- Project skills: `.dsh/skills/release-clipmorph/SKILL.md`, `.dsh/skills/add-upload-platform/SKILL.md`
