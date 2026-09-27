"""Startup reconciliation of checkpoints interrupted by a process restart."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from clipmorph.job import JobManifest
from clipmorph.service import INTERRUPTED_ERROR, JobService


def _future_iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _create_manifest(data_dir: Path, *, conversion_skip: bool = True,
                     name: str = "clip.mp4") -> tuple[JobManifest, Path]:
    """Persist one manifest plus a real artifact, returning it and its jobs dir."""
    source_dir = data_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / name
    source.write_bytes(b"video")
    jobs_dir = data_dir / "jobs"
    configuration: dict = {"general": {"source": name}}
    if conversion_skip:
        configuration["conversion"] = {"skip": True, "subtitles": {"skip": True}}
    manifest = JobManifest.create(str(source), configuration, jobs_dir)
    manifest.record_artifact("source", source, jobs_dir)
    return manifest, jobs_dir


def _start_stage(manifest: JobManifest, jobs_dir: Path, stage: str) -> None:
    """Put one checkpoint in the running state a crash would leave behind."""
    checkpoint = manifest.checkpoints[stage]
    if checkpoint["status"] == "pending" and stage == "upload":
        # Upload only reaches running through its review gate.
        manifest.transition_checkpoint(
            stage, "awaiting_review", checkpoint["revision"], jobs_dir)
        checkpoint = manifest.checkpoints[stage]
    manifest.transition_checkpoint(
        stage, "running", checkpoint["revision"], jobs_dir)
    manifest.set_status("running", jobs_dir)


def _add_pending_attempt(manifest: JobManifest, jobs_dir: Path,
                         publish_at: str | None) -> None:
    """Append one pending upload attempt in the state a crash would leave."""
    artifact = manifest.artifacts[manifest.current_artifact_id]
    attempt = {
        "attempt_id": "attempt-1",
        "platform": "youtube",
        "artifact_id": artifact["id"],
        "artifact_hash": artifact["sha256"],
        "configuration_snapshot": {"platforms": {"include": ["youtube"]}},
        "configuration_hash": "configuration-hash",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None,
        "status": "pending",
        "result": None,
    }
    if publish_at is not None:
        attempt["scheduled"] = True
        attempt["scheduled_publish_at"] = publish_at
    manifest.upload_attempts.append(attempt)
    manifest.checkpoints["upload"]["references"]["attempt_ids"] = [
        attempt["attempt_id"]]
    manifest.save(jobs_dir)


class StartupReconciliationTests(unittest.TestCase):
    def _heal(self, data_dir: Path, job_id: str) -> JobManifest:
        service = JobService(data_dir)
        try:
            return service.get_job(job_id)
        finally:
            service.close()

    def test_running_transcript_checkpoint_fails_with_the_interrupted_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir, conversion_skip=False)
            _start_stage(manifest, jobs_dir, "transcript")

            healed = self._heal(data_dir, manifest.job_id)

            self.assertEqual(healed.checkpoints["transcript"]["status"], "failed")
            self.assertEqual(healed.checkpoints["transcript"]["error"]["code"],
                             INTERRUPTED_ERROR["code"])
            self.assertEqual(healed.checkpoints["transcript"]["error"]["message"],
                             INTERRUPTED_ERROR["message"])
            self.assertTrue(healed.checkpoints["transcript"]["error"]["retryable"])
            self.assertEqual(healed.status, "failed")

    def test_running_conversion_checkpoint_fails_with_the_interrupted_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir, conversion_skip=False)
            _start_stage(manifest, jobs_dir, "conversion")

            healed = self._heal(data_dir, manifest.job_id)

            self.assertEqual(healed.checkpoints["conversion"]["status"], "failed")
            self.assertEqual(healed.checkpoints["conversion"]["error"]["code"],
                             "interrupted_by_restart")
            self.assertEqual(healed.status, "failed")

    def test_scheduled_upload_attempts_are_left_running_for_re_arm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir)
            publish_at = _future_iso(hours=2)
            _add_pending_attempt(manifest, jobs_dir, publish_at)
            _start_stage(manifest, jobs_dir, "upload")

            service = JobService(data_dir)
            try:
                healed = service.get_job(manifest.job_id)
                armed = {key: len(value)
                         for key, value in service._scheduled_timers.items()}
            finally:
                service.close()

            self.assertEqual(healed.checkpoints["upload"]["status"], "running")
            self.assertEqual(healed.upload_attempts[0]["status"], "pending")
            self.assertEqual(healed.upload_attempts[0]["scheduled_publish_at"],
                             publish_at)
            # Reaching the re-arm scan at all proves reconciliation skipped it.
            self.assertEqual(armed, {f"upload:{manifest.job_id}": 1})

    def test_unscheduled_pending_upload_attempts_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir)
            _add_pending_attempt(manifest, jobs_dir, None)
            _start_stage(manifest, jobs_dir, "upload")

            service = JobService(data_dir)
            try:
                healed = service.get_job(manifest.job_id)
                armed = dict(service._scheduled_timers)
            finally:
                service.close()

            self.assertEqual(healed.checkpoints["upload"]["status"], "failed")
            self.assertEqual(healed.checkpoints["upload"]["error"]["code"],
                             "interrupted_by_restart")
            self.assertEqual(healed.upload_attempts[0]["status"], "pending")
            self.assertEqual(armed, {})

    def test_upload_with_a_past_schedule_is_treated_as_a_real_stall(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir)
            _add_pending_attempt(manifest, jobs_dir, _future_iso(minutes=-5))
            _start_stage(manifest, jobs_dir, "upload")

            healed = self._heal(data_dir, manifest.job_id)

            self.assertEqual(healed.checkpoints["upload"]["status"], "failed")

    def test_running_manifest_with_terminal_checkpoints_rebuilds_derived_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir)
            manifest.transition_checkpoint(
                "upload", "skipped", manifest.checkpoints["upload"]["revision"],
                jobs_dir)
            manifest.set_status("running", jobs_dir)

            healed = self._heal(data_dir, manifest.job_id)

            self.assertEqual(healed.status, "completed")
            self.assertTrue(all(
                checkpoint["status"] in {"skipped", "completed", "failed",
                                         "cancelled"}
                for checkpoint in healed.checkpoints.values()))

    def test_queued_manifests_are_left_untouched(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir, conversion_skip=False)
            manifest.set_status("queued", jobs_dir)
            before = manifest.updated_at

            healed = self._heal(data_dir, manifest.job_id)

            self.assertEqual(healed.status, "queued")
            self.assertEqual(healed.updated_at, before)
            self.assertEqual(healed.checkpoints["transcript"]["status"], "pending")

    def test_unusable_manifest_is_skipped_without_raising(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            broken = data_dir / "jobs" / "broken"
            broken.mkdir(parents=True)
            (broken / "manifest.json").write_text("{not json", encoding="utf-8")
            incomplete = data_dir / "jobs" / "incomplete"
            incomplete.mkdir(parents=True)
            (incomplete / "manifest.json").write_text(
                json.dumps({"schema_version": 2, "job_id": "incomplete"}),
                encoding="utf-8")
            legacy = data_dir / "jobs" / "legacy"
            legacy.mkdir(parents=True)
            (legacy / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "job_id": "legacy"}),
                encoding="utf-8")
            manifest, jobs_dir = _create_manifest(data_dir, conversion_skip=False)
            _start_stage(manifest, jobs_dir, "transcript")

            healed = self._heal(data_dir, manifest.job_id)

            self.assertEqual(healed.checkpoints["transcript"]["status"], "failed")
            self.assertTrue((broken / "manifest.json").exists())

    def test_reconciliation_is_idempotent_across_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir, conversion_skip=False)
            _start_stage(manifest, jobs_dir, "transcript")

            first = self._heal(data_dir, manifest.job_id)
            second = self._heal(data_dir, manifest.job_id)

            self.assertEqual(second.status, first.status)
            self.assertEqual(second.checkpoints["transcript"]["revision"],
                             first.checkpoints["transcript"]["revision"])
            self.assertEqual(second.updated_at, first.updated_at)

    def test_healed_manifest_can_be_resumed_from_the_failed_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest, jobs_dir = _create_manifest(data_dir, conversion_skip=False)
            _start_stage(manifest, jobs_dir, "transcript")
            self._heal(data_dir, manifest.job_id)

            service = JobService(data_dir)
            try:
                healed = service.get_job(manifest.job_id)
                # failed -> pending is the existing recovery transition.
                healed.transition_checkpoint(
                    "transcript", "pending",
                    healed.checkpoints["transcript"]["revision"], jobs_dir)
                requeued = service.get_job(manifest.job_id)
            finally:
                service.close()

            self.assertEqual(requeued.checkpoints["transcript"]["status"], "pending")
            self.assertEqual(requeued.status, "queued")


if __name__ == "__main__":
    unittest.main()
