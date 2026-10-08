"""Tests for scheduling history filters and platform-side detection."""

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.job import JobManifest
from clipmorph.service import JobService, _parse_utc_timestamp


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


class RestartReArmSharedSliceTests(unittest.TestCase):
    """Re-arm groups scheduled attempts exactly like the live path does.

    The submission coalesces its pipeline calls by (artifact, shared upload
    slice) with each attempt's own ``{platform}``-prefixed options merged into
    the call. A restart must re-arm the timers from the SAME grouping: a
    per-platform override must not resurrect one sequential binding per
    whole-slice hash.
    """

    def _submit_scheduled_submission(self, data_dir: Path):
        """Submit a job whose whole upload defers an hour out via local timers.

        TikTok and Facebook each carry a flat override that differs from the
        registry default, so their whole-snapshot hashes differ from the other
        platforms' while their shared upload slices stay identical.
        """
        upload = _future_schedule()
        upload["schedule"]["mode"] = "local"
        service, manifest = _reviewed_job(data_dir, upload)
        manifest.configuration["platforms"] = {
            "youtube": {"category": "22", "privacy_status": "public"},
            "instagram": {"share_to_feed": True, "thumb_offset": 0},
            "tiktok": {"privacy_level": "SELF_ONLY"},
            "twitter": {"upload": {"skip": True}},
            "facebook": {"content_kind": "video"}}
        manifest.save(service.jobs_dir)

        with patch("clipmorph.upload_attempts.execute_upload_pipeline",
                   side_effect=_upload_results(
                       ["youtube", "instagram", "tiktok", "facebook"])), \
             patch.object(service, "_detect_existing_posts",
                          return_value=({}, [])):
            service.submit_upload(manifest.job_id, honor_schedule=True)
        return service, manifest.job_id

    def test_an_override_does_not_rearm_sequential_bindings(self):
        """The re-arm must carry one binding for tiktok AND facebook."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, job_id = self._submit_scheduled_submission(data_dir)
            try:
                with patch.object(service, "_schedule_attempts") as capture:
                    armed = service._arm_manifest_schedules(
                        service.get_job(job_id))

                self.assertEqual(armed, 4)
                # One timer call, and its binding covers the overrides in one
                # pipeline call instead of re-arming one binding per hash.
                self.assertEqual(len(capture.call_args_list), 1)
                call = capture.call_args_list[0]
                self.assertEqual(call.args[0], job_id)
                groups = call.args[1]
                self.assertEqual(len(groups), 1)
                binding = groups[0]
                self.assertEqual(sorted(binding["platforms"]),
                                 ["facebook", "instagram", "tiktok",
                                  "youtube"])
                options = binding["upload_config"]["platform_options"]
                self.assertEqual(options.get("tiktok_privacy_level"),
                                 "SELF_ONLY")
                self.assertEqual(options.get("facebook_content_kind"),
                                 "video")

                # Each attempt's OWN frozen snapshot survives the merge and
                # its scheduling fields are what the re-arm read.
                saved = service.get_job(job_id)
                frozen = {attempt["platform"]:
                          attempt["configuration_snapshot"][
                              "platform_options"]
                          for attempt in saved.upload_attempts}
                self.assertEqual(frozen["tiktok"],
                                 {"tiktok_privacy_level": "SELF_ONLY"})
                self.assertEqual(frozen["facebook"],
                                 {"facebook_content_kind": "video"})
                self.assertEqual(frozen["youtube"], {})
                self.assertEqual(frozen["instagram"], {})
                for attempt in saved.upload_attempts:
                    self.assertEqual(attempt["scheduled_via"], "local")
                    self.assertEqual(
                        call.args[2],
                        _parse_utc_timestamp(
                            attempt["scheduled_publish_at"]))
            finally:
                service.close()

    def test_a_different_unprefixed_slice_still_splits_the_rearm(self):
        """A retitled attempt splits into its own binding on the same timer.

        The retitled attempt shares artifact and stamp with the others, so the
        re-arm fires one _schedule_attempts call carrying BOTH bindings: the
        split survives at binding level (two pipeline calls from one timer).
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, job_id = self._submit_scheduled_submission(data_dir)
            try:
                saved = service.get_job(job_id)
                victim = next(attempt for attempt in saved.upload_attempts
                              if attempt["platform"] == "tiktok")
                victim["configuration_snapshot"]["content"] = dict(
                    victim["configuration_snapshot"].get("content") or {},
                    title="Retitled")
                saved.save(service.jobs_dir)
                neighbour_title = next(
                    attempt["configuration_snapshot"]["content"]["title"]
                    for attempt in saved.upload_attempts
                    if attempt["platform"] == "facebook")

                with patch.object(service, "_schedule_attempts") as capture:
                    armed = service._arm_manifest_schedules(
                        service.get_job(job_id))

                self.assertEqual(armed, 4)
                # One timer call for the shared stamp; the split lives in its
                # payload, which carries TWO bindings.
                self.assertEqual(len(capture.call_args_list), 1)
                call = capture.call_args_list[0]
                bindings = call.args[1]
                self.assertEqual(
                    {tuple(binding["platforms"]) for binding in bindings},
                    {("tiktok",), ("youtube", "instagram", "facebook")})
                retitled = next(binding for binding in bindings
                                if tuple(binding["platforms"]) == ("tiktok",))
                self.assertEqual(retitled["upload_config"]["content"]["title"],
                                 "Retitled")
                parallel = next(binding for binding in bindings
                                if "tiktok" not in binding["platforms"])
                self.assertEqual(parallel["upload_config"]["content"]["title"],
                                 neighbour_title)
            finally:
                service.close()

    def test_mixed_artifacts_share_one_rearm_timer(self):
        """Attempts on two artifacts at one stamp re-arm as one timer call."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, job_id = self._submit_scheduled_submission(data_dir)
            try:
                saved = service.get_job(job_id)
                render = Path(temp_dir) / "render.mp4"
                render.write_bytes(b"render")
                saved.record_artifact("conversion", render, service.jobs_dir)
                render_artifact_id = saved.current_artifact_id
                # Repoint two attempts' artifact_id to the new render artifact
                # using the sibling test's configuration_snapshot mutation
                # style; the other two keep the source artifact.
                for platform in ("tiktok", "facebook"):
                    attempt = next(item for item in saved.upload_attempts
                                   if item["platform"] == platform)
                    attempt["artifact_id"] = render_artifact_id
                saved.save(service.jobs_dir)

                with patch.object(service, "_schedule_attempts") as capture:
                    armed = service._arm_manifest_schedules(
                        service.get_job(job_id))

                self.assertEqual(armed, 4)
                # One timer call even though the submission is mixed: bindings
                # differed by artifact, not by stamp.
                self.assertEqual(len(capture.call_args_list), 1)
                call = capture.call_args_list[0]
                bindings = call.args[1]
                self.assertEqual(len(bindings), 2)
                # Each binding carries a distinct artifact's storage key.
                self.assertNotEqual(bindings[0]["artifact_key"],
                                    bindings[1]["artifact_key"])
                self.assertEqual(
                    {platform for binding in bindings
                     for platform in binding["platforms"]},
                    {"youtube", "instagram", "tiktok", "facebook"})
                stamp = next(attempt["scheduled_publish_at"]
                             for attempt in saved.upload_attempts)
                self.assertEqual(call.args[2], _parse_utc_timestamp(stamp))

                # The merge never rewrites the persisted snapshots: each
                # attempt's own frozen platform_options survive.
                frozen = {attempt["platform"]:
                          attempt["configuration_snapshot"][
                              "platform_options"]
                          for attempt in saved.upload_attempts}
                self.assertEqual(frozen["tiktok"],
                                 {"tiktok_privacy_level": "SELF_ONLY"})
                self.assertEqual(frozen["facebook"],
                                 {"facebook_content_kind": "video"})
                self.assertEqual(frozen["youtube"], {})
                self.assertEqual(frozen["instagram"], {})
            finally:
                service.close()


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
