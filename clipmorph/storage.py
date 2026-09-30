"""Pluggable artifact storage backends.

Phase 1 ships the local backend only: ``LocalArtifactStorage`` reads and
writes artifact bytes under the ``output_dir`` artifact root configured in
``app.yml``. The ``ArtifactStorage`` protocol is the seam a phase-2 remote
backend (GCS/S3) implements; ``make_storage`` selects the backend from the
``storage.backend`` app.yml block and raises ``ValueError`` for an unknown
backend name.

Storage keys are RELATIVE to the artifact root for every backend: the local
backend resolves them under ``output_dir``, and a remote backend uses the
same key as its object key. A manifest artifact record therefore carries one
canonical reference (``storage.backend`` + ``storage.key``) and never a
local ``path``. ``storage_key_for`` is the single place that derives a key
from a local file and the artifact root.

Phase 2 adds remote backends behind this same seam and must reuse the
``google-cloud-storage`` client and ``GCS_BUCKET_NAME``/``GCP_*`` env naming
already mirrored by
``clipmorph/upload_pipeline/platforms/instagram.py`` rather than defining a
second naming scheme; ``app.yml`` grows the backend-specific block beside
``storage.backend``.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, BinaryIO, Protocol, runtime_checkable
import uuid

# Backend name for the local filesystem backend (phase 1).
LOCAL_BACKEND = "local"

# Status vocabulary shared with the doctor health checks.
STORAGE_STATUS_OK = "ok"
STORAGE_STATUS_WARNING = "warning"
STORAGE_STATUS_FAILED = "failed"
STORAGE_STATUS_UNAVAILABLE = "unavailable"


def storage_key_for(root: str | Path, path: str | Path) -> str:
    """Return the storage key of one local file under the artifact root.

    Conversion artifacts live under ``<root>/<job_id>/`` and key as
    ``<job_id>/<artifact>.mp4``. A file outside the root (the source artifact
    lives in ``source_dir``) keys with the relative path that reaches it, so
    the local backend resolves every key from the one configured root.
    """
    resolved_root = Path(root).resolve()
    resolved_path = Path(path).resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return Path(os.path.relpath(resolved_path, resolved_root)).as_posix()


@runtime_checkable
class ArtifactStorage(Protocol):
    """The artifact storage seam every backend implements.

    Keys are relative paths into the backend's artifact root, as produced by
    ``storage_key_for``; implementations treat them as opaque. ``exists``
    returns ``None`` when the backend cannot answer (for example a remote
    backend without list permission); ``False`` means the artifact is known to
    be absent.

    ``signed_url`` is unsupported for the local backend: local preview and
    download keep streaming the registered bytes directly, so the local
    implementation raises ``NotImplementedError``. A remote backend returns
    a time-limited download URL instead.
    """

    def stage(self, key: str, destination_dir: str | Path) -> Path:
        """Materialize one artifact under ``destination_dir`` and return it.

        The returned path is a local file the upload adapters can read. It is
        a copy the caller owns and releases once the read is done, never the
        registered bytes themselves.
        """
        ...

    def store(self, source: str | Path, key: str) -> str:
        """Persist local bytes under ``key`` and return the stored key."""
        ...

    def open(self, key: str) -> BinaryIO:
        """Open one artifact for streaming read."""
        ...

    def remove(self, key: str) -> None:
        """Delete one artifact; idempotent when the key is already gone."""
        ...

    def signed_url(self, key: str, ttl: int) -> str:
        """Return a time-limited download URL for one artifact.

        Unsupported for the local backend (raises ``NotImplementedError``):
        local preview/download stream the registered bytes directly.
        """
        ...

    def exists(self, key: str) -> bool | None:
        """Report whether one artifact is present; ``None`` when unknown."""
        ...

    def health(self) -> tuple[str, str]:
        """Return ``(status, detail)`` for the doctor storage check.

        Status is one of ``ok``, ``warning``, ``failed``; a caller that cannot
        build or reach the backend reports ``unavailable`` itself.
        """
        ...


class LocalArtifactStorage:
    """Local filesystem backend rooted at the app.yml ``output_dir``."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def local_path(self, key: str) -> Path:
        """Resolve one key to its file under the artifact root.

        Local-only accessor for the surfaces that hand a browser or
        ``FileResponse`` a real path; it is deliberately not part of the
        protocol, because only a backend that owns local bytes has one.
        """
        return (self.root / key).resolve()

    def stage(self, key: str, destination_dir: str | Path) -> Path:
        source = self.local_path(key)
        if not source.is_file():
            raise FileNotFoundError(f"artifact bytes are unavailable: {key}")
        destination = Path(destination_dir)
        destination.mkdir(parents=True, exist_ok=True)
        staged = destination / source.name
        shutil.copy2(source, staged)
        return staged

    def store(self, source: str | Path, key: str) -> str:
        target = self.local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return key

    def open(self, key: str) -> BinaryIO:
        source = self.local_path(key)
        if not source.is_file():
            raise FileNotFoundError(f"artifact bytes are unavailable: {key}")
        return source.open("rb")

    def remove(self, key: str) -> None:
        from send2trash import send2trash

        target = self.local_path(key)
        if target.is_file():
            send2trash(str(target))

    def signed_url(self, key: str, ttl: int) -> str:
        raise NotImplementedError(
            "signed_url is unsupported for the local backend; preview and "
            "download stream the registered bytes directly")

    def exists(self, key: str) -> bool | None:
        return self.local_path(key).is_file()

    def health(self) -> tuple[str, str]:
        """Probe the root through the backend's own write and delete paths."""
        probe_key = f".{uuid.uuid4().hex}.probe"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = Path(temp_dir) / probe_key
                payload.write_bytes(b"clipmorph artifact storage probe")
                self.store(payload, probe_key)
            if not self.exists(probe_key):
                return (STORAGE_STATUS_FAILED,
                        f"artifact root probe missing after write: {self.root}")
            self.remove(probe_key)
            return (STORAGE_STATUS_OK, f"{LOCAL_BACKEND} backend at {self.root}")
        except Exception as error:
            return (STORAGE_STATUS_FAILED, str(error))


def make_storage(app_config: dict[str, Any],
                 data_dir: str | Path) -> ArtifactStorage:
    """Build the artifact storage backend selected by ``app.yml``.

    Reads the top-level ``storage.backend`` block; phase 1 accepts only
    ``local`` and rejects anything else with ``ValueError``.
    """
    storage = app_config.get("storage", {})
    if not isinstance(storage, dict):
        raise ValueError("storage must be an object")
    backend = storage.get("backend", LOCAL_BACKEND)
    if backend != LOCAL_BACKEND:
        raise ValueError(f"unknown storage backend: {backend}")
    from clipmorph.job import resolve_output_dir

    root = resolve_output_dir(app_config.get("output_dir"), data_dir)
    return LocalArtifactStorage(root.resolve())
