from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from typing import Any

from platformdirs import user_data_dir


APP_NAME = "ClipMorph"
MANIFEST_SCHEMA_VERSION = 1


def default_data_dir() -> Path:
    """Return the platform-specific application data directory."""
    return Path(user_data_dir(APP_NAME))


def default_jobs_dir() -> Path:
    return default_data_dir() / "jobs"


def source_sha256(source_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(source_path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class JobManifest:
    schema_version: int
    job_id: str
    source_path: str
    source_sha256: str
    configuration: dict[str, Any]
    status: str = "created"
    artifact_path: str | None = None
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(cls, source_path: str, configuration: dict[str, Any],
               jobs_dir: str | None = None) -> JobManifest:
        path = Path(source_path)
        manifest = cls(MANIFEST_SCHEMA_VERSION, uuid.uuid4().hex,
                       str(path.resolve()), source_sha256(path), configuration)
        manifest.save(jobs_dir)
        return manifest

    @classmethod
    def load(cls, job_id: str, jobs_dir: str | None = None) -> JobManifest:
        directory = Path(jobs_dir) if jobs_dir else default_jobs_dir()
        path = directory / job_id / "manifest.json"
        if not path.exists():
            # Read manifests created by older releases.
            path = directory / f"{job_id}.json"
        if not path.exists() and jobs_dir is None:
            path = Path.cwd() / ".clipmorph" / "jobs" / f"{job_id}.json"
        with path.open("r", encoding="utf-8") as manifest_file:
            data = json.load(manifest_file)
        data.setdefault("schema_version", 0)
        data.setdefault("artifacts", {})
        data.setdefault("steps", {})
        return cls(**data)

    def save(self, jobs_dir: str | None = None) -> Path:
        directory = Path(jobs_dir) if jobs_dir else default_jobs_dir()
        directory = directory / self.job_id
        directory.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        path = directory / "manifest.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def set_status(self, status: str, jobs_dir: str | None = None):
        self.status = status
        self.save(jobs_dir)

    def set_step(self, step: str, status: str, jobs_dir: str | None = None,
                 **details: Any):
        self.steps[step] = {"status": status, **details}
        self.save(jobs_dir)

    def set_artifact(self, artifact_path: str, jobs_dir: str | None = None,
                     name: str = "primary"):
        self.artifact_path = artifact_path
        self.artifacts[name] = {
            "path": str(Path(artifact_path).resolve()),
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "source_sha256": self.source_sha256,
        }
        self.status = "converted"
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
