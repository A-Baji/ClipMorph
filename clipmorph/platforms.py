"""Shared platform registry and metadata rules.

Single source of truth for which platforms ClipMorph supports and how
platform-specific metadata is derived. CLI choices, workflow defaults,
service validation, per-platform configuration defaults, policy validation,
and web surface lists all read from here instead of duplicating the set.
"""

from __future__ import annotations

from typing import Any

SUPPORTED_PLATFORMS: tuple[str, ...] = (
    "youtube", "instagram", "tiktok", "twitter")
SUPPORTED_PLATFORMS_SET: frozenset[str] = frozenset(SUPPORTED_PLATFORMS)

# Platform display order used by surfaces that show a stable list.
PLATFORM_TITLE = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "twitter": "Twitter/X",
}

# Per-platform upload defaults, previously duplicated in cli.build_platform_default_config
# and inlined in upload_pipeline metadata mapping.
PLATFORM_DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "youtube": {"category": "22", "privacy_status": "public"},
    "instagram": {"share_to_feed": True, "thumb_offset": 0},
    "tiktok": {"privacy_level": "PUBLIC_TO_EVERYONE"},
    "twitter": {},
}


def build_platform_default_config() -> dict[str, dict[str, Any]]:
    """Return a fresh copy of per-platform upload defaults."""
    return {platform: dict(values)
            for platform, values in PLATFORM_DEFAULT_CONFIG.items()}


def is_supported_platform(platform: str) -> bool:
    """Return True when the lowercase platform name is supported."""
    return str(platform).lower() in SUPPORTED_PLATFORMS_SET


def enabled_platforms(platforms_config: dict[str, Any] | None) -> list[str]:
    """Resolve upload.platforms config into an ordered platform list.

    Empty or missing ``include`` means all platforms; ``exclude`` removes
    from the included set. Duplicates are dropped while preserving order.
    """
    platforms = platforms_config or {}
    included = platforms.get("include")
    if isinstance(included, str):
        included = [included]
    if not included:
        included = SUPPORTED_PLATFORMS
    excluded = {str(value).lower() for value in (platforms.get("exclude") or [])}
    seen: set[str] = set()
    resolved: list[str] = []
    for value in included:
        name = str(value).lower()
        if name in excluded or name in seen:
            continue
        seen.add(name)
        resolved.append(name)
    return resolved
