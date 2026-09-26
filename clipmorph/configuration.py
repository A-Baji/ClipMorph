"""Shared app/job configuration loading and normalization."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import PurePath
from pathlib import Path
from typing import Any
import uuid

import yaml

from clipmorph.layout import normalize_layout
from clipmorph.layout import resolve_layout_geometry
from clipmorph.platforms import SUPPORTED_PLATFORMS
from clipmorph.platforms import SUPPORTED_PLATFORMS_SET
from clipmorph.layout import validate_layout


SUPPORTED_SOURCE_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}


DEFAULT_APP_CONFIGURATION = {
    "source_dir": "sources",
    "output_dir": "output",
    "job_defaults": {
        "general": {
            "source": None,
            "no_confirm": False,
            "clean": False,
        },
        "conversion": {
            "layout_id": None,
            "skip": False,
            "strict": False,
            "no_confirm": None,
            "clean": None,
            "subtitles": {
                "skip": False,
                "renderer": "overlay",
                "no_confirm": None,
                "clean": None,
                "transcription_language": "en",
                "transcription_model": "tiny",
                "transcription_device": "cpu",
                "transcription_compute_type": "int8",
            },
        },
        "upload": {
            "skip": False,
            "no_confirm": None,
            "content": {"title": "", "description": "", "tags": []},
            "platforms": {"include": [], "exclude": []},
        },
    },
    "layouts": [],
}


def atomic_write_text(path: str | Path, content: str) -> Path:
    """Persist text by replacing the destination only after a full temp write."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def load_app_configuration(path: str | Path) -> dict[str, Any]:
    """Load the canonical app.yml file, returning defaults when it is absent."""
    app_path = Path(path)
    if not app_path.exists():
        return deepcopy(DEFAULT_APP_CONFIGURATION)
    try:
        configuration = yaml.safe_load(app_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"Unable to read app configuration {app_path}: {error}") from error
    if not isinstance(configuration, dict):
        raise ValueError("App configuration root must be an object")
    unknown = set(configuration) - {
        "source_dir", "output_dir", "job_defaults", "layouts"}
    if unknown:
        raise ValueError(
            f"Unknown app configuration field(s): {', '.join(sorted(unknown))}")
    result = merge_configuration(DEFAULT_APP_CONFIGURATION, configuration)
    _validate_app_configuration(result)
    return result


def save_app_configuration(path: str | Path,
                           configuration: dict[str, Any]) -> Path:
    """Validate and atomically write app.yml."""
    if not isinstance(configuration, dict):
        raise ValueError("App configuration root must be an object")
    unknown = set(configuration) - {
        "source_dir", "output_dir", "job_defaults", "layouts"}
    if unknown:
        raise ValueError(
            f"Unknown app configuration field(s): {', '.join(sorted(unknown))}")
    finalized = merge_configuration(DEFAULT_APP_CONFIGURATION, configuration)
    _validate_app_configuration(finalized)
    return atomic_write_text(
        path, yaml.safe_dump(finalized, sort_keys=False, allow_unicode=True))


