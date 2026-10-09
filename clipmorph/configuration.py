"""Shared app/job configuration loading and normalization."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import PurePath
from pathlib import Path
import shutil
from typing import Any
import uuid

import yaml

from clipmorph.layout import normalize_layout
from clipmorph.layout import resolve_layout_geometry
from clipmorph.platforms import SUPPORTED_PLATFORMS
from clipmorph.platforms import build_platform_default_config
from clipmorph.layout import validate_layout


SUPPORTED_SOURCE_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}

# Bumped in the same commit as any breaking app.yml schema change. This stamp is
# independent of the job manifest schema version in clipmorph/job.py; the two
# are never unified. #203 moved `platforms` out of `upload` to the job-config
# top level, so `upload.platforms` is no longer accepted: bumping the stamp
# turns an existing app.yml into one actionable version error instead of an
# `Unknown upload field(s): platforms` validation cascade.
APP_CONFIG_VERSION = 2

# Who holds a future publication for `upload.schedule`: ClipMorph's own timer
# ("local", the default) or the platform's native scheduling ("platform").
# `None` is the unset value the YAML layer writes; it defers to "local".
# Platform eligibility is not a config concern: it is enforced at submission by
# the registry in clipmorph.platforms, so no per-platform mode map exists.
SCHEDULE_MODES = {None, "local", "platform"}

# Number of rotated `<file>.backup[n]` copies kept when retention.backups.keep_n
# is unset or app.yml cannot be read (auth may persist before a valid app.yml).
DEFAULT_BACKUP_KEEP_N = 5

APP_CONFIGURATION_FIELDS = {
    "config_version", "source_dir", "output_dir", "job_defaults", "layouts",
    "retention", "storage",
}

RETENTION_FIELDS = {
    "artifacts": {"max_age_days", "max_bytes"},
    "backups": {"keep_n"},
}

DEFAULT_APP_CONFIGURATION = {
    "config_version": APP_CONFIG_VERSION,
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
            "suggestions": {"provider": "template", "model": None},
        },
        # Per-platform job defaults are generated from the platform registry
        # (clipmorph.platforms.PLATFORM_DEFAULT_CONFIG) so the template and
        # the upload adapters cannot drift apart. Entries merge per job and
        # per platform in the usual layered way (see docs/CONFIG_LAYERS.md);
        # flat scalars freeze into ``{platform}_{option}`` upload kwargs.
        "platforms": build_platform_default_config(),
    },
    "layouts": [],
    "retention": {
        "artifacts": {"max_age_days": None, "max_bytes": None},
        "backups": {"keep_n": None},
    },
    "storage": {
        "backend": "local",
    },
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


def require_app_config_version(configuration: Any) -> None:
    """Reject app.yml files that are unstamped or hold a different version."""
    version = configuration.get("config_version") if isinstance(
        configuration, dict) else None
    if version != APP_CONFIG_VERSION:
        raise ValueError(
            f"app.yml config_version must be {APP_CONFIG_VERSION}; the file is "
            "missing it or holds a different value. Run `clipmorph init` beside "
            "your current app.yml to regenerate a template, then copy your "
            "settings over.")


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
    # The version guard runs before every other field check so an outdated file
    # reports one actionable error instead of a validation cascade.
    require_app_config_version(configuration)
    unknown = set(configuration) - APP_CONFIGURATION_FIELDS
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
    unknown = set(configuration) - APP_CONFIGURATION_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown app configuration field(s): {', '.join(sorted(unknown))}")
    finalized = merge_configuration(DEFAULT_APP_CONFIGURATION, configuration)
    # Stamping is bookkeeping, not a compatibility shim: an explicitly
    # mismatched stamp is still rejected below and on the next load.
    finalized.setdefault("config_version", APP_CONFIG_VERSION)
    _validate_app_configuration(finalized)
    return atomic_write_text(
        path, yaml.safe_dump(finalized, sort_keys=False, allow_unicode=True))


def rotate_backup(path: str | Path, keep_n: int) -> Path:
    """Back a file up to the newest free numbered slot and drop stale copies.

    The newest copy is `<name>.backup`, older ones `<name>.backup1`,
    `<name>.backup2`, and so on. Only the newest ``keep_n`` copies survive.
    """
    destination = Path(path)
    backup_path = destination.with_suffix(destination.suffix + ".backup")
    limit = max(1, int(keep_n))
    highest_index = 0
    while backup_path.with_name(f"{backup_path.name}{highest_index + 1}").exists():
        highest_index += 1

    for index in range(highest_index, 0, -1):
        current = backup_path.with_name(f"{backup_path.name}{index}")
        shifted = backup_path.with_name(f"{backup_path.name}{index + 1}")
        if shifted.exists():
            shifted.unlink()
        current.rename(shifted)
    if backup_path.exists():
        backup_path.replace(backup_path.with_name(f"{backup_path.name}1"))
    shutil.copy2(destination, backup_path)

    for index in range(1, highest_index + 2):
        if index < limit:
            continue
        overflow = backup_path.with_name(f"{backup_path.name}{index}")
        if overflow.exists():
            overflow.unlink()
    return backup_path


def resolve_backup_keep_n(app_config_path: str | Path | None) -> int:
    """Return retention.backups.keep_n, or the default when app.yml is unusable."""
    if app_config_path is None:
        return DEFAULT_BACKUP_KEEP_N
    try:
        configuration = load_app_configuration(app_config_path)
    except (OSError, ValueError):
        return DEFAULT_BACKUP_KEEP_N
    keep_n = configuration.get("retention", {}).get("backups", {}).get("keep_n")
    if isinstance(keep_n, bool) or not isinstance(keep_n, int) or keep_n < 1:
        return DEFAULT_BACKUP_KEEP_N
    return keep_n


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


def _validate_retention(retention: Any) -> None:
    """Validate the opt-in app-level retention policy; every knob defaults off."""
    if not isinstance(retention, dict):
        raise ValueError("retention must be an object")
    unknown = set(retention) - set(RETENTION_FIELDS)
    if unknown:
        raise ValueError(
            f"Unknown retention field(s): {', '.join(sorted(unknown))}")
    for section, allowed in RETENTION_FIELDS.items():
        values = retention.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"retention.{section} must be an object")
        unknown_keys = set(values) - allowed
        if unknown_keys:
            raise ValueError(
                f"Unknown retention.{section} field(s): "
                f"{', '.join(sorted(unknown_keys))}")
        for key, value in values.items():
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value < 1):
                raise ValueError(
                    f"retention.{section}.{key} must be a positive integer or null")


def _validate_storage(storage: Any) -> None:
    """Validate the artifact storage backend selection."""
    if not isinstance(storage, dict):
        raise ValueError("storage must be an object")
    backend = storage.get("backend")
    if backend != "local":
        raise ValueError(f"unknown storage backend: {backend}")


def _validate_app_configuration(configuration: dict[str, Any]) -> None:
    require_app_config_version(configuration)
    for path_key in ("source_dir", "output_dir"):
        if not isinstance(configuration.get(path_key), str) or not configuration[path_key]:
            raise ValueError(f"{path_key} must be a non-empty path")
    if not isinstance(configuration.get("job_defaults"), dict):
        raise ValueError("job_defaults must be an object")
    validate_job_configuration(configuration["job_defaults"])
    layouts = configuration.get("layouts")
    if not isinstance(layouts, list):
        raise ValueError("layouts must be a list")
    _validate_retention(configuration.get("retention", {}))
    _validate_storage(configuration.get("storage", {}))
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


def _check_object(value: Any, label: str, allowed: set[str]) -> dict[str, Any]:
    """Require a dict with no unknown keys, returning it for chaining."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(
            f"Unknown {label} field(s): {', '.join(sorted(unknown))}")
    return value


