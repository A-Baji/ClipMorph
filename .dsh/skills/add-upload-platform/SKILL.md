---
name: add-upload-platform
description: Wire a new upload platform into ClipMorph — pipeline module, orchestrator registration, CLI choices, override flattening, config block, and credentials
whenToUse: When adding a new upload target beyond YouTube, Instagram, TikTok, and Twitter
---

# Add an Upload Platform to ClipMorph

## Purpose

Add a new upload target end to end, following the existing per-platform pattern, so it works through the CLI, config, overrides, and `.env` credentials.

## When

Use when asked to support uploading to a new platform. Do not use for fixing or reconfiguring an existing platform.

## Prerequisites

- A lowercase platform name (the string used in `--upload-to`, config blocks, and override keys)
- The platform's upload API understood well enough to drive it with `requests`, consistent with `platforms/base.py`

## Procedure — verified touchpoints

1. `clipmorph/upload_pipeline/platforms/<name>.py` — create `<Name>UploadPipeline(BaseUploadPipeline)`; sibling modules (`youtube.py`, `tiktok.py`, …) show the shape: implement the upload, rely on `base.py` for retry (`MAX_RETRIES`, retriable status codes) and progress handling.
2. `clipmorph/upload_pipeline/platforms/__init__.py` — export the class the way the four existing ones are (`from .<name> import <Name>UploadPipeline`).
3. `clipmorph/upload_pipeline/__init__.py` — `UploadPipeline.__init__` currently takes `(youtube, instagram, tiktok, twitter, max_workers=4)`; add the new pipeline parameter, its `as_completed` fan-out, and its row in the smart title/description/tags mapping.
4. `clipmorph/cli.py` — add `<name>` to the `--upload-to` / `--skip` argparse choices; add it to `_process_platform_overrides` (flattened key = `{name}_{param}`); add a `<name>` block to `create_config_template()` so `--init` emits it.
5. `template.env` (and the user's `.env`) — add the platform's credential variable names following the existing convention (`GOOGLE_*`, `FACEBOOK_*` for Instagram, `TIKTOK_*`, `TWITTER_*`; Instagram additionally uses `GCS_*` to host the video temporarily).

## Verification

- `clipmorph --init` output contains a block for the new platform
- `clipmorph input.mp4 --title "t" --upload-to <name>` reaches the new pipeline (its log lines appear) with other platforms still uploaded when `--skip <name>` is not given
- `clipmorph input.mp4 --title "t" --upload-to <name> --platform-overrides '{"<name>_someparam": "..."}'` applies the flattened override
- `pip install .` in a clean venv, then the runs above on the target OS

## Failure modes

- Platform name mismatch across touchpoints (e.g. in `--upload-to` choices but missing from override flattening or the upload mapping) → the platform is silently skipped or overrides silently ignored
- Missing `.env` credentials → that platform's upload fails and is isolated (warning + failed result, others continue); check per-platform results, not just the exit code
- Forgetting `platforms/__init__.py` or the `UploadPipeline` constructor → `ImportError` or the pipeline is never constructed

## Constraints

- Follow the one-class-per-module `platforms/<name>.py` + `BaseUploadPipeline` pattern; do not change the concurrent model (`ThreadPoolExecutor`, per-platform failure isolation)
- Keep platform-name strings lowercase and identical in every layer
- Do not commit credential values; `template.env` holds names only
