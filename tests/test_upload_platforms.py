import unittest
from unittest.mock import MagicMock, patch

from clipmorph.policy import CAPABILITY_MATRIX, validate_artifact
from clipmorph.upload_pipeline import UploadPipeline


class UploadPipelineTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
