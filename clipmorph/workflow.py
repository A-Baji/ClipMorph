"""Checkpoint-driven per-job transcription, conversion, and review workflow."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from clipmorph.configuration import load_app_configuration
from clipmorph.ffmpeg import FFmpegRunner, configure_ffmpeg
from clipmorph.job import JobManifest, resolve_output_dir
from clipmorph.platforms import resolve_upload_participants
from clipmorph.preflight import PreflightValidator
from clipmorph.service import CancellationToken, JobService
from clipmorph.service import _stage_skipped, conversion_groups
from clipmorph.storage import storage_key_for


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


def _enabled_platforms(configuration: dict[str, Any]) -> list[str]:
    return resolve_upload_participants(configuration)


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
    transcript_skipped = _stage_skipped(configuration, "transcript")
    conversion_skipped = _stage_skipped(configuration, "conversion")
    upload_skipped = _stage_skipped(configuration, "upload")
    enabled_platforms = _enabled_platforms(configuration)
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
        if transcript_checkpoint["status"] in {
                "pending", "stale", "failed", "cancelled", "skipped"}:
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
            manifest.set_artifact(
                manifest.source_path, jobs_root, name="source",
                storage_key=storage_key_for(output_root, manifest.source_path))
        manifest = JobManifest.load(manifest.job_id, jobs_root)
    elif conversion_checkpoint["status"] == "awaiting_review":
        return
    elif conversion_checkpoint["status"] != "completed":
        if conversion_checkpoint["status"] == "skipped":
            # A born-``skipped`` aggregate whose per-platform sections are not
            # all skipped (a platform override un-skipped it) is returned to
            # ``pending`` so the group loop below reconciles and renders it.
            _transition(manifest, "conversion", "pending", jobs_root)
            manifest = JobManifest.load(manifest.job_id, jobs_root)
            conversion_checkpoint = manifest.checkpoints["conversion"]
        groups = conversion_groups(manifest.configuration)
        # Reconcile the stored group set with what the current configuration
        # derives, so a group created or dropped by a configuration edit (or by
        # a layout registry change) is rendered or forgotten instead of
        # silently skipped.
        manifest.sync_conversion_groups(groups)
        manifest = JobManifest.load(manifest.job_id, jobs_root)
        conversion_checkpoint = manifest.checkpoints["conversion"]
        for group in groups:
            group_id = group["id"]
            group_record = conversion_checkpoint.get("groups", {}).get(group_id)
            if group_record is None:
                continue
            group_conversion = group["conversion"]
            group_subtitles = group_conversion.get("subtitles", {})
            if group_record["status"] == "awaiting_review":
                continue
            if group_record["status"] == "completed":
                continue
            if group_record["status"] in {"stale", "failed", "cancelled"}:
                manifest.transition_checkpoint(
                    "conversion", "pending", group_record["revision"],
                    jobs_root, group_id=group_id)
                group_record = conversion_checkpoint["groups"][group_id]
            if group_conversion.get("skip"):
                # A conversion.skip group never renders: it binds to the source
                # artifact and keeps the ``skipped`` state it is born in, which
                # is terminal (``skipped -> completed`` is not a legal
                # transition).  The aggregate reports one completed group and
                # one intentionally skipped one.
                if group_record.get("current_artifact_id") is None:
                    manifest.record_artifact(
                        "source", manifest.source_path, jobs_root,
                        storage_key=storage_key_for(
                            output_root, manifest.source_path),
                        group_id=group_id)
                    group_record = conversion_checkpoint["groups"][group_id]
                if group_record["status"] != "skipped":
                    manifest.transition_checkpoint(
                        "conversion", "skipped", group_record["revision"],
                        jobs_root, group_id=group_id)
                    manifest = JobManifest.load(manifest.job_id, jobs_root)
                    conversion_checkpoint = manifest.checkpoints["conversion"]
                continue
            # Preflight runs per group: each group's own layout and title
            # must validate before it renders, so a bad group fails alone
            # instead of failing the whole conversion stage.
            for warning in PreflightValidator(ffmpeg_runner).validate(
                input_path=manifest.source_path,
                output_dir=str(output_dir),
                conversion=group_conversion,
                upload=upload,
                enabled_platforms=enabled_platforms,
                title=title,
                layout=group_conversion.get("layout"),
            ):
                if warning not in manifest.warnings:
                    manifest.warnings.append(warning)
            if token.is_cancelled:
                return
            manifest.transition_checkpoint(
                "conversion", "running", group_record["revision"],
                jobs_root, group_id=group_id)
            manifest.set_step("conversion", "running", jobs_root)
            from clipmorph.conversion_pipeline import ConversionPipeline
            transcript_path = None
            if not group_subtitles.get("skip") and manifest.active_transcript:
                transcript_path = str(jobs_root / manifest.job_id /
                                      manifest.active_transcript["path"])
            conversion_pipeline = ConversionPipeline(
                input_path=manifest.source_path,
                skip_subtitles=bool(group_subtitles.get("skip")),
                reviewed_transcript_path=transcript_path,
                output_dir=str(output_dir),
                layout=group_conversion.get("layout", {}),
            )
            artifact_path = conversion_pipeline.run()
            manifest.record_artifact(
                "conversion", artifact_path, jobs_root,
                storage_key=storage_key_for(output_root, artifact_path),
                group_id=group_id)
            # Reloading replaces the manifest object, so the group record is
            # re-read from the reloaded checkpoint: the captured one still
            # holds the pre-artifact revision and every transition would be
            # rejected as stale.
            manifest = JobManifest.load(manifest.job_id, jobs_root)
            conversion_checkpoint = manifest.checkpoints["conversion"]
            group_record = conversion_checkpoint["groups"][group_id]
            manifest.transition_checkpoint(
                "conversion", "awaiting_review", group_record["revision"],
                jobs_root, group_id=group_id)
            manifest.set_step("conversion", "awaiting_review", jobs_root,
                              artifact_id=group_record.get("current_artifact_id"))
            if not _effective_no_confirm(configuration, "conversion"):
                continue
            manifest = JobManifest.load(manifest.job_id, jobs_root)
            conversion_checkpoint = manifest.checkpoints["conversion"]
            group_record = conversion_checkpoint["groups"][group_id]
            manifest.transition_checkpoint(
                "conversion", "completed", group_record["revision"],
                jobs_root, group_id=group_id)
        if manifest.actionable_group("conversion") is None:
            # Every group is terminal, so the projection writes ``completed``.
            # A configuration edit that re-pointed platforms onto already
            # rendered groups leaves the aggregate ``stale`` with no work left;
            # re-deriving it follows the groups instead of staying stuck.  A
            # group awaiting review is actionable and keeps the aggregate on
            # its review gate.
            manifest.derive_checkpoint_status("conversion")
            manifest.save(jobs_root)
        if not _effective_no_confirm(configuration, "conversion"):
            return
        manifest = JobManifest.load(manifest.job_id, jobs_root)

    if upload_skipped:
        checkpoint = manifest.checkpoints["upload"]
        if checkpoint["status"] != "skipped":
            _transition(manifest, "upload", "skipped", jobs_root)
        return

    upload_checkpoint = manifest.checkpoints["upload"]
    if upload_checkpoint["status"] == "skipped":
        # A born-``skipped`` upload checkpoint whose participating platforms
        # were un-skipped by a per-platform ``upload.skip: false`` override is
        # returned to ``pending`` so the review gate below is reached.
        _transition(manifest, "upload", "pending", jobs_root)
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