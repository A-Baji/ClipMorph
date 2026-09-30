from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.job import JobManifest
from clipmorph.service import JobService
from clipmorph.service import UnknownUploadAttempt
from clipmorph.service import UploadAttemptNotScheduled
from clipmorph.storage import LocalArtifactStorage
from clipmorph.upload_attempts import content_options


class JobServiceTests(unittest.TestCase):
    def test_service_persists_completed_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "data" / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "input.mp4"
            source.write_bytes(b"video")
            service = JobService(Path(temp_dir) / "data")

            def complete_job(job, _token):
                for stage in ("transcript", "conversion", "upload"):
                    checkpoint = job.checkpoints[stage]
                    if checkpoint["status"] == "skipped":
                        continue
                    checkpoint = job.transition_checkpoint(
                        stage, "running", checkpoint["revision"], service.jobs_dir)
                    job.transition_checkpoint(
                        stage, "completed", checkpoint["revision"], service.jobs_dir)

            try:
                manifest = service.create_job(
                    str(source), {}, complete_job)
                service._futures[manifest.job_id].result(timeout=2)
                self.assertEqual(service.get_job(manifest.job_id).status,
                                 "completed")
            finally:
                service.close()

    def test_service_cancels_queued_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "data" / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "input.mp4"
            source.write_bytes(b"video")
            service = JobService(Path(temp_dir) / "data")
            try:
                manifest = service.create_job(str(source), {})
                cancelled = service.cancel_job(manifest.job_id)
                self.assertEqual(cancelled.status, "cancelled")
            finally:
                service.close()


def _reviewed_job(data_dir: Path) -> tuple[JobService, JobManifest]:
    """Create a service whose single job sits at the upload review gate."""
    source_dir = data_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / "clip.mp4"
    source.write_bytes(b"video")
    service = JobService(data_dir)
    manifest = JobManifest.create(
        str(source),
        {"general": {"source": source.name},
         "conversion": {"skip": True, "subtitles": {"skip": True}}},
        service.jobs_dir)
    manifest.record_artifact("source", source, service.jobs_dir)
    manifest.transition_checkpoint(
        "upload", "awaiting_review", manifest.checkpoints["upload"]["revision"],
        service.jobs_dir)
    return service, manifest


def _upload_results(platforms):
    """A mocked upload pipeline returning success for each requested platform."""
    def run(_artifact_path, _title, *_args, **_kwargs):
        stamp = datetime.now(timezone.utc).isoformat()
        return {platform: {"success": True, "result": f"{platform} ok",
                           "started_at": stamp, "completed_at": stamp}
                for platform in platforms}

    return run


