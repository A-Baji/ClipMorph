"""Versioned platform capability policy and pre-upload decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

POLICY_VERSION = "2026-09-23"


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


CAPABILITY_MATRIX = {
    "youtube": CapabilityRule(codecs=("h264",), caption_limit=5000),
    "instagram": CapabilityRule(
        minimum_duration=3,
        maximum_duration=900,
        maximum_width=1920,
        maximum_bytes=300 * 1024 * 1024,
        codecs=("h264", "hevc"),
        caption_limit=2200,
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
    ),
    "twitter": CapabilityRule(
        maximum_duration=1200,
        maximum_bytes=8 * 1024 * 1024 * 1024,
        caption_limit=280,
    ),
}


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