def _validate_general_section(general: Any, label: str = "general") -> None:
    """Validate a general section (top-level or per-platform override)."""
    general = _check_object(general, label, {"source", "no_confirm", "clean"})
    if general.get("source") is not None:
        validate_source_name(general["source"])
    for key in ("no_confirm", "clean"):
        if key in general and not isinstance(general[key], bool):
            raise ValueError(f"{label}.{key} must be a boolean")


def _validate_subtitles_section(subtitles: Any,
                                label: str = "conversion.subtitles",
                                per_platform: bool = False) -> None:
    """Validate a subtitles section (top-level or per-platform override).

    ``transcription_*`` keys drive the ONE transcript session a job produces.
    A per-platform override of them is rejected rather than silently ignored:
    honouring it would need one transcript group per distinct transcription
    config, and no concrete case needs that yet (the guide's YAGNI checkpoint
    makes protected keys the documented fallback until one does).
    """
    transcription_keys = {
        "transcription_language", "transcription_model",
        "transcription_device", "transcription_compute_type",
    }
    subtitles = _check_object(subtitles, label, {
        "skip", "renderer", "no_confirm", "clean", *transcription_keys,
    })
    if per_platform:
        for key in sorted(transcription_keys & set(subtitles)):
            raise ValueError(
                f"{label}.{key} is not allowed per platform; the job shares "
                "one transcript session")
    if subtitles.get("renderer", "overlay") not in {"overlay", "stacked"}:
        raise ValueError(f"{label}.renderer must be overlay or stacked")
    if "skip" in subtitles and not isinstance(subtitles["skip"], bool):
        raise ValueError(f"{label}.skip must be a boolean")
    for key in ("no_confirm", "clean"):
        if key in subtitles and subtitles[key] is not None and not isinstance(subtitles[key], bool):
            raise ValueError(f"{label}.{key} must be a boolean or null")
    for key in transcription_keys:
        if key in subtitles and not isinstance(subtitles[key], str):
            raise ValueError(f"{label}.{key} must be a string")


