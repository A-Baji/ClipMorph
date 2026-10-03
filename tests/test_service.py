from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.job import CHECKPOINT_STATES, JobManifest
from clipmorph.platforms import SUPPORTED_PLATFORMS, resolve_upload_participants
from clipmorph.service import CancellationToken, JobService
from clipmorph.service import UnknownUploadAttempt
from clipmorph.service import UploadAttemptNotScheduled
from clipmorph.service import _stage_skipped, conversion_groups
from clipmorph.storage import LocalArtifactStorage
from clipmorph.upload_attempts import content_options
from clipmorph.workflow import execute_job


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


def _reviewed_job(data_dir: Path, upload: dict | None = None
                  ) -> tuple[JobService, JobManifest]:
    """Create a service whose single job sits at the upload review gate.

    ``upload`` seeds the job's own upload section.  A submission now freezes
    each target platform's effective upload slice out of that configuration
    instead of accepting a caller-supplied snapshot, so a scheduled upload is
    produced by configuring ``schedule.publish_at`` here.
    """
    source_dir = data_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / "clip.mp4"
    source.write_bytes(b"video")
    service = JobService(data_dir)
    configuration = {"conversion": {"skip": True, "subtitles": {"skip": True}}}
    if upload:
        configuration["upload"] = upload
    manifest = JobManifest.create(
        str(source), configuration, service.jobs_dir)
    manifest.record_artifact("source", source, service.jobs_dir)
    manifest.transition_checkpoint(
        "upload", "awaiting_review", manifest.checkpoints["upload"]["revision"],
        service.jobs_dir)
    return service, manifest