class DeferredUploadTests(unittest.TestCase):
    def test_submit_upload_with_future_publish_at_defers_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])) as pipeline:
                result = service.submit_upload(
                    manifest.job_id, ["youtube"],
                    configuration_snapshot={
                        "platforms": {"include": ["youtube"]},
                        "schedule": {"publish_at": publish_at}})

                pipeline.assert_not_called()
                self.assertTrue(result["scheduled"])
                attempt = result["attempts"][0]
                self.assertEqual(attempt["status"], "scheduled")
                self.assertEqual(attempt["scheduled_publish_at"], publish_at)
                self.assertNotIn(f"upload:{manifest.job_id}",
                                 service._futures)
                checkpoint = service.get_job(
                    manifest.job_id).checkpoints["upload"]
                self.assertEqual(checkpoint["status"], "running")

                # Fire the stored timer early instead of waiting an hour.
                timer = service._scheduled_timers[f"upload:{manifest.job_id}"][0]
                timer.cancel()
                service._run_upload_attempts(
                    manifest.job_id, [attempt["attempt_id"]],
                    service.get_job(manifest.job_id).artifacts[
                        attempt["artifact_id"]]["storage"]["key"],
                    {"platforms": {"include": ["youtube"]}}, ["youtube"])

            saved = service.get_job(manifest.job_id)
            self.assertEqual(pipeline.call_count, 1)
            self.assertEqual(
                pipeline.call_args.args[0], ["youtube"])
            self.assertEqual(saved.upload_attempts[0]["status"], "published")
            self.assertTrue(saved.platforms["youtube"]["success"])
            self.assertEqual(saved.checkpoints["upload"]["status"], "completed")

    def test_scheduled_timers_are_cancelled_on_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service.submit_upload(
                manifest.job_id, ["youtube"],
                configuration_snapshot={
                    "platforms": {"include": ["youtube"]},
                    "schedule": {"publish_at": publish_at}})
            timer = service._scheduled_timers[f"upload:{manifest.job_id}"][0]

            service.close()

            self.assertTrue(timer.finished.is_set())
            self.assertEqual(service._scheduled_timers, {})
            self.assertEqual(
                service.get_job(manifest.job_id).upload_attempts[0]["status"],
                "scheduled")

    def test_retry_of_a_scheduled_attempt_runs_immediately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            try:
                publish_at = (datetime.now(timezone.utc)
                              + timedelta(hours=1)).isoformat()
                service.submit_upload(
                    manifest.job_id, ["youtube"],
                    configuration_snapshot={
                        "platforms": {"include": ["youtube"]},
                        "schedule": {"publish_at": publish_at}})
                attempt = service.get_job(manifest.job_id).upload_attempts[0]
                service._run_upload_attempts(
                    manifest.job_id, [attempt["attempt_id"]],
                    service.get_job(manifest.job_id).artifacts[
                        attempt["artifact_id"]]["storage"]["key"],
                    {"platforms": {"include": ["youtube"]}}, ["youtube"])
                failed = service.get_job(manifest.job_id).upload_attempts[0]
                failed["status"] = "failed"
                service.get_job(manifest.job_id).save(service.jobs_dir)

                with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                           side_effect=_upload_results(["youtube"])) as pipeline:
                    retried = service.retry_upload(
                        manifest.job_id, "youtube", failed["attempt_id"])
                    # The retry runs on the executor, so wait for the attempt
                    # to finish before reading its recorded result.
                    service._futures[
                        f"upload:{manifest.job_id}"].result(timeout=5)

                pipeline.assert_called_once()
                self.assertFalse(retried["scheduled"])
                self.assertEqual(retried["attempts"][0]["status"], "pending")
                self.assertEqual(retried["attempts"][0]["retry_of"],
                                 failed["attempt_id"])
            finally:
                service.close()

    def test_publish_at_in_the_past_uploads_immediately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])) as pipeline:
                result = service.submit_upload(
                    manifest.job_id, ["youtube"],
                    configuration_snapshot={
                        "platforms": {"include": ["youtube"]},
                        "schedule": {"publish_at": (
                            datetime.now(timezone.utc)
                            - timedelta(hours=1)).isoformat()}})
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            pipeline.assert_called_once()
            self.assertFalse(result["scheduled"])

    def test_unparsable_publish_at_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)

            with self.assertRaisesRegex(ValueError, "ISO-8601"):
                service.submit_upload(
                    manifest.job_id, ["youtube"],
                    configuration_snapshot={
                        "platforms": {"include": ["youtube"]},
                        "schedule": {"publish_at": "next tuesday"}})

    def test_startup_rearm_scheduled_attempts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=2)).isoformat()
            service.submit_upload(
                manifest.job_id, ["youtube"],
                configuration_snapshot={
                    "platforms": {"include": ["youtube"]},
                    "schedule": {"publish_at": publish_at}})
            service.close()

            restarted = JobService(data_dir)
            try:
                armed = {key: len(value) for key, value
                         in restarted._scheduled_timers.items()}
                healed = restarted.get_job(manifest.job_id)
            finally:
                restarted.close()

            self.assertEqual(list(armed), [f"upload:{manifest.job_id}"])
            self.assertEqual(armed[f"upload:{manifest.job_id}"], 1)
            # Reconciliation must not have failed the checkpoint it re-armed.
            self.assertEqual(healed.checkpoints["upload"]["status"], "running")
            self.assertEqual(healed.upload_attempts[0]["status"], "scheduled")
            self.assertEqual(healed.upload_attempts[0]["scheduled_publish_at"],
                             publish_at)


    def test_draft_change_disarms_the_armed_schedule(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            first = service.submit_upload(
                manifest.job_id, ["youtube"],
                configuration_snapshot={
                    "platforms": {"include": ["youtube"]},
                    "schedule": {"publish_at": publish_at}})
            key = f"upload:{manifest.job_id}"
            armed = service._scheduled_timers[key][0]

            service.update_upload_draft(
                manifest.job_id, {"platforms": {"include": ["youtube"]}},
                service.get_job(manifest.job_id).checkpoints["upload"]["revision"])

            # The superseded schedule must not survive the draft edit, or the
            # old configuration would post alongside the resubmitted one.
            self.assertTrue(armed.finished.is_set())
            self.assertNotIn(key, service._scheduled_timers)
            discarded = service.get_job(manifest.job_id)
            self.assertEqual(discarded.checkpoints["upload"]["status"],
                             "awaiting_review")
            self.assertEqual(discarded.upload_attempts[0]["status"], "pending")
            self.assertNotIn("scheduled_publish_at",
                             discarded.upload_attempts[0])

            second = service.submit_upload(
                manifest.job_id, ["youtube"],
                configuration_snapshot={
                    "platforms": {"include": ["youtube"]},
                    "schedule": {"publish_at": publish_at},
                    "content": {"title": "Updated", "description": "", "tags": []}})

            timers = service._scheduled_timers[key]
            self.assertEqual(len(timers), 1)
            self.assertIsNot(timers[0], armed)
            self.assertNotEqual(second["attempts"][0]["attempt_id"],
                                first["attempts"][0]["attempt_id"])

    def test_restart_does_not_rearm_a_discarded_schedule(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service.submit_upload(
                manifest.job_id, ["youtube"],
                configuration_snapshot={
                    "platforms": {"include": ["youtube"]},
                    "schedule": {"publish_at": publish_at}})
            service.update_upload_draft(
                manifest.job_id, {"platforms": {"include": ["youtube"]}},
                service.get_job(manifest.job_id).checkpoints["upload"]["revision"])
            service.close()

            restarted = JobService(data_dir)
            try:
                armed = {key: len(value) for key, value
                         in restarted._scheduled_timers.items()}
                healed = restarted.get_job(manifest.job_id)
            finally:
                restarted.close()

            self.assertEqual(armed, {})
            self.assertEqual(healed.checkpoints["upload"]["status"],
                             "awaiting_review")
            self.assertEqual(healed.upload_attempts[0]["status"], "pending")

    def test_rerender_disarms_the_schedule_it_supersedes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service.submit_upload(
                manifest.job_id, ["youtube"],
                configuration_snapshot={
                    "platforms": {"include": ["youtube"]},
                    "schedule": {"publish_at": publish_at}})
            key = f"upload:{manifest.job_id}"
            armed = service._scheduled_timers[key][0]
            service.get_job(manifest.job_id).invalidate_checkpoint(
                "upload", {"code": "rerender", "message": "Conversion rerendered"},
                service.jobs_dir)

            self.assertEqual(service.discard_scheduled_uploads(manifest.job_id), 1)

            self.assertTrue(armed.finished.is_set())
            self.assertNotIn(key, service._scheduled_timers)
            superseded = service.get_job(manifest.job_id)
            self.assertEqual(superseded.checkpoints["upload"]["status"], "stale")
            self.assertEqual(superseded.upload_attempts[0]["status"], "pending")
            # A stale upload checkpoint cannot be finalized by a stray timer,
            # so the unmarked attempt also fails the startup re-arm scan.
            self.assertFalse(service._upload_awaits_schedule(superseded))
            self.assertEqual(service.discard_scheduled_uploads(manifest.job_id), 0)

    def test_duplicate_active_attempt_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            try:
                # Create a scheduled attempt (active status) without firing it
                future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                service.submit_upload(
                    manifest.job_id, ["youtube"],
                    configuration_snapshot={
                        "platforms": {"include": ["youtube"]},
                        "schedule": {"publish_at": future},
                        "content": {"title": "Test", "description": "", "tags": []}})
                # Reset the checkpoint to awaiting_review for the second submission
                saved = service.get_job(manifest.job_id)
                service.update_upload_draft(
                    manifest.job_id, {"platforms": {"include": ["youtube"]}},
                    saved.checkpoints["upload"]["revision"], reopen=True)

                with self.assertRaisesRegex(ValueError, "active upload attempt"):
                    service.submit_upload(
                        manifest.job_id, ["youtube"],
                        configuration_snapshot={
                            "platforms": {"include": ["youtube"]},
                            "content": {"title": "Test", "description": "", "tags": []}})
            finally:
                service.close()

    def test_exact_attempt_retry_bypasses_dedup_guard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            try:
                with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                           side_effect=_upload_results(["youtube"])):
                    service.submit_upload(
                        manifest.job_id, ["youtube"],
                        configuration_snapshot={
                            "platforms": {"include": ["youtube"]},
                            "content": {"title": "Test", "description": "", "tags": []}})
                    service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

                saved = service.get_job(manifest.job_id)
                saved.upload_attempts[0]["status"] = "failed"
                saved.checkpoints["upload"]["status"] = "failed"
                saved.save(service.jobs_dir)

                with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                           side_effect=_upload_results(["youtube"])):
                    retried = service.retry_upload(
                        manifest.job_id, "youtube",
                        saved.upload_attempts[0]["attempt_id"])
                self.assertEqual(retried["attempts"][0]["retry_of"],
                                 saved.upload_attempts[0]["attempt_id"])
            finally:
                service.close()

    def test_published_attempt_propagates_platform_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])):
                service.submit_upload(
                    manifest.job_id, ["youtube"],
                    configuration_snapshot={
                        "platforms": {"include": ["youtube"]},
                        "content": {"title": "Test", "description": "", "tags": []}})
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            saved = service.get_job(manifest.job_id)
            attempt = saved.upload_attempts[0]
            self.assertEqual(attempt["status"], "published")
            self.assertEqual(attempt["result"]["platform_post_id"], "youtube ok")
            self.assertEqual(attempt["result"]["platform_url"],
                             "https://www.youtube.com/watch?v=youtube ok")
            self.assertEqual(saved.platforms["youtube"]["status"], "published")
            self.assertEqual(saved.platforms["youtube"]["platform_post_id"],
                             "youtube ok")

    def test_cancel_all_scheduled_uploads_marks_cancelled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            service.submit_upload(
                manifest.job_id, ["youtube"],
                configuration_snapshot={
                    "platforms": {"include": ["youtube"]},
                    "schedule": {"publish_at": future},
                    "content": {"title": "Test", "description": "", "tags": []}})

            cancelled = service.cancel_all_scheduled_uploads(manifest.job_id)
            self.assertEqual(cancelled, 1)

            saved = service.get_job(manifest.job_id)
            self.assertEqual(saved.upload_attempts[0]["status"], "cancelled")
            self.assertIsNotNone(saved.upload_attempts[0]["completed_at"])