def _validate_conversion_section(conversion: Any, label: str = "conversion",
                                 per_platform: bool = False) -> None:
    """Validate a conversion section (top-level or per-platform override)."""
    conversion = _check_object(conversion, label, {
        "layout_id", "layout", "skip", "strict", "no_confirm", "clean", "subtitles",
    })
    for key in ("skip", "strict"):
        if key in conversion and not isinstance(conversion[key], bool):
            raise ValueError(f"{label}.{key} must be a boolean")
    for key in ("no_confirm", "clean"):
        if key in conversion and conversion[key] is not None and not isinstance(conversion[key], bool):
            raise ValueError(f"{label}.{key} must be a boolean or null")
    if conversion.get("layout_id") is not None and not isinstance(conversion["layout_id"], str):
        raise ValueError(f"{label}.layout_id must be a string or null")
    if "layout" in conversion and not isinstance(conversion["layout"], dict):
        raise ValueError(f"{label}.layout must be an object")
    _validate_subtitles_section(conversion.get("subtitles", {}),
                                f"{label}.subtitles", per_platform)


def _validate_suggestions_section(suggestions: Any,
                                  label: str = "upload.suggestions") -> None:
    """Validate the suggestions provider selector and generated platform rows."""
    suggestions = _check_object(suggestions, label,
                                {"provider", "model", *SUPPORTED_PLATFORMS})
    if "provider" in suggestions and (
            not isinstance(suggestions["provider"], str)
            or not suggestions["provider"].strip()):
        raise ValueError(f"{label}.provider must be a non-empty string")
    if "model" in suggestions and suggestions["model"] is not None and not isinstance(
            suggestions["model"], str):
        raise ValueError(f"{label}.model must be a string or null")
    for platform in SUPPORTED_PLATFORMS:
        if platform in suggestions and not isinstance(suggestions[platform], dict):
            raise ValueError(f"{label}.{platform} must be an object")


def _validate_upload_section(upload: Any, label: str = "upload") -> None:
    """Validate an upload section (top-level or per-platform override)."""
    upload = _check_object(upload, label, {
        "skip", "no_confirm", "schedule", "content", "suggestions",
    })
    if "skip" in upload and not isinstance(upload["skip"], bool):
        raise ValueError(f"{label}.skip must be a boolean")
    if "no_confirm" in upload and upload["no_confirm"] is not None and not isinstance(upload["no_confirm"], bool):
        raise ValueError(f"{label}.no_confirm must be a boolean or null")
    schedule = _check_object(upload.get("schedule", {}), f"{label}.schedule",
                             {"publish_at", "timezone", "mode"})
    for key, value in schedule.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{label}.schedule.{key} must be a string or null")
    if schedule.get("mode") not in SCHEDULE_MODES:
        raise ValueError(f"{label}.schedule.mode must be one of: local, platform")
    publish_at = schedule.get("publish_at")
    if publish_at is not None:
        try:
            parsed_publish_at = datetime.fromisoformat(publish_at)
        except ValueError as error:
            raise ValueError(
                f"{label}.schedule.publish_at is not an ISO-8601 timestamp: {error}"
            ) from error
        if parsed_publish_at.tzinfo is None:
            raise ValueError(
                f"{label}.schedule.publish_at must include a UTC offset")
    _validate_suggestions_section(upload.get("suggestions", {}),
                                  f"{label}.suggestions")
    content = _check_object(upload.get("content", {}), f"{label}.content",
                            {"title", "description", "tags"})
    for key in ("title", "description"):
        if key in content and content[key] is not None and not isinstance(content[key], str):
            raise ValueError(f"{label}.content.{key} must be a string or null")
    if "tags" in content and (not isinstance(content["tags"], list)
                             or any(not isinstance(tag, str) for tag in content["tags"])):
        raise ValueError(f"{label}.content.tags must be a list of strings")


