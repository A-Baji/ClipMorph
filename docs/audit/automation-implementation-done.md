# Implementation Done: #101 Analytics Ingestion

## Guide items implemented

1. **New module `clipmorph/metrics.py`** — Standard-library only at the top level with lazy platform imports. Provides `load_snapshots`, `append_snapshot`, `collect_platform_metrics`, and per-platform collector functions (YouTube, Instagram, TikTok, Twitter). Metric names normalized to `{views, likes, comments, shares, saves, reach, total_interactions}`.

2. **Service — `clipmorph/service.py`** — `pull_metrics(job_id)` runs in three phases: (1) gather published attempts under the lock, (2) run network collectors outside the lock on a dedicated short-lived executor, (3) re-acquire the lock to append snapshot records and persist. `list_metrics(job_id)` returns snapshots read-only.

3. **CLI — `clipmorph/cli.py`** — `clipmorph job metrics JOB` lists snapshots. `clipmorph job metrics JOB --pull` triggers a bounded pull then lists.

4. **Web — `clipmorph/web.py`** — `GET /api/v1/jobs/{job_id}/metrics` returns snapshot records. `POST /api/v1/jobs/{job_id}/metrics/pull` (202) triggers a pull. No GET-triggered network calls.

5. **Frontend** — Uploads view gains a "Refresh metrics" action and a metrics readout showing metric names, values, `captured_at`, and unavailable reasons.

6. **Docs** — `docs/CLI_WEB_PARITY.md` updated with CLI and API rows. `docs/CONFIG_LAYERS.md` updated with the `metrics/snapshots.jsonl` file spec. `docs/AUTHENTICATION.md` updated with re-consent steps for IG `instagram_manage_insights` and TikTok `video.list`.

7. **Tests** — `tests/test_metrics.py` (new), `tests/test_service.py` (pull_metrics tests), `tests/test_web.py` (metrics route tests), `tests/test_cli.py` (job metrics CLI tests).

## Files touched

- `clipmorph/metrics.py` (new)
- `clipmorph/service.py`
- `clipmorph/cli.py`
- `clipmorph/web.py`
- `frontend/src/App.svelte`
- `docs/CLI_WEB_PARITY.md`
- `docs/CONFIG_LAYERS.md`
- `docs/AUTHENTICATION.md`
- `tests/test_metrics.py` (new)
- `tests/test_service.py`
- `tests/test_web.py`
- `tests/test_cli.py`
- `tests/test_cli_surface.py`

## Gate results

- `scripts/check_structure.py` — PASSED
- `scripts/check_docs.py` — PASSED
- `python -m ruff check --select E9,F clipmorph scripts tests quality` — PASSED
- `python -m mypy --ignore-missing-imports clipmorph` — PASSED (0 issues)
- `python -m compileall -q clipmorph` — PASSED
- `python -m unittest discover -s tests` — PASSED (370 tests, OK)

## Decisions made

1. **Guide left open: how to handle the `quality/spec_audits/analytics_capabilities.md` reference in the Twitter unavailable reason.** The guide's Twitter collector emits an unavailable reason referencing `quality/spec_audits/analytics_capabilities.md`, but that file does not exist in the repository. I chose to keep the reference as-is in the reason string because the guide explicitly specifies this text and the file is referenced as a research artifact that may be created separately. The reason string is user-facing documentation of why Twitter metrics are unavailable, and the reference points to the research that established the metering wall.

2. **Guide left open: how to stamp correlation fields (`duration_seconds`, `title`, `configuration_hash`) when artifact records may not have them.** The guide says "Nulls, not errors, when missing." I chose to look up the artifact record by `artifact_id` from the attempt and read `duration_seconds` and `title` from it, falling back to `None` when the artifact or field is absent. The `configuration_hash` comes from the attempt record's own `configuration_hash` field, which is always present on published attempts.

3. **Guide left open: whether the `collect_platform_metrics` function should be called with a timeout.** The guide says "bounded" but does not specify a timeout value. I chose a 120-second timeout on the future result, which is generous enough for platform API calls while preventing indefinite hangs. The dedicated executor is short-lived and shut down after each pull.

## Patch cycle 1 changes

Applied spec review cycle 1 patch plan (F1-F4):

- **F1 (major/gap):** Added module-level `_retry_request` helper mirroring `BaseUploadPipeline._retry_request` (retries on 500/502/503/504 with exponential backoff and jitter). Wrapped Instagram `requests.get` and TikTok `requests.post` calls with it.
- **F2 (minor/quality):** Removed the unused `reason` parameter from `_unavailable_snapshot()`. All callers updated.
- **F3 (minor/quality):** Fixed Instagram collector token lookup: now calls `load_auth_config()` first, then reads token from environment via `_get_env_token("instagram")`. Removed the awkward double-check of `attempt.get("_access_token")`.
- **F4 (minor/gap):** Added `test_retry_request_retries_on_500_then_succeeds` and `test_retry_request_raises_after_max_retries` tests exercising the shared backoff helper.
