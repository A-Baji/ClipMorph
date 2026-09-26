"""Shared job service used by the CLI and local web API."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable
import uuid

from clipmorph.configuration import discover_source_entries
from clipmorph.configuration import load_app_configuration
from clipmorph.configuration import merge_configuration
from clipmorph.configuration import merge_source_configurations
from clipmorph.configuration import resolve_job_configuration
from clipmorph.configuration import validate_source_name
from clipmorph.job import JobManifest
from clipmorph.job import checkpoint_configuration_hash
from clipmorph.job import configuration_sha256
from clipmorph.job import safe_error_message
from clipmorph.job import source_sha256
from clipmorph.platforms import enabled_platforms
from clipmorph.platforms import SUPPORTED_PLATFORMS_SET


def _stage_skipped(configuration: dict[str, Any], stage: str) -> bool:
    conversion = configuration.get("conversion", {})
    if stage == "transcript":
        return bool(conversion.get("skip") or
                    conversion.get("subtitles", {}).get("skip"))
    if stage == "conversion":
        return bool(conversion.get("skip"))
    if stage == "upload":
        return bool(configuration.get("upload", {}).get("skip"))
    raise ValueError(f"Unknown checkpoint: {stage}")


class CancellationToken:
    """Cooperative cancellation signal passed to a running job."""

    def __init__(self):
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


class JobService:
    """Persist job lifecycle state while executing bounded background work."""

    def __init__(self, data_dir: str | Path, max_workers: int = 1,
                 app_config_path: str | Path | None = None):
        self.data_dir = Path(data_dir)
        self.jobs_dir = self.data_dir / "jobs"
        self.app_config_path = Path(app_config_path) if app_config_path else self.data_dir / "app.yml"
        self.executor = ThreadPoolExecutor(max_workers=max(1, max_workers))
        self._lock = Lock()
        self._tokens: dict[str, CancellationToken] = {}
        self._futures: dict[str, Future] = {}

    def create_job(self, source_path: str, configuration: dict[str, Any],
                   runner: Callable[[JobManifest, CancellationToken], None] | None = None
                   ) -> JobManifest:
        source, effective, global_defaults = self.resolve_job(source_path, configuration)
        manifest = JobManifest.create(
            str(source), effective, self.jobs_dir,
            global_defaults=global_defaults)
        if runner is not None:
            manifest.set_status("queued", self.jobs_dir)
            token = CancellationToken()
            with self._lock:
                self._tokens[manifest.job_id] = token
            future = self.executor.submit(self._run, manifest.job_id, runner, token)
            with self._lock:
                self._futures[manifest.job_id] = future
        return manifest

    def resolve_job(self, source_path: str, configuration: dict[str, Any],
                    config_dir: str | Path | None = None
                    ) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        """Normalize a source and job override object without writing state."""
        app_configuration = load_app_configuration(self.app_config_path)
        source_root = Path(app_configuration["source_dir"])
        if not source_root.is_absolute():
            source_root = self.app_config_path.parent / source_root
        source_root = source_root.resolve()

        requested_source = Path(source_path)
        if requested_source.is_absolute():
            source = requested_source.resolve()
            try:
                source.relative_to(source_root)
            except ValueError as error:
                raise ValueError("source is outside app.yml source_dir") from error
            source_name = validate_source_name(source.name)
        else:
            source_name = validate_source_name(source_path)
            source = (source_root / source_name).resolve()
            try:
                source.relative_to(source_root)
            except ValueError as error:
                raise ValueError("source is outside app.yml source_dir") from error

        if not source.is_file():
            raise FileNotFoundError(f"source file was not found: {source_name}")
        source_suffix = source.suffix.lower()
        if source_suffix not in {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}:
            raise ValueError(f"unsupported source extension: {source_suffix}")

        if not isinstance(configuration, dict):
            raise ValueError("job configuration must be an object")
        sidecars = merge_source_configurations(source_name, [], config_dir, source_root)
        overrides = merge_configuration(sidecars, configuration)
        general = overrides.get("general", {})
        if not isinstance(general, dict):
            raise ValueError("general must be an object")
        configured_source = general.get("source")
        if configured_source is not None and validate_source_name(configured_source) != source_name:
            raise ValueError("configuration source does not match selected source")
        general["source"] = source_name
        overrides["general"] = general
        effective = resolve_job_configuration(
            app_configuration["job_defaults"], overrides,
            app_configuration["layouts"])
        return source, effective, app_configuration["job_defaults"]

    def create_jobs(self, source_names: list[str] | None = None,
                    job_configs: list[Any] | None = None,
                    config_dir: str | Path | None = None,
                    overrides: dict[str, Any] | None = None,
                    runner: Callable[[JobManifest, CancellationToken], None] | None = None,
                    dry_run: bool = False) -> dict[str, Any]:
        """Fan out a source selection into independent jobs with partial results."""
        app_configuration = load_app_configuration(self.app_config_path)
        source_root = Path(app_configuration["source_dir"])
        if not source_root.is_absolute():
            source_root = self.app_config_path.parent / source_root
        source_root = source_root.resolve()
        records = job_configs or []
        if not isinstance(records, list):
            raise ValueError("job_configs must be a list")

        record_names = []
        invalid_records = []
        duplicate_records = []
        seen_record_names: set[str] = set()
        for index, record in enumerate(records, 1):
            if not isinstance(record, dict):
                invalid_records.append(self._source_outcome(
                    None, index, "failed", "invalid_record",
                    "Job configuration record must be an object"))
                continue
            general = record.get("general")
            name = general.get("source") if isinstance(general, dict) else None
            if not isinstance(name, str) or not name:
                invalid_records.append(self._source_outcome(
                    None, index, "failed", "invalid_record",
                    "Job configuration record requires general.source"))
                continue
            if name in seen_record_names:
                duplicate_records.append(self._source_outcome(
                    name, index, "skipped", "duplicate_source",
                    "A prior configuration record already targets this source"))
                continue
            seen_record_names.add(name)
            record_names.append(name)

        if source_names is None:
            candidates = sorted(
                set(discover_source_entries(source_root)).union(record_names),
                key=lambda name: (name.casefold(), name))
        else:
            if not isinstance(source_names, list) or any(
                    not isinstance(name, str) for name in source_names):
                raise ValueError("source_names must be a list of filenames")
            candidates = list(source_names)
        ordered_names = candidates

        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = duplicate_records
        failed: list[dict[str, Any]] = list(invalid_records)
        effective_configurations: list[dict[str, Any]] = []
        seen_hashes = {job.source_sha256 for job in self.list_jobs()}
        seen_names: set[str] = set()
        shared = overrides or {}
        for source_name in ordered_names:
            record_indexes = [index for index, record in enumerate(records, 1)
                              if isinstance(record, dict)
                              and isinstance(record.get("general"), dict)
                              and record["general"].get("source") == source_name]
            record_index = record_indexes[0] if record_indexes else None
            try:
                safe_name = validate_source_name(source_name)
            except ValueError as error:
                failed.append(self._source_outcome(
                    source_name, record_index, "failed", "source_outside_root", str(error)))
                continue
            if safe_name in seen_names:
                skipped.append(self._source_outcome(
                    safe_name, record_index, "skipped", "duplicate_source",
                    "Source was already included"))
                continue
            seen_names.add(safe_name)
            if Path(safe_name).suffix.lower() not in {
                    ".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}:
                skipped.append(self._source_outcome(
                    safe_name, record_index, "skipped", "unsupported_extension",
                    "Source extension is not supported"))
                continue
            source_path = (source_root / safe_name).resolve()
            try:
                source_path.relative_to(source_root)
            except ValueError:
                failed.append(self._source_outcome(
                    safe_name, record_index, "failed", "source_outside_root",
                    "Source resolves outside app.yml source_dir"))
                continue
            if not source_path.is_file():
                skipped.append(self._source_outcome(
                    safe_name, record_index, "skipped", "source_missing",
                    "Source file was not found"))
                continue
            try:
                sidecars = merge_source_configurations(
                    safe_name, [], config_dir, source_root)
                per_source = merge_configuration(sidecars, shared)
                if record_index is not None:
                    per_source = merge_configuration(per_source, records[record_index - 1])
                general = per_source.setdefault("general", {})
                if not isinstance(general, dict):
                    raise ValueError("general must be an object")
                general["source"] = safe_name
                effective = resolve_job_configuration(
                    app_configuration["job_defaults"], per_source,
                    app_configuration["layouts"])
                digest = source_sha256(source_path)
                if digest in seen_hashes:
                    skipped.append(self._source_outcome(
                        safe_name, record_index, "skipped", "duplicate_content",
                        "Source content matches an existing job"))
                    continue
                effective_configurations.append({
                    "source": safe_name, "configuration": effective})
                if dry_run:
                    created.append(self._source_outcome(
                        safe_name, record_index, "created", "validated",
                        "Configuration is valid"))
                    seen_hashes.add(digest)
                    continue
                manifest = self.create_job(safe_name, per_source, runner)
                created.append(self._source_outcome(
                    safe_name, record_index, "created", "created",
                    "Job created", manifest.job_id,
                    f"/api/v1/jobs/{manifest.job_id}"))
                seen_hashes.add(digest)
            except FileNotFoundError as error:
                skipped.append(self._source_outcome(
                    safe_name, record_index, "skipped", "source_missing", str(error)))
            except ValueError as error:
                failed.append(self._source_outcome(
                    safe_name, record_index, "failed", "invalid_config", str(error)))
            except Exception as error:
                failed.append(self._source_outcome(
                    safe_name, record_index, "failed", "creation_failed", str(error)))

        return {
            "created": created,
            "skipped": skipped,
            "failed": failed,
            "summary": {
                "total": len(created) + len(skipped) + len(failed),
                "created": len(created), "skipped": len(skipped),
                "failed": len(failed),
            },
            "effective_configurations": effective_configurations,
        }

    @staticmethod
    def _source_outcome(source: str | None, record_index: int | None,
                        status: str, code: str, message: str,
                        job_id: str | None = None,
                        status_url: str | None = None) -> dict[str, Any]:
        return {
            "source": source,
            "record_index": record_index,
            "status": status,
            "code": code,
            "message": message,
            "job_id": job_id,
            "status_url": status_url,
        }

    def save_transcript_session(self, job_id: str, session: dict[str, Any],
                                expected_revision: int,
                                expected_checkpoint_revision: int | None = None,
                                reopen: bool = False) -> dict[str, Any]:
        from clipmorph.layout import materialize_generated_captions
        from clipmorph.layout import validate_layout
        from clipmorph.transcript import save_edit_session, validate_edit_session

        with self._lock:
            manifest = self.get_job(job_id)
            if manifest.status == "completed" and not reopen:
                raise ValueError("completed job requires explicit reopen confirmation")
            if session.get("source_sha256") != manifest.source_sha256:
                raise ValueError("transcript source does not match job")
            active_revision = (manifest.active_transcript or {}).get("revision", 0)
            if expected_revision != active_revision:
                raise ValueError("stale transcript revision")
            checkpoint = manifest.checkpoints["transcript"]
            if (expected_checkpoint_revision is not None and
                    checkpoint["revision"] != expected_checkpoint_revision):
                raise ValueError("stale checkpoint revision")

            next_session = deepcopy(session)
            next_session["revision"] = active_revision + 1
            validate_edit_session(next_session)
            configuration = deepcopy(manifest.configuration)
            conversion = configuration["conversion"]
            renderer = conversion["subtitles"]["renderer"]
            conversion["layout"] = materialize_generated_captions(
                conversion["layout"], renderer, next_session["segments"])
            validate_layout(conversion["layout"], media_duration=next_session["media_duration"])

            transcript_dir = self.jobs_dir / job_id / "transcripts"
            session_path = transcript_dir / f"revision-{next_session['revision']:04d}.json"
            saved_path = save_edit_session(next_session, session_path)
            session_hash = source_sha256(saved_path)
            now = datetime.now(timezone.utc).isoformat()
            manifest.configuration = configuration
            manifest.active_transcript = {
                "revision": next_session["revision"],
                "path": str(saved_path.relative_to(self.jobs_dir / job_id)),
                "sha256": session_hash,
                "source_sha256": manifest.source_sha256,
            }
            checkpoint["revision"] += 1
            checkpoint["status"] = "awaiting_review"
            checkpoint["artifact_hash"] = session_hash
            checkpoint["updated_at"] = now
            checkpoint["completed_at"] = None
            checkpoint["error"] = None
            checkpoint["references"]["session"] = manifest.active_transcript.copy()
            if checkpoint["started_at"] is None:
                checkpoint["started_at"] = now
            reason = {"code": "transcript_edited", "message": "Transcript session changed"}
            manifest.invalidate_checkpoint("conversion", reason, persist=False)
            manifest.invalidate_checkpoint("upload", reason, persist=False)
            for stage in ("transcript", "conversion", "upload"):
                manifest.checkpoints[stage]["configuration_hash"] = (
                    checkpoint_configuration_hash(configuration, stage))
            manifest._derive_status()
            manifest.save(self.jobs_dir)
            return next_session

    def update_job_configuration(
            self, job_id: str, patch: dict[str, Any],
            expected_configuration_hash: str, reopen: bool = False) -> JobManifest:
        if not isinstance(patch, dict):
            raise ValueError("configuration patch must be an object")
        with self._lock:
            manifest = self.get_job(job_id)
            if manifest.current_configuration_hash != expected_configuration_hash:
                raise ValueError("stale configuration hash")
            if manifest.status == "completed" and not reopen:
                raise ValueError("completed job requires explicit reopen confirmation")

            updated = merge_configuration(manifest.configuration, patch)
            old_source = manifest.configuration.get("general", {}).get("source")
            new_source = updated.get("general", {}).get("source")
            if new_source != old_source:
                raise ValueError("source identity is immutable; create a new job")

            conversion_patch = patch.get("conversion", {})
            old_layout_id = manifest.configuration.get("conversion", {}).get("layout_id")
            new_layout_id = updated.get("conversion", {}).get("layout_id")
            if (isinstance(conversion_patch, dict)
                    and "layout_id" in conversion_patch
                    and new_layout_id != old_layout_id
                    and "layout" not in conversion_patch):
                updated["conversion"].pop("layout", None)

            app_configuration = load_app_configuration(self.app_config_path)
            layouts = list(app_configuration["layouts"])
            layout_id = updated.get("conversion", {}).get("layout_id")
            if (layout_id and layout_id == manifest.configuration.get(
                    "conversion", {}).get("layout_id")
                    and not any(record.get("id") == layout_id for record in layouts)):
                layouts.append({
                    "id": layout_id,
                    "name": layout_id,
                    "layout": manifest.configuration["conversion"]["layout"],
                })
            updated = resolve_job_configuration({}, updated, layouts)

            old_hashes = {
                stage: manifest.checkpoints[stage]["configuration_hash"]
                for stage in ("transcript", "conversion", "upload")
            }
            new_hashes = {
                stage: checkpoint_configuration_hash(updated, stage)
                for stage in ("transcript", "conversion", "upload")
            }
            manifest.configuration = updated
            for stage in old_hashes:
                manifest.checkpoints[stage]["configuration_hash"] = new_hashes[stage]

            changed = {stage for stage in old_hashes if old_hashes[stage] != new_hashes[stage]}
            affected: tuple[str, ...] = ()
            if "transcript" in changed:
                affected = ("transcript", "conversion", "upload")
            elif "conversion" in changed:
                affected = ("conversion", "upload")
            elif "upload" in changed:
                affected = ("upload",)
            reason = {"code": "configuration_changed", "message": "Stage inputs changed"}
            for stage in affected:
                if (manifest.checkpoints[stage]["status"] == "skipped"
                        and not _stage_skipped(updated, stage)):
                    checkpoint = manifest.checkpoints[stage]
                    checkpoint["revision"] += 1
                    checkpoint["status"] = "pending"
                    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
                    checkpoint["invalidation_reason"] = reason
                else:
                    manifest.invalidate_checkpoint(stage, reason, persist=False)
            if manifest.status == "completed" and reopen:
                manifest.status = "queued"
            manifest._derive_status()
            manifest.save(self.jobs_dir)
            return manifest

    def accept_checkpoint(self, job_id: str, stage: str,
                          expected_revision: int) -> JobManifest:
        if stage not in {"transcript", "conversion"}:
            raise ValueError("only transcript and conversion checkpoints require acceptance")
        with self._lock:
            manifest = self.get_job(job_id)
            checkpoint = manifest.checkpoints[stage]
            if checkpoint["revision"] != expected_revision:
                raise ValueError("stale checkpoint revision")
            if checkpoint["status"] != "awaiting_review":
                raise ValueError("checkpoint is not awaiting review")
            checkpoint["revision"] += 1
            checkpoint["status"] = "completed"
            now = datetime.now(timezone.utc).isoformat()
            checkpoint["completed_at"] = now
            checkpoint["updated_at"] = now
            if stage == "conversion" and manifest.checkpoints["upload"]["status"] == "pending":
                upload = manifest.checkpoints["upload"]
                upload["revision"] += 1
                upload["status"] = "awaiting_review"
                upload["updated_at"] = now
                upload["started_at"] = now
            manifest._derive_status()
            manifest.save(self.jobs_dir)
            return manifest

    def update_upload_draft(self, job_id: str, upload_configuration: dict[str, Any],
                            expected_revision: int, reopen: bool = False) -> JobManifest:
        if not isinstance(upload_configuration, dict):
            raise ValueError("upload draft must be an object")
        with self._lock:
            manifest = self.get_job(job_id)
            checkpoint = manifest.checkpoints["upload"]
            if checkpoint["revision"] != expected_revision:
                raise ValueError("stale checkpoint revision")
            if manifest.status == "completed" and not reopen:
                raise ValueError("completed job requires explicit reopen confirmation")

            updated = merge_configuration(
                manifest.configuration, {"upload": upload_configuration})
            app_configuration = load_app_configuration(self.app_config_path)
            layouts = list(app_configuration["layouts"])
            conversion = updated.get("conversion", {})
            layout_id = conversion.get("layout_id")
            if (layout_id and not any(record.get("id") == layout_id for record in layouts)):
                layouts.append({"id": layout_id, "name": layout_id,
                                "layout": conversion.get("layout", {})})
            updated = resolve_job_configuration({}, updated, layouts)
            manifest.configuration = updated
            checkpoint = manifest.checkpoints["upload"]
            checkpoint["revision"] += 1
            checkpoint["status"] = "awaiting_review"
            checkpoint["configuration_hash"] = checkpoint_configuration_hash(
                updated, "upload")
            checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
            checkpoint["completed_at"] = None
            checkpoint["error"] = None
            checkpoint["invalidation_reason"] = None
            if checkpoint["started_at"] is None:
                checkpoint["started_at"] = checkpoint["updated_at"]
            manifest._derive_status()
            manifest.save(self.jobs_dir)
            return manifest

    def delete_upload_draft(self, job_id: str, expected_revision: int,
                            reopen: bool = False) -> JobManifest:
        manifest = self.get_job(job_id)
        defaults = manifest.configuration_sources.get("global_defaults", {})
        default_upload = defaults.get("upload", {})
        return self.update_upload_draft(
            job_id, default_upload, expected_revision, reopen=reopen)

    def submit_upload(self, job_id: str, platforms: list[str] | None = None,
                      artifact_id: str | None = None,
                      confirm_historical_artifact: bool = False,
                      configuration_snapshot: dict[str, Any] | None = None,
                      retry_of: str | None = None) -> dict[str, Any]:
        with self._lock:
            manifest = self.get_job(job_id)
            checkpoint = manifest.checkpoints["upload"]
            if checkpoint["status"] != "awaiting_review":
                raise ValueError("upload checkpoint is not awaiting review")
            selected_artifact_id = artifact_id or manifest.current_artifact_id
            artifact = (manifest.artifacts.get(selected_artifact_id)
                        if selected_artifact_id else None)
            if artifact is None:
                raise ValueError("selected artifact is unavailable")
            is_historical = selected_artifact_id != manifest.current_artifact_id
            if is_historical and (not confirm_historical_artifact or not artifact_id):
                raise ValueError("historical artifact requires explicit confirmation")
            artifact_path = Path(artifact["path"])
            if not artifact_path.is_file():
                raise ValueError("selected artifact bytes are unavailable")
            actual_artifact_hash = source_sha256(artifact_path)
            if not artifact.get("sha256") or actual_artifact_hash != artifact["sha256"]:
                raise ValueError("selected artifact hash does not match manifest")

            upload_config = deepcopy(
                configuration_snapshot if configuration_snapshot is not None
                else manifest.configuration.get("upload", {}))
            platform_settings = upload_config.get("platforms", {})
            include = platforms or platform_settings.get("include")
            selected = enabled_platforms(
                {**platform_settings, "include": include})
            supported = SUPPORTED_PLATFORMS_SET
            if not selected or any(platform not in supported for platform in selected):
                raise ValueError("upload platforms are empty or unsupported")
            if len(set(selected)) != len(selected):
                raise ValueError("upload platforms must not contain duplicates")

            upload_hash = configuration_sha256(upload_config)
            now = datetime.now(timezone.utc).isoformat()
            attempts: list[dict[str, Any]] = []
            for platform in selected:
                attempt = {
                    "attempt_id": uuid.uuid4().hex,
                    "platform": platform,
                    "artifact_id": selected_artifact_id,
                    "artifact_hash": artifact.get("sha256"),
                    "configuration_snapshot": upload_config,
                    "configuration_hash": upload_hash,
                    "created_at": now,
                    "started_at": None,
                    "completed_at": None,
                    "status": "pending",
                    "result": None,
                }
                if retry_of is not None:
                    attempt["retry_of"] = retry_of
                attempts.append(attempt)
                manifest.upload_attempts.append(attempt)
            checkpoint["artifact_hash"] = artifact.get("sha256")
            checkpoint["references"]["artifact_id"] = selected_artifact_id
            checkpoint["references"]["attempt_ids"] = [
                item["attempt_id"] for item in attempts]
            manifest.transition_checkpoint(
                "upload", "running", checkpoint["revision"], self.jobs_dir)

        future = self.executor.submit(
            self._run_upload_attempts, job_id,
            [attempt["attempt_id"] for attempt in attempts],
            str(artifact_path), upload_config, selected)
        with self._lock:
            self._futures[f"upload:{job_id}"] = future
        return {"job_id": job_id, "attempts": attempts,
                "status_url": f"/api/v1/jobs/{job_id}"}

    def _run_upload_attempts(self, job_id: str, attempt_ids: list[str],
                             artifact_path: str, upload_config: dict[str, Any],
                             platforms: list[str]) -> None:
        from clipmorph.upload_attempts import execute_upload_pipeline
        from clipmorph.upload_attempts import normalize_results
        try:
            results = execute_upload_pipeline(
                platforms, artifact_path, upload_config)
        except Exception as error:
            now = datetime.now(timezone.utc).isoformat()
            results = {platform: {"success": False, "error": str(error),
                                  "started_at": now, "completed_at": now}
                       for platform in platforms}

        normalized_results = normalize_results(results)
        with self._lock:
            manifest = self.get_job(job_id)
            success_count = 0
            failure_count = 0
            for attempt_id in attempt_ids:
                attempt = next((item for item in manifest.upload_attempts
                                if item["attempt_id"] == attempt_id), None)
                if attempt is None:
                    continue
                platform = attempt["platform"]
                result = normalized_results.get(platform, {
                    "success": False, "error": "platform returned no result"})
                success = bool(result.get("success"))
                started_at = result.get("started_at") or attempt["started_at"]
                attempt["started_at"] = started_at or attempt["created_at"]
                attempt["completed_at"] = (result.get("completed_at")
                                           or datetime.now(timezone.utc).isoformat())
                attempt["status"] = "completed" if success else "failed"
                attempt["result"] = {
                    "success": success,
                    "message": str(result.get("error") or result.get("result") or "")[:1000],
                }
                manifest.platforms[platform] = {
                    "success": success,
                    "message": attempt["result"]["message"],
                    "attempt_id": attempt_id,
                    "artifact_id": attempt["artifact_id"],
                    "artifact_hash": attempt["artifact_hash"],
                }
                if success:
                    success_count += 1
                else:
                    failure_count += 1
            checkpoint = manifest.checkpoints["upload"]
            final_status = ("completed" if failure_count == 0 else
                            "partial_failure" if success_count else "failed")
            manifest.transition_checkpoint(
                "upload", final_status, checkpoint["revision"], self.jobs_dir)

    def retry_upload(self, job_id: str, platform: str, attempt_id: str,
                     artifact_id: str | None = None,
                     confirm_historical_artifact: bool = False) -> dict[str, Any]:
        manifest = self.get_job(job_id)
        previous = next((item for item in manifest.upload_attempts
                         if item["attempt_id"] == attempt_id
                         and item["platform"] == platform.lower()), None)
        if previous is None or previous.get("status") != "failed":
            raise ValueError("failed upload attempt was not found")
        previous_artifact_id = previous["artifact_id"]
        target_artifact_id = artifact_id or previous_artifact_id
        if target_artifact_id != previous_artifact_id:
            raise ValueError("retry artifact does not match failed attempt")
        if target_artifact_id != manifest.current_artifact_id and (
                not confirm_historical_artifact or artifact_id != target_artifact_id):
            raise ValueError("historical artifact retry requires matching ID and confirmation")
        artifact = manifest.artifacts.get(target_artifact_id)
        if artifact is None or not Path(artifact["path"]).is_file():
            raise ValueError("retry artifact bytes are unavailable")
        if (not artifact.get("sha256")
                or source_sha256(artifact["path"]) != artifact["sha256"]
                or previous.get("artifact_hash") != artifact["sha256"]):
            raise ValueError("retry artifact hash does not match failed attempt")
        checkpoint = manifest.checkpoints["upload"]
        if checkpoint["status"] == "failed":
            manifest.transition_checkpoint(
                "upload", "pending", checkpoint["revision"], self.jobs_dir)
            manifest = self.get_job(job_id)
            checkpoint = manifest.checkpoints["upload"]
            manifest.transition_checkpoint(
                "upload", "awaiting_review", checkpoint["revision"], self.jobs_dir)
        elif checkpoint["status"] == "partial_failure":
            with self._lock:
                manifest = self.get_job(job_id)
                checkpoint = manifest.checkpoints["upload"]
                checkpoint["status"] = "awaiting_review"
                checkpoint["revision"] += 1
                checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
                manifest.save(self.jobs_dir)
        retry_result = self.submit_upload(
            job_id, [platform], target_artifact_id,
            confirm_historical_artifact=confirm_historical_artifact,
            configuration_snapshot=previous["configuration_snapshot"],
            retry_of=attempt_id)
        return retry_result
    def _run(self, job_id: str, runner: Callable,
             token: CancellationToken) -> None:
        manifest = JobManifest.load(job_id, self.jobs_dir)
        if token.is_cancelled:
            self._cancel_manifest(manifest)
            return
        manifest.set_status("running", self.jobs_dir)
        try:
            runner(manifest, token)
            manifest = self.get_job(job_id)
            if token.is_cancelled:
                self._cancel_manifest(manifest)
            elif manifest.current_checkpoint is None:
                manifest.set_status("completed", self.jobs_dir)
            elif manifest.checkpoints[manifest.current_checkpoint]["status"] == "awaiting_review":
                manifest.set_status("awaiting_review", self.jobs_dir)
            else:
                manifest._derive_status()
                manifest.save(self.jobs_dir)
        except Exception as error:
            manifest = self.get_job(job_id)
            message = safe_error_message(error)
            manifest.errors.append({
                "code": "execution_failed",
                "message": message,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            })
            stage = manifest.current_checkpoint
            if stage is not None:
                checkpoint = manifest.checkpoints[stage]
                if checkpoint["status"] in {"pending", "running", "awaiting_review"}:
                    try:
                        manifest.transition_checkpoint(
                            stage, "failed", checkpoint["revision"], self.jobs_dir,
                            error={"code": "execution_failed", "message": message})
                        return
                    except ValueError:
                        pass
            manifest.set_status("failed", self.jobs_dir)

    def _cancel_manifest(self, manifest: JobManifest) -> None:
        stage = manifest.current_checkpoint
        if stage is not None:
            checkpoint = manifest.checkpoints[stage]
            try:
                manifest.transition_checkpoint(
                    stage, "cancelled", checkpoint["revision"], self.jobs_dir)
                return
            except ValueError:
                pass
        manifest.set_status("cancelled", self.jobs_dir)

    def get_job(self, job_id: str) -> JobManifest:
        return JobManifest.load(job_id, self.jobs_dir)

    def list_jobs(self) -> list[JobManifest]:
        if not self.jobs_dir.exists():
            return []
        jobs = []
        for path in self.jobs_dir.glob("*/manifest.json"):
            jobs.append(JobManifest.load(path.parent.name, self.jobs_dir))
        return sorted(jobs, key=lambda item: item.updated_at, reverse=True)

    def cancel_job(self, job_id: str) -> JobManifest:
        manifest = self.get_job(job_id)
        with self._lock:
            token = self._tokens.get(job_id)
        if token is not None:
            token.cancel()
        if manifest.status in {"created", "queued", "awaiting_review"}:
            self._cancel_manifest(manifest)
        return self.get_job(job_id)

    def resume_job(self, job_id: str, runner: Callable) -> JobManifest:
        manifest = self.get_job(job_id)
        if (manifest.current_checkpoint is not None and
                manifest.checkpoints[manifest.current_checkpoint]["status"] == "awaiting_review"):
            raise ValueError("job requires review before it can resume")
        if manifest.status == "completed":
            raise ValueError("completed job requires explicit reopen confirmation")
        if manifest.status not in {"failed", "cancelled", "partial_failure", "queued"}:
            raise ValueError("job is not resumable")
        token = CancellationToken()
        manifest.set_status("queued", self.jobs_dir)
        with self._lock:
            self._tokens[job_id] = token
            self._futures[job_id] = self.executor.submit(
                self._run, job_id, runner, token)
        return manifest

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
