"""Shared job service used by the CLI and local web API."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import shutil
from threading import Event, Lock, Timer
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
from clipmorph.platforms import native_scheduling_support
from clipmorph.platforms import SUPPORTED_PLATFORMS_SET
from clipmorph.storage import ArtifactStorage, LocalArtifactStorage, make_storage


logger = logging.getLogger(__name__)

# Emitted when a checkpoint was still running in a manifest found at startup,
# meaning the process that owned it never finished or reported.
INTERRUPTED_ERROR = {
    "code": "interrupted_by_restart",
    "message": "Job step did not finish; the service restarted.",
    "retryable": True,
}

# A publish_at closer to now than this is treated as "now" rather than deferred.
SCHEDULE_MINIMUM_DELAY_SECONDS = 1.0

# Attempt statuses that still block a new submission for the same content.
ACTIVE_ATTEMPT_STATUSES = {"pending", "scheduled", "running"}

# Attempt statuses a worker must never rewrite: a stale batch timer can fire
# after one member of its group was cancelled or already reported.
TERMINAL_ATTEMPT_STATUSES = {"published", "failed", "cancelled"}

# Platform post-id to public URL templates for platforms whose posts are
# addressable by id alone. Platforms without a template record no URL.
PLATFORM_URL_TEMPLATES = {
    "youtube": "https://www.youtube.com/watch?v={post_id}",
}


class UnknownUploadAttempt(LookupError):
    """No upload attempt with the requested id exists in the job."""


class UploadAttemptNotScheduled(ValueError):
    """The upload attempt is not in the cancellable scheduled state."""


def _platform_url(platform: str, post_id: str) -> str | None:
    """Return the public URL for one platform post id, when addressable."""
    template = PLATFORM_URL_TEMPLATES.get(platform)
    return template.format(post_id=post_id) if template else None


def _upload_adapter(platform: str):
    """Return one platform's upload adapter, or None when it cannot load.

    Adapter construction is lazy and never raises: a platform whose credentials
    or optional dependency are missing simply has no adapter, which the caller
    reports as an unavailable platform action.
    """
    from clipmorph.platforms import PLATFORM_TITLE
    from clipmorph.upload_pipeline import UploadPipeline

    pipeline = UploadPipeline(**{platform: True})
    return pipeline.enabled_platforms.get(PLATFORM_TITLE.get(platform, platform))


def _parse_utc_timestamp(value: str) -> datetime:
    """Parse one ISO-8601 stamp as an aware UTC datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
        self._scheduled_timers: dict[str, list[Timer]] = {}
        # One batch timer serves every attempt in its group, so the per-attempt
        # cancel surface needs the reverse index to disarm the right batch.
        self._attempt_timers: dict[str, Timer] = {}
        # Artifact storage backend selected by app.yml; staging holds the
        # machine-local copy upload adapters read during one attempt.
        self._storage = make_storage(
            load_app_configuration(self.app_config_path), self.data_dir)
        self._staging_dir = self.data_dir / "staging"
        # Live per-platform upload percents (job_id -> {platform: percent}),
        # held in service memory only while an upload is in flight; the
        # final snapshot is written into the attempt record at completion.
        self._live_progress: dict[str, dict[str, int]] = {}
        # Order matters: reconciliation must settle stalled checkpoints first so
        # that only genuinely scheduled uploads survive into the re-arm scan.
        self._reconcile_interrupted_jobs()
        self._rearm_scheduled_attempts()

    @property
    def storage(self) -> ArtifactStorage:
        """The artifact storage backend this workspace selected in app.yml."""
        return self._storage

    def artifact_path(self, artifact: dict[str, Any]) -> Path:
        """Return the local file path of one registered artifact record.

        Preview and download hand a real file to the browser or to a
        ``FileResponse``, so this resolves the record's key through the
        backend that owns the bytes. A backend without local bytes has no
        path to hand over and says so.
        """
        storage = self._storage
        if not isinstance(storage, LocalArtifactStorage):
            raise ValueError(
                f"storage backend {type(storage).__name__} has no local path")
        return storage.local_path(artifact["storage"]["key"])

    def _stage_artifact(self, key: str) -> Path:
        """Copy one artifact into a private staging directory for the caller.

        Each copy lands in its own directory under ``data_dir/staging``, so
        concurrent attempts of the same artifact never share bytes and the
        caller releases exactly what it read with ``_release_staging``.
        """
        return self._storage.stage(key, self._staging_dir / uuid.uuid4().hex)

    def _release_staging(self, staged_path: Path) -> None:
        """Drop one staged artifact copy and the directory that held it."""
        try:
            staged_path.unlink(missing_ok=True)
        except OSError as error:  # pragma: no cover - locked scratch file
            logger.warning("Could not remove staged artifact %s: %s",
                           staged_path, error)
        shutil.rmtree(staged_path.parent, ignore_errors=True)

    def _staged_artifact_sha256(self, key: str) -> str:
        """Hash one artifact's bytes through a throwaway staging copy.

        Raises ``FileNotFoundError`` when the backend no longer holds the
        bytes, which callers report as unavailable bytes.
        """
        staged = self._stage_artifact(key)
        try:
            return source_sha256(staged)
        finally:
            self._release_staging(staged)

    def _manifest_paths(self) -> list[Path]:
        """Return every job manifest path, tolerating an absent jobs tree."""
        if not self.jobs_dir.exists():
            return []
        try:
            return sorted(self.jobs_dir.glob("*/manifest.json"))
        except OSError as error:  # pragma: no cover - unreadable jobs tree
            logger.warning("Unable to scan %s: %s", self.jobs_dir, error)
            return []

    def _load_startup_manifest(self, path: Path) -> JobManifest | None:
        """Load one manifest for a startup pass, skipping unusable files."""
        try:
            return JobManifest.load(path.parent.name, self.jobs_dir)
        except (ValueError, TypeError, OSError) as error:
            logger.warning("Skipping unusable job manifest %s: %s", path, error)
            return None

    def _reconcile_interrupted_jobs(self) -> None:
        """Fail checkpoints left running by a process that never returned.

        Runs on every service construction, so the CLI and the web API both
        heal phantom queue entries on first touch. It is idempotent: a healed
        manifest is already terminal for the next scan. Two long-running
        instances of the service may still mark each other's live jobs failed at
        the exact moment a process starts; the review checkpoint flow is the
        user-facing guard for that documented limitation.
        """
        for path in self._manifest_paths():
            manifest = self._load_startup_manifest(path)
            if manifest is None:
                continue
            self._reconcile_manifest(manifest)

    def _reconcile_manifest(self, manifest: JobManifest) -> None:
        """Apply the interrupted-work rules to one loaded manifest."""
        if manifest.status != "running":
            # queued manifests hold all-pending checkpoints, which is not
            # evidence of a crash: no started stage exists to reconcile.
            return
        for stage in ("transcript", "conversion"):
            if manifest.checkpoints.get(stage, {}).get("status") == "running":
                self._fail_interrupted_checkpoint(manifest, stage)
        upload = manifest.checkpoints.get("upload", {})
        if upload.get("status") == "running":
            # A platform-scheduled attempt can be stranded between the
            # platform accepting the upload and this process recording the
            # result, so it is healed from platform state before the
            # interrupted-work rule below reads its status.
            self._heal_platform_scheduled_attempts(manifest)
            if not self._upload_awaits_schedule(manifest):
                self._fail_interrupted_checkpoint(manifest, "upload")
        if manifest.status == "running" and not any(
                checkpoint.get("status") == "running"
                for checkpoint in manifest.checkpoints.values()):
            # Status drift only: every checkpoint is terminal.
            manifest._derive_status()
            manifest.save(self.jobs_dir)

    def _heal_platform_scheduled_attempts(self,
                                          manifest: JobManifest) -> int:
        """Settle platform-scheduled attempts stranded on a running upload pass.

        A platform-scheduled attempt is created ``scheduled`` and the platform
        already holds the content, so a crash between the platform accepting
        the upload and this process writing the result leaves a live private
        post with no recorded outcome. The adapter's existing-post lookup is
        the only honest source: a post found completes the attempt as
        ``published`` without re-uploading, and no post marks it ``failed``
        with a retryable note, so the ordinary retry is both the re-upload and
        the refresh. Returns the number of attempts settled.
        """
        stranded = [attempt for attempt in manifest.upload_attempts
                    if (attempt.get("status") == "scheduled"
                        and attempt.get("scheduled_via") == "platform"
                        and not attempt.get("result"))]
        healed = 0
        for attempt in stranded:
            platform = str(attempt.get("platform"))
            post_id: str | None = None
            adapter = _upload_adapter(platform)
            if adapter is not None:
                try:
                    found = adapter.find_existing_post(attempt.get("artifact_hash"))
                except Exception as error:
                    logger.warning("Could not read %s post state for attempt %s: %s",
                                   platform, attempt["attempt_id"], error)
                    found = None
                if isinstance(found, str) and found:
                    post_id = found
            now = datetime.now(timezone.utc).isoformat()
            if post_id:
                attempt["status"] = "published"
                attempt["completed_at"] = now
                attempt["result"] = {
                    "success": True,
                    "message": ("re-attached to the platform post that was "
                                f"already scheduled (id {post_id})"),
                    "platform_post_id": post_id,
                    "platform_url": _platform_url(platform, post_id),
                    "scheduled_publish_at": attempt.get("scheduled_publish_at"),
                    "published_at": None,
                }
            else:
                attempt["status"] = "failed"
                attempt["completed_at"] = now
                attempt["result"] = {
                    "success": False,
                    "message": ("scheduled publication could not be confirmed "
                                "after a restart; retry the attempt to "
                                "re-upload"),
                    "platform_post_id": None,
                    "platform_url": None,
                    "published_at": None,
                }
                attempt.setdefault("errors", []).append({
                    "code": "platform_schedule_unconfirmed",
                    "message": "no scheduled post was found for this attempt",
                    "retryable": True,
                    "occurred_at": now,
                })
            healed += 1
        if healed:
            logger.info("Healed %d platform-scheduled upload attempt(s) of %s",
                        healed, manifest.job_id)
            manifest.save(self.jobs_dir)
        return healed

    def _fail_interrupted_checkpoint(self, manifest: JobManifest,
                                     stage: str) -> None:
        """Move one running checkpoint to failed with the structured reason."""
        checkpoint = manifest.checkpoints[stage]
        try:
            manifest.transition_checkpoint(
                stage, "failed", checkpoint["revision"], self.jobs_dir,
                error=dict(INTERRUPTED_ERROR))
        except ValueError as error:
            logger.warning("Could not fail interrupted %s checkpoint of %s: %s",
                           stage, manifest.job_id, error)

    def _upload_awaits_schedule(self, manifest: JobManifest) -> bool:
        """Report whether every scheduled attempt waits on a future publish_at.

        A platform-scheduled attempt is not waiting on this process: the
        platform already holds the content and holds its own publication
        timer, so it never keeps a pass alive and is excluded here. That is
        what lets a ``running`` upload checkpoint holding only a platform
        publication fall through to the interrupted-work rule.
        """
        now = datetime.now(timezone.utc)
        scheduled: list[dict[str, Any]] = []
        for attempt in manifest.upload_attempts:
            if (attempt.get("status") != "scheduled"
                    or attempt.get("scheduled_via") == "platform"):
                continue
            scheduled.append(attempt)
            stamp = attempt.get("scheduled_publish_at")
            if not isinstance(stamp, str):
                return False
            try:
                if _parse_utc_timestamp(stamp) <= now:
                    return False
            except ValueError:
                return False
        return bool(scheduled)

    def _rearm_scheduled_attempts(self) -> None:
        """Re-arm timers for scheduled upload attempts left pending by a restart."""
        for path in self._manifest_paths():
            manifest = self._load_startup_manifest(path)
            if manifest is None:
                continue
            self._arm_manifest_schedules(manifest)

    def _arm_manifest_schedules(self, manifest: JobManifest) -> int:
        """Arm this process's timers for one manifest's future local schedules.

        Platform-scheduled attempts are excluded: the platform already holds
        the content and holds its own publication timer, so a local timer
        would post the same artifact a second time. Returns the number of
        attempts armed.
        """
        if manifest.checkpoints.get("upload", {}).get("status") != "running":
            return 0
        if not self._upload_awaits_schedule(manifest):
            return 0
        now = datetime.now(timezone.utc)
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for attempt in manifest.upload_attempts:
            if attempt.get("status") != "scheduled":
                continue
            if attempt.get("scheduled_via") == "platform":
                # Second line of defense: reconciliation already settled these
                # from platform state, and a re-arm would double-post.
                continue
            stamp = attempt.get("scheduled_publish_at")
            if not isinstance(stamp, str):
                continue
            try:
                publish_at = _parse_utc_timestamp(stamp)
            except ValueError:
                continue
            if publish_at <= now:
                continue
            key = (str(attempt.get("artifact_id")),
                   str(attempt.get("configuration_hash")), stamp)
            groups.setdefault(key, []).append(attempt)
        armed = 0
        for (artifact_id, _hash, stamp), group in groups.items():
            artifact = manifest.artifacts.get(artifact_id)
            snapshot = group[0].get("configuration_snapshot")
            if artifact is None or not isinstance(snapshot, dict):
                logger.warning(
                    "Skipping re-arm for %s: artifact %s or its upload "
                    "snapshot is missing", manifest.job_id, artifact_id)
                continue
            self._schedule_attempts(
                manifest.job_id, [item["attempt_id"] for item in group],
                artifact["storage"]["key"], snapshot,
                [item["platform"] for item in group],
                _parse_utc_timestamp(stamp))
            armed += len(group)
        return armed

    def _schedule_attempts(self, job_id: str, attempt_ids: list[str],
                           artifact_key: str, upload_config: dict[str, Any],
                           platforms: list[str], publish_at: datetime) -> Timer:
        """Run one upload attempt group at publish_at on a daemon timer."""
        delay = max(
            0.0,
            (publish_at - datetime.now(timezone.utc)).total_seconds())
        handle = Timer(delay, self._run_upload_attempts,
                       args=(job_id, list(attempt_ids), artifact_key,
                             deepcopy(upload_config), list(platforms)))
        handle.daemon = True
        with self._lock:
            self._scheduled_timers.setdefault(
                f"upload:{job_id}", []).append(handle)
            for attempt_id in attempt_ids:
                self._attempt_timers[attempt_id] = handle
        handle.start()
        logger.info("Scheduled %d upload attempt(s) of %s in %.1fs",
                    len(attempt_ids), job_id, delay)
        return handle

    def _disarm_attempt_timers(self, job_id: str,
                               attempt_ids: list[str]) -> None:
        """Cancel the batch timers that would run the given attempts.

        One timer serves a whole group, so every handle reached from the
        per-attempt index is cancelled and dropped from both registries; the
        surviving group members are re-armed by the ordinary re-arm path.
        """
        with self._lock:
            handles: set[Timer] = set()
            for attempt_id in attempt_ids:
                handle = self._attempt_timers.pop(attempt_id, None)
                if handle is not None:
                    handles.add(handle)
            remaining = [timer for timer in self._scheduled_timers.get(
                f"upload:{job_id}", []) if timer not in handles]
            if remaining:
                self._scheduled_timers[f"upload:{job_id}"] = remaining
            else:
                self._scheduled_timers.pop(f"upload:{job_id}", None)
        for handle in handles:
            handle.cancel()

    def _discard_scheduled_uploads_locked(self, manifest: JobManifest) -> int:
        """Disarm one job's scheduled uploads. Caller holds ``self._lock``.

        Cancels the armed timers and unmarks their scheduled attempts, so
        neither this process nor a later startup re-arms a configuration the user
        has since replaced. The attempt records return to ``pending``: their
        real fate is unknown, exactly as when a stalled upload is failed.
        Returns the number of attempts unmarked.
        """
        for timer in self._scheduled_timers.pop(
                f"upload:{manifest.job_id}", []):
            timer.cancel()
        for attempt in manifest.upload_attempts:
            self._attempt_timers.pop(str(attempt.get("attempt_id")), None)
        unmarked = 0
        for attempt in manifest.upload_attempts:
            if attempt.get("status") == "scheduled":
                attempt["status"] = "pending"
                attempt.pop("scheduled_publish_at", None)
                attempt.pop("scheduled_via", None)
                unmarked += 1
        return unmarked

    def _cancel_platform_scheduled_posts(
            self, job_id: str, posts: list[tuple[str, str]]) -> None:
        """Best-effort platform cancellation of scheduled post ids.

        A rerender supersedes the accepted upload, so the live private post
        must not survive it. A platform that refuses or cannot be reached is
        recorded as a manifest warning: inventing a terminal state would lie
        about what the platform actually holds.
        """
        for platform, post_id in posts:
            try:
                adapter = _upload_adapter(platform)
                if adapter is None:
                    raise RuntimeError("no upload adapter is available")
                adapter.cancel_scheduled_post(post_id)
            except Exception as error:
                logger.warning("Could not cancel scheduled %s post %s: %s",
                               platform, post_id, error)
                with self._lock:
                    manifest = self.get_job(job_id)
                    manifest.warnings.append(
                        f"scheduled {platform} post {post_id} could not be "
                        f"cancelled: {error}")
                    manifest.save(self.jobs_dir)

    def discard_scheduled_uploads(self, job_id: str) -> int:
        """Disarm a job's scheduled uploads and persist the unmarked attempts.

        Used where the accepted upload is superseded without a draft edit, such
        as a rerender invalidating the upload checkpoint. Platform-scheduled
        attempts are not backed by a local timer, so their recorded post ids
        are handed to the platform as well, or the rerender would leave a live
        private post behind. Persists only when a schedule was actually pending.
        """
        with self._lock:
            manifest = self.get_job(job_id)
            posts = [(str(attempt.get("platform")),
                      str((attempt.get("result") or {}).get("platform_post_id")))
                     for attempt in manifest.upload_attempts
                     if (attempt.get("status") == "scheduled"
                         and attempt.get("scheduled_via") == "platform"
                         and (attempt.get("result") or {}).get("platform_post_id"))]
            unmarked = self._discard_scheduled_uploads_locked(manifest)
            if unmarked:
                manifest.save(self.jobs_dir)
        self._cancel_platform_scheduled_posts(job_id, posts)
        return unmarked

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
            # The draft accepted here is what the next submission uploads, so a
            # schedule armed by an earlier submission is dropped rather than
            # firing later with the superseded configuration. Done last, so a
            # rejected edit above leaves both the timer and the manifest intact.
            self._discard_scheduled_uploads_locked(manifest)
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
                      retry_of: str | None = None,
                      honor_schedule: bool = True) -> dict[str, Any]:
        # Resolve the submission outside the lock so platform-side existing-post
        # detection (network I/O) never runs while the service lock is held. The
        # artifact hash is verified here too, so detection never runs for bytes
        # that will be rejected anyway.
        pre_manifest = self.get_job(job_id)
        pre_artifact_id = artifact_id or pre_manifest.current_artifact_id
        pre_artifact = (pre_manifest.artifacts.get(pre_artifact_id)
                        if pre_artifact_id else None)
        if pre_artifact is None:
            raise ValueError("selected artifact is unavailable")
        pre_storage_key = pre_artifact["storage"]["key"]
        try:
            pre_actual_hash = self._staged_artifact_sha256(pre_storage_key)
        except FileNotFoundError as error:
            raise ValueError("selected artifact bytes are unavailable") from error
        if (not pre_artifact.get("sha256")
                or pre_actual_hash != pre_artifact["sha256"]):
            raise ValueError("selected artifact hash does not match manifest")
        pre_config = deepcopy(
            configuration_snapshot if configuration_snapshot is not None
            else pre_manifest.configuration.get("upload", {}))
        pre_settings = pre_config.get("platforms", {})
        pre_include = platforms or pre_settings.get("include")
        pre_selected = enabled_platforms({**pre_settings, "include": pre_include})
        pre_sha = pre_artifact.get("sha256")
        existing_posts, detection_unavailable = self._detect_existing_posts(
            pre_selected, pre_sha)

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
            artifact_key = artifact["storage"]["key"]
            try:
                actual_artifact_hash = self._staged_artifact_sha256(artifact_key)
            except FileNotFoundError as error:
                raise ValueError("selected artifact bytes are unavailable") from error
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

            scheduled_for = self._resolve_publish_at(
                upload_config, honor_schedule)
            schedule_mode = self._resolve_schedule_mode(
                upload_config, scheduled_for)
            upload_hash = configuration_sha256(upload_config)
            content_hash = configuration_sha256(upload_config.get("content", {}))
            if retry_of is None:
                self._reject_duplicate_active_attempt(
                    manifest, selected, artifact.get("sha256"), content_hash)
            if schedule_mode == "platform":
                # Strict by decision: a platform that cannot hold the future
                # publication is refused before any attempt exists, rather than
                # silently falling back to ClipMorph's own timer.
                self._reject_unsupported_schedule_platforms(selected)
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
                    "content_hash": content_hash,
                    "created_at": now,
                    "started_at": None,
                    "completed_at": None,
                    "status": "pending",
                    "result": None,
                }
                if retry_of is not None:
                    attempt["retry_of"] = retry_of
                if scheduled_for is not None:
                    attempt["scheduled_publish_at"] = scheduled_for.isoformat()
                    attempt["scheduled_via"] = schedule_mode
                    attempt["status"] = "scheduled"
                if platform in existing_posts:
                    post_id = existing_posts[platform]
                    attempt["status"] = "published"
                    attempt["started_at"] = now
                    attempt["completed_at"] = now
                    result_message = (
                        "skipped upload: platform already holds "
                        f"this content (id {post_id})")
                    attempt["result"] = {
                        "success": True,
                        "message": result_message,
                        "platform_post_id": post_id,
                        "platform_url": _platform_url(platform, post_id),
                        "published_at": now,
                    }
                    manifest.platforms[platform] = {
                        "success": True,
                        "status": "published",
                        "message": result_message,
                        "attempt_id": attempt["attempt_id"],
                        "artifact_id": attempt["artifact_id"],
                        "artifact_hash": attempt["artifact_hash"],
                        "platform_post_id": post_id,
                        "platform_url": _platform_url(platform, post_id),
                        "published_at": now,
                    }
                attempts.append(attempt)
                manifest.upload_attempts.append(attempt)
            checkpoint["artifact_hash"] = artifact.get("sha256")
            checkpoint["references"]["artifact_id"] = selected_artifact_id
            checkpoint["references"]["attempt_ids"] = [
                item["attempt_id"] for item in attempts]
            if all(item["status"] == "published" for item in attempts):
                # Every platform already holds this content, so the upload
                # checkpoint completes without running a pipeline. Transition
                # through "running" first: "awaiting_review" cannot jump straight
                # to "completed".
                manifest.transition_checkpoint(
                    "upload", "running", checkpoint["revision"], self.jobs_dir)
                checkpoint = manifest.checkpoints["upload"]
                manifest.transition_checkpoint(
                    "upload", "completed", checkpoint["revision"], self.jobs_dir)
            else:
                manifest.transition_checkpoint(
                    "upload", "running", checkpoint["revision"], self.jobs_dir)

        attempt_ids = [attempt["attempt_id"] for attempt in attempts
                       if attempt["status"] != "published"]
        upload_platforms = [platform for platform in selected
                            if platform not in existing_posts]
        scheduled_config = upload_config
        if scheduled_for is not None and schedule_mode == "platform":
            # The platform holds the publication from the moment the upload
            # lands, so submission is immediate: the resolved instant rides the
            # ordinary per-platform override shape (which is what becomes the
            # adapter's ``scheduled_publish_at`` keyword), while the attempt's
            # frozen snapshot keeps recording the configuration the user
            # accepted.
            scheduled_config = deepcopy(upload_config)
            overrides = scheduled_config.setdefault("platforms", {})
            for platform in upload_platforms:
                platform_overrides = overrides.get(platform)
                platform_overrides = (deepcopy(platform_overrides)
                                      if isinstance(platform_overrides, dict)
                                      else {})
                platform_overrides["scheduled_publish_at"] = (
                    scheduled_for.isoformat())
                overrides[platform] = platform_overrides
        if scheduled_for is not None and schedule_mode == "local" and attempt_ids:
            self._schedule_attempts(
                job_id, attempt_ids, artifact_key, upload_config,
                upload_platforms, scheduled_for)
        elif attempt_ids:
            future = self.executor.submit(
                self._run_upload_attempts, job_id, attempt_ids,
                artifact_key, scheduled_config, upload_platforms)
            with self._lock:
                self._futures[f"upload:{job_id}"] = future
        return {"job_id": job_id, "attempts": attempts,
                "scheduled": scheduled_for is not None,
                "scheduled_via": (schedule_mode
                                  if scheduled_for is not None else None),
                "status_url": f"/api/v1/jobs/{job_id}",
                "detection": {
                    "existing_posts": existing_posts,
                    "unavailable": detection_unavailable,
                }}

    def _reject_duplicate_active_attempt(self, manifest: JobManifest,
                                        platforms: list[str],
                                        artifact_sha: str | None,
                                        content_hash: str) -> None:
        """Raise when an active attempt already targets the same content.

        A scheduled or immediate submission is refused when the same platform
        already holds a pending, scheduled, or running attempt for the same
        artifact bytes and upload content. Exact-attempt retries bypass this
        guard because they name the failed attempt being retried.
        """
        for attempt in manifest.upload_attempts:
            if (attempt.get("platform") in platforms
                    and attempt.get("artifact_hash") == artifact_sha
                    and attempt.get("content_hash") == content_hash
                    and attempt.get("status") in ACTIVE_ATTEMPT_STATUSES):
                raise ValueError(
                    f"active upload attempt exists for {attempt['platform']} "
                    f"(attempt {attempt['attempt_id']})")

    def _detect_existing_posts(
            self, platforms: list[str],
            artifact_sha: str | None) -> tuple[dict[str, str], list[str]]:
        """Run platform-side existing-post detection outside the service lock.

        Returns ``(found, unavailable)``: ``found`` maps a platform to the id
        of an existing post carrying the artifact marker; ``unavailable``
        lists platforms whose detection hook could not run (for example a
        token that lacks the read scope). Detection is best-effort and never
        blocks a submission.
        """
        from clipmorph.platforms import PLATFORM_TITLE
        from clipmorph.upload_pipeline import UploadPipeline

        found: dict[str, str] = {}
        unavailable: list[str] = []
        if not artifact_sha:
            return found, unavailable
        pipeline = UploadPipeline(**{platform: True for platform in platforms})
        for platform in platforms:
            adapter = pipeline.enabled_platforms.get(
                PLATFORM_TITLE.get(platform, platform))
            if adapter is None:
                continue
            if getattr(adapter, "supports_existing_detection", False) is not True:
                continue
            try:
                post_id = adapter.find_existing_post(artifact_sha)
            except Exception as error:
                logger.warning("existing-post detection unavailable for %s: %s",
                               platform, error)
                unavailable.append(platform)
                continue
            if isinstance(post_id, str) and post_id:
                found[platform] = post_id
        return found, unavailable

    @staticmethod
    def _resolve_schedule_mode(upload_config: dict[str, Any],
                               publish_at: datetime | None) -> str:
        """Return who holds a future publication: "local" or "platform".

        The configured mode is inert without a deferred upload: with no future
        ``publish_at`` there is nothing to schedule, so an immediate submission
        reads as ``local`` whatever the mode says.
        """
        schedule = upload_config.get("schedule") or {}
        mode = schedule.get("mode") if isinstance(schedule, dict) else None
        if publish_at is None:
            return "local"
        return mode if mode == "platform" else "local"

    @staticmethod
    def _reject_unsupported_schedule_platforms(platforms: list[str]) -> None:
        """Refuse a platform-scheduled submission the registry cannot bless.

        A platform's registry entry in ``SUPPORTED_NATIVE_SCHEDULING`` is only
        ``True`` after the maintainer's sandbox probe, so this raises for every
        platform that cannot hold the publication itself. The message names the
        probe so the gate is actionable instead of mysterious.
        """
        culprits = [platform for platform in platforms
                    if not native_scheduling_support(platform)]
        if culprits:
            raise ValueError(
                "upload.schedule.mode platform is not enabled for: "
                f"{', '.join(culprits)}\n"
                "See quality/research/scheduling_probe.py — run it with "
                "sandbox tokens, then flip SUPPORTED_NATIVE_SCHEDULING in "
                "clipmorph/platforms.py.")

    @staticmethod
    def _resolve_publish_at(upload_config: dict[str, Any],
                            honor_schedule: bool) -> datetime | None:
        """Return the future publish_at to defer to, or None to run now."""
        if not honor_schedule:
            # A retry is an explicit immediate user action.
            return None
        schedule = upload_config.get("schedule") or {}
        if not isinstance(schedule, dict):
            raise ValueError("upload.schedule must be an object")
        publish_at = schedule.get("publish_at")
        if publish_at is None or not isinstance(publish_at, str) or not publish_at.strip():
            return None
        try:
            parsed = _parse_utc_timestamp(publish_at)
        except ValueError as error:
            raise ValueError(
                f"upload.schedule.publish_at is not an ISO-8601 timestamp: {error}"
            ) from error
        if parsed <= (datetime.now(timezone.utc)
                      + timedelta(seconds=SCHEDULE_MINIMUM_DELAY_SECONDS)):
            return None
        return parsed

    def _on_progress(self, job_id: str) -> Callable[[str, int], None]:
        """Return a progress callback that records live percents for one job."""
        def record(platform: str, percent: int) -> None:
            with self._lock:
                self._live_progress.setdefault(job_id, {})[platform.lower()] = percent
        return record

    def live_progress_for(self, job_id: str) -> dict[str, int]:
        """Return a copy of the live upload percents for one job.

        Empty when no upload is in flight; the final snapshot persists in the
        attempt record instead.
        """
        with self._lock:
            return dict(self._live_progress.get(job_id, {}))

    def _run_upload_attempts(self, job_id: str, attempt_ids: list[str],
                             artifact_key: str, upload_config: dict[str, Any],
                             platforms: list[str]) -> None:
        from clipmorph.upload_attempts import execute_upload_pipeline
        from clipmorph.upload_attempts import normalize_results
        with self._lock:
            manifest = self.get_job(job_id)
            now = datetime.now(timezone.utc).isoformat()
            runnable: list[str] = []
            for attempt_id in attempt_ids:
                attempt = next((item for item in manifest.upload_attempts
                                if item["attempt_id"] == attempt_id), None)
                if attempt is None:
                    continue
                if attempt["status"] in TERMINAL_ATTEMPT_STATUSES:
                    # One member of a batch group can be cancelled while the
                    # group's timer is still armed, so a stale timer must never
                    # resurrect a terminal attempt as published.
                    logger.info(
                        "Skipping terminal upload attempt %s of job %s",
                        attempt_id, job_id)
                    continue
                attempt["status"] = "running"
                attempt["started_at"] = now
                runnable.append(attempt_id)
            if runnable:
                manifest.save(self.jobs_dir)
        if not runnable:
            # Nothing this group can still do: the checkpoint keeps whatever
            # state the cancel left it in.
            return
        try:
            staged_path = self._stage_artifact(artifact_key)
        except Exception as error:
            # Staging is the precondition of the transport, so a storage
            # failure fails the attempts the way an upload failure does and is
            # recorded with its own code.
            message = safe_error_message(error)
            self._record_manifest_error(job_id, "staging_failed", message)
            now = datetime.now(timezone.utc).isoformat()
            results = {platform: {
                "success": False,
                "error": f"artifact staging failed: {message}",
                "started_at": now, "completed_at": now} for platform in platforms}
        else:
            try:
                results = execute_upload_pipeline(
                    platforms, str(staged_path), upload_config,
                    progress_callback=self._on_progress(job_id))
            except Exception as error:
                now = datetime.now(timezone.utc).isoformat()
                results = {platform: {"success": False, "error": str(error),
                                      "started_at": now, "completed_at": now}
                           for platform in platforms}
            finally:
                self._release_staging(staged_path)

        normalized_results = normalize_results(results)
        with self._lock:
            manifest = self.get_job(job_id)
            success_count = 0
            failure_count = 0
            live_progress = self._live_progress.get(job_id, {})
            for attempt_id in runnable:
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
                completed_at = (result.get("completed_at")
                                or datetime.now(timezone.utc).isoformat())
                attempt["completed_at"] = completed_at
                post_id = result.get("result")
                if success and not isinstance(post_id, str):
                    post_id = None
                platform_scheduled = (attempt.get("scheduled_via") == "platform")
                attempt["status"] = (
                    "scheduled" if success and platform_scheduled
                    else "published" if success else "failed")
                if success and platform_scheduled:
                    attempt["result"] = {
                        "success": True,
                        "message": (
                            "uploaded private; platform holds publication "
                            f"until {attempt.get('scheduled_publish_at')}"),
                        "platform_post_id": post_id,
                        "platform_url": (_platform_url(platform, post_id)
                                         if post_id else None),
                        "scheduled_publish_at": attempt.get(
                            "scheduled_publish_at"),
                        "published_at": None,
                        "progress_percent": live_progress.get(
                            platform.lower(), 0),
                    }
                    manifest.platforms[platform] = {
                        "success": True,
                        "status": "scheduled",
                        "message": attempt["result"]["message"],
                        "attempt_id": attempt_id,
                        "artifact_id": attempt["artifact_id"],
                        "artifact_hash": attempt["artifact_hash"],
                        "platform_post_id": post_id,
                        "platform_url": attempt["result"]["platform_url"],
                        "scheduled_publish_at": attempt["result"][
                            "scheduled_publish_at"],
                        "published_at": None,
                    }
                    success_count += 1
                    continue
                attempt["result"] = {
                    "success": success,
                    "message": str(result.get("error") or result.get("result") or "")[:1000],
                    "platform_post_id": post_id if success else None,
                    "platform_url": (_platform_url(platform, post_id)
                                     if success and post_id else None),
                    "published_at": completed_at if success else None,
                    "progress_percent": live_progress.get(platform.lower(), 0),
                }
                manifest.platforms[platform] = {
                    "success": success,
                    "status": "published" if success else "failed",
                    "message": attempt["result"]["message"],
                    "attempt_id": attempt_id,
                    "artifact_id": attempt["artifact_id"],
                    "artifact_hash": attempt["artifact_hash"],
                    "platform_post_id": attempt["result"]["platform_post_id"],
                    "platform_url": attempt["result"]["platform_url"],
                    "published_at": attempt["result"]["published_at"],
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
            # The final snapshot is written; clear the live registry so a
            # restart (or a later submission) starts from empty.
            self._live_progress.pop(job_id, None)

    def _record_manifest_error(self, job_id: str, code: str,
                               message: str) -> None:
        """Append one coded error to a job's manifest."""
        with self._lock:
            manifest = self.get_job(job_id)
            manifest.errors.append({
                "code": code,
                "message": message,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            })
            manifest.save(self.jobs_dir)

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
        if artifact is None:
            raise ValueError("retry artifact bytes are unavailable")
        artifact_key = artifact["storage"]["key"]
        try:
            actual_hash = self._staged_artifact_sha256(artifact_key)
        except FileNotFoundError as error:
            raise ValueError("retry artifact bytes are unavailable") from error
        if (not artifact.get("sha256")
                or actual_hash != artifact["sha256"]
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
            retry_of=attempt_id, honor_schedule=False)
        return retry_result

    def enforce_retention(self, job_id: str) -> dict[str, Any]:
        """Prune superseded artifacts per the app.yml retention policy.

        Candidates are non-source artifacts in the `superseded` state, aged from
        `superseded_at` (falling back to `created_at`). `current` and `stale`
        artifacts are never touched, so a rerender target always survives. Every
        knob defaults to null, which makes this a no-op until a policy is set.
        """
        policy = load_app_configuration(
            self.app_config_path).get("retention", {}).get("artifacts", {})
        max_age_days = policy.get("max_age_days")
        max_bytes = policy.get("max_bytes")
        manifest = self.get_job(job_id)
        if max_age_days is None and max_bytes is None:
            return {"pruned": []}

        now = datetime.now(timezone.utc)
        total_bytes = 0
        obsolete: list[tuple[str, datetime, int]] = []
        for artifact_id, artifact in manifest.artifacts.items():
            size = _artifact_size(artifact, self._storage)
            if artifact.get("state") != "deleted":
                total_bytes += size
            if (artifact.get("state") != "superseded"
                    or artifact.get("kind") == "source"):
                continue
            stamp = artifact.get("superseded_at") or artifact.get("created_at")
            try:
                obsolete_at = _parse_utc_timestamp(stamp) if isinstance(
                    stamp, str) else now
            except ValueError:
                obsolete_at = now
            obsolete.append((artifact_id, obsolete_at, size))
        obsolete.sort(key=lambda item: (item[1], item[0]))

        selected: set[str] = set()
        if max_age_days is not None:
            cutoff = now - timedelta(days=max_age_days)
            selected.update(artifact_id for artifact_id, obsolete_at, _size
                            in obsolete if obsolete_at <= cutoff)
        if max_bytes is not None:
            remaining = total_bytes - sum(
                size for artifact_id, _at, size in obsolete
                if artifact_id in selected)
            for artifact_id, _obsolete_at, size in obsolete:
                if artifact_id in selected or remaining <= max_bytes:
                    continue
                selected.add(artifact_id)
                remaining -= size

        pruned: list[str] = []
        bytes_freed = 0
        if selected:
            now_iso = now.isoformat()
            for artifact_id, _obsolete_at, size in obsolete:
                if artifact_id not in selected:
                    continue
                artifact = manifest.artifacts[artifact_id]
                storage_key = artifact["storage"]["key"]
                try:
                    self._storage.remove(storage_key)
                    bytes_freed += size
                except Exception as error:
                    logger.warning("Could not remove artifact %s: %s",
                                   artifact_id, error)
                    manifest.warnings.append(
                        f"artifact {artifact_id} could not be recycled: {error}")
                    continue
                artifact["state"] = "deleted"
                artifact["deleted_at"] = now_iso
                pruned.append(artifact_id)
            manifest.save(self.jobs_dir)
        return {"pruned": pruned, "bytes_freed": bytes_freed}

    def _enforce_retention_quietly(self, job_id: str) -> None:
        """Apply retention after a run, never failing the job over cleanup."""
        try:
            self.enforce_retention(job_id)
        except Exception as error:  # cleanup must not mask job results
            logger.warning("Retention enforcement failed for %s: %s",
                           job_id, error)

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
            if not token.is_cancelled:
                # The conversion flow records its artifact during execute_job, so
                # this is the one post-run point where obsolete bytes are known.
                self._enforce_retention_quietly(job_id)
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
        elif manifest.status == "scheduled":
            self.cancel_all_scheduled_uploads(job_id)
            self._cancel_manifest(self.get_job(job_id))
        return self.get_job(job_id)

    def cancel_all_scheduled_uploads(self, job_id: str) -> int:
        """Abort a job's scheduled upload attempts before their timers fire.

        Disarms the armed timers and moves every ``scheduled`` attempt to the
        ``cancelled`` terminal state. Returns the number of attempts cancelled.
        """
        with self._lock:
            manifest = self.get_job(job_id)
            for timer in self._scheduled_timers.pop(f"upload:{job_id}", []):
                timer.cancel()
            cancelled = 0
            now = datetime.now(timezone.utc).isoformat()
            for attempt in manifest.upload_attempts:
                if attempt.get("status") == "scheduled":
                    attempt["status"] = "cancelled"
                    attempt["completed_at"] = now
                    self._attempt_timers.pop(str(attempt.get("attempt_id")), None)
                    cancelled += 1
            if cancelled:
                manifest._derive_status()
                manifest.save(self.jobs_dir)
            return cancelled

    def cancel_scheduled_upload(self, job_id: str,
                                attempt_id: str) -> dict[str, Any]:
        """Cancel one scheduled upload attempt before its publication.

        A local-path attempt is disarmed locally: its batch timer is cancelled
        and the surviving group members are re-armed through the ordinary
        re-arm path. A platform-scheduled attempt is not backed by a local
        timer, so the adapter owns the platform action: its scheduled post is
        cancelled first and the attempt only becomes terminal once the platform
        confirms. A platform that refuses leaves the attempt ``scheduled`` with
        the reason in its ``errors`` list, because a forced terminal state would
        claim a visibility the platform never granted.
        """
        manifest = self.get_job(job_id)
        attempt = next((item for item in manifest.upload_attempts
                        if item.get("attempt_id") == attempt_id), None)
        if attempt is None:
            raise UnknownUploadAttempt(
                f"upload attempt {attempt_id} was not found in job {job_id}")
        if attempt.get("status") != "scheduled":
            raise UploadAttemptNotScheduled(
                f"upload attempt {attempt_id} is {attempt.get('status')}, "
                "not scheduled")
        platform = str(attempt.get("platform"))
        via = attempt.get("scheduled_via")
        post_id = (attempt.get("result") or {}).get("platform_post_id")
        if via == "platform":
            self._cancel_scheduled_post(job_id, platform, attempt_id, post_id)
        else:
            self._disarm_attempt_timers(job_id, [attempt_id])
        with self._lock:
            manifest = self.get_job(job_id)
            attempt = next(item for item in manifest.upload_attempts
                           if item.get("attempt_id") == attempt_id)
            now = datetime.now(timezone.utc).isoformat()
            attempt["status"] = "cancelled"
            attempt["completed_at"] = now
            if via == "platform":
                attempt["result"] = {
                    "success": True,
                    "message": f"scheduled {platform} post {post_id} cancelled",
                    "platform_post_id": post_id,
                    "platform_url": _platform_url(platform, str(post_id)),
                    "scheduled_publish_at": attempt.get("scheduled_publish_at"),
                    "published_at": None,
                }
            checkpoint = manifest.checkpoints.get("upload", {})
            still_waiting = any(
                item.get("status") in ACTIVE_ATTEMPT_STATUSES
                for item in manifest.upload_attempts)
            if checkpoint.get("status") == "running" and not still_waiting:
                # Nothing is left to publish, so the pass the user just
                # cancelled must not keep the job reading as scheduled.
                manifest.transition_checkpoint(
                    "upload", "cancelled", checkpoint["revision"],
                    self.jobs_dir)
            else:
                manifest._derive_status()
                manifest.save(self.jobs_dir)
        if via != "platform":
            # The cancelled attempt shared its batch timer with the members
            # still waiting on the same publish_at, so they are re-armed.
            self._arm_manifest_schedules(self.get_job(job_id))
        return {"job_id": job_id, "attempt_id": attempt_id,
                "platform": platform, "scheduled_via": via,
                "status": "cancelled"}

    def _cancel_scheduled_post(self, job_id: str, platform: str,
                               attempt_id: str, post_id: Any) -> None:
        """Ask the platform to drop one scheduled post, or record why it stayed.

        A platform-scheduled attempt with no recorded post id is a submission
        that never landed, so there is nothing to delete and the attempt is
        safe to cancel locally. A refusal leaves the attempt ``scheduled`` with
        the reason in its ``errors`` list and raises.
        """
        if not isinstance(post_id, str) or not post_id:
            return
        try:
            adapter = _upload_adapter(platform)
            if adapter is None:
                raise RuntimeError("no upload adapter is available")
            adapter.cancel_scheduled_post(post_id)
        except Exception as error:
            message = safe_error_message(error)
            logger.warning("Could not cancel scheduled %s post %s: %s",
                           platform, post_id, message)
            with self._lock:
                manifest = self.get_job(job_id)
                attempt = next(item for item in manifest.upload_attempts
                               if item.get("attempt_id") == attempt_id)
                attempt.setdefault("errors", []).append({
                    "code": "platform_cancel_failed",
                    "message": message[:500],
                    "retryable": True,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                })
                manifest.save(self.jobs_dir)
            raise ValueError(
                f"the {platform} platform refused to cancel post {post_id}: "
                f"{message}")

    def list_upload_attempts(self, job_id: str, status: str | None = None,
                             platform: str | None = None,
                             since: str | None = None) -> list[dict[str, Any]]:
        """Return a job's upload attempts filtered by status, platform, or age.

        ``since`` keeps only attempts created at or after the given ISO-8601
        instant; an unparsable value raises ``ValueError``.
        """
        manifest = self.get_job(job_id)
        attempts = list(manifest.upload_attempts)
        if status is not None:
            attempts = [item for item in attempts if item.get("status") == status]
        if platform is not None:
            attempts = [item for item in attempts
                        if item.get("platform") == platform.lower()]
        if since is not None:
            try:
                cutoff = _parse_utc_timestamp(since)
            except ValueError as error:
                raise ValueError(
                    f"since is not an ISO-8601 timestamp: {error}") from error
            attempts = [item for item in attempts
                        if _attempt_on_or_after(item, cutoff)]
        return attempts

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
        # Unlike discard_scheduled_uploads, a clean shutdown leaves the attempts
        # marked: the next startup re-arms them instead of losing the schedule.
        with self._lock:
            timers = [timer for group in self._scheduled_timers.values()
                      for timer in group]
            self._scheduled_timers.clear()
            self._attempt_timers.clear()
        for timer in timers:
            timer.cancel()
        self.executor.shutdown(wait=True, cancel_futures=False)


def _artifact_size(artifact: dict[str, Any],
                   storage: ArtifactStorage) -> int:
    """Return one artifact's stored size, or 0 when its bytes are gone.

    Only a backend that owns local bytes is measured today; a remote backend
    reports its own object sizes when it lands, and until then its artifacts
    count as nothing toward ``retention.artifacts.max_bytes``.
    """
    key = artifact.get("storage", {}).get("key", "")
    if not key or not isinstance(storage, LocalArtifactStorage):
        return 0
    try:
        path = storage.local_path(key)
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _attempt_on_or_after(attempt: dict[str, Any], cutoff: datetime) -> bool:
    """Report whether an attempt was created at or after ``cutoff``."""
    stamp = attempt.get("created_at")
    if not isinstance(stamp, str):
        return False
    try:
        return _parse_utc_timestamp(stamp) >= cutoff
    except ValueError:
        return False