def _bindings_for(service: JobService, job_id: str, *attempts: dict) -> list[dict]:
    """Rebuild the execution bindings a submission froze for these attempts.

    ``submit_upload`` coalesces attempts that share an artifact and a frozen
    upload slice into one binding; a test that fires a timer early drives the
    same shape.
    """
    artifacts = service.get_job(job_id).artifacts
    bindings: list[dict] = []
    for attempt in attempts:
        match = next((item for item in bindings
                      if item["artifact_key"]
                      == artifacts[attempt["artifact_id"]]["storage"]["key"]
                      and item["upload_config"]
                      == attempt["configuration_snapshot"]), None)
        if match is None:
            match = {
                "artifact_key": artifacts[attempt["artifact_id"]]["storage"]["key"],
                "upload_config": attempt["configuration_snapshot"],
                "attempt_ids": [],
                "platforms": [],
            }
            bindings.append(match)
        match["attempt_ids"].append(attempt["attempt_id"])
        match["platforms"].append(attempt["platform"])
    return bindings


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
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": publish_at}})
            self.addCleanup(service.close)

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])) as pipeline:
                result = service.submit_upload(manifest.job_id, ["youtube"])

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
                    manifest.job_id, _bindings_for(service, manifest.job_id,
                                                   attempt))

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
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": publish_at}})
            service.submit_upload(manifest.job_id, ["youtube"])
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
                service, manifest = _reviewed_job(
                    data_dir, {"schedule": {"publish_at": publish_at}})
                service.submit_upload(manifest.job_id, ["youtube"])
                attempt = service.get_job(manifest.job_id).upload_attempts[0]
                service._run_upload_attempts(
                    manifest.job_id,
                    _bindings_for(service, manifest.job_id, attempt))
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
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": past}})
            self.addCleanup(service.close)

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])) as pipeline:
                result = service.submit_upload(manifest.job_id, ["youtube"])
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            pipeline.assert_called_once()
            self.assertFalse(result["scheduled"])

    def test_unparsable_publish_at_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": "next tuesday"}})
            self.addCleanup(service.close)

            with self.assertRaisesRegex(ValueError, "ISO-8601"):
                service.submit_upload(manifest.job_id, ["youtube"])

    def test_startup_rearm_scheduled_attempts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=2)).isoformat()
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": publish_at}})
            service.submit_upload(manifest.job_id, ["youtube"])
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
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": publish_at}})
            self.addCleanup(service.close)
            first = service.submit_upload(manifest.job_id, ["youtube"])
            key = f"upload:{manifest.job_id}"
            armed = service._scheduled_timers[key][0]

            service.update_upload_draft(
                manifest.job_id, {"content": {"title": "Updated draft"}},
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

            second = service.submit_upload(manifest.job_id, ["youtube"])

            timers = service._scheduled_timers[key]
            self.assertEqual(len(timers), 1)
            self.assertIsNot(timers[0], armed)
            self.assertNotEqual(second["attempts"][0]["attempt_id"],
                                first["attempts"][0]["attempt_id"])

    def test_restart_does_not_rearm_a_discarded_schedule(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": publish_at}})
            service.submit_upload(manifest.job_id, ["youtube"])
            service.update_upload_draft(
                manifest.job_id, {"content": {"title": "Updated draft"}},
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
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": publish_at}})
            self.addCleanup(service.close)
            service.submit_upload(manifest.job_id, ["youtube"])
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
            future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(data_dir, {
                "content": {"title": "Test", "description": "", "tags": []},
                "schedule": {"publish_at": future}})
            try:
                # Create a scheduled attempt (active status) without firing it
                service.submit_upload(manifest.job_id, ["youtube"])
                # Reset the checkpoint to awaiting_review for the second submission
                saved = service.get_job(manifest.job_id)
                service.update_upload_draft(
                    manifest.job_id, {"content": {"title": "Test"}},
                    saved.checkpoints["upload"]["revision"], reopen=True)

                with self.assertRaisesRegex(ValueError, "active upload attempt"):
                    service.submit_upload(manifest.job_id, ["youtube"])
            finally:
                service.close()

    def test_exact_attempt_retry_bypasses_dedup_guard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir, {
                "content": {"title": "Test", "description": "", "tags": []}})
            try:
                with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                           side_effect=_upload_results(["youtube"])):
                    service.submit_upload(manifest.job_id, ["youtube"])
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
            service, manifest = _reviewed_job(data_dir, {
                "content": {"title": "Test", "description": "", "tags": []}})
            self.addCleanup(service.close)

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])):
                service.submit_upload(manifest.job_id, ["youtube"])
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            saved = service.get_job(manifest.job_id)
            attempt = saved.upload_attempts[0]
            self.assertEqual(attempt["status"], "published")
            self.assertEqual(attempt["result"]["platform_post_id"], "youtube ok")
            self.assertEqual(attempt["result"]["platform_url"],
                             "https://www.youtube.com/watch?v=youtube ok")

    def test_mixed_platform_results_keep_the_job_as_partial_failure(self):
        """One failed platform must not erase a sibling's success.

        Ported from a removed manifest-level helper that duplicated this
        logic: the real writer (``_run_upload_attempts``) normalizes each
        per-platform result, transitions the upload checkpoint to
        ``partial_failure`` when success and failure coexist, and the manifest
        status derives from it.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir, {
                "content": {"title": "Test", "description": "", "tags": []}})
            self.addCleanup(service.close)

            def mixed_results(_artifact_path, _title, *_args, **_kwargs):
                stamp = datetime.now(timezone.utc).isoformat()
                return {
                    "youtube": {"success": False, "error": "quota exhausted",
                                "started_at": stamp, "completed_at": stamp},
                    "instagram": {"success": True, "result": "instagram ok",
                                  "started_at": stamp, "completed_at": stamp},
                }

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=mixed_results):
                service.submit_upload(manifest.job_id, ["youtube", "instagram"])
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)

            saved = service.get_job(manifest.job_id)
            self.assertTrue(saved.platforms["instagram"]["success"])
            self.assertFalse(saved.platforms["youtube"]["success"])
            self.assertEqual(
                [item["status"] for item in saved.upload_attempts
                 if item["platform"] == "youtube"],
                ["failed"])
            self.assertEqual(saved.checkpoints["upload"]["status"],
                             "partial_failure")
            self.assertEqual(saved.status, "partial_failure")

    def test_cancel_all_scheduled_uploads_marks_cancelled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(data_dir, {
                "content": {"title": "Test", "description": "", "tags": []},
                "schedule": {"publish_at": future}})
            self.addCleanup(service.close)
            service.submit_upload(manifest.job_id, ["youtube"])

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
        snapshot = {
            "schedule": {"publish_at": publish_at, "mode": mode},
            "content": {"title": "Test", "description": "", "tags": []},
            "platform_options": {},
        }
        if notify_subscribers is not None:
            snapshot["platform_options"]["youtube_notify_subscribers"] = (
                notify_subscribers)
        return service.submit_upload(
            manifest.job_id, platforms,
            platform_snapshots={platform: snapshot for platform in platforms})

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
            options = content_options(pipeline.call_args.args[2])
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
            options = content_options(
                schedule.call_args.args[1][0]["upload_config"])
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
                    manifest.job_id, [{
                        "attempt_ids": [attempt_id],
                        "platforms": ["youtube"],
                        "artifact_key": "artifact-key",
                        "upload_config": {"platforms": {"include": ["youtube"]}},
                    }])

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
                    platform_snapshots={"youtube": {
                        "content": {"title": "Test", "description": "",
                                    "tags": []}}})
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
            publish_at = (datetime.now(timezone.utc)
                          + timedelta(hours=1)).isoformat()
            service, manifest = _reviewed_job(
                data_dir, {"schedule": {"publish_at": publish_at}})
            self.addCleanup(service.close)
            service._storage = _ArmedStagingStorage(service._storage.root)

            with patch("clipmorph.upload_attempts.execute_upload_pipeline") as pipeline:
                result = service.submit_upload(manifest.job_id, ["youtube"])
                # Hold the attempt back, then fail only its staging copy.
                service._scheduled_timers[f"upload:{manifest.job_id}"][0].cancel()
                service._storage.armed = True
                attempt = result["attempts"][0]
                service._run_upload_attempts(
                    manifest.job_id,
                    _bindings_for(service, manifest.job_id, attempt))

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


class PullMetricsTests(unittest.TestCase):
    def _published_job(self, data_dir: Path) -> tuple[JobService, JobManifest]:
        """Create a service with one published upload attempt."""
        service, manifest = _reviewed_job(data_dir)
        attempt = {
            "attempt_id": "test-attempt-id",
            "platform": "youtube",
            "artifact_id": manifest.current_artifact_id,
            "artifact_hash": "abc123",
            "configuration_snapshot": {"platforms": {"include": ["youtube"]}},
            "configuration_hash": "hash123",
            "content_hash": "content123",
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:01+00:00",
            "completed_at": "2026-01-01T00:00:02+00:00",
            "status": "published",
            "result": {
                "success": True,
                "message": "uploaded",
                "platform_post_id": "yt123",
                "platform_url": "https://www.youtube.com/watch?v=yt123",
                "published_at": "2026-01-01T00:00:02+00:00",
            },
        }
        manifest.upload_attempts.append(attempt)
        manifest.save(service.jobs_dir)
        return service, manifest

    def test_pull_metrics_no_published_attempts_is_noop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            result = service.pull_metrics(manifest.job_id)
            self.assertEqual(result["pulled"], 0)
            self.assertEqual(result["snapshots"], [])

    def test_pull_metrics_collects_and_persists_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._published_job(data_dir)
            self.addCleanup(service.close)

            with patch("clipmorph.service.collect_platform_metrics",
                       return_value={"yt123": {"views": 100, "likes": 5}}):
                result = service.pull_metrics(manifest.job_id)

            self.assertEqual(result["pulled"], 1)
            snapshot = result["snapshots"][0]
            self.assertEqual(snapshot["platform"], "youtube")
            self.assertEqual(snapshot["platform_post_id"], "yt123")
            self.assertEqual(snapshot["metrics"], {"views": 100, "likes": 5})
            self.assertFalse(snapshot["unavailable"])

            # Verify persistence.
            loaded = service.list_metrics(manifest.job_id)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["platform_post_id"], "yt123")

    def test_pull_metrics_isolation_on_platform_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._published_job(data_dir)
            self.addCleanup(service.close)

            with patch("clipmorph.service.collect_platform_metrics",
                       side_effect=RuntimeError("network error")):
                result = service.pull_metrics(manifest.job_id)

            # Should still return a snapshot, marked unavailable.
            self.assertEqual(result["pulled"], 1)
            snapshot = result["snapshots"][0]
            self.assertTrue(snapshot["unavailable"])
            self.assertIn("unavailable", snapshot["unavailable_reason"])

    def test_pull_metrics_redacts_error_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._published_job(data_dir)
            self.addCleanup(service.close)

            with patch("clipmorph.service.collect_platform_metrics",
                       side_effect=RuntimeError("token=secret123")):
                result = service.pull_metrics(manifest.job_id)

            snapshot = result["snapshots"][0]
            self.assertTrue(snapshot["unavailable"])
            # The raw error should not contain the secret.
            self.assertNotIn("secret123", str(snapshot))


class PerPlatformGroupTests(unittest.TestCase):
    def test_groups_derived_at_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = service.create_job("clip.mp4", {
                    "conversion": {"skip": True, "subtitles": {"skip": True}},
                    "upload": {"skip": True},
                    "platforms": {
                        "youtube": {"upload": {"skip": False}},
                        "tiktok": {"upload": {"skip": False}},
                    },
                })
                groups = manifest.checkpoints["conversion"].get("groups", {})
                self.assertEqual(len(groups), 1)
                group = next(iter(groups.values()))
                self.assertEqual(
                    set(group["platforms"]),
                    {"youtube", "instagram", "tiktok", "twitter", "facebook"})
            finally:
                service.close()

    def test_mixed_skip_render_produces_two_groups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = service.create_job("clip.mp4", {
                    "conversion": {"skip": False, "subtitles": {"skip": True}},
                    "upload": {"skip": True},
                    "platforms": {
                        "youtube": {"conversion": {"skip": True}},
                        "tiktok": {"conversion": {"skip": False}},
                    },
                })
                groups = manifest.checkpoints["conversion"].get("groups", {})
                self.assertEqual(len(groups), 2)
            finally:
                service.close()

    def test_explicit_submission_to_skipped_platform_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            # Skip youtube in the configuration
            manifest.configuration["platforms"] = {
                "youtube": {"upload": {"skip": True}}}
            manifest.save(service.jobs_dir)
            with self.assertRaisesRegex(ValueError, "skipped"):
                service.submit_upload(manifest.job_id, ["youtube"])

    def test_per_platform_upload_skip_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            manifest.configuration["upload"] = {"skip": True}
            manifest.configuration["platforms"] = {
                "youtube": {"upload": {"skip": False}}}
            manifest.save(service.jobs_dir)
            with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline_type:
                pipeline_type.return_value.run.return_value = {
                    "YouTube": {"success": True, "result": "ok"}}
                result = service.submit_upload(manifest.job_id)
                service._futures[f"upload:{manifest.job_id}"].result(timeout=5)
            self.assertEqual(len(result["attempts"]), 1)
            self.assertEqual(result["attempts"][0]["platform"], "youtube")
            # A skipped platform never becomes an attempt, a binding, or a slot
            # in the submission's bar: the bar only ever counts platforms that
            # will upload.
            bars = [call.kwargs["submission_progress"]
                    for call in pipeline_type.call_args_list
                    if call.kwargs.get("submission_progress") is not None]
            self.assertEqual(len(bars), 1)
            self.assertEqual(list(bars[0]._percents), ["youtube"])

    def test_all_platforms_skip_a_stage_skips_it(self):
        configuration = {
            "conversion": {"skip": False, "subtitles": {"skip": False}},
            "upload": {"skip": False},
            "platforms": {
                platform: {"conversion": {"skip": True}}
                for platform in SUPPORTED_PLATFORMS
            },
        }
        # Reaching the end of the loop means every platform's effective
        # conversion section is skipped, so the stage is skipped too.
        self.assertTrue(_stage_skipped(configuration, "conversion"))
        self.assertTrue(_stage_skipped(configuration, "transcript"))
        configuration["platforms"]["youtube"]["conversion"]["skip"] = False
        self.assertFalse(_stage_skipped(configuration, "conversion"))

    def test_non_participating_platform_does_not_unskip_a_stage(self):
        configuration = {
            "conversion": {"skip": True, "subtitles": {"skip": True}},
            "upload": {"skip": True},
            "platforms": {"youtube": {"upload": {"skip": False}}},
        }
        # Only YouTube participates; the other platforms' non-skipped
        # conversion defaults must not force conversion or transcription.
        self.assertEqual(resolve_upload_participants(configuration), ["youtube"])
        self.assertTrue(_stage_skipped(configuration, "conversion"))
        self.assertTrue(_stage_skipped(configuration, "transcript"))

    def test_pending_group_keeps_conversion_actionable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "clip.mp4").write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = service.create_job("clip.mp4", {
                    "conversion": {"skip": False, "subtitles": {"skip": True}},
                    "platforms": {"youtube": {"conversion": {"strict": True}}},
                })
                checkpoint = manifest.checkpoints["conversion"]
                self.assertIn(checkpoint["status"], CHECKPOINT_STATES)
                self.assertEqual(manifest.current_checkpoint, "conversion")
                groups = checkpoint.get("groups", {})
                self.assertEqual(len(groups), 2)
                self.assertTrue(all(group["status"] == "pending"
                                    for group in groups.values()))
            finally:
                service.close()


class WorkflowStageSkipReconciliationTests(unittest.TestCase):
    """A per-platform override that un-skips a born-``skipped`` stage runs it.

    ``JobManifest.create`` marks a stage ``skipped`` from the job-level flag
    only, so ``execute_job`` must return the checkpoint to ``pending`` when a
    per-platform section un-skips it; otherwise the stage is left skipped (or
    the transcript branch returns) and the participating platform never runs.
    """

    @staticmethod
    def _fake_runner():
        return type("FakeRunner", (), {
            "get_video_info": lambda _self, _path: {
                "format": {"duration": "3"},
                "streams": [{"codec_type": "video", "width": 1920,
                             "height": 1080}],
            },
        })()

    def test_upload_stage_unskipped_by_platform_reaches_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            (data_dir / "sources" / "clip.mp4").write_bytes(b"video")
            service = JobService(data_dir)
            self.addCleanup(service.close)
            manifest = service.create_job("clip.mp4", {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"skip": True},
                "platforms": {"youtube": {"upload": {"skip": False}}},
            })
            self.assertEqual(manifest.checkpoints["upload"]["status"], "skipped")

            with patch("clipmorph.workflow.configure_ffmpeg"), \
                    patch("clipmorph.workflow.FFmpegRunner",
                          return_value=self._fake_runner()), \
                    patch("clipmorph.workflow.PreflightValidator"):
                execute_job(manifest, CancellationToken(), service.jobs_dir)

            saved = service.get_job(manifest.job_id)
            self.assertEqual(saved.checkpoints["upload"]["status"],
                             "awaiting_review")
            self.assertEqual(saved.current_checkpoint, "upload")

    def test_conversion_stage_unskipped_by_platform_renders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            (data_dir / "sources" / "clip.mp4").write_bytes(b"video")
            rendered = data_dir / "render.mp4"
            rendered.write_bytes(b"render")
            service = JobService(data_dir)
            self.addCleanup(service.close)
            manifest = service.create_job("clip.mp4", {
                "general": {"no_confirm": True},
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"skip": True},
                "platforms": {"youtube": {
                    "upload": {"skip": False},
                    "conversion": {"skip": False}}},
            })
            self.assertEqual(manifest.checkpoints["conversion"]["status"],
                             "skipped")
            # Isolate the born-skipped conversion reconciliation from the
            # transcript: a born-skipped transcript cannot render its captions
            # collection, which is a separate interaction.  Pre-completing it
            # lets this test observe the conversion branch of the fix.
            manifest.checkpoints["transcript"]["status"] = "completed"
            manifest.save(service.jobs_dir)

            pipeline = type("FakePipeline", (), {
                "__init__": lambda self, **kwargs: None,
                "run": lambda self: str(rendered),
            })()
            with patch("clipmorph.workflow.configure_ffmpeg"), \
                    patch("clipmorph.workflow.FFmpegRunner",
                          return_value=self._fake_runner()), \
                    patch("clipmorph.workflow.PreflightValidator"), \
                    patch("clipmorph.conversion_pipeline.ConversionPipeline",
                          return_value=pipeline):
                execute_job(manifest, CancellationToken(), service.jobs_dir)

            saved = service.get_job(manifest.job_id)
            self.assertEqual(saved.checkpoints["conversion"]["status"],
                             "completed")
            render_group = next(
                group for group in conversion_groups(saved.configuration)
                if not group["conversion"].get("skip"))
            self.assertIn("youtube", render_group["platforms"])
            self.assertIsNotNone(
                saved.checkpoints["conversion"]["groups"][render_group["id"]][
                    "current_artifact_id"])


class WorkflowAutoUploadTests(unittest.TestCase):
    def test_upload_gate_auto_accepts_and_submits_under_no_confirm(self):
        """`general.no_confirm = true` skips the upload approval gate.

        The workflow parks a pending upload checkpoint at `awaiting_review`
        and then, because the gate is confirmed, submits the attempts through
        a borrowed service and waits for them to settle before returning.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            self.addCleanup(service.close)
            manifest = JobManifest.create(str(source), {
                "general": {"no_confirm": True},
                "conversion": {"skip": True, "subtitles": {"skip": True}},
            }, service.jobs_dir)
            manifest.record_artifact("source", source, service.jobs_dir)
            fake_runner = type("FakeRunner", (), {
                "get_video_info": lambda _self, _path: {
                    "format": {"duration": "3"},
                    "streams": [{"codec_type": "video", "width": 1920,
                                 "height": 1080}],
                },
            })()

            with patch("clipmorph.workflow.configure_ffmpeg"), \
                    patch("clipmorph.workflow.FFmpegRunner",
                          return_value=fake_runner), \
                    patch("clipmorph.workflow.PreflightValidator"), \
                    patch("clipmorph.upload_attempts.execute_upload_pipeline",
                          side_effect=_upload_results(
                              ["youtube", "instagram", "tiktok", "twitter",
                               "facebook"])):
                execute_job(manifest, CancellationToken(), service.jobs_dir)

            saved = service.get_job(manifest.job_id)
            self.assertEqual(saved.checkpoints["upload"]["status"], "completed")
            self.assertEqual(saved.upload_attempts[0]["status"], "published")
            self.assertEqual(saved.status, "completed")


