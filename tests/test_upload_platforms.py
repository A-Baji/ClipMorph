import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from clipmorph.job import source_sha256
from clipmorph.policy import CAPABILITY_MATRIX, validate_artifact
from clipmorph.upload_pipeline import UploadPipeline
from clipmorph.upload_pipeline.platforms.base import BaseUploadPipeline
from clipmorph.upload_pipeline.platforms.youtube import YouTubeUploadPipeline


class UploadPipelineTests(unittest.TestCase):
    def test_tiktok_code_verifier_is_alphanumeric_only(self):
        """TikTok rejects the punctuation-bearing PKCE verifier alphabet.

        Its token endpoint answered "Code verifier or code challenge is
        invalid" for a verifier drawn from the full unreserved set, which is
        why the TikTok attempt never progressed to an upload call; the
        alphanumeric subset is interoperable.
        """
        from clipmorph.upload_pipeline.platforms.tiktok import (
            TikTokUploadPipeline,
        )
        verifier = TikTokUploadPipeline._generate_code_verifier(MagicMock())
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9]{64}", verifier))

    def test_initialization_failure_remains_in_results(self):
        with patch("clipmorph.upload_pipeline.YouTubeUploadPipeline",
                   side_effect=ValueError("missing credentials")):
            pipeline = UploadPipeline(youtube=True)

        results = pipeline.run("video.mp4", "A title")
        self.assertIn("YouTube", results)
        self.assertFalse(results["YouTube"]["success"])
        self.assertIn("missing credentials", results["YouTube"]["error"])

    def test_interactive_authentication_is_prepared_before_parallel_uploads(self):
        pipeline = UploadPipeline()
        tiktok = MagicMock()
        tiktok.access_token = None
        pipeline.enabled_platforms = {"TikTok": tiktok}
        results = {}

        pipeline._prepare_interactive_authentication(results)

        tiktok._refresh_access_token.assert_called_once_with()
        self.assertEqual(results, {})

    def test_twitter_is_prepared_before_parallel_uploads(self):
        pipeline = UploadPipeline()
        twitter = MagicMock()
        twitter.oauth_session = None
        pipeline.enabled_platforms = {"Twitter": twitter}
        results = {}

        pipeline._prepare_interactive_authentication(results)

        twitter._authenticate.assert_called_once_with()
        self.assertEqual(results, {})

    def test_twitter_pre_auth_failure_removes_platform_from_run(self):
        pipeline = UploadPipeline()
        twitter = MagicMock()
        twitter.oauth_session = None
        twitter._authenticate.side_effect = ValueError("auth failed")
        pipeline.enabled_platforms = {"Twitter": twitter}
        results = {}

        pipeline._prepare_interactive_authentication(results)

        self.assertNotIn("Twitter", pipeline.enabled_platforms)
        self.assertIn("auth failed", results["Twitter"]["error"])

    def test_platform_policy_blocks_known_incompatible_artifact(self):
        decision = validate_artifact("instagram", {
            "duration": 2,
            "width": 1080,
            "height": 1920,
            "video_codec": "h264",
            "file_size": 1000,
        }, {"title": "caption"})
        self.assertFalse(decision.allowed)
        self.assertIn("duration", decision.blockers[0])

    def test_platform_policy_warns_on_unknown_rules_without_blocking(self):
        decision = validate_artifact("tiktok", {"duration": 10}, {"title": "caption"})
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.warnings)