def _validate_platform_entry(entry: Any, platform: str) -> None:
    """Validate one per-platform override entry.

    Platform entries carry ``general``/``conversion``/``upload`` override
    sections (validated by the shared section validators) plus flat adapter
    option scalars.  Structural impossibilities are rejected: nested
    ``platforms`` (the selection map is not a mirrored section) and
    ``general.source`` (source identity is fixed per job).
    """
    label = f"platforms.{platform}"
    if not isinstance(entry, dict):
        raise ValueError(f"{label} must be an object")
    if "platforms" in entry:
        raise ValueError(
            f"{label}.platforms is not allowed; selection overrides are not "
            "configured per platform")
    general = entry.get("general", {})
    if isinstance(general, dict) and "source" in general:
        raise ValueError(
            f"{label}.general.source is not allowed; source identity is "
            "fixed per job")
    if "general" in entry:
        _validate_general_section(entry["general"], f"{label}.general")
    if "conversion" in entry:
        _validate_conversion_section(entry["conversion"], f"{label}.conversion",
                                     per_platform=True)
    if "upload" in entry:
        _validate_upload_section(entry["upload"], f"{label}.upload")


def validate_job_configuration(configuration: dict[str, Any]) -> None:
    """Validate the canonical general/conversion/upload/platforms job configuration shape.

    Each section's rules live in its dedicated ``_validate_*_section``
    validator so the root configuration and per-platform overrides cannot
    drift; the root validator composes them and keeps only the extra
    structural level (the ``platforms`` map and its entries).
    """
    root = _check_object(configuration, "job configuration",
                         {"general", "conversion", "upload", "platforms"})
    _validate_general_section(root.get("general", {}))
    _validate_conversion_section(root.get("conversion", {}))
    _validate_upload_section(root.get("upload", {}))
    platforms = _check_object(root.get("platforms", {}), "platforms",
                              set(SUPPORTED_PLATFORMS))
    for platform in SUPPORTED_PLATFORMS:
        if platform in platforms:
            _validate_platform_entry(platforms[platform], platform)

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
    # Materialize ``layout_id`` (even as None) so the resolved shape always
    # carries the key; readers may index it directly.
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

    # A per-platform ``conversion`` section composes exactly like the
    # job-level one, so a platform that names a layout is materialized here
    # instead of on every later re-resolution: the manifest then stores one
    # already-resolved shape, and group digests, the review summary and the
    # render loop all read the same layout.  The job's layout is the base and
    # the named preset wins per key, the same law inline layouts compose under.
    for platform, entry in effective.get("platforms", {}).items():
        platform_conversion = entry.get("conversion")
        if not isinstance(platform_conversion, dict):
            continue
        platform_layout_id = platform_conversion.get("layout_id")
        if platform_layout_id is None:
            continue
        matching = [record for record in (layouts or [])
                    if record.get("id") == platform_layout_id]
        if not matching:
            raise ValueError(
                f"Unknown platforms.{platform}.conversion.layout_id: "
                f"{platform_layout_id}")
        preset = matching[0].get("layout")
        if not isinstance(preset, dict):
            raise ValueError(
                f"Layout registry entry {platform_layout_id} has no layout object")
        platform_conversion["layout"] = merge_configuration(
            conversion["layout"], deepcopy(preset))

    return effective


