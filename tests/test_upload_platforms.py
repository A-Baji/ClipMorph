import logging
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
from clipmorph.upload_pipeline.progress import SubmissionProgress


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


class _FakeBar:
    """A tqdm stand-in recording exactly what it was told."""

    def __init__(self, **kwargs):
        self.total = kwargs.get("total")
        self.disable = False
        self.n = 0
        self.updates = []
        self.postfixes = []
        self.descriptions = []
        self.messages = []
        self.closed = False

    def update(self, delta):
        self.n += delta
        self.updates.append(delta)

    def set_postfix_str(self, text):
        self.postfixes.append(text)

    def set_description(self, text):
        self.descriptions.append(text)

    def write(self, message):
        self.messages.append(message)

    def refresh(self):
        pass

    def close(self):
        self.closed = True


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
        with patch("clipmorph.upload_pipeline.progress.tqdm") as orchestrator_tqdm, \
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

    def test_completion_fills_a_bar_that_opened_after_an_early_step(self):
        # The orchestrator's interactive-auth pass runs before the upload opens
        # a bar, so TikTok's "authenticate" step counted into _progress_seen
        # without moving the bar. Completion must still reach 100% instead of
        # announcing "Upload complete" over a bar frozen short of it.
        adapter = _FakeAdapter({"authenticate": 5, "video": 95})
        bar = _FakeBar(total=100)
        adapter._update_progress("authenticate")  # no bar yet
        adapter.progress_bar = bar
        adapter._update_progress("video")
        self.assertEqual(bar.n, 95)

        adapter._complete_progress_bar(True)
        self.assertEqual(bar.n, 100)
        self.assertEqual(bar.descriptions[-1], "[TikTok] Upload complete")

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
        with patch("clipmorph.upload_pipeline.progress.tqdm") as orchestrator_tqdm:
            pipeline = UploadPipeline()
            tiktok = _FakeAdapter({"step_a": 50, "step_b": 50})
            twitter = _FakeAdapter({"step_a": 50, "step_b": 50})
            twitter.platform_name = "Twitter"
            twitter.oauth_session = object()
            pipeline.enabled_platforms = {"TikTok": tiktok, "Twitter": twitter}
            pipeline.run("video.mp4", "title")
        self.assertIs(orchestrator_tqdm.call_args.kwargs["disable"], None)

    def test_multi_platform_uses_one_combined_progress_bar(self):
        with patch("clipmorph.upload_pipeline.progress.tqdm") as orchestrator_tqdm, \
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


