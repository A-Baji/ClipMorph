import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.preflight import PreflightError, PreflightValidator


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


class PreflightTests(unittest.TestCase):
    def test_rejects_layout_crop_outside_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.mp4"
            input_path.write_bytes(b"video")
            with self.assertRaises(PreflightError):
                PreflightValidator(FakeFFmpegRunner()).validate(
                    input_path=str(input_path),
                    output_dir=temp_dir,
                    conversion={"skip": False},
                    upload={"skip": True},
                    enabled_platforms=[],
                    title="clip",
                    layout={"crop": {
                        "enabled": True,
                        "source": {"x": 1800, "y": 0,
                                   "width": 320, "height": 240},
                        "sizing": {"mode": "native"},
                        "composition": {"mode": "overlay", "placement": "top"},
                    }})

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
                    conversion={"skip": True},
                    upload={"skip": False},
                    enabled_platforms=["youtube"],
                    title="A title",
                    layout={})
            self.assertTrue(any("youtube" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
