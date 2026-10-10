"""Build-time form specification for the dashboard configuration form.

The dashboard renders every settable job-configuration field from this spec
instead of hardcoded per-field form code (issue #257). The spec is generated
from ``clipmorph.configuration`` so a schema change cannot silently drop a
field: the walk below visits the canonical job-defaults tree, and a freshness
test asserts the shipped JSON matches this module's output and that every
settable leaf is represented.

Regenerate the shipped artifact with::

    python -m clipmorph.form_spec

The JSON is written to ``frontend/public/form-spec.json``; the frontend build
copies it into ``clipmorph/web_assets/form-spec.json``, which the web service
serves at ``/form-spec.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from clipmorph.configuration import DEFAULT_APP_CONFIGURATION
from clipmorph.configuration import SCHEDULE_MODES
from clipmorph.configuration import SUBTITLE_RENDERERS
from clipmorph.platforms import SUPPORTED_PLATFORMS
from clipmorph.platforms import build_platform_default_config


FORM_SPEC_VERSION = 1

# Human labels for section and leaf paths. A missing leaf label falls back to a
# title-cased leaf key, so a new schema field still renders (never dropped).
_SECTION_LABELS = {
    "general": "General",
    "conversion": "Conversion",
    "conversion.subtitles": "Subtitles & transcription",
    "upload": "Upload",
    "upload.schedule": "Schedule",
    "upload.content": "Content",
    "upload.suggestions": "Suggestions",
    "platforms": "Platforms",
}

_FIELD_LABELS = {
    "general.clean": "Clean generated files",
    "general.no_confirm": "Skip confirmations",
    "conversion.layout_id": "Layout preset",
    "conversion.layout": "Inline layout",
    "conversion.skip": "Skip conversion",
    "conversion.strict": "Strict validation",
    "conversion.no_confirm": "Skip conversion confirmations",
    "conversion.clean": "Clean conversion files",
    "conversion.subtitles.skip": "Skip transcript",
    "conversion.subtitles.renderer": "Caption renderer",
    "conversion.subtitles.no_confirm": "Skip subtitle confirmations",
    "conversion.subtitles.clean": "Clean subtitle files",
    "conversion.subtitles.transcription_language": "Transcription language",
    "conversion.subtitles.transcription_model": "Transcription model",
    "conversion.subtitles.transcription_device": "Transcription device",
    "conversion.subtitles.transcription_compute_type": "Transcription compute type",
    "upload.skip": "Skip upload",
    "upload.no_confirm": "Skip upload confirmations",
    "upload.schedule.publish_at": "Publish at",
    "upload.schedule.timezone": "Timezone",
    "upload.schedule.mode": "Schedule mode",
    "upload.content.title": "Title",
    "upload.content.description": "Description",
    "upload.content.tags": "Tags",
    "upload.suggestions.provider": "Suggestion provider",
    "upload.suggestions.model": "Suggestion model",
}

_FIELD_HINTS = {
    "general.clean": "Remove intermediate conversion files once a job finishes.",
    "conversion.layout_id": "Materialize a saved layout preset over the inline layout.",
    "upload.schedule.publish_at": "UTC ISO-8601 timestamp; a future instant defers publication.",
    "upload.schedule.mode": "Who holds a future publication: ClipMorph or the platform.",
    "upload.content.tags": "Comma-separated list of tags.",
}

# Enum options are derived from the schema constants the validator owns, so a
# schema-side change to either option set flows into the form spec (issue #257).
_ENUM_OPTIONS = {
    "conversion.subtitles.renderer": sorted(SUBTITLE_RENDERERS),
    "upload.schedule.mode": sorted(
        mode for mode in SCHEDULE_MODES if mode is not None),
}

_TEXT_FIELDS = {"upload.content.description"}
_LIST_FIELDS = {"upload.content.tags"}
_DATETIME_FIELDS = {"upload.schedule.publish_at"}
_OBJECT_FIELDS = {"conversion.layout"}
# Nullable leaves whose default is ``None`` and whose type is not inferable
# from the value alone.
_BOOLEAN_NULLABLE = {
    "general.no_confirm", "conversion.no_confirm", "conversion.clean",
    "conversion.subtitles.no_confirm", "conversion.subtitles.clean",
    "upload.no_confirm",
}
_STRING_NULLABLE = {
    "conversion.layout_id", "upload.schedule.timezone",
    "upload.suggestions.model",
}
# ``upload.schedule`` is absent from the defaults tree (an unset schedule is
# the default), so its fields are declared here.
_SCHEDULE_DEFAULTS = {"publish_at": None, "timezone": None, "mode": "local"}

# Transcription keys drive the ONE transcript session a job produces, so a
# per-platform override of them is rejected by the schema (issue #240); the
# spec marks them protected so the per-platform form can hide or disable them.
_PROTECTED_PER_PLATFORM = {
    "conversion.subtitles.transcription_language",
    "conversion.subtitles.transcription_model",
    "conversion.subtitles.transcription_device",
    "conversion.subtitles.transcription_compute_type",
}


def _label_for(path: str, leaf: str) -> str:
    return _FIELD_LABELS.get(path) or leaf.replace("_", " ").capitalize()


def _infer_type(path: str, value: Any) -> str:
    if path in _ENUM_OPTIONS:
        return "enum"
    if path in _TEXT_FIELDS:
        return "text"
    if path in _LIST_FIELDS:
        return "string_list"
    if path in _DATETIME_FIELDS:
        return "datetime"
    if path in _OBJECT_FIELDS:
        return "object"
    if path in _BOOLEAN_NULLABLE:
        return "boolean"
    if path in _STRING_NULLABLE:
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "string_list"
    return "string"


def _field(path: str, value: Any, per_platform: bool = False) -> dict[str, Any]:
    leaf = path.rsplit(".", 1)[-1]
    record: dict[str, Any] = {
        "path": path,
        "key": leaf,
        "label": _label_for(path, leaf),
        "type": _infer_type(path, value),
        "default": value,
    }
    if path in _ENUM_OPTIONS:
        record["options"] = list(_ENUM_OPTIONS[path])
    if path in _FIELD_HINTS:
        record["hint"] = _FIELD_HINTS[path]
    if per_platform and path in _PROTECTED_PER_PLATFORM:
        record["protected"] = True
    return record


def _walk(node: dict[str, Any], prefix: str = "", per_platform: bool = False
          ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Split a defaults subtree into leaf fields and nested child sections."""
    fields: list[dict[str, Any]] = []
    children: dict[str, dict[str, Any]] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            children[key] = {"path": path, "node": value}
        else:
            fields.append(_field(path, value, per_platform))
    return fields, children