def load_job_records(path: str | Path) -> list[Any]:
    """Read JSONL objects or a YAML list of full job configuration objects."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"Unable to read job configurations {source}: {error}") from error
    suffix = source.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            records = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ValueError(f"Invalid YAML job configurations: {error}") from error
        if not isinstance(records, list):
            raise ValueError("YAML job configurations must be a list")
        return records
    records = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid JSONL job configuration on line {line_number}: {error.msg}") from error
    return records


def _load_sidecar(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"Unable to read job sidecar {path}: {error}") from error
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Job sidecar {path} must contain an object")
    return value


def _load_matching_sidecar(directory: str | Path, source_name: str) -> dict[str, Any]:
    root = Path(directory)
    if not root.is_dir():
        return {}

    matches = []
    sidecar_paths = sorted(
        (path for path in root.iterdir()
         if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}),
        key=lambda path: (path.name.casefold(), path.name))
    for path in sidecar_paths:
        sidecar = _load_sidecar(path)
        if not sidecar:
            continue
        general = sidecar.get("general")
        if not isinstance(general, dict) or not isinstance(general.get("source"), str):
            raise ValueError(f"Job sidecar {path} requires general.source")
        sidecar_source = validate_source_name(general["source"])
        if sidecar_source == source_name:
            matches.append((path, sidecar))

    if len(matches) > 1:
        paths = ", ".join(str(path) for path, _ in matches)
        raise ValueError(
            f"Multiple job sidecars target source {source_name}: {paths}")
    return matches[0][1] if matches else {}


def merge_source_configurations(
        source_name: str, records: list[Any],
        explicit_config_dir: str | Path | None,
        source_dir: str | Path) -> dict[str, Any]:
    """Merge source-keyed sidecars and a matching full job record by priority."""
    source_name = validate_source_name(source_name)
    result = _load_matching_sidecar(source_dir, source_name)
    if explicit_config_dir is not None:
        explicit_sidecar = _load_matching_sidecar(
            explicit_config_dir, source_name)
        result = merge_configuration(result, explicit_sidecar)
    matches = []
    for record in records:
        if not isinstance(record, dict):
            continue
        general = record.get("general")
        if isinstance(general, dict) and general.get("source") == source_name:
            matches.append(record)
    if matches:
        result = merge_configuration(result, matches[0])
    return result


def discover_source_names(source_dir: str | Path) -> list[str]:
    """Return supported immediate child files in stable case-insensitive order."""
    root = Path(source_dir)
    if not root.is_dir():
        return []
    names = [entry.name for entry in root.iterdir()
             if entry.is_file() and entry.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS]
    return sorted(names, key=lambda name: (name.casefold(), name))


def discover_source_entries(source_dir: str | Path) -> list[str]:
    """Return immediate source-like files, including unsupported extensions."""
    root = Path(source_dir)
    if not root.is_dir():
        return []
    names = [entry.name for entry in root.iterdir()
             if entry.is_file() and entry.suffix.lower() not in {".yml", ".yaml"}]
    return sorted(names, key=lambda name: (name.casefold(), name))


def _validate_app_configuration(configuration: dict[str, Any]) -> None:
    for path_key in ("source_dir", "output_dir"):
        if not isinstance(configuration.get(path_key), str) or not configuration[path_key]:
            raise ValueError(f"{path_key} must be a non-empty path")
    if not isinstance(configuration.get("job_defaults"), dict):
        raise ValueError("job_defaults must be an object")
    validate_job_configuration(configuration["job_defaults"])
    layouts = configuration.get("layouts")
    if not isinstance(layouts, list):
        raise ValueError("layouts must be a list")
    ids: set[str] = set()
    for record in layouts:
        if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
                or not record["id"] or not isinstance(record.get("name"), str)
                or not record["name"].strip() or not isinstance(record.get("layout"), dict)):
            raise ValueError("Each layout registry record requires id, name, and layout")
        if record["id"] in ids:
            raise ValueError(f"Duplicate layout ID: {record['id']}")
        from clipmorph.layout import validate_layout
        try:
            validate_layout(record["layout"])
        except ValueError as error:
            raise ValueError(f"Invalid layout {record['id']}: {error}") from error
        ids.add(record["id"])


def validate_job_configuration(configuration: dict[str, Any]) -> None:
    """Validate the canonical general/conversion/upload job configuration shape."""
    if not isinstance(configuration, dict):
        raise ValueError("job configuration must be an object")

    def check_object(value: Any, label: str, allowed: set[str]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be an object")
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                f"Unknown {label} field(s): {', '.join(sorted(unknown))}")
        return value

    root = check_object(configuration, "job configuration",
                        {"general", "conversion", "upload"})
    general = check_object(root.get("general", {}), "general",
                           {"source", "no_confirm", "clean"})
    if general.get("source") is not None:
        validate_source_name(general["source"])
    for key in ("no_confirm", "clean"):
        if key in general and not isinstance(general[key], bool):
            raise ValueError(f"general.{key} must be a boolean")

    conversion = check_object(root.get("conversion", {}), "conversion", {
        "layout_id", "layout", "skip", "strict", "no_confirm", "clean", "subtitles",
    })
    for key in ("skip", "strict"):
        if key in conversion and not isinstance(conversion[key], bool):
            raise ValueError(f"conversion.{key} must be a boolean")
    for key in ("no_confirm", "clean"):
        if key in conversion and conversion[key] is not None and not isinstance(conversion[key], bool):
            raise ValueError(f"conversion.{key} must be a boolean or null")
    if conversion.get("layout_id") is not None and not isinstance(conversion["layout_id"], str):
        raise ValueError("conversion.layout_id must be a string or null")
    if "layout" in conversion and not isinstance(conversion["layout"], dict):
        raise ValueError("conversion.layout must be an object")
    subtitles = check_object(conversion.get("subtitles", {}), "conversion.subtitles", {
        "skip", "renderer", "no_confirm", "clean", "transcription_language",
        "transcription_model", "transcription_device", "transcription_compute_type",
    })
    if subtitles.get("renderer", "overlay") not in {"overlay", "stacked"}:
        raise ValueError("conversion.subtitles.renderer must be overlay or stacked")
    for key in ("skip",):
        if key in subtitles and not isinstance(subtitles[key], bool):
            raise ValueError(f"conversion.subtitles.{key} must be a boolean")
    for key in ("no_confirm", "clean"):
        if key in subtitles and subtitles[key] is not None and not isinstance(subtitles[key], bool):
            raise ValueError(f"conversion.subtitles.{key} must be a boolean or null")
    for key in ("transcription_language", "transcription_model",
                "transcription_device", "transcription_compute_type"):
        if key in subtitles and not isinstance(subtitles[key], str):
            raise ValueError(f"conversion.subtitles.{key} must be a string")

    upload = check_object(root.get("upload", {}), "upload", {
        "skip", "no_confirm", "schedule", "content", "platforms",
    })
    if "skip" in upload and not isinstance(upload["skip"], bool):
        raise ValueError("upload.skip must be a boolean")
    if "no_confirm" in upload and upload["no_confirm"] is not None and not isinstance(upload["no_confirm"], bool):
        raise ValueError("upload.no_confirm must be a boolean or null")
    schedule = check_object(upload.get("schedule", {}), "upload.schedule",
                            {"publish_at", "timezone"})
    for key, value in schedule.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"upload.schedule.{key} must be a string or null")
    content = check_object(upload.get("content", {}), "upload.content",
                           {"title", "description", "tags"})
    for key in ("title", "description"):
        if key in content and content[key] is not None and not isinstance(content[key], str):
            raise ValueError(f"upload.content.{key} must be a string or null")
    if "tags" in content and (not isinstance(content["tags"], list)
                               or any(not isinstance(tag, str) for tag in content["tags"])):
        raise ValueError("upload.content.tags must be a list of strings")
    platforms = check_object(upload.get("platforms", {}), "upload.platforms",
                             {"include", "exclude", *SUPPORTED_PLATFORMS})
    for key in ("include", "exclude"):
        values = platforms.get(key, [])
        if not isinstance(values, list) or any(
                not isinstance(value, str) or value not in
                SUPPORTED_PLATFORMS_SET for value in values):
            raise ValueError(f"upload.platforms.{key} must contain supported platform names")
    for platform in SUPPORTED_PLATFORMS:
        if platform in platforms and not isinstance(platforms[platform], dict):
            raise ValueError(f"upload.platforms.{platform} must be an object")

def merge_configuration(global_defaults: dict[str, Any],
                        job_overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge job overrides over defaults without mutating either input."""
    if not isinstance(global_defaults, dict) or not isinstance(job_overrides, dict):
        raise ValueError("Global defaults and job overrides must be objects")

    def merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(base)
        for key, value in patch.items():
            if isinstance(result.get(key), dict) and isinstance(value, dict):
                result[key] = merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    return merge(global_defaults, job_overrides)


