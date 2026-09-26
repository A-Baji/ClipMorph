from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from typing import Any

from platformdirs import user_data_dir
import yaml

from clipmorph.configuration import atomic_write_text


APP_NAME = "ClipMorph"
MANIFEST_SCHEMA_VERSION = 2
CHECKPOINT_STATES = {
    "pending", "running", "awaiting_review", "completed", "partial_failure",
    "skipped", "failed", "cancelled", "stale",
}
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(client_secret|api_key|access_token|refresh_token|password|secret|token)"
    r"(\s*[=:]\s*)([^\s,;&]+)")


def safe_error_message(message: Any) -> str:
    return _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", str(message))[:1000]
CHECKPOINT_TRANSITIONS = {
    "transcript": {
        "pending": {"running", "awaiting_review", "skipped", "failed", "cancelled"},
        "running": {"awaiting_review", "completed", "failed", "cancelled"},
        "awaiting_review": {"awaiting_review", "completed", "pending", "cancelled"},
        "completed": {"stale"}, "partial_failure": {"pending", "stale"},
        "skipped": {"pending"}, "failed": {"pending"}, "cancelled": {"pending"},
        "stale": {"pending", "running", "awaiting_review", "skipped"},
    },
    "conversion": {
        "pending": {"running", "awaiting_review", "skipped", "failed", "cancelled"},
        "running": {"awaiting_review", "completed", "failed", "cancelled"},
        "awaiting_review": {"awaiting_review", "completed", "pending", "cancelled"},
        "completed": {"stale"}, "partial_failure": {"pending", "stale"},
        "skipped": {"pending"}, "failed": {"pending"}, "cancelled": {"pending"},
        "stale": {"pending", "running", "awaiting_review", "skipped"},
    },
    "upload": {
        "pending": {"awaiting_review", "running", "skipped", "failed", "cancelled"},
        "awaiting_review": {"awaiting_review", "running", "pending", "cancelled"},
        "running": {"completed", "partial_failure", "failed", "cancelled"},
        "completed": {"stale"}, "partial_failure": {"running", "stale", "pending"},
        "skipped": {"pending"}, "failed": {"pending"}, "cancelled": {"pending"},
        "stale": {"pending", "awaiting_review", "running", "skipped"},
    },
}


def default_data_dir() -> Path:
    """Return the platform-specific application data directory."""
    return Path(user_data_dir(APP_NAME))


def default_jobs_dir() -> Path:
    return default_data_dir() / "jobs"


def default_output_dir(data_dir: str | Path | None = None) -> Path:
    """Return the default directory for generated media artifacts."""
    root = Path(data_dir) if data_dir else default_data_dir()
    return root / "output"


def resolve_output_dir(output_dir: str | Path | None = None,
                       data_dir: str | Path | None = None) -> Path:
    """Resolve relative output paths inside the selected ClipMorph data directory."""
    path = Path(output_dir) if output_dir else Path("output")
    if path.is_absolute():
        return path
    return (Path(data_dir) if data_dir else default_data_dir()) / path