class _RecordingAdapter:
    """Stand-in upload adapter recording scheduled-post cancellations."""

    def __init__(self, error: Exception | None = None):
        self.cancelled: list[str] = []
        self.error = error

    def cancel_scheduled_post(self, platform_post_id: str) -> None:
        if self.error is not None:
            raise self.error
        self.cancelled.append(platform_post_id)


class PlatformScheduledUploadTests(unittest.TestCase):
    """``upload.schedule.mode: platform`` hands publication to the platform."""

    def _submit(self, service, manifest, platforms, publish_at, mode="platform",
                notify_subscribers=None):
        overrides = {"include": platforms}
        if notify_subscribers is not None:
            overrides["youtube"] = {"notify_subscribers": notify_subscribers}
        return service.submit_upload(
            manifest.job_id, platforms,
            configuration_snapshot={
                "platforms": overrides,
                "schedule": {"publish_at": publish_at, "mode": mode},
                "content": {"title": "Test", "description": "", "tags": []}})

    def test_platform_mode_names_every_ineligible_platform_before_any_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()

            with self.assertRaises(ValueError) as raised:
                self._submit(service, manifest, ["youtube", "instagram"],
                             publish_at)

            self.assertIn(
                "upload.schedule.mode platform is not enabled for: "
                "youtube, instagram", str(raised.exception))
            self.assertIn("scheduling_probe.py", str(raised.exception))
            untouched = service.get_job(manifest.job_id)
            self.assertEqual(untouched.upload_attempts, [])
            self.assertEqual(untouched.checkpoints["upload"]["status"],
                             "awaiting_review")

    def test_platform_schedule_uploads_immediately_and_stays_scheduled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()

            with patch.dict("clipmorph.platforms.SUPPORTED_NATIVE_SCHEDULING",
                            {"youtube": True}), patch(
                "clipmorph.upload_attempts.execute_upload_pipeline",
                side_effect=_upload_results(["youtube"])) as pipeline:
                result = self._submit(service, manifest, ["youtube"], publish_at)
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            # The platform holds the timer, so nothing is armed locally.
            self.assertEqual(service._scheduled_timers, {})
            self.assertEqual(result["scheduled_via"], "platform")
            attempt = result["attempts"][0]
            self.assertEqual(attempt["status"], "scheduled")
            self.assertEqual(attempt["scheduled_via"], "platform")
            self.assertEqual(attempt["scheduled_publish_at"], publish_at)

            # The resolved instant rides the per-platform override into the
            # adapter keyword the production mapping derives from it.
            options = content_options(pipeline.call_args.args[2], ["youtube"])
            self.assertEqual(options["youtube_scheduled_publish_at"], publish_at)

            saved = service.get_job(manifest.job_id)
            self.assertEqual(saved.upload_attempts[0]["status"], "scheduled")
            attempt_result = saved.upload_attempts[0]["result"]
            self.assertTrue(attempt_result["success"])
            self.assertEqual(attempt_result["platform_post_id"], "youtube ok")
            self.assertEqual(attempt_result["scheduled_publish_at"], publish_at)
            self.assertIsNone(attempt_result["published_at"])
            self.assertIn("platform holds publication", attempt_result["message"])
            self.assertEqual(saved.platforms["youtube"]["status"], "scheduled")
            self.assertIsNone(saved.platforms["youtube"]["published_at"])
            self.assertEqual(saved.checkpoints["upload"]["status"], "completed")

    def test_local_schedule_keeps_its_own_timer_and_sends_no_platform_kwarg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()

            with patch.object(service, "_schedule_attempts") as schedule:
                result = self._submit(service, manifest, ["youtube"],
                                      publish_at, mode="local")

            self.assertEqual(result["scheduled_via"], "local")
            self.assertEqual(result["attempts"][0]["scheduled_via"], "local")
            self.assertEqual(
                service.get_job(manifest.job_id).checkpoints["upload"]["status"],
                "running")
            # The local path is untouched: one timer, and nothing in what the
            # worker is handed tells the adapter about a scheduled publication.
            schedule.assert_called_once()
            options = content_options(schedule.call_args.args[3], ["youtube"])
            self.assertNotIn("youtube_scheduled_publish_at", options)

    def test_cancelled_attempt_is_not_resurrected_by_a_stale_batch_timer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            result = self._submit(service, manifest, ["youtube"], publish_at,
                                  mode="local")
            attempt_id = result["attempts"][0]["attempt_id"]
            service.cancel_scheduled_upload(manifest.job_id, attempt_id)

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])) as pipeline:
                service._run_upload_attempts(
                    manifest.job_id, [attempt_id], "artifact-key",
                    {"platforms": {"include": ["youtube"]}}, ["youtube"])

            pipeline.assert_not_called()
            self.assertEqual(
                service.get_job(manifest.job_id).upload_attempts[0]["status"],
                "cancelled")

    def test_cancelling_one_local_attempt_rearms_the_rest_of_its_batch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            result = self._submit(service, manifest,
                                  ["youtube", "instagram"], publish_at,
                                  mode="local")
            armed = service._scheduled_timers[f"upload:{manifest.job_id}"][0]
            by_platform = {attempt["platform"]: attempt
                           for attempt in result["attempts"]}

            cancelled = service.cancel_scheduled_upload(
                manifest.job_id, by_platform["youtube"]["attempt_id"])

            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(cancelled["scheduled_via"], "local")
            self.assertTrue(armed.finished.is_set())
            saved = service.get_job(manifest.job_id)
            statuses = {attempt["platform"]: attempt["status"]
                        for attempt in saved.upload_attempts}
            self.assertEqual(statuses, {"youtube": "cancelled",
                                        "instagram": "scheduled"})
            # The surviving member is still armed through the re-arm path.
            rearmed = service._scheduled_timers[f"upload:{manifest.job_id}"]
            self.assertEqual(len(rearmed), 1)
            self.assertIsNot(rearmed[0], armed)
            rearmed[0].cancel()

    def test_platform_cancel_deletes_the_post_and_marks_the_attempt_cancelled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            adapter = _RecordingAdapter()

            with patch.dict("clipmorph.platforms.SUPPORTED_NATIVE_SCHEDULING",
                            {"youtube": True}), patch(
                "clipmorph.upload_attempts.execute_upload_pipeline",
                side_effect=_upload_results(["youtube"])):
                result = self._submit(service, manifest, ["youtube"], publish_at)
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            with patch("clipmorph.service._upload_adapter",
                       return_value=adapter):
                cancelled = service.cancel_scheduled_upload(
                    manifest.job_id, result["attempts"][0]["attempt_id"])

            self.assertEqual(adapter.cancelled, ["youtube ok"])
            self.assertEqual(cancelled["scheduled_via"], "platform")
            self.assertEqual(cancelled["status"], "cancelled")
            attempt = service.get_job(manifest.job_id).upload_attempts[0]
            self.assertEqual(attempt["status"], "cancelled")
            self.assertEqual(attempt["result"]["platform_post_id"], "youtube ok")
            self.assertIn("cancelled", attempt["result"]["message"])

    def test_platform_cancel_failure_leaves_the_attempt_scheduled_with_a_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()

            with patch.dict("clipmorph.platforms.SUPPORTED_NATIVE_SCHEDULING",
                            {"youtube": True}), patch(
                "clipmorph.upload_attempts.execute_upload_pipeline",
                side_effect=_upload_results(["youtube"])):
                result = self._submit(service, manifest, ["youtube"], publish_at)
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            with patch("clipmorph.service._upload_adapter",
                       return_value=_RecordingAdapter(
                           RuntimeError("quota exceeded"))):
                with self.assertRaisesRegex(
                        ValueError, "refused to cancel post youtube ok"):
                    service.cancel_scheduled_upload(
                        manifest.job_id, result["attempts"][0]["attempt_id"])

            attempt = service.get_job(manifest.job_id).upload_attempts[0]
            self.assertEqual(attempt["status"], "scheduled")
            self.assertEqual(attempt["errors"][-1]["code"],
                             "platform_cancel_failed")
            self.assertTrue(attempt["errors"][-1]["retryable"])

    def test_cancel_refuses_an_unknown_or_unscheduled_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])):
                service.submit_upload(
                    manifest.job_id, ["youtube"],
                    configuration_snapshot={
                        "platforms": {"include": ["youtube"]},
                        "content": {"title": "Test", "description": "",
                                    "tags": []}})
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            with self.assertRaises(UnknownUploadAttempt):
                service.cancel_scheduled_upload(manifest.job_id, "missing")
            attempt_id = service.get_job(
                manifest.job_id).upload_attempts[0]["attempt_id"]
            with self.assertRaises(UploadAttemptNotScheduled):
                service.cancel_scheduled_upload(manifest.job_id, attempt_id)


