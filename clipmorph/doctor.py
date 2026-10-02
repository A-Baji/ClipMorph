"""Read-only environment health checks for the ``clipmorph doctor`` command.

Every check returns one record ``{"id", "status", "detail"}`` where status is
``ok``, ``warning``, or ``failed``; a storage backend that cannot be built or
reached reports ``unavailable``. The doctor never writes manifests and never
contacts network services: directory writability is asserted with permission
and disk-space probes only, and the artifact-storage check writes and recycles
a single probe object inside the storage root so the backend's own write path is
exercised, leaving nothing behind. Heavy imports stay lazy inside the
individual check functions so the ``--help`` and ``init`` paths remain
dependency-free.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

# Minimum free space (bytes) required beside a writable directory, mirroring
# PreflightValidator._validate_output_dir.
_MIN_FREE_BYTES = 100 * 1024 * 1024

# Bundled caption font shipped inside the package.
_FONT_PATH = Path("resources") / "fonts" / "roboto" / "Roboto-Bold.ttf"


def _record(check_id: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "status": status, "detail": detail}


def _check_ffmpeg() -> dict[str, str]:
    return _check_binary("ffmpeg")


def _check_ffprobe() -> dict[str, str]:
    return _check_binary("ffprobe")


def _check_binary(check_id: str) -> dict[str, str]:
    from clipmorph.ffmpeg import FFmpegConfig, FFmpegError

    try:
        config = FFmpegConfig()
        path = config.ffmpeg_path if check_id == "ffmpeg" else config.ffprobe_path
        if not path:
            raise FFmpegError(f"{check_id} binary not found at: {path}")
        result = subprocess.run([path, "-version"], capture_output=True,
                                text=True, timeout=10, check=True)
    except (FFmpegError, subprocess.SubprocessError, OSError) as error:
        return _record(check_id, "failed", str(error))
    first_line = result.stdout.splitlines()[0].strip() if result.stdout else ""
    return _record(check_id, "ok", first_line or f"{check_id} version unavailable")


def _load_app_configuration(
        app_config_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    from clipmorph.configuration import load_app_configuration

    try:
        return load_app_configuration(app_config_path), None
    except (ValueError, OSError) as error:
        return None, str(error)


def _resolve_source_dir(source_dir: str | Path, app_config_path: Path) -> Path:
    """Resolve source_dir exactly as JobService does against the config location."""
    path = Path(source_dir)
    if not path.is_absolute():
        path = app_config_path.parent / path
    return path.resolve()


def _resolve_output_dir(output_dir: str | Path, data_dir: Path) -> Path:
    """Resolve output_dir exactly as clipmorph.job.resolve_output_dir does."""
    path = Path(output_dir)
    if path.is_absolute():
        return path
    return data_dir / path


def _writable_dir_problem(path: Path, label: str) -> str | None:
    """Assert writability without writing, reusing the preflight messages."""
    if not os.access(path, os.W_OK):
        return f"{label} is not writable: {path}"
    if shutil.disk_usage(path).free < _MIN_FREE_BYTES:
        return f"Less than 100 MB free in {label.lower()}: {path}"
    return None


def _check_source_dir(configuration: dict[str, Any],
                      app_config_path: Path) -> dict[str, str]:
    path = _resolve_source_dir(configuration["source_dir"], app_config_path)
    problem = _writable_dir_problem(path, "Source directory")
    if problem:
        return _record("source_dir", "failed", problem)
    return _record("source_dir", "ok", str(path))


def _check_output_dir(configuration: dict[str, Any],
                      data_dir: Path) -> dict[str, str]:
    path = _resolve_output_dir(configuration["output_dir"], data_dir)
    problem = _writable_dir_problem(path, "Output directory")
    if problem:
        return _record("output_dir", "failed", problem)
    return _record("output_dir", "ok", str(path))


def _check_layouts(configuration: dict[str, Any]) -> dict[str, str]:
    from clipmorph.layout import validate_layout

    layouts = configuration.get("layouts") or []
    for record in layouts:
        try:
            validate_layout(record["layout"])
        except ValueError as error:
            return _record("layouts", "failed", f"layout {record['id']}: {error}")
    return _record("layouts", "ok", f"{len(layouts)} layout(s) valid")


def _check_fonts() -> dict[str, str]:
    font_path = Path(__file__).resolve().parent / _FONT_PATH
    if font_path.is_file():
        return _record("fonts", "ok", str(font_path))
    return _record("fonts", "failed", f"bundled font missing: {font_path}")


def _check_credentials(data_dir: str | Path) -> dict[str, str]:
    from clipmorph.auth import credential_status, load_auth_config

    # The auth file is the credential source for CLI-run jobs; check the
    # workspace's real configuration, not just pre-set environment values.
    load_auth_config(data_dir)
    status = credential_status()
    unconfigured = sorted(platform for platform, configured in status.items()
                          if not configured)
    if unconfigured:
        return _record("credentials", "warning",
                       f"no credentials configured for: {', '.join(unconfigured)}")
    return _record("credentials", "ok", f"all {len(status)} platforms configured")


def _check_device() -> dict[str, str]:
    try:
        import torch
    except ImportError:
        return _record("device", "warning",
                       "torch not installed; transcription unavailable on this "
                       "installation")
    try:
        if torch.cuda.is_available():
            return _record("device", "ok", f"cuda available: {torch.cuda.get_device_name(0)}")
        from clipmorph.conversion_pipeline.transcribe import resolve_transcription_device
        fallback = resolve_transcription_device("cuda")
        return _record("device", "ok",
                       f"cuda unavailable; transcription falls back to {fallback}")
    except Exception as error:  # the device check never fails the run
        return _record("device", "warning", f"cuda probe failed: {error}")


def _check_artifacts_storage(configuration: dict[str, Any],
                             data_dir: Path) -> dict[str, str]:
    """Exercise the configured artifact storage backend once.

    Construction failures (an unknown backend, a missing dependency) are
    reported as ``unavailable``, mirroring how the device check treats an
    absent optional import; the backend itself reports its own probe result.
    """
    from clipmorph.storage import make_storage

    try:
        storage = make_storage(configuration, data_dir)
    except Exception as error:
        return _record("artifacts_storage", "unavailable", str(error))
    status, detail = storage.health()
    return _record("artifacts_storage", status, detail)


def _check_source_media(source: Path) -> dict[str, str]:
    from clipmorph.configuration import SUPPORTED_SOURCE_EXTENSIONS
    from clipmorph.ffmpeg import FFmpegError, FFmpegRunner

    if source.suffix.lower() not in SUPPORTED_SOURCE_EXTENSIONS:
        return _record("source_media", "failed",
                       f"unsupported source extension: {source.suffix}")
    if not source.exists():
        return _record("source_media", "failed", f"Input file does not exist: {source}")
    if not source.is_file() or source.stat().st_size == 0:
        return _record("source_media", "failed",
                       f"Input file is empty or not a file: {source}")
    try:
        info = FFmpegRunner().get_video_info(str(source))
    except FFmpegError as error:
        return _record("source_media", "failed", str(error))
    streams = info.get("streams", [])
    video = next((stream for stream in streams
                  if stream.get("codec_type") == "video"), None)
    if not video:
        return _record("source_media", "failed",
                       "Input does not contain a video stream.")
    width, height = video.get("width"), video.get("height")
    if (not isinstance(width, int) or not isinstance(height, int)
            or width <= 0 or height <= 0):
        return _record("source_media", "failed", "Video stream has invalid dimensions.")
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    if duration <= 0:
        return _record("source_media", "failed",
                       "Video duration could not be determined.")
    return _record("source_media", "ok", f"{width}x{height}, {duration}s")


def run_checks(data_dir: str | Path, app_config_path: str | Path,
               source_probe: str | Path | None = None) -> list[dict]:
    """Run every read-only health check and return the check records.

    Check ids, in order: ``ffmpeg``, ``ffprobe``, ``app_config``,
    ``source_dir``, ``output_dir``, ``layouts``, ``fonts``, ``credentials``,
    ``device``, ``artifacts_storage`` (only when app.yml loaded), and
    ``source_media`` (only when ``source_probe`` is given).
    """
    data_dir = Path(data_dir)
    app_config_path = Path(app_config_path)
    checks = [_check_ffmpeg(), _check_ffprobe()]
    configuration, config_error = _load_app_configuration(app_config_path)
    if configuration is None:
        checks.append(_record("app_config", "failed", config_error or
                              "app configuration could not be loaded"))
        for check_id in ("source_dir", "output_dir", "layouts"):
            checks.append(_record(check_id, "failed",
                                  f"app configuration could not be loaded: "
                                  f"{config_error}"))
    else:
        source_dir = _resolve_source_dir(configuration["source_dir"], app_config_path)
        output_dir = _resolve_output_dir(configuration["output_dir"], data_dir)
        checks.append(_record("app_config", "ok",
                              f"source_dir={source_dir} output_dir={output_dir}"))
        checks.append(_check_source_dir(configuration, app_config_path))
        checks.append(_check_output_dir(configuration, data_dir))
        checks.append(_check_layouts(configuration))
    checks.append(_check_fonts())
    checks.append(_check_credentials(data_dir))
    checks.append(_check_device())
    if configuration is not None:
        checks.append(_check_artifacts_storage(configuration, data_dir))
    if source_probe is not None:
        checks.append(_check_source_media(Path(source_probe)))
    return checks


def _print_text_report(checks: list[dict]) -> None:
    """Render one deterministic line per check: ``{id:<60} {status} {detail}``."""
    for check in checks:
        print(f"{check['id']:<60} {check['status']} {check['detail']}")
