"""Versioned transcript edit sessions and validation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from clipmorph.configuration import atomic_write_text

EDIT_SESSION_SCHEMA_VERSION = 2
TYPOGRAPHY_KEYS = {
    "size", "color", "font_file", "outline_color", "bold", "italic", "underline"
}


def validate_segments(segments: list[dict[str, Any]],
                      media_duration: float | None = None) -> None:
    """Reject invalid or overlapping segment timing without normalizing edits."""
    previous_end = 0.0
    seen_ids = set()
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
        segment_id = segment.get("id")
        if not isinstance(segment_id, str) or not segment_id:
            raise ValueError("Transcript segments require stable IDs")
        if segment_id in seen_ids:
            raise ValueError("Transcript segment IDs must be unique")
        seen_ids.add(segment_id)
        if "typography" in segment:
            typography = segment["typography"]
            if not isinstance(typography, dict):
                raise ValueError("Transcript segment typography must be an object")
            unknown = set(typography) - TYPOGRAPHY_KEYS
            if unknown:
                raise ValueError(
                    f"Unknown transcript typography field(s): {', '.join(sorted(unknown))}")
        previous_end = end


def create_edit_session(source_sha256: str, segments: list[dict[str, Any]],
                        media_duration: float | None = None) -> dict[str, Any]:
    original = deepcopy(segments)
    for index, segment in enumerate(original):
        if not isinstance(segment, dict):
            raise ValueError("Each transcript segment must be an object")
        if not segment.get("id"):
            identity = json.dumps(
                [index, segment.get("start"), segment.get("end"), segment.get("text", "")],
                ensure_ascii=False, separators=(",", ":"))
            segment["id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    validate_segments(original, media_duration)
    return {
        "schema_version": EDIT_SESSION_SCHEMA_VERSION,
        "revision": 1,
        "source_sha256": source_sha256,
        "media_duration": media_duration,
        "original_segments": original,
        "segments": deepcopy(original),
    }


def validate_edit_session(session: dict[str, Any]) -> None:
    if not isinstance(session, dict):
        raise ValueError("Transcript edit session must be an object")
    if session.get("schema_version") != EDIT_SESSION_SCHEMA_VERSION:
        raise ValueError("Unsupported transcript edit-session schema version")
    revision = session.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("Transcript edit session requires a positive revision")
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
    original_ids = {segment["id"] for segment in original}
    if any(segment["id"] not in original_ids for segment in segments):
        raise ValueError("Edited transcript contains an unknown segment ID")


def save_edit_session(session: dict[str, Any], path: str | Path) -> Path:
    validate_edit_session(session)
    destination = Path(path)
    if destination.exists():
        raise FileExistsError(f"Transcript revision already exists: {destination}")
    atomic_write_text(destination, json.dumps(session, indent=2, ensure_ascii=False))
    return destination


def load_edit_session(path: str | Path) -> dict[str, Any]:
    session = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_edit_session(session)
    return session
