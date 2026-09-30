"""Analytics ingestion: pull engagement metrics from published posts.

Snapshot storage is ``jobs/<job_id>/metrics/snapshots.jsonl`` — one JSON
record per captured pull, append-only, newest last. The file is per-job local
state, deliberately outside the manifest (no schema bump).

Schema version: 1
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Retry configuration matching BaseUploadPipeline.
MAX_RETRIES = 3
RETRIABLE_STATUS_CODES = (500, 502, 503, 504)

METRIC_SNAPSHOT_SCHEMA_VERSION = 1

# Normalized metric names in stable lowercase.
METRIC_NAMES = (
    "views", "likes", "comments", "shares", "saves", "reach",
    "total_interactions",
)

# Platforms with a collector. Twitter/X is excluded (metered reads).
COLLECTIBLE_PLATFORMS = ("youtube", "instagram", "tiktok")

_TWITTER_UNAVAILABLE_REASON = (
    "metrics not available at the standard tier: X API reads are metered "
    "per post (see quality/spec_audits/analytics_capabilities.md)"
)


def load_snapshots(job_dir: str | Path) -> list[dict]:
    """Load snapshot records from a job's metrics file, tolerating bad lines."""
    path = Path(job_dir) / "metrics" / "snapshots.jsonl"
    if not path.is_file():
        return []
    records: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        logger.warning("Could not read metrics file %s: %s", path, error)
        return []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as error:
            logger.warning("Skipping malformed metrics line in %s: %s", path, error)
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def append_snapshot(job_dir: str | Path, record: dict) -> None:
    """Append one snapshot record to a job's metrics file."""
    metrics_dir = Path(job_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / "snapshots.jsonl"
    line = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _youtube_collector(attempts: list[dict]) -> dict[str, dict]:
    """Collect YouTube statistics via videos.list."""
    from clipmorph.upload_pipeline.platforms.youtube import YouTubeUploadPipeline

    results: dict[str, dict] = {}
    ids = [a["platform_post_id"] for a in attempts if a.get("platform_post_id")]
    if not ids:
        return results

    try:
        pipeline = YouTubeUploadPipeline()
        if not pipeline.credentials:
            pipeline._authenticate()
        service = pipeline.youtube_service
        if service is None:
            raise RuntimeError("youtube service unavailable")

        # Batch: one call per 50 ids.
        for start in range(0, len(ids), 50):
            batch = ids[start:start + 50]
            response = service.videos().list(
                part="statistics",
                id=",".join(batch),
                maxResults=50,
            ).execute()
            for item in response.get("items", []):
                video_id = item.get("id", "")
                stats = item.get("statistics", {})
                metrics = _normalize_metrics({
                    "viewCount": stats.get("viewCount"),
                    "likeCount": stats.get("likeCount"),
                    "commentCount": stats.get("commentCount"),
                })
                results[video_id] = metrics
    except Exception as error:
        logger.warning("YouTube metrics collection failed: %s", error)
        for post_id in ids:
            results[post_id] = _unavailable_snapshot()

    return results


def _instagram_collector(attempts: list[dict]) -> dict[str, dict]:
    """Collect Instagram insights via Graph API."""
    import requests

    results: dict[str, dict] = {}
    for attempt in attempts:
        media_id = attempt.get("platform_post_id")
        if not media_id:
            continue
        try:
            from clipmorph.auth import load_auth_config
            load_auth_config()
            token = _get_env_token("instagram")
            if not token:
                results[media_id] = _unavailable_snapshot()
                continue

            url = (
                f"https://graph.facebook.com/v25.0/{media_id}/insights"
            )
            params = {
                "metric": "views,reach,likes,comments,shares,saved,total_interactions",
                "period": "lifetime",
                "access_token": token,
            }
            response = _retry_request(requests.get, url, params=params, timeout=30)
            data = response.json().get("data", [])
            if not data:
                results[media_id] = _unavailable_snapshot()
                continue

            raw: dict[str, Any] = {}
            for entry in data:
                name = entry.get("name", "")
                values = entry.get("values", [])
                if values and isinstance(values, list):
                    raw[name] = values[0].get("value")
            metrics = _normalize_metrics({
                "views": raw.get("views"),
                "reach": raw.get("reach"),
                "likes": raw.get("likes"),
                "comments": raw.get("comments"),
                "shares": raw.get("shares"),
                "saved": raw.get("saved"),
                "total_interactions": raw.get("total_interactions"),
            })
            results[media_id] = metrics
        except Exception as error:
            logger.warning("Instagram metrics collection failed for %s: %s",
                           media_id, error)
            results[media_id] = _unavailable_snapshot()

    return results


def _tiktok_collector(attempts: list[dict]) -> dict[str, dict]:
    """Collect TikTok video query counts."""
    import requests

    results: dict[str, dict] = {}
    ids = [a["platform_post_id"] for a in attempts if a.get("platform_post_id")]
    if not ids:
        return results

    try:
        from clipmorph.auth import load_auth_config
        load_auth_config()
        access_token = _get_env_token("tiktok")
        if not access_token:
            for post_id in ids:
                results[post_id] = _unavailable_snapshot()
            return results

        url = "https://open.tiktokapis.com/v2/video/query/"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"fields": "id,like_count,comment_count,share_count,view_count"}

        # TikTok allows up to 20 ids per call.
        for start in range(0, len(ids), 20):
            batch = ids[start:start + 20]
            body = {"filters": {"video_ids": batch}}
            response = _retry_request(
                requests.post,
                url, json=body, headers=headers, params=params, timeout=30)
            data = response.json().get("data", {})
            videos = data.get("videos", [])
            for video in videos:
                video_id = video.get("id", "")
                metrics = _normalize_metrics({
                    "view_count": video.get("view_count"),
                    "like_count": video.get("like_count"),
                    "comment_count": video.get("comment_count"),
                    "share_count": video.get("share_count"),
                })
                results[video_id] = metrics
            # Any id not in the response is unavailable.
            for post_id in batch:
                if post_id not in results:
                    results[post_id] = _unavailable_snapshot()
    except Exception as error:
        logger.warning("TikTok metrics collection failed: %s", error)
        for post_id in ids:
            results[post_id] = _unavailable_snapshot()

    return results


