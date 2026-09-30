"""Tests for clipmorph/metrics.py: collectors, normalization, and storage."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from clipmorph.metrics import (
    append_snapshot,
    collect_platform_metrics,
    load_snapshots,
    _normalize_metrics,
    _TWITTER_UNAVAILABLE_REASON,
)


class MetricsNormalizationTests(unittest.TestCase):
    def test_normalize_metrics_maps_youtube_counts(self):
        raw = {"viewCount": "100", "likeCount": "5", "commentCount": "2"}
        result = _normalize_metrics(raw)
        self.assertEqual(result, {"views": 100, "likes": 5, "comments": 2})

    def test_normalize_metrics_maps_instagram_names(self):
        raw = {
            "views": 50, "reach": 200, "likes": 10, "comments": 3,
            "shares": 1, "saved": 2, "total_interactions": 16,
        }
        result = _normalize_metrics(raw)
        self.assertEqual(result["views"], 50)
        self.assertEqual(result["reach"], 200)
        self.assertEqual(result["total_interactions"], 16)

    def test_normalize_metrics_maps_tiktok_counts(self):
        raw = {
            "view_count": 1000, "like_count": 50,
            "comment_count": 5, "share_count": 2,
        }
        result = _normalize_metrics(raw)
        self.assertEqual(result, {
            "views": 1000, "likes": 50, "comments": 5, "shares": 2,
        })

    def test_normalize_metrics_ignores_unknown_keys(self):
        raw = {"viewCount": "10", "unknownMetric": "99"}
        result = _normalize_metrics(raw)
        self.assertEqual(result, {"views": 10})

    def test_normalize_metrics_skips_non_numeric(self):
        raw = {"viewCount": "not-a-number", "likeCount": "5"}
        result = _normalize_metrics(raw)
        self.assertEqual(result, {"likes": 5})


class MetricsStorageTests(unittest.TestCase):
    def test_append_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir) / "job"
            record = {
                "captured_at": "2026-01-01T00:00:00+00:00",
                "platform": "youtube",
                "platform_post_id": "abc123",
                "metrics": {"views": 100},
                "unavailable": False,
                "unavailable_reason": None,
            }
            append_snapshot(job_dir, record)
            append_snapshot(job_dir, {**record, "platform_post_id": "def456"})

            loaded = load_snapshots(job_dir)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["platform_post_id"], "abc123")
            self.assertEqual(loaded[1]["platform_post_id"], "def456")

    def test_load_snapshots_returns_empty_for_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = load_snapshots(Path(temp_dir) / "nonexistent")
            self.assertEqual(result, [])

    def test_load_snapshots_tolerates_malformed_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir) / "job"
            metrics_dir = job_dir / "metrics"
            metrics_dir.mkdir(parents=True)
            path = metrics_dir / "snapshots.jsonl"
            good = json.dumps({"platform": "youtube", "metrics": {}})
            path.write_text(f"not-json\n{good}\n\n", encoding="utf-8")

            loaded = load_snapshots(job_dir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["platform"], "youtube")


class MetricsCollectorTests(unittest.TestCase):
    def test_twitter_collector_emits_unavailable(self):
        attempts = [{
            "platform": "twitter",
            "platform_post_id": "123456",
            "platform_url": "https://x.com/user/status/123456",
        }]
        with patch("clipmorph.metrics._TWITTER_UNAVAILABLE_REASON",
                       _TWITTER_UNAVAILABLE_REASON):
            result = collect_platform_metrics(["twitter"], attempts)
        self.assertIn("123456", result)
        self.assertEqual(result["123456"], {})

    def test_collect_platform_metrics_empty_attempts(self):
        result = collect_platform_metrics(["youtube"], [])
        self.assertEqual(result, {})

    def test_collect_platform_metrics_unknown_platform(self):
        result = collect_platform_metrics(["unknown"], [
            {"platform": "unknown", "platform_post_id": "123"},
        ])
        self.assertEqual(result, {})

    def test_retry_request_retries_on_500_then_succeeds(self):
        """A 500 followed by a 200 exercises the shared backoff helper."""
        from clipmorph.metrics import _retry_request

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            if call_count == 1:
                response.ok = False
                response.status_code = 500
            else:
                response.ok = True
                response.status_code = 200
            return response

        with patch("clipmorph.metrics.requests.get", side_effect=mock_get), \
             patch("clipmorph.metrics.time.sleep"):
            result = _retry_request(mock_get, "http://test")

        self.assertEqual(call_count, 2)
        self.assertTrue(result.ok)

    def test_retry_request_raises_after_max_retries(self):
        """A persistent 500 raises after MAX_RETRIES attempts."""
        from clipmorph.metrics import _retry_request, MAX_RETRIES

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            response.ok = False
            response.status_code = 500
            response.raise_for_status.side_effect = requests.HTTPError("500")
            return response

        with patch("clipmorph.metrics.requests.get", side_effect=mock_get), \
             patch("clipmorph.metrics.time.sleep"):
            with self.assertRaises(requests.HTTPError):
                _retry_request(mock_get, "http://test")

        self.assertEqual(call_count, MAX_RETRIES)


if __name__ == "__main__":
    unittest.main()