def _two_group_job(service: JobService, data_dir: Path) -> JobManifest:
    """Create a job with a rendered group and a source-bound group.

    YouTube resolves to a distinct conversion section, so the job has two
    conversion groups; the helper renders the other group's artifact on disk and
    stamps it on that group, leaving the source artifact registered for the
    group that skips conversion.
    """
    source_dir = data_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / "clip.mp4"
    source.write_bytes(b"video")
    manifest = service.create_job("clip.mp4", {
        "conversion": {"skip": False, "subtitles": {"skip": True}},
        "upload": {"content": {"title": "Job title"}},
        "platforms": {
            "youtube": {"conversion": {"skip": True}},
            "tiktok": {"privacy_level": "SELF_ONLY"},
        },
    })
    derived = conversion_groups(manifest.configuration)
    render_group = next(group["id"] for group in derived
                        if not group["conversion"].get("skip"))
    skip_group = next(group["id"] for group in derived
                      if group["id"] != render_group)
    output = service.jobs_dir / manifest.job_id / "render.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"vertical")
    manifest.record_artifact("primary", output, service.jobs_dir,
                             group_id=render_group)
    manifest.record_artifact("source", source, service.jobs_dir,
                             group_id=skip_group)
    manifest.transition_checkpoint(
        "upload", "awaiting_review",
        manifest.checkpoints["upload"]["revision"], service.jobs_dir)
    return service.get_job(manifest.job_id)


