"""Shared platform registry and per-platform upload defaults.

Single source of truth for which platforms ClipMorph supports and for each
platform's plain upload defaults. CLI choices, workflow defaults, service
validation, per-platform configuration defaults, and web surface lists all read
from here instead of duplicating the set.

Ownership boundary: the values here are *defaults* (category, privacy status,
share-to-feed, thumbnail offset), not content rules. How ``upload.content``
(title, description, tags) becomes a platform payload, and every character
limit applied to it, is owned by ``clipmorph.policy``; this module only reports
which platform a default belongs to.

Native scheduling contract (``SUPPORTED_NATIVE_SCHEDULING``): an entry is
``True`` only after the maintainer has run ``quality/research/scheduling_probe.py``
with sandbox credentials and observed a full schedule -> inspect -> cancel
cycle. Flipping an entry is a maintainer action that updates this dict and the
"Native publish scheduling" row in ``docs/PLATFORM_CAPABILITIES.md`` in the
same commit, with the probe date recorded in the doc; until then every entry is
``False`` and ``upload.schedule.mode: platform`` is rejected at submission.
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

# Per-platform upload defaults, consumed by the upload pipeline when it folds
# them into composed metadata and by the CLI runtime summary.
PLATFORM_DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "youtube": {"category": "22", "privacy_status": "public"},
    "instagram": {"share_to_feed": True, "thumb_offset": 0},
    "tiktok": {"privacy_level": "PUBLIC_TO_EVERYONE"},
    "twitter": {},
}

# Whether each platform's own API can hold a future publication, which is what
# ``upload.schedule.mode: platform`` selects. Every entry ships ``False``: a
# platform is only marked ``True`` after the maintainer's sandbox probe has run
# (see the module docstring). Instagram, TikTok, and X expose no scheduled
# publication parameter at all, so they stay ``False`` permanently unless their
# APIs gain one.
SUPPORTED_NATIVE_SCHEDULING: dict[str, bool] = {
    "youtube": False,
    "instagram": False,
    "tiktok": False,
    "twitter": False,
}


def build_platform_default_config() -> dict[str, dict[str, Any]]:
    """Return a fresh copy of per-platform upload defaults."""
    return {platform: dict(values)
            for platform, values in PLATFORM_DEFAULT_CONFIG.items()}


def is_supported_platform(platform: str) -> bool:
    """Return True when the lowercase platform name is supported."""
    return str(platform).lower() in SUPPORTED_PLATFORMS_SET


def native_scheduling_support(platform: str) -> bool:
    """Report whether a platform's own API can hold a future publication.

    Unknown platforms are reported as unsupported: only a registry entry the
    maintainer's probe has blessed may back ``upload.schedule.mode: platform``.
    """
    return bool(SUPPORTED_NATIVE_SCHEDULING.get(str(platform).lower(), False))


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
