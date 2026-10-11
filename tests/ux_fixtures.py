"""Seeded ClipMorph workspaces for the #259 UX audit, re-audit, and CI smoke test.

Test-only: nothing in the package imports this module. Each scenario builds a
fresh data directory with the same on-disk shape ``clipmorph.web.create_app``
serves, so the Phase 0 audit, the Phase 3 re-audit, and ``tests/e2e/smoke.js``
all exercise identical states.

Coverage (issue #259, section 0.2): every job status, every checkpoint status,
every platform, plus empty, error, long-content, and 50+ job workspaces.

Usage::

    from tests.ux_fixtures import seed_workspace, SCENARIOS
    seed_workspace(data_dir, "states")
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

# The four checkpoint stages the pipeline persists (see clipmorph.job).
STAGES = ("transcript", "conversion", "upload")

# Job.status values produced by JobManifest._derive_status plus the transient
# "created"/"queued" pre-run states the board still renders.
JOB_STATUSES = (
    "created",
    "queued",
    "running",
    "awaiting_review",
    "scheduled",
    "completed",
    "failed",
    "partial_failure",
    "cancelled",
)

# Checkpoint.status values (clipmorph.job.CHECKPOINT_STATES).
CHECKPOINT_STATUSES = (
    "pending",
    "running",
    "awaiting_review",
    "completed",
    "partial_failure",
    "skipped",
    "failed",
    "cancelled",
    "stale",
)

PLATFORMS = ("youtube", "instagram", "tiktok", "twitter", "facebook")

SCENARIOS = ("empty", "states", "errors", "long", "large")

# A checkpoint preset per job status: a plausible full triple so the card and
# the detail modal both render a coherent pipeline position.
_STATUS_PRESETS = {
    "created": ("pending", "pending", "pending"),
    "queued": ("pending", "pending", "pending"),
    "running": ("completed", "running", "pending"),
    "awaiting_review": ("awaiting_review", "pending", "pending"),
    "scheduled": ("completed", "completed", "running"),
    "completed": ("completed", "completed", "completed"),
    "failed": ("completed", "failed", "pending"),
    "partial_failure": ("completed", "completed", "partial_failure"),
    "cancelled": ("completed", "cancelled", "pending"),
}

_CLIP_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"clipmorph-audit"
_LONG_TITLE = (
    "Absolutely unbelievably long clip title that keeps going past any sane "
    "width so the card has to wrap, truncate, or overflow somewhere visible "
    "in the audit at every tested viewport and state combination"
)
_LONG_NAME = (
    "a-very-long-source-filename-that-also-keeps-going-well-past-any-reasonable-"
    "column-width-so-overflow-and-ellipsis-behaviour-is-visible.mp4"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(days: int = 0, hours: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days, hours=hours)).isoformat()


def _write_source(data_dir: Path, name: str) -> str:
    sources = Path(data_dir) / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    path = sources / name
    if not path.exists():
        path.write_bytes(_CLIP_BYTES)
    return name


def _service(data_dir: Path):
    from clipmorph.service import JobService

    return JobService(Path(data_dir), reconcile=False)


def _new_job(service, name: str, *, title: str | None = None,
             platforms: list[str] | None = None):
    config: dict = {}
    if platforms:
        config["platforms"] = {platform: {} for platform in platforms}
    if title is not None:
        config["upload"] = {"content": {"title": title}}
    return service.create_job(name, config)


def _apply(manifest, service, *, status: str, checkpoints: tuple[str, str, str],
           attempts: list[dict] | None = None,
           platforms: dict | None = None,
           errors: list[dict] | None = None,
           error_message: str | None = None):
    for stage, checkpoint_status in zip(STAGES, checkpoints):
        record = manifest.checkpoints[stage]
        record["status"] = checkpoint_status
        record["revision"] = 1
        record["updated_at"] = _now()
        if checkpoint_status in {"completed", "failed", "cancelled",
                                 "partial_failure", "skipped"}:
            record["completed_at"] = _now()
        if checkpoint_status == "failed":
            record["error"] = {
                "code": "audit_fixture_failure",
                "message": error_message or "Fixture conversion failed",
                "occurred_at": _now(),
                "attempt_id": None,
                "retryable": True,
            }
    if attempts is not None:
        manifest.upload_attempts = attempts
    if platforms is not None:
        manifest.platforms = platforms
    if errors is not None:
        manifest.errors = errors
    manifest.status = status
    manifest.save(service.jobs_dir)
    return manifest


def _registered_artifact(manifest, service, *, name: str = "render",
                         group_id: str | None = None):
    """Register one real file under output/<job_id>/ so preview can stream it."""
    output = service.data_dir / "output" / manifest.job_id
    output.mkdir(parents=True, exist_ok=True)
    media = output / f"{name}.mp4"
    if not media.exists():
        media.write_bytes(_CLIP_BYTES + b"\x00" * 4096)
    manifest.record_artifact(name, media, service.jobs_dir, group_id=group_id)
    return manifest


def _attempt(manifest, platform: str, status: str, *, index: int = 1) -> dict:
    published = status == "published"
    result = {
        "success": published,
        "message": "Fixture attempt",
        "platform_post_id": f"{platform}-{index}" if published else None,
        "platform_url": (
            f"https://example.invalid/{platform}/{index}" if published else None),
        "published_at": _iso(-1) if published else None,
    }
    return {
        "attempt_id": f"{platform}-attempt-{index}",
        "platform": platform,
        "artifact_id": manifest.current_artifact_id,
        "artifact_hash": "a" * 64,
        "configuration_snapshot": {
            "upload": {"content": {"title": manifest.configuration
                                   .get("upload", {}).get("content", {})
                                   .get("title", "Fixture")}}} ,
        "configuration_hash": "b" * 64,
        "content_hash": "c" * 64,
        "created_at": _iso(-2),
        "status": status,
        "result": result if published else None,
    }


def _platform_record(platform: str, status: str, *, index: int = 1) -> dict:
    published = status == "published"
    return {
        "success": published,
        "status": status,
        "message": "Fixture platform state",
        "attempt_id": f"{platform}-attempt-{index}",
        "artifact_id": None,
        "artifact_hash": None,
        "platform_post_id": f"{platform}-{index}" if published else None,
        "platform_url": (
            f"https://example.invalid/{platform}/{index}" if published else None),
        "published_at": _iso(-1) if published else None,
    }


def _seed_states(data_dir: Path, service) -> None:
    """One job per job status, then one per checkpoint status, then platforms."""
    for index, status in enumerate(JOB_STATUSES):
        name = _write_source(data_dir, f"status-{status}.mp4")
        manifest = _new_job(service, name, title=f"Status fixture: {status}")
        attempts = None
        platforms = None
        if status == "scheduled":
            attempts = [_attempt(manifest, "youtube", "scheduled")]
            platforms = {"youtube": _platform_record("youtube", "scheduled")}
        elif status == "completed":
            _registered_artifact(manifest, service)
            attempts = [
                _attempt(manifest, "youtube", "published", index=1),
                _attempt(manifest, "tiktok", "published", index=2),
            ]
            platforms = {
                "youtube": _platform_record("youtube", "published", index=1),
                "tiktok": _platform_record("tiktok", "published", index=2),
            }
        elif status == "partial_failure":
            _registered_artifact(manifest, service)
            attempts = [
                _attempt(manifest, "youtube", "published", index=1),
                _attempt(manifest, "instagram", "failed", index=2),
            ]
            platforms = {
                "youtube": _platform_record("youtube", "published", index=1),
                "instagram": _platform_record("instagram", "failed", index=2),
            }
        elif status == "failed":
            attempts = [_attempt(manifest, "twitter", "failed")]
            platforms = {"twitter": _platform_record("twitter", "failed")}
        _apply(manifest, service, status=status,
               checkpoints=_STATUS_PRESETS[status], attempts=attempts,
               platforms=platforms)

    # Every checkpoint status at least once (on the conversion stage).
    for index, checkpoint_status in enumerate(CHECKPOINT_STATUSES):
        name = _write_source(data_dir, f"checkpoint-{checkpoint_status}.mp4")
        manifest = _new_job(service, name,
                            title=f"Checkpoint fixture: {checkpoint_status}")
        triple = list(_STATUS_PRESETS["running"])
        triple[1] = checkpoint_status
        job_status = {
            "completed": "completed",
            "awaiting_review": "awaiting_review",
            "failed": "failed",
            "partial_failure": "partial_failure",
            "cancelled": "cancelled",
            "running": "running",
            "skipped": "queued",
            "stale": "queued",
            "pending": "queued",
        }[checkpoint_status]
        _apply(manifest, service, status=job_status, checkpoints=tuple(triple))

    # Every platform at least once, with a mixed attempt map.
    name = _write_source(data_dir, "platforms.mp4")
    manifest = _new_job(service, name, title="Platform coverage fixture",
                        platforms=list(PLATFORMS))
    _registered_artifact(manifest, service)
    attempt_status = {
        "youtube": "published",
        "instagram": "scheduled",
        "tiktok": "running",
        "twitter": "failed",
        "facebook": "cancelled",
    }
    attempts = [_attempt(manifest, platform, status, index=index)
                for index, (platform, status)
                in enumerate(attempt_status.items(), start=1)]
    platforms = {platform: _platform_record(platform, status, index=index)
                 for index, (platform, status)
                 in enumerate(attempt_status.items(), start=1)}
    _apply(manifest, service, status="partial_failure",
           checkpoints=("completed", "completed", "partial_failure"),
           attempts=attempts, platforms=platforms,
           errors=[{"code": "audit_fixture_error", "message": "Fixture error row",
                    "occurred_at": _now()}])


def _seed_long(data_dir: Path, service) -> None:
    name = _write_source(data_dir, _LONG_NAME)
    manifest = _new_job(service, name, title=_LONG_TITLE)
    _registered_artifact(manifest, service, name="render")
    manifest.artifacts[next(reversed(manifest.artifacts))]["display_name"] = (
        "an-equally-long-artifact-display-name-that-needs-to-truncate-or-wrap.mp4")
    _apply(manifest, service, status="awaiting_review",
           checkpoints=_STATUS_PRESETS["awaiting_review"])

    # A long-title completed card so the archive/card composition is stressed.
    name2 = _write_source(data_dir, "long-title-completed.mp4")
    manifest2 = _new_job(service, name2, title=_LONG_TITLE + " (completed)")
    _registered_artifact(manifest2, service)
    _apply(manifest2, service, status="completed",
           checkpoints=_STATUS_PRESETS["completed"],
           attempts=[_attempt(manifest2, "youtube", "published")],
           platforms={"youtube": _platform_record("youtube", "published")})


def _seed_large(data_dir: Path, service, count: int = 55) -> None:
    statuses = list(JOB_STATUSES)
    for index in range(count):
        status = statuses[index % len(statuses)]
        name = _write_source(data_dir, f"bulk-{index:03d}.mp4")
        manifest = _new_job(service, name,
                            title=f"Bulk fixture clip {index:03d} — {status}")
        if status == "completed":
            _registered_artifact(manifest, service)
        _apply(manifest, service, status=status,
               checkpoints=_STATUS_PRESETS[status])


def seed_workspace(data_dir: str | Path, scenario: str = "states") -> Path:
    """Populate ``data_dir`` with the given scenario and return the path.

    Scenarios:
      ``empty``  — no jobs (fresh workspace).
      ``states`` — every job status, checkpoint status, and platform.
      ``errors`` — failed jobs with error records (alias over states + errors).
      ``long``   — very long titles, filenames, and artifact names.
      ``large``  — the states set plus 55 extra jobs.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario!r}")
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if scenario == "empty":
        return data_dir

    service = _service(data_dir)
    try:
        if scenario in {"states", "errors", "large"}:
            _seed_states(data_dir, service)
        if scenario in {"states", "errors", "long", "large"}:
            _seed_long(data_dir, service)
        if scenario == "large":
            _seed_large(data_dir, service)
    finally:
        service.close()
    return data_dir