class SubmissionProgressBarTests(unittest.TestCase):
    """One bar per submission, however the bindings split.

    A submission whose platforms freeze different upload slices runs several
    pipeline calls. That split is a transport detail, so every call reports into
    the one bar the submission owns instead of drawing a bar of its own.
    """

    def _bars(self):
        """Patch the bar factory, recording every bar it hands out."""
        created: list[_FakeBar] = []

        def factory(**kwargs):
            bar = _FakeBar(**kwargs)
            created.append(bar)
            return bar

        return created, patch("clipmorph.upload_pipeline.progress.tqdm",
                              side_effect=factory)

    def _run_binding(self, platform_name, allocations, progress,
                     progress_callback=None):
        adapter = _FakeAdapter(allocations)
        adapter.platform_name = platform_name
        # Runtime state the orchestrator needs to skip its interactive-auth pass.
        adapter.credentials = object()
        adapter.oauth_session = object()
        adapter.access_token = "fake"
        pipeline = UploadPipeline(submission_progress=progress,
                                  progress_callback=progress_callback)
        pipeline.enabled_platforms = {platform_name: adapter}
        pipeline.run("video.mp4", "title")
        return adapter

    def test_two_pipeline_calls_share_one_bar(self):
        created, bar_patch = self._bars()
        with bar_patch, patch("clipmorph.upload_pipeline.platforms.base.tqdm"
                              ) as adapter_tqdm:
            progress = SubmissionProgress(["YouTube", "TikTok"])
            self._run_binding("YouTube", {"a": 50, "b": 50}, progress)
            self._run_binding("TikTok", {"a": 25, "b": 75}, progress)

        # One bar for the submission, and neither binding drew one of its own.
        self.assertEqual(len(created), 1)
        adapter_tqdm.assert_not_called()
        # Both platforms were declared before the first binding ran, so the
        # second binding's platform filled its own slot rather than opening a
        # new one.
        self.assertEqual(created[0].total, 200)
        self.assertEqual(created[0].n, 200)

    def test_a_later_binding_never_moves_the_total_or_the_description(self):
        # A bar that widens mid-run reads as a bug: it reaches 100%, sits
        # there, then a new platform appears and the same bar starts over.
        created, bar_patch = self._bars()
        with bar_patch:
            progress = SubmissionProgress(["YouTube", "TikTok"])
            self._run_binding("YouTube", {"a": 50, "b": 50}, progress)

            self.assertEqual(created[0].total, 200)
            self.assertEqual(created[0].descriptions, ["Uploading 2 platforms"])
            # The platform whose binding runs later is already visible as
            # queued rather than appearing once the bar reached 100%.
            self.assertEqual(created[0].postfixes[-1],
                             "YouTube 100% | TikTok 0%")

            self._run_binding("TikTok", {"a": 25, "b": 75}, progress)

        self.assertEqual(created[0].total, 200)
        self.assertEqual(created[0].n, 200)
        self.assertEqual(created[0].descriptions, ["Uploading 2 platforms"])
        self.assertEqual(created[0].postfixes[-1],
                         "YouTube 100% | TikTok 100%")

    def test_a_single_platform_call_still_reports_into_the_shared_bar(self):
        created, bar_patch = self._bars()
        with bar_patch, patch("clipmorph.upload_pipeline.platforms.base.tqdm"
                              ) as adapter_tqdm:
            self._run_binding("TikTok", {"a": 60, "b": 40},
                              SubmissionProgress())

        self.assertEqual(len(created), 1)
        adapter_tqdm.assert_not_called()
        self.assertEqual(created[0].total, 100)
        self.assertEqual(created[0].n, 100)

    def test_the_postfix_lists_every_platform(self):
        # The submission declares lowercase names while an adapter reports its
        # own spelling, so both must land on one slot under one label.
        created, bar_patch = self._bars()
        with bar_patch:
            progress = SubmissionProgress(["youtube", "twitter", "tiktok"])
            self._run_binding("YouTube", {"a": 50, "b": 50}, progress)
            self._run_binding("Twitter", {"a": 100}, progress)
            self._run_binding("TikTok", {"a": 25, "b": 75}, progress)

        self.assertEqual(created[0].total, 300)
        self.assertEqual(created[0].postfixes[-1],
                         "YouTube 100% | Twitter/X 100% | TikTok 100%")

    def test_outcomes_print_above_the_shared_bar(self):
        created, bar_patch = self._bars()
        with bar_patch:
            self._run_binding("TikTok", {"a": 100}, SubmissionProgress())
        self.assertEqual(created[0].messages, ["TikTok upload completed"])

    def test_a_failed_platform_is_announced_through_the_bar(self):
        class _FailingAdapter(_FakeAdapter):
            def run(self, video_path, **kwargs):
                raise RuntimeError("platform is down")

        created, bar_patch = self._bars()
        with bar_patch:
            adapter = _FailingAdapter({"a": 100})
            adapter.platform_name = "TikTok"
            adapter.access_token = "fake"
            pipeline = UploadPipeline(
                submission_progress=SubmissionProgress())
            pipeline.enabled_platforms = {"TikTok": adapter}
            pipeline.run("video.mp4", "title")
        self.assertEqual(created[0].messages,
                         ["TikTok upload failed: platform is down"])

    def test_a_disabled_bar_keeps_messages_in_the_log_stream(self):
        # tqdm.write prints to stderr even on a bar it disabled, which would put
        # progress chatter in front of a server log instead of in it.
        created, bar_patch = self._bars()
        with bar_patch, patch("clipmorph.upload_pipeline.progress.logging"
                              ) as log:
            progress = SubmissionProgress()
            self._run_binding("TikTok", {"a": 100}, progress)
            # tqdm suppresses the bar itself when stderr is not a terminal, but
            # its write() would still print: the message goes to the log instead.
            created[0].disable = True
            progress.write("late message")
        self.assertEqual(created[0].messages, ["TikTok upload completed"])
        log.log.assert_called_once_with(logging.INFO, "late message")

    def test_the_caller_callback_still_receives_every_platform(self):
        updates = []
        created, bar_patch = self._bars()
        with bar_patch:
            progress = SubmissionProgress()
            self._run_binding(
                "YouTube", {"a": 50, "b": 50}, progress,
                progress_callback=lambda name, percent: updates.append(
                    (name, percent)))
            self._run_binding(
                "TikTok", {"a": 25, "b": 75}, progress,
                progress_callback=lambda name, percent: updates.append(
                    (name, percent)))
        self.assertEqual(updates, [("YouTube", 50), ("YouTube", 100),
                                   ("TikTok", 25), ("TikTok", 100)])

    def test_adapter_messages_reach_the_shared_bar(self):
        created, bar_patch = self._bars()
        with bar_patch:
            adapter = self._run_binding(
                "TikTok", {"a": 100}, SubmissionProgress())
            adapter._bar_write("[TikTok] Video uploaded successfully")
        self.assertEqual(created[0].messages,
                         ["TikTok upload completed",
                          "[TikTok] Video uploaded successfully"])

    def test_a_caller_that_cannot_declare_up_front_still_sizes_its_own_bar(self):
        # A directly constructed pipeline has no submission to declare for it,
        # so it registers the adapters it actually initialized; one that
        # failed to initialize is never a slot the bar waits on.
        created, bar_patch = self._bars()
        with bar_patch, \
                patch("clipmorph.upload_pipeline.YouTubeUploadPipeline",
                      side_effect=ValueError("missing credentials")):
            pipeline = UploadPipeline(
                youtube=True, submission_progress=SubmissionProgress())
            pipeline.enabled_platforms["TikTok"] = _FakeAdapter({"a": 100})
            results = pipeline.run("video.mp4", "title")

        self.assertFalse(results["YouTube"]["success"])
        self.assertEqual(created[0].total, 100)
        self.assertEqual(created[0].n, 100)

    def test_a_declared_platform_that_never_uploads_stays_at_zero(self):
        # A platform whose binding fails before any adapter reports keeps its
        # slot at 0%: the bar ends short of its total rather than claiming an
        # upload that never happened.
        created, bar_patch = self._bars()
        with bar_patch:
            progress = SubmissionProgress(["youtube", "tiktok"])
            self._run_binding("TikTok", {"a": 100}, progress)

        self.assertEqual(created[0].n, 100)
        self.assertEqual(created[0].postfixes[-1],
                         "YouTube 0% | TikTok 100%")

    def test_a_shared_bar_survives_until_the_submission_closes_it(self):
        # A pipeline call that did not create the bar must not close it: the
        # next binding of the same submission still reports into it.
        created, bar_patch = self._bars()
        with bar_patch:
            progress = SubmissionProgress()
            self._run_binding("TikTok", {"a": 100}, progress)
            self.assertFalse(created[0].closed)
            progress.close()
        self.assertTrue(created[0].closed)


if __name__ == "__main__":
    unittest.main()