class PerPlatformBindingTests(unittest.TestCase):
    """A submission binds each platform to its own group's artifact/snapshot."""

    def test_identical_platforms_share_one_render_and_one_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "clip.mp4").write_bytes(b"video")
            service = JobService(data_dir)
            self.addCleanup(service.close)
            # No per-platform conversion overrides, so every platform resolves
            # to the job section and there is exactly one group to render.
            manifest = service.create_job("clip.mp4", {
                "conversion": {"skip": False, "subtitles": {"skip": True}},
            })
            groups = manifest.checkpoints["conversion"]["groups"]
            self.assertEqual(len(groups), 1)
            group_id = next(iter(groups))
            output = service.jobs_dir / manifest.job_id / "render.mp4"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"vertical")
            manifest.record_artifact("primary", output, service.jobs_dir,
                                     group_id=group_id)
            manifest.transition_checkpoint(
                "upload", "awaiting_review",
                manifest.checkpoints["upload"]["revision"], service.jobs_dir)

            with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline:
                pipeline.return_value.run.return_value = {
                    name: {"success": True, "result": "ok"}
                    for name in ("YouTube", "Instagram", "TikTok", "Twitter",
                                 "Facebook")}
                result = service.submit_upload(manifest.job_id)
                service._futures[f"upload:{manifest.job_id}"].result(timeout=10)

            # One render, one artifact, every attempt bound to it.
            self.assertEqual(pipeline.return_value.run.call_count, 1)
            bound = {attempt["platform"]: attempt["artifact_id"]
                     for attempt in result["attempts"]}
            self.assertEqual(
                set(bound),
                {"youtube", "instagram", "tiktok", "twitter", "facebook"})
            self.assertEqual(len(set(bound.values())), 1)
            self.assertEqual(
                {attempt["group_id"] for attempt in result["attempts"]},
                {group_id})

    def test_each_platform_freezes_its_own_upload_slice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service = JobService(data_dir)
            self.addCleanup(service.close)
            manifest = _two_group_job(service, data_dir)

            with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline:
                pipeline.return_value.run.return_value = {
                    "YouTube": {"success": True, "result": "ok"},
                    "TikTok": {"success": True, "result": "ok"}}
                result = service.submit_upload(
                    manifest.job_id, ["youtube", "tiktok"])
                service._futures[f"upload:{manifest.job_id}"].result(timeout=10)

            snapshots = {attempt["platform"]: attempt["configuration_snapshot"]
                         for attempt in result["attempts"]}
            self.assertEqual(snapshots["youtube"]["content"]["title"], "Job title")
            self.assertEqual(
                snapshots["tiktok"]["platform_options"],
                {"tiktok_privacy_level": "SELF_ONLY"})
            # The two platforms are on different artifacts: the untouched source
            # for the group that skips conversion, the render for the other.
            bound = {attempt["platform"]: attempt["artifact_id"]
                     for attempt in result["attempts"]}
            self.assertNotEqual(bound["youtube"], bound["tiktok"])
            kinds = {platform: manifest.artifacts[artifact_id]["kind"]
                     for platform, artifact_id in bound.items()}
            self.assertEqual(kinds["youtube"], "source")
            self.assertEqual(kinds["tiktok"], "primary")

    def test_every_binding_of_one_submission_shares_one_progress_bar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service = JobService(data_dir)
            self.addCleanup(service.close)
            manifest = _two_group_job(service, data_dir)

            with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline:
                pipeline.return_value.run.return_value = {
                    "YouTube": {"success": True, "result": "ok"},
                    "TikTok": {"success": True, "result": "ok"}}
                service.submit_upload(manifest.job_id, ["youtube", "tiktok"])
                service._futures[f"upload:{manifest.job_id}"].result(timeout=10)

            # Two bindings, because the platforms differ in artifact. (Other calls
            # construct a pipeline for existing-post detection, which draws
            # nothing, so only the uploading ones carry a bar.)
            bar_calls = [call for call in pipeline.call_args_list
                         if call.kwargs.get("submission_progress") is not None]
            self.assertEqual(len(bar_calls), 2)
            # ...but the split stays a transport detail: one submission, one bar.
            bars = [call.kwargs["submission_progress"] for call in bar_calls]
            self.assertIs(bars[0], bars[1])

    def test_a_per_platform_upload_option_keeps_the_uploads_parallel(self):
        """One deliberate override must not serialize the whole submission."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = _reviewed_job(data_dir)
            self.addCleanup(service.close)
            # Every participating platform restates its registry default except
            # TikTok, so it is the only one whose frozen slice differs.
            manifest.configuration["platforms"] = {
                "youtube": {"category": "22", "privacy_status": "public"},
                "instagram": {"share_to_feed": True, "thumb_offset": 0},
                "tiktok": {"privacy_level": "SELF_ONLY"},
                "twitter": {"upload": {"skip": True}},
                "facebook": {"content_kind": "reel"}}
            manifest.save(service.jobs_dir)

            with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline:
                pipeline.return_value.run.return_value = {
                    name: {"success": True, "result": "ok"}
                    for name in ("YouTube", "Instagram", "TikTok", "Facebook")}
                result = service.submit_upload(manifest.job_id)
                service._futures[f"upload:{manifest.job_id}"].result(timeout=10)

            # All four ride ONE pipeline call, in parallel: the option is
            # already prefixed with its own platform's name, so it never needed
            # a call of its own.
            upload_calls = [call for call in pipeline.call_args_list
                            if call.kwargs.get("submission_progress") is not None]
            self.assertEqual(len(upload_calls), 1)
            self.assertEqual(
                sorted(name for name, enabled in upload_calls[0].kwargs.items()
                       if enabled is True),
                ["facebook", "instagram", "tiktok", "youtube"])
            # The override still reaches TikTok and only TikTok.
            sent = pipeline.return_value.run.call_args.kwargs
            self.assertEqual(sent["tiktok_privacy_level"], "SELF_ONLY")
            self.assertNotIn("youtube_privacy_level", sent)
            # ...and each attempt still records its OWN frozen slice, so the
            # merge never rewrites the configuration accepted for a platform.
            frozen = {attempt["platform"]: attempt["configuration_snapshot"][
                "platform_options"] for attempt in result["attempts"]}
            self.assertEqual(frozen["tiktok"],
                             {"tiktok_privacy_level": "SELF_ONLY"})
            self.assertEqual(frozen["youtube"], {})

    def test_the_submission_declares_every_platform_before_the_first_upload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service = JobService(data_dir)
            self.addCleanup(service.close)
            manifest = _two_group_job(service, data_dir)

            totals = []

            def _record_run(*_args, **_kwargs):
                # Snapshot the shared bar as each binding starts; the mocked
                # pipeline never reports a percent, so the declared total is
                # the only thing that ever sizes this bar.
                bar = pipeline.call_args_list[-1].kwargs["submission_progress"]
                totals.append((sorted(bar._percents), bar._bar.total))
                return {
                    "YouTube": {"success": True, "result": "ok"},
                    "TikTok": {"success": True, "result": "ok"}}

            with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline:
                pipeline.return_value.run.side_effect = _record_run
                service.submit_upload(manifest.job_id, ["youtube", "tiktok"])
                service._futures[f"upload:{manifest.job_id}"].result(timeout=10)

            # Two bindings, both already fully sized when each one started: the
            # total and the description cannot move once the second one begins.
            self.assertEqual(
                totals, [(["tiktok", "youtube"], 200)] * 2)

    def test_upload_draft_summary_reports_each_platform_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service = JobService(data_dir)
            self.addCleanup(service.close)
            manifest = _two_group_job(service, data_dir)
            manifest.configuration["platforms"]["twitter"] = {
                "upload": {"skip": True}}
            manifest.save(service.jobs_dir)

            summary = service.upload_draft_summary(manifest.job_id)
            # YouTube skips conversion but still uploads, as the 16:9 VOD.
            self.assertTrue(summary["youtube"]["participates"])
            self.assertTrue(summary["tiktok"]["participates"])
            self.assertFalse(summary["twitter"]["participates"])
            self.assertEqual(summary["youtube"]["kind"], "source")
            self.assertEqual(summary["tiktok"]["kind"], "vertical")
            self.assertNotEqual(
                summary["youtube"]["group_id"], summary["tiktok"]["group_id"])
            self.assertTrue(summary["youtube"]["conversion"]["skip"])
            self.assertFalse(summary["tiktok"]["conversion"]["skip"])
            self.assertEqual(
                summary["tiktok"]["upload"]["content"]["title"], "Job title")


if __name__ == "__main__":
    unittest.main()