def resolve_platform_configuration(
        manifest_configuration: dict[str, Any],
        global_defaults: dict[str, Any],
        layouts: list[dict[str, Any]] | None,
        platform: str) -> dict[str, Any]:
    """Resolve one platform's effective configuration by deep-merging its
    override sections over the job's effective configuration.

    ``global_defaults`` come from the manifest's
    ``configuration_sources["global_defaults"]`` so the result is a full
    job-shaped effective configuration (layout materialization, title
    derivation, etc.) exactly like ``resolve_job_configuration`` produces.
    """
    overrides = manifest_configuration.get("platforms", {}).get(platform, {})
    sections = {key: overrides[key] for key in ("general", "conversion", "upload")
                if key in overrides}
    effective = merge_configuration(manifest_configuration, sections)
    return resolve_job_configuration(global_defaults, effective, layouts)


# --set inline overrides (issue #238): one override implementation feeds the
# CLI's repeatable ``--set DOT.PATH=VALUE`` flag wherever a job configuration
# can be supplied. Paths are dotted keys relative to the app-config root
# (a literal ``config.`` prefix is stripped); values parse in YAML/JSON scalar
# order. The overlay is validated here so unknown leaves report their closest
# valid sibling paths and type mismatches name the expected type, then it is
# applied exactly like a partial configuration overlay (create overrides,
# patch merge, upload draft edit). The section key sets mirror the shared
# ``_validate_*_section`` validators above; the CLI-surface test suite pins
# them together so a schema change that silences one side fails the other.
_OVERLAY_ROOT_KEYS = frozenset({"general", "conversion", "upload", "platforms"})
_OVERLAY_GENERAL_KEYS = frozenset({"source", "no_confirm", "clean"})
_OVERLAY_CONVERSION_KEYS = frozenset({
    "layout_id", "layout", "skip", "strict", "no_confirm", "clean", "subtitles",
})
_OVERLAY_SUBTITLES_KEYS = frozenset({
    "skip", "renderer", "no_confirm", "clean", "transcription_language",
    "transcription_model", "transcription_device", "transcription_compute_type",
})
_OVERLAY_UPLOAD_KEYS = frozenset(
    {"skip", "no_confirm", "schedule", "content", "suggestions"})
_OVERLAY_SCHEDULE_KEYS = frozenset({"publish_at", "timezone", "mode"})
_OVERLAY_CONTENT_KEYS = frozenset({"title", "description", "tags"})
_OVERLAY_SUGGESTIONS_KEYS = frozenset(
    {"provider", "model", *SUPPORTED_PLATFORMS})
_TRANSCRIPTION_KEYS = frozenset({
    "transcription_language", "transcription_model",
    "transcription_device", "transcription_compute_type",
})


def _parse_override_scalar(raw: str) -> Any:
    """Coerce one ``--set`` value in YAML/JSON scalar order."""
    text = raw.strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"--set list value is not valid JSON: {error}") from error
        if not isinstance(parsed, list):
            raise ValueError("--set list value must decode to a JSON list")
        return parsed
    try:
        return int(text, 10)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _assign_overlay_path(overlay: dict[str, Any], segments: list[str],
                         value: Any) -> None:
    """Write one value into a nested overlay, creating parent objects."""
    node = overlay
    for segment in segments[:-1]:
        child = node.get(segment)
        if not isinstance(child, dict):
            child = {}
            node[segment] = child
        node = child
    node[segments[-1]] = value


def parse_config_overrides(pairs: list[str]) -> dict[str, Any]:
    """Parse repeatable ``--set dotted.path=value`` pairs into an overlay.

    A literal ``config.`` prefix is accepted and stripped, and later
    occurrences of the same path apply over earlier ones. The result is a
    partial job configuration object that ``validate_config_overlay`` checks.
    """
    overlay: dict[str, Any] = {}
    for pair in pairs:
        key, separator, raw = pair.partition("=")
        key = key.strip()
        if not separator or not key or "." not in key:
            raise ValueError(f"--set expects a dotted path and a value: {pair!r}")
        if key.startswith("config."):
            key = key[len("config."):]
        segments = [segment.strip() for segment in key.split(".")]
        if not all(segments):
            raise ValueError(f"--set path has an empty segment: {key!r}")
        _assign_overlay_path(overlay, segments, _parse_override_scalar(raw))
    return overlay


