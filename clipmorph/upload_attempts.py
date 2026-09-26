"""Upload attempt execution and result normalization.

Owns the mechanics of turning one submitted upload draft into per-platform
pipeline results: option mapping, pipeline construction, execution, and
per-result normalization. Manifest/checkpoint state transitions stay in
``clipmorph.service``; platform transport stays in ``upload_pipeline``.
"""

from __future__ import annotations

from typing import Any


def content_options(upload_config: dict[str, Any],
                    platforms: list[str]) -> dict[str, Any]:
    """Build the common pipeline options for one upload submission."""
    content = upload_config.get("content", {})
    options: dict[str, Any] = {
        "description": content.get("description", ""),
        "tags": content.get("tags", []),
    }
    for platform, values in upload_config.get("platforms", {}).items():
        if platform in platforms and isinstance(values, dict):
            options.update({f"{platform}_{key}": value
                            for key, value in values.items()})
    return options


def execute_upload_pipeline(platforms: list[str], artifact_path: str,
                            upload_config: dict[str, Any]) -> dict[str, Any]:
    """Run the upload pipeline and return per-platform results.

    Platform failures that abort the whole pipeline are normalized into a
    failed result per requested platform so no requested destination silently
    disappears (#87).
    """
    from clipmorph.upload_pipeline import UploadPipeline

    platform_flags = {platform: True for platform in platforms}
    pipeline = UploadPipeline(**platform_flags)
    content = upload_config.get("content", {})
    try:
        return pipeline.run(artifact_path, content.get("title", ""),
                            **content_options(upload_config, platforms))
    except Exception as error:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return {platform: {"success": False, "error": str(error),
                           "started_at": now, "completed_at": now}
                for platform in platforms}


def normalize_results(results: dict[str, Any]) -> dict[str, Any]:
    """Key results by lowercase platform name with separators removed."""
    return {
        str(platform).lower().replace(" ", ""): result
        for platform, result in results.items()
    }