def validate_source_name(source: Any) -> str:
    """Require a non-empty root-level filename, rejecting traversal/separators."""
    if not isinstance(source, str) or not source or source in {".", ".."}:
        raise ValueError("general.source must be a root-level filename")
    if "/" in source or "\\" in source or PurePath(source).name != source:
        raise ValueError("general.source must not contain directory separators")
    if any(ord(character) < 32 for character in source):
        raise ValueError("general.source contains invalid control characters")
    return source


def filename_title(source: str) -> str:
    """Remove one final supported media extension without changing the stem."""
    stem, separator, extension = source.rpartition(".")
    if separator and f".{extension.lower()}" in SUPPORTED_SOURCE_EXTENSIONS:
        return stem
    return source


def resolve_job_configuration(
        global_defaults: dict[str, Any],
        job_overrides: dict[str, Any],
        layouts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Resolve defaults and a per-job object into a finalized configuration."""
    validate_job_configuration(global_defaults)
    validate_job_configuration(job_overrides)
    overrides = deepcopy(job_overrides)
    override_general = overrides.get("general", {})
    if not isinstance(override_general, dict):
        raise ValueError("general must be an object")
    defaults_general = global_defaults.get("general", {})
    if not isinstance(defaults_general, dict):
        raise ValueError("global defaults general must be an object")
    source = override_general.get("source")
    if source is None:
        source = defaults_general.get("source")
    if source is not None:
        source = validate_source_name(source)
        override_general["source"] = source
        overrides["general"] = override_general

    effective = merge_configuration(global_defaults, overrides)
    general = effective.setdefault("general", {})
    if source is not None:
        general["source"] = source

    upload = effective.setdefault("upload", {})
    content = upload.setdefault("content", {})
    title = content.get("title")
    if not isinstance(title, str) or not title.strip():
        content["title"] = filename_title(source) if source is not None else ""

    conversion = effective.setdefault("conversion", {})
    layout_id = conversion.get("layout_id")
    conversion.setdefault("layout_id", layout_id)
    inline_layout = conversion.get("layout")
    if layout_id is not None:
        matching = [record for record in (layouts or [])
                    if record.get("id") == layout_id]
        if not matching:
            raise ValueError(f"Unknown conversion.layout_id: {layout_id}")
        preset = matching[0].get("layout")
        if not isinstance(preset, dict):
            raise ValueError(f"Layout registry entry {layout_id} has no layout object")
        conversion["layout"] = merge_configuration(
            preset, inline_layout if isinstance(inline_layout, dict) else {})
    elif inline_layout is not None:
        conversion["layout"] = deepcopy(inline_layout)
    else:
        conversion["layout"] = {}

    subtitles = conversion.setdefault("subtitles", {})
    if not isinstance(subtitles, dict):
        raise ValueError("conversion.subtitles must be an object")
    renderer = subtitles.setdefault("renderer", "overlay")
    if renderer not in {"overlay", "stacked"}:
        raise ValueError("conversion.subtitles.renderer must be overlay or stacked")
    layout = conversion["layout"]
    if not isinstance(layout, dict):
        raise ValueError("conversion.layout must be an object")
    validate_layout(layout)
    layout = normalize_layout(layout)
    captions = layout.setdefault("captions", {})
    if not isinstance(captions, dict):
        raise ValueError("conversion.layout.captions must be an object")
    if not conversion.get("skip", False) and not subtitles.get("skip", False):
        collection = captions.setdefault(renderer, {"items": []})
        if not isinstance(collection, dict):
            raise ValueError(f"conversion.layout.captions.{renderer} must be an object")
        collection.setdefault("items", [])
    layout = resolve_layout_geometry(layout)
    validate_layout(layout)
    conversion["layout"] = layout

    return effective