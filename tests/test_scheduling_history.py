"""Tests for scheduling history filters and platform-side detection."""

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.job import JobManifest
from clipmorph.service import JobService


def _reviewed_job(data_dir: Path, upload: dict | None = None
                  ) -> tuple[JobService, JobManifest]:
    """Create a service whose single job sits at the upload review gate."""
    source_dir = data_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / "clip.mp4"
    source.write_bytes(b"video")
    service = JobService(data_dir)
    configuration = {"conversion": {"skip": True, "subtitles": {"skip": True}}}
    if upload:
        configuration["upload"] = upload
    manifest = JobManifest.create(str(source), configuration, service.jobs_dir)
    manifest.record_artifact("source", source, service.jobs_dir)
    manifest.transition_checkpoint(
        "upload", "awaiting_review", manifest.checkpoints["upload"]["revision"],
        service.jobs_dir)
    return service, manifest


def _future_schedule() -> dict:
    """An upload section carrying a publish_at an hour out."""
    return {"schedule": {
        "publish_at": (datetime.now(timezone.utc)
                       + timedelta(hours=1)).isoformat()}}


def _upload_results(platforms):
    """A mocked upload pipeline returning success for each requested platform."""
    def run(_artifact_path, _title, *_args, **_kwargs):
        stamp = datetime.now(timezone.utc).isoformat()
        return {platform: {"success": True, "result": f"{platform} ok",
                            "started_at": stamp, "completed_at": stamp}
                for platform in platforms}

    return run


class UploadFilterTests(unittest.TestCase):
    """Tests for the uploads-list filters on the service."""

    def _submit_with_attempts(self, service, manifest):
        """Submit uploads to create attempts with varied statuses."""
        with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                   side_effect=_upload_results(["youtube", "tiktok"])):
            # First submission: youtube + tiktok (both succeed), ignoring the
            # schedule the job's configuration carries.
            service.submit_upload(manifest.job_id, ["youtube", "tiktok"],
                                  honor_schedule=False)
            service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            # Reset the checkpoint to awaiting_review for the second submission
            saved = service.get_job(manifest.job_id)
            service.update_upload_draft(
                manifest.job_id, {"content": {"title": "Second"}},
                saved.checkpoints["upload"]["revision"], reopen=True)

            # Second submission: youtube only (scheduled)
            service.submit_upload(manifest.job_id, ["youtube"])

    def test_list_upload_attempts_filters_by_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir, _future_schedule())
            try:
                self._submit_with_attempts(service, manifest)

                published = service.list_upload_attempts(
                    manifest.job_id, status="published")
                self.assertEqual(len(published), 2)
                self.assertTrue(all(a["status"] == "published" for a in published))

                scheduled = service.list_upload_attempts(
                    manifest.job_id, status="scheduled")
                self.assertEqual(len(scheduled), 1)
                self.assertEqual(scheduled[0]["status"], "scheduled")
            finally:
                service.close()

    def test_list_upload_attempts_filters_by_platform(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir, _future_schedule())
            try:
                self._submit_with_attempts(service, manifest)

                youtube = service.list_upload_attempts(
                    manifest.job_id, platform="youtube")
                self.assertEqual(len(youtube), 2)
                self.assertTrue(all(a["platform"] == "youtube" for a in youtube))

                tiktok = service.list_upload_attempts(
                    manifest.job_id, platform="tiktok")
                self.assertEqual(len(tiktok), 1)
                self.assertEqual(tiktok[0]["platform"], "tiktok")
            finally:
                service.close()

    def test_list_upload_attempts_filters_by_since(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir, _future_schedule())
            try:
                self._submit_with_attempts(service, manifest)

                now = datetime.now(timezone.utc)
                recent = service.list_upload_attempts(
                    manifest.job_id,
                    since=(now - timedelta(hours=1)).isoformat())
                self.assertEqual(len(recent), 3)

                past = service.list_upload_attempts(
                    manifest.job_id,
                    since=(now - timedelta(hours=2)).isoformat())
                self.assertEqual(len(past), 3)

                future = service.list_upload_attempts(
                    manifest.job_id,
                    since=(now + timedelta(hours=1)).isoformat())
                self.assertEqual(len(future), 0)
            finally:
                service.close()

    def test_list_upload_attempts_rejects_invalid_since(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            try:
                with self.assertRaisesRegex(ValueError, "since"):
                    service.list_upload_attempts(
                        manifest.job_id, since="not-a-timestamp")
            finally:
                service.close()

    def test_list_upload_attempts_combines_filters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir, _future_schedule())
            try:
                self._submit_with_attempts(service, manifest)

                filtered = service.list_upload_attempts(
                    manifest.job_id, status="published", platform="youtube")
                self.assertEqual(len(filtered), 1)
                self.assertEqual(filtered[0]["status"], "published")
                self.assertEqual(filtered[0]["platform"], "youtube")
            finally:
                service.close()


class PlatformDetectionTests(unittest.TestCase):
    """Tests for platform-side existing-post detection."""

    def test_detection_finds_existing_post(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            try:
                with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                           side_effect=_upload_results(["youtube"])), \
                     patch("clipmorph.service.JobService._detect_existing_posts",
                           return_value=({"youtube": "existing-video-id"}, [])):
                    result = service.submit_upload(manifest.job_id, ["youtube"])

                attempt = result["attempts"][0]
                self.assertEqual(attempt["status"], "published")
                self.assertEqual(attempt["result"]["platform_post_id"],
                                 "existing-video-id")
                self.assertIn("already holds", attempt["result"]["message"])
                self.assertEqual(result["detection"]["existing_posts"],
                                 {"youtube": "existing-video-id"})
            finally:
                service.close()

    def test_detection_unavailable_does_not_block(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            try:
                with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                           side_effect=_upload_results(["youtube"])), \
                     patch("clipmorph.service.JobService._detect_existing_posts",
                           return_value=({}, ["youtube"])):
                    result = service.submit_upload(manifest.job_id, ["youtube"])

                self.assertEqual(result["detection"]["unavailable"], ["youtube"])
                self.assertEqual(result["attempts"][0]["status"], "pending")
            finally:
                service.close()

    def test_detection_skips_platform_without_support(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            try:
                with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                           side_effect=_upload_results(["tiktok"])), \
                     patch("clipmorph.service.JobService._detect_existing_posts",
                           return_value=({}, [])) as detect:
                    result = service.submit_upload(manifest.job_id, ["tiktok"])

                detect.assert_called_once()
                self.assertEqual(result["attempts"][0]["status"], "pending")
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
