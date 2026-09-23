from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from typing import Any


@dataclass
class JobManifest:
    job_id: str
    source_path: str
    source_sha256: str
    configuration: dict[str, Any]
    status: str = "created"
    artifact_path: str | None = None
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(cls, source_path: str, configuration: dict[str, Any],
               jobs_dir: str = ".clipmorph/jobs") -> JobManifest:
        path = Path(source_path)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest = cls(uuid.uuid4().hex, str(path.resolve()), digest.hexdigest(),
                       configuration)
        manifest.save(jobs_dir)
        return manifest

    @classmethod
    def load(cls, job_id: str, jobs_dir: str = ".clipmorph/jobs") -> JobManifest:
        path = Path(jobs_dir) / f"{job_id}.json"
        with path.open("r", encoding="utf-8") as manifest_file:
            return cls(**json.load(manifest_file))

    def save(self, jobs_dir: str = ".clipmorph/jobs") -> Path:
        directory = Path(jobs_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        path = directory / f"{self.job_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def set_status(self, status: str, jobs_dir: str = ".clipmorph/jobs"):
        self.status = status
        self.save(jobs_dir)

    def set_artifact(self, artifact_path: str, jobs_dir: str = ".clipmorph/jobs"):
        self.artifact_path = artifact_path
        self.status = "converted"
        self.save(jobs_dir)

    def record_platform(self, platform: str, result: dict[str, Any],
                        jobs_dir: str = ".clipmorph/jobs"):
        self.platforms[platform] = result
        self.status = "published" if result.get("success") else "partial_failure"
        self.save(jobs_dir)
