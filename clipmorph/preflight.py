"""Validate nested job configuration and source media before execution."""

import os
from pathlib import Path
import shutil
from typing import Any


PLATFORM_CREDENTIALS = {
    "youtube": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "instagram": ("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET", "FACEBOOK_PAGE_ID",
                  "GCS_BUCKET_NAME"),
    "tiktok": ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
    "twitter": ("TWITTER_CLIENT_ID", "TWITTER_CLIENT_SECRET",
                "TWITTER_OAUTH2_ACCESS_TOKEN"),
}


class PreflightError(ValueError):
    """Raised when a job cannot safely begin its next stage."""


class PreflightValidator:
    def __init__(self, ffmpeg_runner):
        self.ffmpeg_runner = ffmpeg_runner

    def validate(self, *, input_path: str, output_dir: str,
                 conversion: dict[str, Any], upload: dict[str, Any],
                 enabled_platforms: list[str], title: str | None,
                 layout: dict[str, Any] | None = None) -> list[str]:
        self._validate_input(input_path)
        info = self.ffmpeg_runner.get_video_info(input_path)
        video = self._validate_video_stream(info)
        conversion_skipped = bool(conversion.get("skip"))
        upload_skipped = bool(upload.get("skip"))
        self._validate_output_dir(output_dir, conversion_skipped)
        if layout is not None:
            from clipmorph.layout import validate_layout
            duration = float(info.get("format", {}).get("duration", 0) or 0)
            try:
                validate_layout(layout, video["width"], video["height"], duration)
            except ValueError as error:
                raise PreflightError(str(error)) from error
        warnings = []
        if not upload_skipped:
            if not title:
                raise PreflightError("upload.content.title is required before upload")
            self._validate_title(title, enabled_platforms)
            warnings.extend(self._validate_credentials(enabled_platforms))
        return warnings

    def _validate_input(self, input_path: str) -> None:
        path = Path(input_path)
        if not path.exists():
            raise PreflightError(f"Input file does not exist: {path}")
        if not path.is_file() or path.stat().st_size == 0:
            raise PreflightError(f"Input file is empty or not a file: {path}")

    def _validate_video_stream(self, info: dict[str, Any]) -> dict[str, Any]:
        streams = info.get("streams", [])
        video = next((stream for stream in streams
                      if stream.get("codec_type") == "video"), None)
        if not video:
            raise PreflightError("Input does not contain a video stream.")
        width, height = video.get("width"), video.get("height")
        if (not isinstance(width, int) or not isinstance(height, int)
                or width <= 0 or height <= 0):
            raise PreflightError("Video stream has invalid dimensions.")
        duration = float(info.get("format", {}).get("duration", 0) or 0)
        if duration <= 0:
            raise PreflightError("Video duration could not be determined.")
        return video

    def _validate_output_dir(self, output_dir: str, conversion_skipped: bool) -> None:
        if conversion_skipped:
            return
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.W_OK):
            raise PreflightError(f"Output directory is not writable: {path}")
        if shutil.disk_usage(path).free < 100 * 1024 * 1024:
            raise PreflightError(f"Less than 100 MB free in output directory: {path}")

    def _validate_title(self, title: str, platforms: list[str]) -> None:
        if "youtube" in platforms and len(title) > 100:
            raise PreflightError("YouTube title must be 100 characters or fewer.")
        if "twitter" in platforms and len(title) > 280:
            raise PreflightError("X post text must be 280 characters or fewer.")

    def _validate_credentials(self, platforms: list[str]) -> list[str]:
        warnings = []
        for platform in platforms:
            missing = [name for name in PLATFORM_CREDENTIALS[platform]
                       if not os.getenv(name)]
            if missing:
                warnings.append(
                    f"{platform}: missing credentials ({', '.join(missing)})")
        return warnings