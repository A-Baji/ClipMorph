import unittest
from unittest.mock import MagicMock, patch

from clipmorph.policy import validate_artifact
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


if __name__ == "__main__":
    unittest.main()