class CommonParameterMappingTests(unittest.TestCase):
    """The wrapper composes content, folds defaults, then applies overrides."""

    def _upload_kwargs(self, platform_name, title, **kwargs):
        adapter = MagicMock()
        adapter.credentials = True
        pipeline = UploadPipeline()
        pipeline.enabled_platforms = {platform_name: adapter}
        pipeline.run("video.mp4", title, **kwargs)
        return adapter.run.call_args.kwargs

    def test_composed_content_and_platform_defaults_reach_the_adapter(self):
        sent = self._upload_kwargs(
            "YouTube", "Boss fight", description="No healing",
            tags=["gaming", "boss fight"])

        self.assertEqual(sent["title"], "Boss fight")
        self.assertEqual(sent["description"], "No healing")
        self.assertEqual(sent["keywords"], ["gaming", "boss fight"])
        self.assertEqual(sent["category"], "22")
        self.assertEqual(sent["privacy_status"], "public")

    def test_combined_platforms_receive_one_prepared_field(self):
        sent = self._upload_kwargs("Twitter", "Boss fight",
                                   description="No healing", tags=["gaming"])

        self.assertEqual(list(sent), ["video_path", "tweet_text"])
        self.assertEqual(sent["tweet_text"],
                         "Boss fight\n\nNo healing\n\n#gaming")
        self.assertLessEqual(
            len(sent["tweet_text"]), CAPABILITY_MATRIX["twitter"].caption_limit)

    def test_facebook_receives_the_composed_description_and_kind_default(self):
        sent = self._upload_kwargs("Facebook", "Boss fight",
                                   description="No healing", tags=["gaming"])

        self.assertEqual(set(sent) - {"video_path"},
                         {"description", "content_kind"})
        self.assertEqual(sent["description"],
                         "Boss fight\n\nNo healing\n\n#gaming")
        self.assertEqual(sent["content_kind"], "reel")

    def test_facebook_content_kind_override_wins(self):
        sent = self._upload_kwargs("Facebook", "Boss fight",
                                   facebook_content_kind="video")

        self.assertEqual(sent["content_kind"], "video")

    def test_platform_overrides_win_over_composed_values(self):
        sent = self._upload_kwargs(
            "Instagram", "Boss fight", tags=["gaming"],
            instagram_share_to_feed=False, instagram_thumb_offset=1200)

        self.assertEqual(sent["caption"], "Boss fight\n\n#gaming")
        self.assertEqual(sent["share_to_feed"], False)
        self.assertEqual(sent["thumb_offset"], 1200)

    def test_overrides_never_leak_across_platforms(self):
        sent = self._upload_kwargs("Instagram", "Boss fight",
                                   youtube_category="20",
                                   tiktok_privacy_level="SELF_ONLY")

        self.assertEqual(set(sent) - {"video_path"},
                         {"caption", "share_to_feed", "thumb_offset"})


class YouTubeNativeSchedulingTests(unittest.TestCase):
    """The scheduled insert body, and the unchanged unscheduled one."""

    def setUp(self):
        # MediaFileUpload holds the file open, so cleanup must tolerate it.
        self._temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._temp.cleanup)
        self.video = Path(self._temp.name) / "clip.mp4"
        self.video.write_bytes(b"video")
        self.adapter = YouTubeUploadPipeline(google_client_id="id",
                                             google_client_secret="secret")
        self.adapter.credentials = object()
        self.adapter.youtube_service = MagicMock()
        # A plain mapping is what a real execute() hands back; the retry
        # helper inspects the response for HTTP-shaped attributes.
        self.adapter.youtube_service.videos.return_value.delete.return_value \
            .execute.return_value = {}

    def _run(self, **kwargs):
        """Run the adapter with the transfer stubbed, returning the insert call."""
        with patch.object(self.adapter, "_validate_video_file",
                          return_value=1024), patch.object(
                self.adapter, "_execute_resumable_upload",
                return_value="post-1"):
            self.adapter.run(str(self.video), "Boss fight",
                             description="No healing", keywords=["gaming"],
                             category="22", **kwargs)
        return self.adapter.youtube_service.videos().insert.call_args

    def test_scheduled_insert_carries_publish_at_private_and_notify(self):
        call = self._run(privacy_status="public",
                         scheduled_publish_at="2026-10-01T12:30:00+00:00",
                         notify_subscribers=True)

        body = call.kwargs["body"]
        # A scheduled upload is only accepted as a private video, so the
        # request carries the future instant and drops public visibility.
        self.assertEqual(body["status"],
                         {"privacyStatus": "private",
                          "publishAt": "2026-10-01T12:30:00Z"})
        self.assertTrue(call.kwargs["notifySubscribers"])
        self.assertEqual(call.kwargs["part"], "snippet,status")

    def test_scheduled_insert_can_withhold_the_subscriber_notification(self):
        call = self._run(scheduled_publish_at="2026-10-01T12:30:00+00:00",
                         notify_subscribers=False)

        self.assertFalse(call.kwargs["notifySubscribers"])

    def test_unscheduled_insert_body_is_unchanged(self):
        call = self._run()

        self.assertEqual(call.kwargs["body"], {
            "snippet": {"title": "Boss fight", "description": "No healing\n\n"
                        "clip:" + source_sha256(self.video),
                        "tags": ["gaming"], "categoryId": "22"},
            "status": {"privacyStatus": "public"},
        })
        self.assertNotIn("notifySubscribers", call.kwargs)
        self.assertEqual(call.kwargs["part"], "snippet,status")

    def test_publish_at_is_normalized_to_utc(self):
        call = self._run(scheduled_publish_at="2026-10-01T08:30:00-04:00")

        self.assertEqual(call.kwargs["body"]["status"]["publishAt"],
                         "2026-10-01T12:30:00Z")

    def test_naive_publish_at_fails_before_an_upload_session_is_opened(self):
        with self.assertRaisesRegex(ValueError, "must include a UTC offset"):
            self.adapter.run(str(self.video), "Boss fight",
                             scheduled_publish_at="2026-10-01T12:30:00")

        self.adapter.youtube_service.videos().insert.assert_not_called()

    def test_cancel_scheduled_post_deletes_the_future_post(self):
        self.adapter.cancel_scheduled_post("post-1")

        self.adapter.youtube_service.videos.return_value.delete \
            .assert_called_once_with(id="post-1")