def _twitter_collector(attempts: list[dict]) -> dict[str, dict]:
    """Twitter/X has no collector; emit unavailable rows."""
    results: dict[str, dict] = {}
    for attempt in attempts:
        media_id = attempt.get("platform_post_id")
        if not media_id:
            continue
        results[media_id] = _unavailable_snapshot()
    return results


_COLLECTORS = {
    "youtube": _youtube_collector,
    "instagram": _instagram_collector,
    "tiktok": _tiktok_collector,
    "twitter": _twitter_collector,
}


def _get_env_token(platform: str) -> str | None:
    """Return the access token for a platform from the environment."""
    import os
    from clipmorph.auth import AUTH_ENVIRONMENT_KEYS
    fields = AUTH_ENVIRONMENT_KEYS.get(platform, {})
    for env_key in fields.values():
        value = os.getenv(env_key)
        if value:
            return value
    return None


def _retry_request(func, *args, **kwargs):
    """Retry HTTP requests with exponential backoff on transient failures.

    Mirrors BaseUploadPipeline._retry_request: retries on 500/502/503/504
    with exponential backoff and jitter, raises immediately on other errors.
    """
    last_exception: BaseException | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = func(*args, **kwargs)
            if hasattr(response, "status_code") and hasattr(response, "ok"):
                if not response.ok:
                    if response.status_code in RETRIABLE_STATUS_CODES:
                        if attempt == MAX_RETRIES - 1:
                            response.raise_for_status()
                        wait_time = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "Retriable HTTP error %s (attempt %d/%d), "
                            "retrying in %.1fs",
                            response.status_code, attempt + 1, MAX_RETRIES,
                            wait_time)
                        time.sleep(wait_time)
                        continue
                    else:
                        response.raise_for_status()
            return response
        except requests.exceptions.RequestException as error:
            if isinstance(error, requests.exceptions.HTTPError):
                raise error
            if isinstance(error, (requests.exceptions.ConnectionError,
                                   requests.exceptions.Timeout,
                                   requests.exceptions.ChunkedEncodingError)):
                last_exception = error
                if attempt == MAX_RETRIES - 1:
                    raise error
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Network error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, MAX_RETRIES, wait_time, error)
                time.sleep(wait_time)
            else:
                raise error
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected error in retry logic")


_METRIC_KEY_MAP = {
    "viewcount": "views",
    "view_count": "views",
    "views": "views",
    "likecount": "likes",
    "like_count": "likes",
    "likes": "likes",
    "commentcount": "comments",
    "comment_count": "comments",
    "comments": "comments",
    "sharecount": "shares",
    "share_count": "shares",
    "shares": "shares",
    "saved": "saves",
    "saves": "saves",
    "reach": "reach",
    "total_interactions": "total_interactions",
}


def _normalize_metrics(raw: dict[str, Any]) -> dict[str, int]:
    """Normalize raw platform metrics to the stable lowercase set."""
    result: dict[str, int] = {}
    for key, value in raw.items():
        normalized = _METRIC_KEY_MAP.get(key.lower())
        if normalized is not None:
            try:
                result[normalized] = int(value)
            except (TypeError, ValueError):
                pass
    return result


def _unavailable_snapshot() -> dict[str, int]:
    """Return an unavailable metrics payload."""
    return {}


def collect_platform_metrics(
    platforms: list[str],
    attempts: list[dict],
) -> dict[str, dict]:
    """Collect metrics for published attempts across the given platforms.

    Returns a mapping of ``platform_post_id`` to normalized metrics dicts.
    Unavailable posts map to an empty dict (the caller stamps the reason).
    """
    results: dict[str, dict] = {}
    for platform in platforms:
        collector = _COLLECTORS.get(platform)
        if collector is None:
            continue
        platform_attempts = [
            a for a in attempts if a.get("platform") == platform
        ]
        if not platform_attempts:
            continue
        try:
            collected = collector(platform_attempts)
            results.update(collected)
        except Exception as error:
            logger.warning("Collector for %s failed: %s", platform, error)
            for attempt in platform_attempts:
                post_id = attempt.get("platform_post_id")
                if post_id:
                    results[post_id] = {}
    return results