class _ArmedStagingStorage(LocalArtifactStorage):
    """Local backend whose ``stage`` starts failing once ``armed`` is set."""

    def __init__(self, root):
        super().__init__(root)
        self.armed = False

    def stage(self, key, destination_dir):
        if self.armed:
            raise OSError("artifact storage is offline")
        return super().stage(key, destination_dir)


def _upload_results_capturing_staged(platforms, captured):
    """A mocked upload pipeline recording the staged file it was handed."""
    def execute(_platforms, artifact_path, *_args, **_kwargs):
        staged = Path(artifact_path)
        captured.append((staged, staged.read_bytes()))
        stamp = datetime.now(timezone.utc).isoformat()
        return {platform: {"success": True, "result": f"{platform} ok",
                           "started_at": stamp, "completed_at": stamp}
                for platform in platforms}

    return execute


class ArtifactStagingTests(unittest.TestCase):
    def test_upload_reads_a_staged_copy_that_is_released_afterwards(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            registered = service.artifact_path(
                service.get_job(manifest.job_id).artifacts[
                    manifest.current_artifact_id])
            captured = []

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results_capturing_staged(
                           ["youtube"], captured)):
                service.submit_upload(manifest.job_id, ["youtube"])
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            staged, staged_bytes = captured[0]
            # The adapter reads a private copy, never the registered bytes.
            self.assertNotEqual(staged, registered)
            self.assertEqual(staged_bytes, registered.read_bytes())
            self.assertEqual(service.get_job(manifest.job_id).upload_attempts[0]
                             ["status"], "published")
            # Verification and upload copies are both released.
            self.assertFalse(staged.exists())
            self.assertFalse(staged.parent.exists())
            leftovers = (sorted(service._staging_dir.rglob("*"))
                         if service._staging_dir.exists() else [])
            self.assertEqual(leftovers, [])

    def test_staging_failure_fails_the_attempt_and_records_a_manifest_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            service._storage = _ArmedStagingStorage(service._storage.root)
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()

            with patch("clipmorph.upload_attempts.execute_upload_pipeline") as pipeline:
                result = service.submit_upload(
                    manifest.job_id, ["youtube"],
                    configuration_snapshot={
                        "platforms": {"include": ["youtube"]},
                        "schedule": {"publish_at": publish_at}})
                # Hold the attempt back, then fail only its staging copy.
                service._scheduled_timers[f"upload:{manifest.job_id}"][0].cancel()
                service._storage.armed = True
                attempt = result["attempts"][0]
                service._run_upload_attempts(
                    manifest.job_id, [attempt["attempt_id"]],
                    service.get_job(manifest.job_id).artifacts[
                        attempt["artifact_id"]]["storage"]["key"],
                    {"platforms": {"include": ["youtube"]}}, ["youtube"])

            pipeline.assert_not_called()
            saved = service.get_job(manifest.job_id)
            self.assertEqual(saved.upload_attempts[0]["status"], "failed")
            self.assertIn("artifact staging failed",
                          saved.upload_attempts[0]["result"]["message"])
            self.assertFalse(saved.platforms["youtube"]["success"])
            self.assertEqual(saved.checkpoints["upload"]["status"], "failed")
            self.assertEqual(saved.errors[-1]["code"], "staging_failed")
            self.assertIn("artifact storage is offline", saved.errors[-1]["message"])


