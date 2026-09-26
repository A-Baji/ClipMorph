"""Checkpoint-driven per-job transcription, conversion, and review workflow."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from clipmorph.configuration import load_app_configuration
from clipmorph.ffmpeg import FFmpegRunner, configure_ffmpeg
from clipmorph.job import JobManifest, resolve_output_dir
from clipmorph.platforms import enabled_platforms as resolve_enabled_platforms
from clipmorph.preflight import PreflightValidator
from clipmorph.service import CancellationToken, JobService


def _transition(manifest: JobManifest, stage: str, status: str,
                jobs_dir: str | Path) -> dict[str, Any]:
    checkpoint = manifest.checkpoints[stage]
    return manifest.transition_checkpoint(
        stage, status, checkpoint["revision"], jobs_dir)


def _effective_no_confirm(configuration: dict[str, Any], stage: str) -> bool:
    general = configuration.get("general", {})
    conversion = configuration.get("conversion", {})
    if stage == "transcript":
        subtitles = conversion.get("subtitles", {})
        value = subtitles.get("no_confirm")
        if value is None:
            value = conversion.get("no_confirm")
    elif stage == "conversion":
        value = conversion.get("no_confirm")
    else:
        value = configuration.get("upload", {}).get("no_confirm")
    return bool(general.get("no_confirm", False) if value is None else value)


def _enabled_platforms(upload: dict[str, Any]) -> list[str]:
    return resolve_enabled_platforms(upload.get("platforms", {}))


def execute_job(manifest: JobManifest, token: CancellationToken,
                jobs_dir: str | Path,
                app_config_path: str | Path | None = None) -> None:
    """Run required checkpoints until the next review gate or terminal state."""
    jobs_root = Path(jobs_dir)
    data_dir = jobs_root.parent
    app_configuration = load_app_configuration(
        app_config_path if app_config_path is not None else data_dir / "app.yml")
    output_root = resolve_output_dir(app_configuration["output_dir"], data_dir)
    output_dir = output_root / manifest.job_id
    configuration = manifest.configuration
    conversion = configuration.get("conversion", {})
    subtitles = conversion.get("subtitles", {})
    upload = configuration.get("upload", {})
    transcript_skipped = bool(conversion.get("skip") or subtitles.get("skip"))
    conversion_skipped = bool(conversion.get("skip"))
    upload_skipped = bool(upload.get("skip"))
    enabled_platforms = _enabled_platforms(upload)
    title = upload.get("content", {}).get("title", "")

    configure_ffmpeg()
    ffmpeg_runner = FFmpegRunner()
    manifest.set_step("preflight", "running", jobs_root)
    warnings = PreflightValidator(ffmpeg_runner).validate(
        input_path=manifest.source_path,
        output_dir=str(output_dir),
        conversion=conversion,
        upload=upload,
        enabled_platforms=enabled_platforms,
        title=title,
        layout=conversion.get("layout"),
    )
    for warning in warnings:
        manifest.warnings.append(warning)
    manifest.set_step("preflight", "completed", jobs_root)
    if token.is_cancelled:
        return

    if transcript_skipped:
        checkpoint = manifest.checkpoints["transcript"]
        if checkpoint["status"] not in {"skipped", "completed"}:
            _transition(manifest, "transcript", "skipped", jobs_root)
    else:
        transcript_checkpoint = manifest.checkpoints["transcript"]
        if transcript_checkpoint["status"] == "awaiting_review":
            return
        if transcript_checkpoint["status"] in {"pending", "stale", "failed", "cancelled"}:
            if transcript_checkpoint["status"] != "pending":
                _transition(manifest, "transcript", "pending", jobs_root)
                transcript_checkpoint = manifest.checkpoints["transcript"]
            _transition(manifest, "transcript", "running", jobs_root)
            manifest.set_step("transcript", "running", jobs_root)
            audio_path = ffmpeg_runner.extract_audio(manifest.source_path)
            from clipmorph.conversion_pipeline.transcribe import TranscriptionPipeline
            segments = TranscriptionPipeline(
                audio_path,
                language=subtitles.get("transcription_language", "en"),
                model_name=subtitles.get("transcription_model", "tiny"),
                device=subtitles.get("transcription_device", "cpu"),
                compute_type=subtitles.get("transcription_compute_type", "int8"),
            ).run()
            from clipmorph.transcript import create_edit_session
            video_info = ffmpeg_runner.get_video_info(manifest.source_path)
            duration = float(video_info.get("format", {}).get("duration", 0) or 0)
            session = create_edit_session(manifest.source_sha256, segments, duration)
            session_service = JobService(data_dir)
            try:
                session_service.save_transcript_session(
                    manifest.job_id, session,
                    expected_revision=(manifest.active_transcript or {}).get("revision", 0),
                    expected_checkpoint_revision=manifest.checkpoints[
                        "transcript"]["revision"],
                )
            finally:
                session_service.close()
            manifest = JobManifest.load(manifest.job_id, jobs_root)
            manifest.set_step("transcript", "awaiting_review", jobs_root,
                              segment_count=len(segments))
            if not _effective_no_confirm(configuration, "transcript"):
                return
            _transition(manifest, "transcript", "completed", jobs_root)
            manifest = JobManifest.load(manifest.job_id, jobs_root)
        elif transcript_checkpoint["status"] != "completed":
            return

    if token.is_cancelled:
        return

    conversion_checkpoint = manifest.checkpoints["conversion"]
    if conversion_skipped:
        if conversion_checkpoint["status"] != "skipped":
            _transition(manifest, "conversion", "skipped", jobs_root)
        if manifest.current_artifact_id is None:
            manifest.set_artifact(manifest.source_path, jobs_root, name="source")
        manifest = JobManifest.load(manifest.job_id, jobs_root)
    elif conversion_checkpoint["status"] == "awaiting_review":
        return
    elif conversion_checkpoint["status"] != "completed":
        if conversion_checkpoint["status"] in {"stale", "failed", "cancelled"}:
            _transition(manifest, "conversion", "pending", jobs_root)
            conversion_checkpoint = manifest.checkpoints["conversion"]
        _transition(manifest, "conversion", "running", jobs_root)
        manifest.set_step("conversion", "running", jobs_root)
        from clipmorph.conversion_pipeline import ConversionPipeline
        transcript_path = None
        if not subtitles.get("skip") and manifest.active_transcript:
            transcript_path = str(jobs_root / manifest.job_id /
                                  manifest.active_transcript["path"])
        conversion_pipeline = ConversionPipeline(
            input_path=manifest.source_path,
            skip_subtitles=bool(subtitles.get("skip")),
            no_confirm=True,
            strict=bool(conversion.get("strict", False)),
            reviewed_transcript_path=transcript_path,
            output_dir=str(output_dir),
            layout=conversion.get("layout", {}),
        )
        artifact_path = conversion_pipeline.run()
        manifest.set_artifact(artifact_path, jobs_root, name="conversion")
        manifest = JobManifest.load(manifest.job_id, jobs_root)
        _transition(manifest, "conversion", "awaiting_review", jobs_root)
        manifest.set_step("conversion", "awaiting_review", jobs_root,
                          artifact_id=manifest.current_artifact_id)
        if not _effective_no_confirm(configuration, "conversion"):
            return
        manifest = JobManifest.load(manifest.job_id, jobs_root)
        _transition(manifest, "conversion", "completed", jobs_root)
        manifest = JobManifest.load(manifest.job_id, jobs_root)

    if upload_skipped:
        checkpoint = manifest.checkpoints["upload"]
        if checkpoint["status"] != "skipped":
            _transition(manifest, "upload", "skipped", jobs_root)
        return

    upload_checkpoint = manifest.checkpoints["upload"]
    if upload_checkpoint["status"] in {"pending", "stale"}:
        if upload_checkpoint["status"] == "stale":
            _transition(manifest, "upload", "pending", jobs_root)
            upload_checkpoint = manifest.checkpoints["upload"]
        _transition(manifest, "upload", "awaiting_review", jobs_root)
        manifest.set_step("upload", "awaiting_review", jobs_root,
                          artifact_id=manifest.current_artifact_id)
        return
    if upload_checkpoint["status"] == "awaiting_review":
        return
    if manifest.current_checkpoint is None:
        manifest._derive_status()
        manifest.save(jobs_root)
    logging.info("Job %s reached checkpoint %s", manifest.job_id,
                 manifest.current_checkpoint)