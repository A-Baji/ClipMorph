# Implementation Done: #209 Analytics Comparisons Dashboard

## Guide items implemented

1. **Dimension join — `clipmorph/metrics.py`** — `join_dimensions(snapshot, manifest)` is a pure function returning `duration_seconds` (snapshot pull-time stamp, falling back to the attempt's artifact record), `title` (from the attempt's `configuration_snapshot.upload.content.title`), `layout_id` + `subtitles_renderer` (from the job configuration), and `platform_overrides` (`null` until #203). `duration_bucket(seconds)` returns the fixed half-open buckets with `null -> "unknown"`.

2. **Cross-job comparison read layer — `clipmorph/metrics.py`** — `compare_metrics(jobs_dir, platform=None, limit=100)` walks `jobs/*/metrics/snapshots.jsonl`, keeps the latest snapshot per `(platform, platform_post_id)`, joins dimensions from each manifest, and computes first → latest deltas. Sorted by `captured_at` descending, bounded to `limit`. Read-only; no pull is triggered. Unreadable manifests are skipped.

3. **Web routes — `clipmorph/web.py`** — `GET /api/v1/jobs/{job_id}/metrics` gains `include=dimensions` (422 on any other value; empty/absent = raw Phase 1 rows). New `GET /api/v1/metrics/comparison?platform=&limit=` returns the cross-job table; `platform` validates against `SUPPORTED_PLATFORMS_SET`, `limit` is an int 1-500 (default 100), empty state is `[]` (200).

4. **CLI — `clipmorph/cli.py`** — `clipmorph job metrics JOB --dimensions` prints the dimension-joined rows. New top-level `clipmorph metrics compare [--platform P] [--limit N]` prints the cross-job table via the same read-layer function; `--limit` and `--platform` are validated (exit 2 on bad input).

5. **Frontend — `frontend/src/App.svelte` (+ `styles.css`)** — New "Metrics" nav view with the cross-job table (columns `platform, title, duration_bucket, layout_id, views, likes, comments, views Δ, likes Δ`), platform filter chips, and muted "unavailable: <reason>" rows. Job detail side panel gains a per-post delta card (first → latest per metric, platform icon + URL link from `platform_url`). The Svelte store reads the two routes; no polling, no auto-pull.

6. **Docs — `docs/CLI_WEB_PARITY.md`** — CLI contract rows for `job metrics --dimensions` and `metrics compare`; API contract rows for `include=dimensions` and `GET /metrics/comparison`; a parity-matrix row. `docs/CONFIG_LAYERS.md` left unchanged (no config changes in this issue).

7. **Tests** — `tests/test_metrics.py` (join_dimensions missing artifact/title/unknown post, duration_bucket boundaries 29/30/59/60/179/180/181/None, compare_metrics latest-only/deltas/platform/limit/sort/empty/unreadable-manifest), `tests/test_web.py` (include=dimensions join shape, empty include, comparison route latest-rows/platform-validation/limit-bounds/empty-state), `tests/test_cli.py` (job metrics --dimensions json+table, metrics compare empty/output-shape/limit-validation/platform-validation), `tests/test_cli_surface.py` (command manifest updated), `tests/test_e2e_dashboard.py` (Metrics view renders cross-job table with fixture snapshots).

## Files touched

- `clipmorph/metrics.py`
- `clipmorph/web.py`
- `clipmorph/cli.py`
- `frontend/src/App.svelte`
- `frontend/src/styles.css`
- `clipmorph/web_assets` (rebuilt frontend bundle)
- `docs/CLI_WEB_PARITY.md`
- `tests/test_metrics.py`
- `tests/test_web.py`
- `tests/test_cli.py`
- `tests/test_cli_surface.py`
- `tests/test_e2e_dashboard.py`

## Gate results

- `scripts/check_structure.py` — PASSED
- `scripts/check_docs.py` — PASSED
- `python -m ruff check --select E9,F clipmorph scripts tests quality` — PASSED
- `python -m mypy --ignore-missing-imports clipmorph` — PASSED (0 issues)
- `python -m compileall -q clipmorph` — PASSED
- `python -m unittest discover -s tests` — PASSED (399 tests, OK)
- `python -m clipmorph metrics compare --limit 10` — PASSED (empty state)

## Decisions made

1. **Guide left open: which duration bucket contains exactly 180 seconds.** The guide lists the buckets as `<30s`; `[30,60)`; `[60,180)`; `>180s` and states the boundary tests (29/30/59/60/179/180/181/None) must be uniquely decidable. Taken literally, 180 falls in no bucket, so the boundary set would not be decidable. I chose to treat the last bucket as `>=180s` (180 and above), so `duration_bucket(180) == ">180s"`. This is the only reading under which all eight boundary values are uniquely decidable, which the guide explicitly requires.

2. **Guide left open: what "Svelte store reads the two routes" means given the repository has no store files.** The guide's frontend section says "(+ stores)" and the design decisions say "Svelte store reads the two routes", but the frontend is a single `App.svelte` using local component state and an `api()` helper; there is no store module or convention anywhere in `frontend/src`. I chose to implement the Metrics view and the job-detail delta panel in `App.svelte` with local state, following the existing convention, rather than introducing a new store module. The user-visible outcome (a Metrics view reading the two routes, a job-detail delta panel) is identical, and AGENTS.md directs preferring existing machinery and conventions.

3. **Guide left open: what delta a post with a single snapshot shows.** The guide specifies "first → latest snapshot per metric, plus delta columns" but does not address posts that have only one snapshot. I chose delta = 0 when first == latest (a single snapshot), and `null` when a metric is missing from either the first or the latest snapshot. This is the natural arithmetic of first → latest and keeps every table cell decidable.

4. **Guide left open: whether `job metrics --dimensions` implies JSON output.** The guide says "`clipmorph job metrics JOB --dimensions` prints the dimension-joined rows (`_print_json`)". The parenthetical `(_print_json)` is ambiguous — it could mean `--dimensions` always prints JSON. I chose to keep the table/JSON parity that CLI_WEB_PARITY.md establishes for every command (rich table for humans by default, JSON via `_print_json` only with `--json`) and to add the dimension columns to the rendered table when `--dimensions` is passed. This preserves the documented parity contract instead of making `--dimensions` a special case that breaks it.