def _overlay_unknown(label: str, unknown: set[str], valid: set[str]) -> ValueError:
    return ValueError(
        f"Unknown {label} field(s): {', '.join(sorted(unknown))}; "
        f"closest valid: {', '.join(sorted(valid))}")


def _overlay_check_object(value: Any, label: str,
                          allowed: frozenset[str]) -> dict[str, Any]:
    """Require a dict with only allowed keys, reporting valid sibling paths."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(value) - set(allowed)
    if unknown:
        raise _overlay_unknown(label, unknown, set(allowed))
    return value


def _validate_overlay_general(general: Any, label: str) -> None:
    general = _overlay_check_object(general, label, _OVERLAY_GENERAL_KEYS)
    for key in ("no_confirm", "clean"):
        if key in general and not isinstance(general[key], bool):
            raise ValueError(f"{label}.{key} must be a boolean")
    if general.get("source") is not None:
        validate_source_name(general["source"])


def _validate_overlay_conversion(conversion: Any, label: str,
                                 per_platform: bool) -> None:
    conversion = _overlay_check_object(
        conversion, label, _OVERLAY_CONVERSION_KEYS)
    for key in ("skip", "strict"):
        if key in conversion and not isinstance(conversion[key], bool):
            raise ValueError(f"{label}.{key} must be a boolean")
    for key in ("no_confirm", "clean"):
        if key in conversion and conversion[key] is not None and not isinstance(
                conversion[key], bool):
            raise ValueError(f"{label}.{key} must be a boolean or null")
    if conversion.get("layout_id") is not None and not isinstance(
            conversion["layout_id"], str):
        raise ValueError(f"{label}.layout_id must be a string or null")
    if "layout" in conversion and not isinstance(conversion["layout"], dict):
        raise ValueError(f"{label}.layout must be an object")
    subtitles = conversion.get("subtitles")
    if subtitles is not None:
        subtitles = _overlay_check_object(
            subtitles, f"{label}.subtitles", _OVERLAY_SUBTITLES_KEYS)
        if "skip" in subtitles and not isinstance(subtitles["skip"], bool):
            raise ValueError(f"{label}.subtitles.skip must be a boolean")
        for key in ("no_confirm", "clean"):
            if key in subtitles and subtitles[key] is not None and not isinstance(
                    subtitles[key], bool):
                raise ValueError(f"{label}.subtitles.{key} must be a boolean or null")
        for key in _TRANSCRIPTION_KEYS:
            if key in subtitles and not isinstance(subtitles[key], str):
                raise ValueError(f"{label}.subtitles.{key} must be a string")
        if subtitles.get("renderer", "overlay") not in {"overlay", "stacked"}:
            raise ValueError(f"{label}.subtitles.renderer must be overlay or stacked")
        if per_platform:
            protected = sorted(_TRANSCRIPTION_KEYS & set(subtitles))
            if protected:
                raise ValueError(
                    f"{label}.subtitles.{protected[0]} is not allowed per "
                    "platform; the job shares one transcript session")


def _validate_overlay_upload(upload: Any, label: str) -> None:
    upload = _overlay_check_object(upload, label, _OVERLAY_UPLOAD_KEYS)
    if "skip" in upload and not isinstance(upload["skip"], bool):
        raise ValueError(f"{label}.skip must be a boolean")
    if "no_confirm" in upload and upload["no_confirm"] is not None and not isinstance(
            upload["no_confirm"], bool):
        raise ValueError(f"{label}.no_confirm must be a boolean or null")
    schedule = upload.get("schedule")
    if schedule is not None:
        schedule = _overlay_check_object(
            schedule, f"{label}.schedule", _OVERLAY_SCHEDULE_KEYS)
        for key in ("publish_at", "timezone"):
            if key in schedule and schedule[key] is not None and not isinstance(
                    schedule[key], str):
                raise ValueError(f"{label}.schedule.{key} must be a string or null")
        publish_at = schedule.get("publish_at")
        if publish_at is not None:
            try:
                parsed_publish_at = datetime.fromisoformat(publish_at)
            except ValueError as error:
                raise ValueError(
                    f"{label}.schedule.publish_at is not an ISO-8601 "
                    f"timestamp: {error}") from error
            if parsed_publish_at.tzinfo is None:
                raise ValueError(
                    f"{label}.schedule.publish_at must include a UTC offset")
        if schedule.get("mode") not in SCHEDULE_MODES:
            raise ValueError(f"{label}.schedule.mode must be one of: local, platform")
    content = upload.get("content")
    if content is not None:
        content = _overlay_check_object(
            content, f"{label}.content", _OVERLAY_CONTENT_KEYS)
        for key in ("title", "description"):
            if key in content and content[key] is not None and not isinstance(
                    content[key], str):
                raise ValueError(f"{label}.content.{key} must be a string or null")
        if "tags" in content and (not isinstance(content["tags"], list)
                                  or any(not isinstance(tag, str)
                                         for tag in content["tags"])):
            raise ValueError(f"{label}.content.tags must be a list of strings")
    suggestions = upload.get("suggestions")
    if suggestions is not None:
        suggestions = _overlay_check_object(
            suggestions, f"{label}.suggestions", _OVERLAY_SUGGESTIONS_KEYS)
        if "provider" in suggestions and (
                not isinstance(suggestions["provider"], str)
                or not suggestions["provider"].strip()):
            raise ValueError(f"{label}.suggestions.provider must be a non-empty string")
        if "model" in suggestions and suggestions["model"] is not None and not isinstance(
                suggestions["model"], str):
            raise ValueError(f"{label}.suggestions.model must be a string or null")
        for platform in SUPPORTED_PLATFORMS:
            if platform in suggestions and not isinstance(
                    suggestions[platform], dict):
                raise ValueError(f"{label}.suggestions.{platform} must be an object")


def _validate_overlay_platforms(platforms: Any) -> None:
    platforms = _overlay_check_object(
        platforms, "platforms", frozenset(SUPPORTED_PLATFORMS))
    defaults = build_platform_default_config()
    for platform, entry in platforms.items():
        label = f"platforms.{platform}"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be an object")
        flat_keys = set(defaults.get(platform, {}))
        valid = {"general", "conversion", "upload"} | flat_keys
        unknown = set(entry) - valid
        if unknown:
            raise _overlay_unknown(label, unknown, valid)
        if "platforms" in entry:
            raise ValueError(
                f"{label}.platforms is not allowed; selection overrides are "
                "not configured per platform")
        if entry.get("general") is not None:
            general = entry["general"]
            if isinstance(general, dict) and "source" in general:
                raise ValueError(
                    f"{label}.general.source is not allowed; source identity "
                    "is fixed per job")
            _validate_overlay_general(general, f"{label}.general")
        if entry.get("conversion") is not None:
            _validate_overlay_conversion(
                entry["conversion"], f"{label}.conversion", per_platform=True)
        if entry.get("upload") is not None:
            _validate_overlay_upload(entry["upload"], f"{label}.upload")
        for key in sorted(flat_keys & set(entry)):
            expected = defaults[platform][key]
            actual = entry[key]
            if expected is None:
                continue
            if isinstance(expected, bool):
                if not isinstance(actual, bool):
                    raise ValueError(f"{label}.{key} must be a boolean")
            elif isinstance(expected, int):
                if isinstance(actual, bool) or not isinstance(actual, int):
                    raise ValueError(f"{label}.{key} must be an integer")
            elif isinstance(expected, float):
                if isinstance(actual, bool) or not isinstance(actual, (int, float)):
                    raise ValueError(f"{label}.{key} must be a number")
            elif isinstance(expected, str):
                if not isinstance(actual, str):
                    raise ValueError(f"{label}.{key} must be a string")


def validate_config_overlay(overlay: dict[str, Any]) -> None:
    """Validate one ``--set`` overlay against the job configuration schema.

    Unknown leaves report their closest valid sibling paths and type
    mismatches name the expected type (the CLI contract from the #240
    implementation guide); nothing is silently ignored. Per-platform flat
    adapter scalars are checked against the platform registry defaults.
    """
    root = _overlay_check_object(overlay, "job configuration", _OVERLAY_ROOT_KEYS)
    if root.get("general") is not None:
        _validate_overlay_general(root["general"], "general")
    if root.get("conversion") is not None:
        _validate_overlay_conversion(root["conversion"], "conversion",
                                     per_platform=False)
    if root.get("upload") is not None:
        _validate_overlay_upload(root["upload"], "upload")
    if root.get("platforms") is not None:
        _validate_overlay_platforms(root["platforms"])