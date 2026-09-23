"""Versioned transcript edit sessions and validation."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


EDIT_SESSION_SCHEMA_VERSION = 1


def validate_segments(segments: list[dict[str, Any]],
                      media_duration: float | None = None) -> None:
    """Reject invalid or overlapping segment timing without normalizing edits."""
    previous_end = 0.0
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Each transcript segment must be an object")
        start = segment.get("start")
        end = segment.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError("Transcript segment timing must be numeric")
        if start < 0 or end <= start:
            raise ValueError("Transcript segment timing must satisfy 0 <= start < end")
        if start < previous_end:
            raise ValueError("Transcript segments must not overlap")
        if media_duration is not None and end > media_duration:
            raise ValueError("Transcript segment exceeds media duration")
        previous_end = end


def create_edit_session(source_sha256: str, segments: list[dict[str, Any]],
                        media_duration: float | None = None) -> dict[str, Any]:
    validate_segments(segments, media_duration)
    original = deepcopy(segments)
    return {
        "schema_version": EDIT_SESSION_SCHEMA_VERSION,
        "source_sha256": source_sha256,
        "media_duration": media_duration,
        "original_segments": original,
        "segments": deepcopy(original),
    }


def validate_edit_session(session: dict[str, Any]) -> None:
    if session.get("schema_version") != EDIT_SESSION_SCHEMA_VERSION:
        raise ValueError("Unsupported transcript edit-session schema version")
    if not isinstance(session.get("source_sha256"), str) or not session["source_sha256"]:
        raise ValueError("Transcript edit session requires source identity")
    original = session.get("original_segments")
    segments = session.get("segments")
    if not isinstance(original, list) or not isinstance(segments, list):
        raise ValueError("Transcript edit session requires original and edited segments")
    duration = session.get("media_duration")
    if duration is not None and (not isinstance(duration, (int, float)) or duration <= 0):
        raise ValueError("Media duration must be positive")
    validate_segments(original, duration)
    validate_segments(segments, duration)


def save_edit_session(session: dict[str, Any], path: str | Path) -> Path:
    validate_edit_session(session)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(session, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return destination


def load_edit_session(path: str | Path) -> dict[str, Any]:
    session = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_edit_session(session)
    return session
