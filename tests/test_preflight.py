import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.preflight import PreflightError, PreflightValidator

VALID_INFO = {
    "format": {"duration": "12.5"},
    "streams": [{
        "codec_type": "video",
        "width": 1920,
        "height": 1080,
    }],
}


class FakeFFmpegRunner:
    def __init__(self, video_info=None):
        self._video_info = video_info if video_info is not None else VALID_INFO

    def get_video_info(self, _input_path):
        return self._video_info


def _validate(temp_dir, *, info=None, conversion={"skip": False},
              upload={"skip": True}, platforms=None, title="clip",
              output_dir=None, layout=None, input_path=None):
    """Run one validate() pass; a file is staged unless input_path is given."""
    if input_path is None:
        staged = Path(temp_dir) / "input.mp4"
        staged.write_bytes(b"video")
        input_path = staged
    return PreflightValidator(FakeFFmpegRunner(info)).validate(
        input_path=str(input_path),
        output_dir=output_dir or temp_dir,
        conversion=conversion,
        upload=upload,
        enabled_platforms=platforms or [],
        title=title,
        layout=layout)


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

    def test_missing_input_file_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(PreflightError, "does not exist"):
                _validate(temp_dir, input_path=Path(temp_dir) / "ghost.mp4")

    def test_empty_input_file_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "out"
            empty = Path(temp_dir) / "empty.mp4"
            empty.write_bytes(b"")
            with self.assertRaisesRegex(PreflightError, "empty or not a file"):
                PreflightValidator(FakeFFmpegRunner()).validate(
                    input_path=str(empty),
                    output_dir=str(output_dir),
                    conversion={"skip": False},
                    upload={"skip": True},
                    enabled_platforms=[],
                    title="clip")

    def test_non_file_input_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "out"
            with self.assertRaisesRegex(PreflightError, "empty or not a file"):
                PreflightValidator(FakeFFmpegRunner()).validate(
                    input_path=temp_dir,
                    output_dir=str(output_dir),
                    conversion={"skip": False},
                    upload={"skip": True},
                    enabled_platforms=[],
                    title="clip")

    def test_missing_video_stream_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            info = {"format": {"duration": "12.5"}, "streams": [
                {"codec_type": "audio", "width": 1920, "height": 1080}]}
            with self.assertRaisesRegex(PreflightError, "video stream"):
                _validate(temp_dir, info=info, conversion={"skip": True})

    def test_invalid_dimensions_raise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            info = {
                "format": {"duration": "12.5"},
                "streams": [{"codec_type": "video", "width": 0, "height": 1080}],
            }
            with self.assertRaisesRegex(PreflightError, "invalid dimensions"):
                _validate(temp_dir, info=info, conversion={"skip": True})

    def test_non_integer_dimensions_raise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            info = {
                "format": {"duration": "12.5"},
                "streams": [{"codec_type": "video",
                             "width": "1920", "height": 1080}],
            }
            with self.assertRaisesRegex(PreflightError, "invalid dimensions"):
                _validate(temp_dir, info=info, conversion={"skip": True})

    def test_language_tag_in_duration_raises_determinable_error(self):
        """A non-numeric ffprobe duration is an actionable preflight error,
        not a raw float() crash ("N/A" is a real ffprobe value)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            info = {
                "format": {"duration": "N/A"},
                "streams": [{"codec_type": "video",
                             "width": 1920, "height": 1080}],
            }
            with self.assertRaisesRegex(
                    PreflightError, "duration could not be determined"):
                _validate(temp_dir, info=info, conversion={"skip": True})

    def test_zero_duration_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            info = {
                "format": {"duration": 0},
                "streams": [{"codec_type": "video",
                             "width": 1920, "height": 1080}],
            }
            with self.assertRaisesRegex(
                    PreflightError, "duration could not be determined"):
                _validate(temp_dir, info=info, conversion={"skip": True})

    def test_missing_output_dir_is_created(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "nested" / "out"
            _validate(temp_dir, output_dir=str(output_dir))
            self.assertTrue(output_dir.is_dir())

    def test_unwritable_output_dir_raises(self):
        # A path whose parent is a file can never become a writable
        # directory (mkdir fails there on every filesystem), so patch the
        # writability probe to exercise the dedicated raise path directly.
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("clipmorph.preflight.os.access",
                       return_value=False):
                with self.assertRaisesRegex(PreflightError, "not writable"):
                    _validate(temp_dir)

    def test_low_free_disk_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            usage = shutil.disk_usage(temp_dir)
            with patch("clipmorph.preflight.shutil.disk_usage",
                       return_value=usage._replace(free=1024)):
                with self.assertRaisesRegex(PreflightError, "100 MB free"):
                    _validate(temp_dir)

    def test_title_over_youtube_limit_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(PreflightError, "100 characters"):
                _validate(temp_dir, conversion={"skip": True},
                          upload={"skip": False}, platforms=["youtube"],
                          title="y" * 101)

    def test_title_over_twitter_limit_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(PreflightError, "280 characters"):
                _validate(temp_dir, conversion={"skip": True},
                          upload={"skip": False}, platforms=["twitter"],
                          title="x" * 281)

    def test_missing_title_raises_without_upload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(PreflightError, "title is required"):
                _validate(temp_dir, conversion={"skip": True},
                          upload={"skip": False}, platforms=["youtube"],
                          title="")

    def test_credential_warnings_cover_each_platform(self):
        from clipmorph.preflight import PLATFORM_CREDENTIALS
        for platform, names in PLATFORM_CREDENTIALS.items():
            with patch.dict(os.environ, {name: "" for name in names}):
                warnings = PreflightValidator(
                    FakeFFmpegRunner())._validate_credentials([platform])
            self.assertEqual(len(warnings), 1)
            self.assertIn(platform, warnings[0])
            self.assertIn(names[0], warnings[0])


if __name__ == "__main__":
    unittest.main()
