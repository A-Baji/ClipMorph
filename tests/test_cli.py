import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.__main__ import main
from clipmorph.preflight import PreflightError, PreflightValidator
from clipmorph.upload_pipeline import UploadPipeline


class FakeFFmpegRunner:
    def get_video_info(self, _input_path):
        return {
            "format": {"duration": "12.5"},
            "streams": [{
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
            }],
        }


class CliInitializationTests(unittest.TestCase):
    def test_init_creates_template_without_configuring_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "clipmorph.yaml"
            with patch.object(sys, "argv", [
                    "clipmorph", "--init", "--config-path", str(config_path)
            ]), patch("clipmorph.__main__.configure_ffmpeg") as configure:
                main()

            self.assertTrue(config_path.exists())
            self.assertIn("general:", config_path.read_text(encoding="utf-8"))
            configure.assert_not_called()

    def test_init_backs_up_existing_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "clipmorph.yaml"
            config_path.write_text("old: true\n", encoding="utf-8")

            with patch.object(sys, "argv", [
                    "clipmorph", "--init", "--config-path", str(config_path)
            ]):
                main()

            backup_path = Path(f"{config_path}.backup")
            self.assertEqual(backup_path.read_text(encoding="utf-8"),
                             "old: true\n")
            self.assertIn("general:", config_path.read_text(encoding="utf-8"))


class PreflightTests(unittest.TestCase):
    def test_rejects_camera_crop_outside_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.mp4"
            input_path.write_bytes(b"video")
            with self.assertRaises(PreflightError):
                PreflightValidator(FakeFFmpegRunner()).validate(
                    input_path=str(input_path),
                    output_dir=temp_dir,
                    no_conversion=False,
                    no_upload=True,
                    enabled_platforms=[],
                    title=None,
                    cam_x=1800,
                    cam_y=0,
                    cam_width=480,
                    cam_height=270,
                    platform_overrides=None)

    def test_returns_credential_warnings_without_uploading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.mp4"
            input_path.write_bytes(b"video")
            with patch.dict(os.environ, {
                    "GOOGLE_CLIENT_ID": "",
                    "GOOGLE_CLIENT_SECRET": "",
            }):
                warnings = PreflightValidator(FakeFFmpegRunner()).validate(
                    input_path=str(input_path),
                    output_dir=temp_dir,
                    no_conversion=True,
                    no_upload=False,
                    enabled_platforms=["youtube"],
                    title="A title",
                    cam_x=0,
                    cam_y=0,
                    cam_width=1,
                    cam_height=1,
                    platform_overrides=None)
            self.assertTrue(any("youtube" in warning for warning in warnings))


class UploadPipelineTests(unittest.TestCase):
    def test_initialization_failure_remains_in_results(self):
        with patch("clipmorph.upload_pipeline.YouTubeUploadPipeline",
                   side_effect=ValueError("missing credentials")):
            pipeline = UploadPipeline(youtube=True)

        results = pipeline.run("video.mp4", "A title")
        self.assertIn("YouTube", results)
        self.assertFalse(results["YouTube"]["success"])
        self.assertIn("missing credentials", results["YouTube"]["error"])


if __name__ == "__main__":
    unittest.main()
