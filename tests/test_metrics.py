"""Tests for clipmorph/metrics.py: collectors, normalization, and storage."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from clipmorph.job import JobManifest
from clipmorph.metrics import (
    append_snapshot,
    collect_platform_metrics,
    compare_metrics,
    duration_bucket,
    join_dimensions,
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


class MetricsDimensionJoinTests(unittest.TestCase):
    def _manifest(self, **kwargs):
        from clipmorph.job import JobManifest as Manifest
        values = dict(
            schema_version=3,
            job_id="test-job",
            source_path="/tmp/clip.mp4",
            source_sha256="abc",
            configuration={},
        )
        values.update(kwargs)
        return Manifest(**values)

    def test_join_dimensions_reads_all_fields(self):
        manifest = self._manifest(
            configuration={"conversion": {
                "layout_id": "layout-1",
                "subtitles": {"renderer": "overlay"},
            }},
            upload_attempts=[{
                "attempt_id": "a1",
                "platform": "youtube",
                "artifact_id": "1",
                "configuration_snapshot": {
                    "upload": {"content": {"title": "My Title"}},
                },
                "result": {"platform_post_id": "yt123"},
            }],
            artifacts={"1": {"duration_seconds": 45}},
        )
        snapshot = {
            "platform": "youtube",
            "platform_post_id": "yt123",
            "duration_seconds": 45,
        }
        result = join_dimensions(snapshot, manifest)
        self.assertEqual(result["duration_seconds"], 45)
        self.assertEqual(result["title"], "My Title")
        self.assertEqual(result["layout_id"], "layout-1")
        self.assertEqual(result["subtitles_renderer"], "overlay")
        self.assertIsNone(result["platform_overrides"])

    def test_join_dimensions_duration_falls_back_to_artifact(self):
        manifest = self._manifest(
            upload_attempts=[{
                "attempt_id": "a1",
                "platform": "youtube",
                "artifact_id": "1",
                "configuration_snapshot": {},
                "result": {"platform_post_id": "yt123"},
            }],
            artifacts={"1": {"duration_seconds": 90}},
        )
        snapshot = {
            "platform": "youtube",
            "platform_post_id": "yt123",
            "duration_seconds": None,
        }
        result = join_dimensions(snapshot, manifest)
        self.assertEqual(result["duration_seconds"], 90)

    def test_join_dimensions_missing_artifact_duration_none(self):
        manifest = self._manifest(
            upload_attempts=[{
                "attempt_id": "a1",
                "platform": "youtube",
                "artifact_id": "1",
                "configuration_snapshot": {},
                "result": {"platform_post_id": "yt123"},
            }],
            artifacts={},
        )
        snapshot = {
            "platform": "youtube",
            "platform_post_id": "yt123",
            "duration_seconds": None,
        }
        result = join_dimensions(snapshot, manifest)
        self.assertIsNone(result["duration_seconds"])

    def test_join_dimensions_missing_title(self):
        manifest = self._manifest(
            upload_attempts=[{
                "attempt_id": "a1",
                "platform": "youtube",
                "artifact_id": "1",
                "configuration_snapshot": {},
                "result": {"platform_post_id": "yt123"},
            }],
        )
        snapshot = {"platform": "youtube", "platform_post_id": "yt123"}
        result = join_dimensions(snapshot, manifest)
        self.assertIsNone(result["title"])

    def test_join_dimensions_unknown_post(self):
        manifest = self._manifest()
        snapshot = {"platform": "youtube", "platform_post_id": "unknown"}
        result = join_dimensions(snapshot, manifest)
        self.assertIsNone(result["duration_seconds"])
        self.assertIsNone(result["title"])
        self.assertIsNone(result["layout_id"])
        self.assertIsNone(result["subtitles_renderer"])


class DurationBucketTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(duration_bucket(29), "<30s")
        self.assertEqual(duration_bucket(30), "[30,60)")
        self.assertEqual(duration_bucket(59), "[30,60)")
        self.assertEqual(duration_bucket(60), "[60,180)")
        self.assertEqual(duration_bucket(179), "[60,180)")
        self.assertEqual(duration_bucket(180), ">180s")
        self.assertEqual(duration_bucket(181), ">180s")

    def test_none_is_unknown(self):
        self.assertEqual(duration_bucket(None), "unknown")


class CompareMetricsTests(unittest.TestCase):
    def _seed_job(self, job_dir, snapshots, configuration=None,
                  attempts=None, artifacts=None):
        manifest = JobManifest(
            schema_version=3,
            job_id=job_dir.name,
            source_path="/tmp/clip.mp4",
            source_sha256="abc",
            configuration=configuration or {},
            upload_attempts=attempts or [],
            artifacts=artifacts or {},
        )
        manifest.save(job_dir.parent)
        for record in snapshots:
            append_snapshot(job_dir, record)

    def test_empty_state_no_jobs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rows = compare_metrics(Path(temp_dir) / "jobs")
            self.assertEqual(rows, [])

    def test_latest_snapshot_only_and_deltas(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir) / "jobs"
            job_dir = jobs_dir / "job1"
            job_dir.mkdir(parents=True)
            attempts = [{
                "attempt_id": "a1",
                "platform": "youtube",
                "artifact_id": "1",
                "configuration_snapshot": {
                    "upload": {"content": {"title": "Clip"}},
                },
                "result": {"platform_post_id": "yt123"},
            }]
            self._seed_job(job_dir, [
                {"captured_at": "2026-01-01T00:00:00+00:00",
                 "platform": "youtube", "platform_post_id": "yt123",
                 "metrics": {"views": 100, "likes": 10},
                 "unavailable": False, "unavailable_reason": None},
                {"captured_at": "2026-01-02T00:00:00+00:00",
                 "platform": "youtube", "platform_post_id": "yt123",
                 "metrics": {"views": 150, "likes": 15},
                 "unavailable": False, "unavailable_reason": None},
            ], configuration={"conversion": {
                "layout_id": "l1", "subtitles": {"renderer": "overlay"}}},
                attempts=attempts, artifacts={"1": {"duration_seconds": 45}})

            rows = compare_metrics(jobs_dir)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["platform"], "youtube")
            self.assertEqual(row["views"], 150)
            self.assertEqual(row["likes"], 15)
            self.assertEqual(row["views_delta"], 50)
            self.assertEqual(row["likes_delta"], 5)
            self.assertEqual(row["duration_bucket"], "[30,60)")
            self.assertEqual(row["title"], "Clip")
            self.assertEqual(row["layout_id"], "l1")
            self.assertEqual(row["subtitles_renderer"], "overlay")

    def test_single_snapshot_delta_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir) / "jobs"
            job_dir = jobs_dir / "job1"
            job_dir.mkdir(parents=True)
            self._seed_job(job_dir, [
                {"captured_at": "2026-01-01T00:00:00+00:00",
                 "platform": "youtube", "platform_post_id": "yt123",
                 "metrics": {"views": 100},
                 "unavailable": False, "unavailable_reason": None},
            ])
            rows = compare_metrics(jobs_dir)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["views_delta"], 0)

    def test_platform_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir) / "jobs"
            for job_name, platform in [("job1", "youtube"), ("job2", "twitter")]:
                job_dir = jobs_dir / job_name
                job_dir.mkdir(parents=True)
                self._seed_job(job_dir, [
                    {"captured_at": "2026-01-01T00:00:00+00:00",
                     "platform": platform, "platform_post_id": "post1",
                     "metrics": {"views": 10},
                     "unavailable": False, "unavailable_reason": None},
                ])
            rows = compare_metrics(jobs_dir, platform="youtube")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["platform"], "youtube")

    def test_limit_bounds_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir) / "jobs"
            job_dir = jobs_dir / "job1"
            job_dir.mkdir(parents=True)
            snapshots = [
                {"captured_at": f"2026-01-0{i + 1}T00:00:00+00:00",
                 "platform": "youtube", "platform_post_id": f"yt{i}",
                 "metrics": {"views": i},
                 "unavailable": False, "unavailable_reason": None}
                for i in range(5)
            ]
            self._seed_job(job_dir, snapshots)
            rows = compare_metrics(jobs_dir, limit=3)
            self.assertEqual(len(rows), 3)

    def test_sorted_by_captured_at_desc(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir) / "jobs"
            job_dir = jobs_dir / "job1"
            job_dir.mkdir(parents=True)
            self._seed_job(job_dir, [
                {"captured_at": "2026-01-01T00:00:00+00:00",
                 "platform": "youtube", "platform_post_id": "yt1",
                 "metrics": {"views": 1}, "unavailable": False,
                 "unavailable_reason": None},
                {"captured_at": "2026-01-03T00:00:00+00:00",
                 "platform": "youtube", "platform_post_id": "yt2",
                 "metrics": {"views": 2}, "unavailable": False,
                 "unavailable_reason": None},
                {"captured_at": "2026-01-02T00:00:00+00:00",
                 "platform": "youtube", "platform_post_id": "yt3",
                 "metrics": {"views": 3}, "unavailable": False,
                 "unavailable_reason": None},
            ])
            rows = compare_metrics(jobs_dir)
            self.assertEqual([r["platform_post_id"] for r in rows],
                             ["yt2", "yt3", "yt1"])

    def test_unreadable_manifest_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jobs_dir = Path(temp_dir) / "jobs"
            job_dir = jobs_dir / "job1"
            job_dir.mkdir(parents=True)
            (job_dir / "manifest.json").write_text("not json", encoding="utf-8")
            append_snapshot(job_dir, {
                "captured_at": "2026-01-01T00:00:00+00:00",
                "platform": "youtube", "platform_post_id": "yt1",
                "metrics": {"views": 1}, "unavailable": False,
                "unavailable_reason": None,
            })
            rows = compare_metrics(jobs_dir)
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
