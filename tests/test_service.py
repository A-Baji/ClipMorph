from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.job import JobManifest
from clipmorph.service import JobService


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
                self.assertEqual(attempt["status"], "pending")
                self.assertTrue(attempt["scheduled"])
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
                        attempt["artifact_id"]]["path"],
                    {"platforms": {"include": ["youtube"]}}, ["youtube"])

            saved = service.get_job(manifest.job_id)
            self.assertEqual(pipeline.call_count, 1)
            self.assertEqual(
                pipeline.call_args.args[0], ["youtube"])
            self.assertEqual(saved.upload_attempts[0]["status"], "completed")
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
                "pending")

    def test_retry_of_a_scheduled_attempt_runs_immediately(self):
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
            attempt = service.get_job(manifest.job_id).upload_attempts[0]
            service._run_upload_attempts(
                manifest.job_id, [attempt["attempt_id"]],
                service.get_job(manifest.job_id).artifacts[
                    attempt["artifact_id"]]["path"],
                {"platforms": {"include": ["youtube"]}}, ["youtube"])
            failed = service.get_job(manifest.job_id).upload_attempts[0]
            failed["status"] = "failed"
            service.get_job(manifest.job_id).save(service.jobs_dir)

            with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                       side_effect=_upload_results(["youtube"])) as pipeline:
                retried = service.retry_upload(
                    manifest.job_id, "youtube", failed["attempt_id"])

            pipeline.assert_called_once()
            self.assertFalse(retried["scheduled"])
            self.assertNotIn("scheduled", retried["attempts"][0])
            self.assertEqual(retried["attempts"][0]["retry_of"],
                             failed["attempt_id"])

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
            self.assertEqual(healed.upload_attempts[0]["status"], "pending")
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
            self.assertFalse(discarded.upload_attempts[0]["scheduled"])
            self.assertNotIn("scheduled_publish_at",
                             discarded.upload_attempts[0])

            second = service.submit_upload(
                manifest.job_id, ["youtube"],
                configuration_snapshot={
                    "platforms": {"include": ["youtube"]},
                    "schedule": {"publish_at": publish_at}})

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
            self.assertFalse(healed.upload_attempts[0]["scheduled"])

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
            self.assertFalse(superseded.upload_attempts[0]["scheduled"])
            # A stale upload checkpoint cannot be finalized by a stray timer,
            # so the unmarked attempt also fails the startup re-arm scan.
            self.assertFalse(service._upload_awaits_schedule(superseded))
            self.assertEqual(service.discard_scheduled_uploads(manifest.job_id), 0)


if __name__ == "__main__":
    unittest.main()