class _FakeAdapter(BaseUploadPipeline):
    """A minimal adapter that walks its allocation steps during run."""

    def __init__(self, allocations):
        self.progress_allocations = allocations
        self.progress_bar = None
        self.platform_name = "TikTok"
        # Prevent the orchestrator's interactive-auth pass from refreshing.
        self.access_token = "fake"
        super().__init__()

    def run(self, video_path, **kwargs):
        with self._progress_context(
                sum(self.progress_allocations.values()), "Starting upload"):
            for step in self.progress_allocations:
                self._update_progress(step)
        return "fake-result"


class UploadProgressCallbackTests(unittest.TestCase):
    def _run_with_callback(self, allocations):
        updates = []
        pipeline = UploadPipeline(
            progress_callback=lambda name, percent: updates.append(
                (name, percent)))
        pipeline.enabled_platforms = {"TikTok": _FakeAdapter(allocations)}
        pipeline.run("video.mp4", "title")
        return updates

    def test_callback_receives_ordered_percent_updates(self):
        updates = self._run_with_callback(
            {"step_a": 25, "step_b": 50, "step_c": 25})
        self.assertEqual(updates, [
            ("TikTok", 25), ("TikTok", 75), ("TikTok", 100)])

    def test_normalization_pins_allocations_sum_to_90(self):
        updates = self._run_with_callback({"step_a": 30, "step_b": 60})
        self.assertEqual(updates, [("TikTok", 33), ("TikTok", 100)])

    def test_no_callback_by_default_keeps_cli_behavior(self):
        pipeline = UploadPipeline()
        pipeline.enabled_platforms = {
            "TikTok": _FakeAdapter({"step_a": 25, "step_b": 50, "step_c": 25})}
        results = pipeline.run("video.mp4", "title")
        self.assertTrue(results["TikTok"]["success"])

    def test_callback_does_not_suppress_cli_progress_bar(self):
        # A caller callback only records percents; it draws nothing, so a
        # single-platform run still gets the adapter's own bar.
        with patch("clipmorph.upload_pipeline.platforms.base.tqdm") as tqdm:
            updates = []
            pipeline = UploadPipeline(
                progress_callback=lambda name, percent: updates.append(
                    (name, percent)))
            adapter = _FakeAdapter({"step_a": 50, "step_b": 50})
            pipeline.enabled_platforms = {"TikTok": adapter}
            pipeline.run("video.mp4", "title")
        tqdm.assert_called_once()
        self.assertEqual(updates, [("TikTok", 50), ("TikTok", 100)])

    def test_service_progress_callback_keeps_the_combined_cli_bar(self):
        # The real wiring: JobService always installs a progress callback to
        # record live percents, so a callback must not disable CLI progress.
        with patch("clipmorph.upload_pipeline.tqdm") as orchestrator_tqdm, \
                patch("clipmorph.upload_pipeline.platforms.base.tqdm"
                      ) as adapter_tqdm:
            updates = []
            pipeline = UploadPipeline(
                progress_callback=lambda name, percent: updates.append(
                    (name, percent)))
            tiktok = _FakeAdapter({"step_a": 25, "step_b": 50, "step_c": 25})
            twitter = _FakeAdapter({"step_a": 25, "step_b": 50, "step_c": 25})
            twitter.platform_name = "Twitter"
            twitter.oauth_session = object()
            pipeline.enabled_platforms = {"TikTok": tiktok, "Twitter": twitter}
            pipeline.run("video.mp4", "title")

        orchestrator_tqdm.assert_called_once()
        adapter_tqdm.assert_not_called()
        self.assertTrue(tiktok._suppress_cli_progress)
        self.assertTrue(twitter._suppress_cli_progress)
        # The caller's callback still receives every platform's percents.
        self.assertIn(("TikTok", 100), updates)
        self.assertIn(("Twitter", 100), updates)
        # ...and the shared bar still advanced 100% per platform.
        update_totals = sum(
            sum(call.args) for call in
            orchestrator_tqdm.return_value.update.call_args_list)
        self.assertEqual(update_totals, 200)

    def test_interpolated_progress_reaches_the_caller_without_a_bar(self):
        # The adapters' upload/processing loops interpolate through
        # _advance_progress. When the orchestrator owns the combined bar the
        # adapter has no bar of its own, so writing to self.progress_bar
        # directly silently dropped every intermediate update and the shared
        # bar froze at the last step boundary.
        adapter = _FakeAdapter({"step_a": 20, "step_b": 80})
        updates = []
        adapter.progress_callback = updates.append

        adapter._update_progress("step_a")  # 20% reported, no bar
        for target in (40, 60, 80):  # interpolated during the upload
            adapter._advance_progress(target)

        self.assertEqual(updates, [20, 40, 60, 80])
        self.assertEqual(adapter._percent, 80)

        # Completion reaches the caller too, so the bar can finish at 100.
        adapter._complete_progress_bar(True)
        self.assertEqual(updates[-1], 100)

    def test_advance_progress_is_monotonic_and_clamped(self):
        adapter = _FakeAdapter({"step_a": 100})
        adapter.progress_callback = lambda percent: None
        adapter._advance_progress(60)
        adapter._advance_progress(30)  # below what was reported: ignored
        adapter._advance_progress(500)  # clamped
        self.assertEqual(adapter._percent, 100)

    def test_bar_write_falls_back_to_logging_without_a_bar(self):
        adapter = _FakeAdapter({"step_a": 100})
        with patch("clipmorph.upload_pipeline.platforms.base.logging"
                   ) as logging_mock:
            adapter._bar_write("[Instagram] No access token found.")
        # A suppressed bar must not raise AttributeError on progress_bar.write.
        logging_mock.info.assert_called_once_with(
            "[Instagram] No access token found.")

    def test_combined_bar_is_disabled_on_a_non_terminal(self):
        # disable=None keeps the bar out of server logs and redirected
        # output, where the caller's callback is the only progress surface.
        with patch("clipmorph.upload_pipeline.tqdm") as orchestrator_tqdm:
            pipeline = UploadPipeline()
            tiktok = _FakeAdapter({"step_a": 50, "step_b": 50})
            twitter = _FakeAdapter({"step_a": 50, "step_b": 50})
            twitter.platform_name = "Twitter"
            twitter.oauth_session = object()
            pipeline.enabled_platforms = {"TikTok": tiktok, "Twitter": twitter}
            pipeline.run("video.mp4", "title")
        self.assertIs(orchestrator_tqdm.call_args.kwargs["disable"], None)

    def test_multi_platform_uses_one_combined_progress_bar(self):
        with patch("clipmorph.upload_pipeline.tqdm") as orchestrator_tqdm, \
                patch("clipmorph.upload_pipeline.platforms.base.tqdm"
                      ) as adapter_tqdm:
            pipeline = UploadPipeline()
            tiktok = _FakeAdapter({"step_a": 25, "step_b": 50, "step_c": 25})
            twitter = _FakeAdapter({"step_a": 25, "step_b": 50, "step_c": 25})
            twitter.platform_name = "Twitter"
            # Give the fakes enough runtime state to skip pre-authentication.
            twitter.oauth_session = object()
            tiktok.access_token = "fake"
            pipeline.enabled_platforms = {"TikTok": tiktok, "Twitter": twitter}
            pipeline.run("video.mp4", "title")

        # ONE orchestrator bar, no per-adapter bars.
        orchestrator_tqdm.assert_called_once()
        adapter_tqdm.assert_not_called()
        self.assertIsNotNone(tiktok.progress_callback)
        self.assertIsNotNone(twitter.progress_callback)

        # Each platform contributes exactly 100 across the shared bar:
        # step percents 25/75/100 mean deltas 25, 50, 50.
        update_totals = sum(
            sum(call.args) for call in
            orchestrator_tqdm.return_value.update.call_args_list)
        self.assertEqual(update_totals, 200)

    def test_single_platform_without_callback_keeps_cli_bar(self):
        with patch("clipmorph.upload_pipeline.platforms.base.tqdm") as tqdm:
            pipeline = UploadPipeline()
            adapter = _FakeAdapter({"step_a": 50, "step_b": 50})
            pipeline.enabled_platforms = {"TikTok": adapter}
            pipeline.run("video.mp4", "title")
        tqdm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
