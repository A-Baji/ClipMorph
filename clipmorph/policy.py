"""Versioned platform capability policy and pre-upload decisions.

This module owns every per-platform *content* rule: how one upload draft's
``upload.content`` (``title``, ``description``, ``tags``) becomes the exact
keyword arguments a platform adapter's ``run`` method accepts, and the
character bounds that shape it. ``clipmorph.platforms`` owns the supported
platform set and each platform's plain upload defaults (category, privacy,
share-to-feed, thumbnail offset), which are values rather than content rules.
The adapters under ``clipmorph.upload_pipeline.platforms`` transport what this
module shaped and hold no composition knowledge of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import sys
from typing import Any

POLICY_VERSION = "2026-09-27"


@dataclass(frozen=True)
class CapabilityRule:
    minimum_duration: float | None = None
    maximum_duration: float | None = None
    maximum_width: int | None = None
    maximum_height: int | None = None
    minimum_width: int | None = None
    minimum_height: int | None = None
    maximum_bytes: int | None = None
    codecs: tuple[str, ...] = ()
    caption_limit: int | None = None
    # How upload.content becomes adapter kwargs: "separate" keeps the fields
    # apart, "combined"/"caption" compose them into the single output key.
    content_mode: str = "separate"
    # Positional adapter kwarg names, in composition order.
    output_keys: tuple[str, ...] = ()


CAPABILITY_MATRIX = {
    "youtube": CapabilityRule(
        codecs=("h264",),
        caption_limit=5000,
        content_mode="separate",
        output_keys=("title", "description", "keywords"),
    ),
    "instagram": CapabilityRule(
        minimum_duration=3,
        maximum_duration=900,
        maximum_width=1920,
        maximum_bytes=300 * 1024 * 1024,
        codecs=("h264", "hevc"),
        caption_limit=2200,
        content_mode="caption",
        output_keys=("caption",),
    ),
    "tiktok": CapabilityRule(
        minimum_duration=3,
        maximum_duration=None,
        minimum_width=360,
        minimum_height=360,
        maximum_width=4096,
        maximum_height=4096,
        maximum_bytes=4 * 1024 * 1024 * 1024,
        codecs=("h264", "hevc", "vp8", "vp9"),
        caption_limit=4000,
        content_mode="combined",
        output_keys=("title",),
    ),
    "twitter": CapabilityRule(
        maximum_duration=1200,
        maximum_bytes=8 * 1024 * 1024 * 1024,
        caption_limit=280,
        content_mode="combined",
        output_keys=("tweet_text",),
    ),
}

# YouTube bounds its title and its keyword string itself; its description bound
# is the platform's caption_limit so that number is declared once.
SEPARATE_TITLE_LIMIT = 100
SEPARATE_KEYWORDS_LIMIT = 500
# A separate-mode platform with no description still needs something to send.
EMPTY_DESCRIPTION = "Uploaded via API"
# Composition needs an integer bound. A rule that declares no caption_limit
# composes unbounded, and sys.maxsize is a bound no caption reaches, so the
# composition algorithm behaves exactly as it does for a declared limit.
NO_CHARACTER_LIMIT = sys.maxsize


@dataclass
class PolicyDecision:
    platform: str
    policy_version: str = POLICY_VERSION
    warnings: list[str] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return not self.blockers


def validate_artifact(platform: str, metadata: dict[str, Any],
                      content: dict[str, Any] | None = None,
                      account_capabilities: dict[str, Any] | None = None
                      ) -> PolicyDecision:
    platform = platform.lower()
    decision = PolicyDecision(platform=platform)
    rule = CAPABILITY_MATRIX.get(platform)
    if rule is None:
        decision.warnings.append("No capability policy is known for this platform")
        return decision

    account_capabilities = account_capabilities or {}
    duration = metadata.get("duration")
    max_duration = account_capabilities.get("maximum_duration", rule.maximum_duration)
    if duration is None:
        decision.warnings.append("Artifact duration is unknown")
    elif rule.minimum_duration and duration < rule.minimum_duration:
        decision.blockers.append(f"duration is below {rule.minimum_duration} seconds")
    elif max_duration and duration > max_duration:
        decision.blockers.append(f"duration exceeds {max_duration} seconds")

    width, height = metadata.get("width"), metadata.get("height")
    if width is None or height is None:
        decision.warnings.append("Artifact dimensions are unknown")
    else:
        if rule.minimum_width and width < rule.minimum_width:
            decision.blockers.append(f"width is below {rule.minimum_width} pixels")
        if rule.minimum_height and height < rule.minimum_height:
            decision.blockers.append(f"height is below {rule.minimum_height} pixels")
        if rule.maximum_width and width > rule.maximum_width:
            decision.blockers.append(f"width exceeds {rule.maximum_width} pixels")
        if rule.maximum_height and height > rule.maximum_height:
            decision.blockers.append(f"height exceeds {rule.maximum_height} pixels")

    file_size = metadata.get("file_size")
    if file_size is not None and rule.maximum_bytes and file_size > rule.maximum_bytes:
        decision.blockers.append(f"file size exceeds {rule.maximum_bytes} bytes")

    codec = metadata.get("video_codec")
    if codec is None:
        decision.warnings.append("Video codec is unknown")
    elif rule.codecs and codec.lower() not in rule.codecs:
        decision.blockers.append(f"video codec {codec} is unsupported")

    content = content or {}
    caption = str(content.get("caption", content.get("title", "")) or "")
    if rule.caption_limit and len(caption) > rule.caption_limit:
        decision.metadata["caption"] = caption[:rule.caption_limit].rstrip()
        decision.transformations.append(
            f"caption truncated to {rule.caption_limit} characters")
    else:
        decision.metadata["caption"] = caption
    decision.metadata["policy_version"] = POLICY_VERSION
    return decision


def _format_hashtags(tags: Any) -> str:
    """Return ``tags`` as space-separated ``#hashtags``, preserving case."""
    if not tags:
        return ""
    return ' '.join([f"#{tag.strip('#').replace(' ', '')}" for tag in tags
                     if tag.strip()])