def _section(section_id: str, fields: list[dict[str, Any]],
             children: dict[str, dict[str, Any]], per_platform: bool = False
             ) -> dict[str, Any]:
    section: dict[str, Any] = {
        "id": section_id,
        "label": _SECTION_LABELS.get(section_id, section_id),
        "fields": fields,
    }
    if children:
        section["sections"] = [
            _section(f"{section_id}.{key}", *_walk(child["node"], child["path"], per_platform),
                     per_platform=per_platform)
            for key, child in children.items()
        ]
    return section


def _override_sections(per_platform: bool) -> list[dict[str, Any]]:
    defaults = cast(dict[str, Any], DEFAULT_APP_CONFIGURATION["job_defaults"])
    sections: list[dict[str, Any]] = []
    for key in ("general", "conversion", "upload"):
        node = dict(defaults.get(key, {}))
        # ``general.source`` is source identity, not a user-set field.
        node.pop("source", None)
        fields, children = _walk(node, key, per_platform)
        if key == "conversion":
            # The inline layout object is settable but absent from defaults
            # (defaults only carry ``layout_id``); list it explicitly.
            fields.append(_field("conversion.layout", None, per_platform))
        if key == "upload":
            children["schedule"] = {
                "path": "upload.schedule", "node": dict(_SCHEDULE_DEFAULTS)}
        sections.append(_section(key, fields, children, per_platform))
    return sections


def _top_sections() -> list[dict[str, Any]]:
    return _override_sections(per_platform=False)


def _platform_sections() -> list[dict[str, Any]]:
    """Per-platform override sections (transcription keys are protected)."""
    return _override_sections(per_platform=True)


def _platform_flat_fields() -> dict[str, list[dict[str, Any]]]:
    flat: dict[str, list[dict[str, Any]]] = {}
    for platform, values in build_platform_default_config().items():
        flat[platform] = [
            _field(f"platforms.{platform}.{key}", value)
            for key, value in values.items()
        ]
    return flat


def form_spec() -> dict[str, Any]:
    """Return the canonical configuration-form specification."""
    return {
        "schema_version": FORM_SPEC_VERSION,
        "source": "clipmorph.configuration",
        "sections": _top_sections(),
        "platforms": {
            "label": _SECTION_LABELS["platforms"],
            "order": list(SUPPORTED_PLATFORMS),
            "sections": _platform_sections(),
            "flat_fields": _platform_flat_fields(),
        },
    }


def spec_path() -> Path:
    """The shipped spec location, relative to the repository root."""
    return Path(__file__).resolve().parent.parent / "frontend" / "public" / "form-spec.json"


def render_spec() -> str:
    """Serialize the spec deterministically (stable for the freshness check)."""
    return json.dumps(form_spec(), indent=2, ensure_ascii=False) + "\n"


def write_spec(path: str | Path | None = None) -> Path:
    """Write the spec JSON to ``path`` (default: the shipped location)."""
    destination = Path(path) if path is not None else spec_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_spec(), encoding="utf-8")
    return destination


def main() -> None:
    destination = write_spec()
    print(f"Wrote form spec to {destination}")


if __name__ == "__main__":
    main()
