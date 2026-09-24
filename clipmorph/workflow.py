"""Shared job execution workflow for CLI and web callers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from clipmorph.ffmpeg import FFmpegRunner, configure_ffmpeg
from clipmorph.job import JobManifest
from clipmorph.preflight import PreflightValidator
from clipmorph.service import CancellationToken


def execute_job(manifest: JobManifest, token: CancellationToken,
                jobs_dir: str | Path) -> None:
    """Execute conversion/upload steps while persisting observable job state."""
    configuration = dict(manifest.configuration)
    input_path = manifest.source_path
    no_upload = bool(configuration.get("no_upload", False))
    enabled_platforms = configuration.get(
        "upload_to", ["youtube", "instagram", "tiktok", "twitter"])
    enabled_platforms = [platform.lower() for platform in enabled_platforms]
    if configuration.get("skip"):
        enabled_platforms = [
            platform for platform in enabled_platforms
            if platform not in configuration["skip"]
        ]

    configure_ffmpeg()
    ffmpeg_runner = FFmpegRunner()
    manifest.set_step("preflight", "running", jobs_dir)
    info = ffmpeg_runner.get_video_info(input_path)
    video = next(stream for stream in info["streams"]
                 if stream.get("codec_type") == "video")
    PreflightValidator(ffmpeg_runner).validate(
        input_path=input_path,
        output_dir=configuration.get("output_dir", "output/"),
        no_conversion=bool(configuration.get("no_conversion", False)),
        no_upload=no_upload,
        enabled_platforms=enabled_platforms,
        title=configuration.get("title"),
        cam_x=configuration.get("cam_x", 1420),
        cam_y=configuration.get("cam_y", 790),
        cam_width=configuration.get("cam_width", 480),
        cam_height=configuration.get("cam_height", 270),
        platform_overrides=configuration.get("platform_overrides"),
        layout=configuration.get("layout"))
    manifest.set_step("preflight", "completed", jobs_dir)
    if token.is_cancelled:
        return

    if configuration.get("no_conversion"):
        artifact_path = input_path
    else:
        manifest.set_step("conversion", "running", jobs_dir)
        from clipmorph.conversion_pipeline import ConversionPipeline
        conversion_config = dict(configuration)
        conversion_config.pop("input_path", None)
        conversion_config.pop("no_subs", None)
        conversion_config.pop("strict", None)
        conversion = ConversionPipeline(
            input_path=input_path,
            no_subs=configuration.get("no_subs", False),
            no_confirm=True,
            strict=configuration.get("strict", False),
            **conversion_config)
        artifact_path = conversion.run()
    manifest.set_artifact(artifact_path, jobs_dir)
    manifest.set_step("conversion", "completed", jobs_dir)
    if token.is_cancelled:
        return

    if no_upload:
        return
    manifest.set_step("upload", "running", jobs_dir)
    from clipmorph.upload_pipeline import UploadPipeline
    upload = UploadPipeline(**{platform: True for platform in enabled_platforms})
    results = upload.run(
        artifact_path,
        configuration.get("title", ""),
        **configuration)
    for platform, result in results.items():
        manifest.record_platform(platform, result, jobs_dir)
    manifest.set_step("upload", "completed", jobs_dir)
    logging.info("Job %s completed", manifest.job_id)