def _compose_text(title: str, description: str, tags: Any,
                  max_chars: int) -> str:
    """Compose title, hashtags, and description within ``max_chars``.

    Priority is title > hashtags > description: the title is never dropped, the
    hashtags are trimmed to the room left beside it, and the description is only
    added when the leftover space is worth a partial sentence.
    """
    hashtags = _format_hashtags(tags)

    if len(title) >= max_chars:
        return title[:max_chars].strip()

    # Try title + hashtags
    title_tags = f"{title}\n\n{hashtags}".strip() if hashtags else title
    if len(title_tags) <= max_chars:
        # If we have room, try to add description
        if description:
            full_content = f"{title}\n\n{description}\n\n{hashtags}".strip(
            ) if hashtags else f"{title}\n\n{description}".strip()
            if len(full_content) <= max_chars:
                return full_content
            # Truncate description to fit
            available_for_desc = max_chars - len(title_tags) - 4
            if available_for_desc > 10:  # Only add description if we have meaningful space
                truncated_desc = description[:available_for_desc].strip()
                return f"{title}\n\n{truncated_desc}\n\n{hashtags}".strip(
                ) if hashtags else f"{title}\n\n{truncated_desc}".strip()
        return title_tags
    # Truncate hashtags to fit with title
    available_for_tags = max_chars - len(title) - 4
    if available_for_tags > 5:  # Need space for at least one hashtag
        truncated_hashtags = hashtags[:available_for_tags].strip()
        return f"{title}\n\n{truncated_hashtags}".strip()
    return title


def _bounded_caption(platform: str, rule: CapabilityRule, text: str) -> str:
    """Return ``text`` as the policy decision publishes it.

    ``validate_artifact`` is the single owner of the ``caption_limit``
    truncation, so composition asks it for the published caption instead of
    repeating the limit. ``_compose_text`` already bounds the text to the same
    limit, so the request is a consistency guard rather than a second
    truncation, and a rule without a ``caption_limit`` composes unbounded.
    """
    if rule.caption_limit is None:
        return text
    return str(validate_artifact(platform, {}, {"caption": text}
                                 ).metadata["caption"])


def _separate_values(rule: CapabilityRule, title: str, description: str,
                     tags: Any) -> tuple[Any, Any, Any]:
    """Return the separate-field values: title, description, keywords."""
    limit = rule.caption_limit or NO_CHARACTER_LIMIT
    return (
        title[:SEPARATE_TITLE_LIMIT],
        description[:limit] if description else EMPTY_DESCRIPTION,
        tags[:SEPARATE_KEYWORDS_LIMIT] if isinstance(tags, str) else tags,
    )


def build_platform_metadata(platform: str, content: dict[str, Any],
                            options: dict[str, Any] | None = None
                            ) -> dict[str, Any]:
    """Return the adapter keyword arguments for ``platform``.

    ``content`` carries ``upload.content`` (``title``, ``description``,
    ``tags``); ``options`` optionally replaces any of those three values for
    this one composition. The result is keyed by the rule's ``output_keys``, so
    the caller forwards it straight to the adapter's ``run`` method and no
    platform knowledge leaks into the adapters or the orchestration around
    them. A platform with no rule returns ``{}``.
    """
    platform = str(platform).lower()
    rule = CAPABILITY_MATRIX.get(platform)
    if rule is None:
        return {}

    values = dict(content or {})
    values.update({key: value for key, value in (options or {}).items()
                   if key in ("title", "description", "tags")})
    title = str(values.get("title") or "")
    description = str(values.get("description") or "")
    tags = values.get("tags") or []

    if rule.content_mode == "separate":
        fields: tuple[Any, ...] = _separate_values(
            rule, title, description, tags)
    else:
        limit = rule.caption_limit or NO_CHARACTER_LIMIT
        fields = (_bounded_caption(
            platform, rule, _compose_text(title, description, tags, limit)),)

    if len(fields) != len(rule.output_keys):
        raise ValueError(
            f"content_mode {rule.content_mode!r} produces {len(fields)} values "
            f"but rule {platform!r} declares output_keys {rule.output_keys!r}")
    return dict(zip(rule.output_keys, fields))