def _upload_results_reporting_progress(platforms, percents):
    """A mocked execute_upload_pipeline that reports live progress."""
    def execute(*args, **kwargs):
        progress_callback = kwargs.get("progress_callback")
        if progress_callback:
            for platform, percent in zip(platforms, percents):
                progress_callback(platform, percent)
        stamp = datetime.now(timezone.utc).isoformat()
        return {platform: {"success": True, "result": f"{platform} ok",
                           "started_at": stamp, "completed_at": stamp}
                for platform in platforms}
    return execute


class LiveProgressTests(unittest.TestCase):
    def test_restart_clears_live_progress_but_retains_final_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            job_id = manifest.job_id

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results_reporting_progress(
                           ["youtube"], [75])):
                service.submit_upload(job_id, ["youtube"])
                service._futures[f"upload:{job_id}"].result(timeout=2)

            attempt = service.get_job(job_id).upload_attempts[0]
            self.assertEqual(attempt["result"]["progress_percent"], 75)
            # Live progress is cleared once the upload completes.
            self.assertEqual(service.live_progress_for(job_id), {})

            # Simulate a restart: a fresh service instance.
            service.close()
            restarted = JobService(data_dir)
            self.addCleanup(restarted.close)
            self.assertEqual(restarted.live_progress_for(job_id), {})
            # The final snapshot persists in the manifest.
            persisted = restarted.get_job(job_id).upload_attempts[0]
            self.assertEqual(persisted["result"]["progress_percent"], 75)


if __name__ == "__main__":
    unittest.main()
