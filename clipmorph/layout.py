"""Validation for composable crop and caption layout configuration."""

from __future__ import annotations

from math import isfinite
from typing import Any

REGIONS = {"top", "center", "bottom"}
PLACEMENT_MODES = {"none", "fit", "stretch"}
CAPTION_MODES = {"overlay", "background"}


def _positive_dimensions(value: dict[str, Any], label: str) -> None:
    width, height = value.get("width"), value.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError(f"{label} dimensions must be positive integers")


def _validate_range(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must contain [start, end]")
    start, end = value
    if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not isfinite(start) or not isfinite(end) or start < 0 or end <= start):
        raise ValueError(f"{label} must satisfy 0 <= start < end")
    return float(start), float(end)


def validate_layout(layout: dict[str, Any] | None, source_width: int,
                    source_height: int, media_duration: float | None = None) -> None:
    if layout is None:
        return
    if not isinstance(layout, dict):
        raise ValueError("layout must be an object")

    crop = layout.get("crop") or {}
    if not isinstance(crop, dict):
        raise ValueError("layout.crop must be an object")
    if crop.get("enabled", False):
        source = crop.get("source")
        if not isinstance(source, dict):
            raise ValueError("enabled layout.crop requires source")
        _positive_dimensions(source, "crop source")
        x, y = source.get("x"), source.get("y")
        if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0:
            raise ValueError("crop source coordinates must be non-negative integers")
        if x + source["width"] > source_width or y + source["height"] > source_height:
            raise ValueError("crop source rectangle exceeds source video dimensions")
        placement = crop.get("placement", {})
        if not isinstance(placement, dict):
            raise ValueError("crop placement must be an object")
        mode = placement.get("mode", "fit")
        region = placement.get("region", "top")
        if mode not in PLACEMENT_MODES:
            raise ValueError("crop placement mode must be none, fit, or stretch")
        if region not in REGIONS:
            raise ValueError("crop placement region must be top, center, or bottom")
        if mode == "fit" and region == "center":
            raise ValueError("fitted crops cannot use the center region")
        if mode == "stretch":
            dimensions = placement.get("dimensions")
            if not isinstance(dimensions, dict):
                raise ValueError("stretched crops require placement dimensions")
            _positive_dimensions(dimensions, "crop placement")

    caption = layout.get("caption")
    if caption is None:
        return
    if not isinstance(caption, dict):
        raise ValueError("layout.caption must be an object")
    if not caption.get("enabled", False):
        return
    has_text = isinstance(caption.get("text"), str)
    has_items = isinstance(caption.get("items"), list)
    if has_text == has_items:
        raise ValueError("enabled captions require exactly one of text or items")
    mode = caption.get("mode", "overlay")
    region = caption.get("region", "top")
    if mode not in CAPTION_MODES:
        raise ValueError("caption mode must be overlay or background")
    if region not in REGIONS:
        raise ValueError("caption region must be top, center, or bottom")
    if mode == "background" and region == "center":
        raise ValueError("background caption panels cannot use the center region")
    dimensions = caption.get("dimensions")
    if dimensions is not None:
        if not isinstance(dimensions, dict):
            raise ValueError("caption dimensions must be an object")
        _positive_dimensions(dimensions, "caption")
    if has_items:
        previous_end = 0.0
        for index, item in enumerate(caption["items"]):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError(f"caption item {index} requires text")
            start, end = _validate_range(item.get("range"), f"caption item {index} range")
            if start < previous_end:
                raise ValueError("caption item ranges must not overlap")
            if media_duration is not None and end > media_duration:
                raise ValueError("caption item range exceeds media duration")
            previous_end = end