def source_sha256(source_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(source_path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configuration_sha256(configuration: dict[str, Any]) -> str:
    canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def checkpoint_configuration_hash(configuration: dict[str, Any], stage: str) -> str:
    dependencies = {
        "transcript": {
            "conversion.subtitles": configuration.get("conversion", {}).get("subtitles", {}),
        },
        "conversion": {"conversion": configuration.get("conversion", {})},
        "upload": {"upload": configuration.get("upload", {})},
    }
    if stage not in dependencies:
        raise ValueError(f"Unknown checkpoint: {stage}")
    return configuration_sha256(dependencies[stage])


def _checkpoint_record(stage: str, configuration: dict[str, Any],
                       status: str = "pending") -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "status": status,
        "revision": 0,
        "configuration_hash": checkpoint_configuration_hash(configuration, stage),
        "artifact_hash": None,
        "created_at": now,
        "started_at": None,
        "updated_at": now,
        "completed_at": None,
        "invalidation_reason": None,
        "error": None,
        "attempts": [],
        "references": {},
    }


@dataclass
class JobManifest:
    schema_version: int
    job_id: str
    source_path: str
    source_sha256: str
    configuration: dict[str, Any]
    configuration_sources: dict[str, Any] = field(default_factory=dict)
    current_configuration_hash: str = ""
    current_checkpoint: str | None = None
    checkpoints: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_transcript: dict[str, Any] | None = None
    current_artifact_id: str | None = None
    upload_attempts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    status: str = "created"
    artifact_path: str | None = None
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(cls, source_path: str, configuration: dict[str, Any],
               jobs_dir: str | Path | None = None,
               global_defaults: dict[str, Any] | None = None) -> JobManifest:
        path = Path(source_path)
        finalized = json.loads(json.dumps(configuration))
        general = finalized.setdefault("general", {})
        general.setdefault("source", path.name)
        conversion = finalized.get("conversion", {})
        subtitles = conversion.get("subtitles", {})
        upload = finalized.get("upload", {})
        checkpoints = {
            "transcript": _checkpoint_record(
                "transcript", finalized,
                "skipped" if conversion.get("skip") or subtitles.get("skip") else "pending"),
            "conversion": _checkpoint_record(
                "conversion", finalized,
                "skipped" if conversion.get("skip") else "pending"),
            "upload": _checkpoint_record(
                "upload", finalized,
                "skipped" if upload.get("skip") else "pending"),
        }
        manifest = cls(
            schema_version=MANIFEST_SCHEMA_VERSION,
            job_id=uuid.uuid4().hex,
            source_path=str(path.resolve()),
            source_sha256=source_sha256(path),
            configuration=finalized,
            configuration_sources={
                "global_defaults": json.loads(json.dumps(global_defaults or {})),
            },
            current_configuration_hash=configuration_sha256(finalized),
            current_checkpoint=None,
            checkpoints=checkpoints,
        )
        manifest.current_checkpoint = manifest._next_checkpoint()
        manifest.save(jobs_dir)
        return manifest

    @classmethod
    def load(cls, job_id: str, jobs_dir: str | None = None) -> JobManifest:
        directory = Path(jobs_dir) if jobs_dir else default_jobs_dir()
        path = directory / job_id / "manifest.json"
        for attempt in range(4):
            try:
                with path.open("r", encoding="utf-8") as manifest_file:
                    data = json.load(manifest_file)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.01 * (attempt + 1))
        if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ValueError("Unsupported job manifest schema version")
        return cls(**data)

    def save(self, jobs_dir: str | Path | None = None) -> Path:
        directory = Path(jobs_dir) if jobs_dir else default_jobs_dir()
        directory = directory / self.job_id
        directory.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.current_configuration_hash = configuration_sha256(self.configuration)
        self.current_checkpoint = self._next_checkpoint()
        job_config_path = directory / "job.yml"
        atomic_write_text(
            job_config_path,
            yaml.safe_dump(self.configuration, sort_keys=False, allow_unicode=True))
        path = directory / "manifest.json"
        return atomic_write_text(path, json.dumps(asdict(self), indent=2))

    def _next_checkpoint(self) -> str | None:
        for stage in ("transcript", "conversion", "upload"):
            if self.checkpoints.get(stage, {}).get("status") in {
                    "pending", "running", "awaiting_review", "failed",
                    "cancelled", "stale", "partial_failure"}:
                return stage
        return None

    def transition_checkpoint(self, stage: str, status: str,
                              expected_revision: int,
                              jobs_dir: str | Path | None = None,
                              error: dict[str, Any] | None = None,
                              invalidation_reason: dict[str, Any] | None = None,
                              references: dict[str, Any] | None = None
                              ) -> dict[str, Any]:
        if stage not in self.checkpoints:
            raise ValueError(f"Unknown checkpoint: {stage}")
        if status not in CHECKPOINT_STATES:
            raise ValueError(f"Unknown checkpoint status: {status}")
        checkpoint = self.checkpoints[stage]
        if checkpoint["revision"] != expected_revision:
            raise ValueError("stale checkpoint revision")
        if status not in CHECKPOINT_TRANSITIONS[stage].get(checkpoint["status"], set()):
            raise ValueError(
                f"illegal {stage} checkpoint transition: {checkpoint['status']} -> {status}")
        now = datetime.now(timezone.utc).isoformat()
        checkpoint["revision"] += 1
        checkpoint["status"] = status
        checkpoint["updated_at"] = now
        if status == "running":
            checkpoint["started_at"] = now
            checkpoint["attempts"].append({
                "attempt": len(checkpoint["attempts"]) + 1,
                "started_at": now,
                "status": "running",
            })
        if status in {"completed", "failed", "partial_failure", "cancelled"}:
            checkpoint["completed_at"] = now
            if checkpoint["attempts"] and checkpoint["attempts"][-1]["status"] == "running":
                checkpoint["attempts"][-1]["status"] = status
                checkpoint["attempts"][-1]["completed_at"] = now
        if error is not None:
            safe_error = {
                "code": str(error.get("code", "checkpoint_error")),
                "message": safe_error_message(error.get("message", "")),
                "occurred_at": now,
                "attempt_id": error.get("attempt_id"),
                "retryable": bool(error.get("retryable", False)),
            }
            checkpoint["error"] = safe_error
        elif status != "failed":
            checkpoint["error"] = None
        if invalidation_reason is not None:
            checkpoint["invalidation_reason"] = invalidation_reason
        if references is not None:
            checkpoint["references"].update(references)
        self._derive_status()
        self.save(jobs_dir)
        return checkpoint

    def invalidate_checkpoint(self, stage: str, reason: dict[str, Any],
                              jobs_dir: str | Path | None = None,
                              persist: bool = True) -> None:
        checkpoint = self.checkpoints[stage]
        if checkpoint["status"] == "skipped":
            return
        if stage == "conversion" and self.current_artifact_id in self.artifacts:
            artifact = self.artifacts[self.current_artifact_id]
            if artifact.get("state") == "current":
                artifact["state"] = "stale"
        checkpoint["revision"] += 1
        checkpoint["status"] = "stale"
        checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
        checkpoint["completed_at"] = None
        checkpoint["invalidation_reason"] = {
            "code": str(reason.get("code", "configuration_changed")),
            "message": str(reason.get("message", "Inputs changed"))[:500],
        }
        if persist:
            self._derive_status()
            self.save(jobs_dir)

    def _derive_status(self) -> None:
        statuses = [checkpoint["status"] for checkpoint in self.checkpoints.values()]
        if "failed" in statuses:
            self.status = "failed"
        elif "cancelled" in statuses:
            self.status = "cancelled"
        elif "partial_failure" in statuses:
            self.status = "partial_failure"
        elif "running" in statuses:
            self.status = "running"
        elif "awaiting_review" in statuses:
            self.status = "awaiting_review"
        elif any(status in {"pending", "stale"} for status in statuses):
            self.status = "queued"
        else:
            self.status = "completed"

    def set_status(self, status: str, jobs_dir: str | None = None):
        self.status = status
        self.save(jobs_dir)

    def set_step(self, step: str, status: str, jobs_dir: str | None = None,
                 **details: Any):
        self.steps[step] = {"status": status, **details}
        self.save(jobs_dir)

    def set_artifact(self, artifact_path: str, jobs_dir: str | None = None,
                     name: str = "primary"):
        return self.record_artifact(name, artifact_path, jobs_dir)

    def record_artifact(self, name: str, artifact_path: str,
                        jobs_dir: str | None = None,
                        schema_version: int = MANIFEST_SCHEMA_VERSION):
        resolved_path = Path(artifact_path).resolve()
        if self.current_artifact_id in self.artifacts:
            current = self.artifacts[self.current_artifact_id]
            if current.get("state") == "current":
                current["state"] = "superseded"
        revision = max((item.get("revision", 0)
                        for item in self.artifacts.values()), default=0) + 1
        artifact_id = uuid.uuid4().hex
        artifact_hash = source_sha256(resolved_path) if resolved_path.is_file() else None
        self.artifacts[artifact_id] = {
            "id": artifact_id,
            "revision": revision,
            "kind": name,
            "path": str(resolved_path),
            "sha256": artifact_hash,
            "configuration_hash": self.checkpoints.get(
                "conversion", {}).get("configuration_hash"),
            "transcript_revision": (self.active_transcript or {}).get("revision"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state": "current",
            "display_name": resolved_path.name,
            "schema_version": schema_version,
            "source_sha256": self.source_sha256,
        }
        self.current_artifact_id = artifact_id
        self.artifact_path = str(resolved_path)
        conversion = self.checkpoints.get("conversion")
        if conversion is not None:
            conversion["artifact_hash"] = artifact_hash
            conversion["references"]["artifact_id"] = artifact_id
        self.save(jobs_dir)

    def record_platform(self, platform: str, result: dict[str, Any],
                        jobs_dir: str | None = None):
        self.platforms[platform] = result
        if self.platforms and all(
                item.get("success") for item in self.platforms.values()):
            self.status = "published"
        else:
            self.status = "partial_failure"
        self.save(jobs_dir)
