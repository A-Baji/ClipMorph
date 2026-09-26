"""Validation and normalization for crop and caption layout configuration."""

from __future__ import annotations

from copy import deepcopy
from math import ceil, isfinite
from typing import Any


REGIONS = {"top", "center", "bottom"}
TYPOGRAPHY_KEYS = {
    "size", "color", "font_file", "outline_color", "bold", "italic", "underline"
}
CAPTION_DEFAULT_TYPOGRAPHY = {
    "size": 64,
    "color": None,
    "font_file": None,
    "outline_color": "black",
    "bold": False,
    "italic": False,
    "underline": False,
}


def _object(value: Any, label: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"Unknown {label} field(s): {', '.join(sorted(unknown))}")
    return value


def _positive_dimensions(value: Any, label: str,
                         allowed: set[str] | None = None) -> tuple[int, int]:
    dimensions = _object(value, f"{label} dimensions", allowed or {"width", "height"})
    width, height = dimensions.get("width"), dimensions.get("height")
    if (not isinstance(width, int) or isinstance(width, bool) or width <= 0
            or not isinstance(height, int) or isinstance(height, bool) or height <= 0):
        raise ValueError(f"{label} dimensions must be positive integers")
    return width, height


def _validate_typography(value: Any, label: str) -> None:
    typography = _object(value, label, TYPOGRAPHY_KEYS)
    size = typography.get("size", CAPTION_DEFAULT_TYPOGRAPHY["size"])
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError(f"{label}.size must be a positive integer")
    for key in ("color", "font_file"):
        if typography.get(key) is not None and not isinstance(typography[key], str):
            raise ValueError(f"{label}.{key} must be a string or null")
    if not isinstance(typography.get("outline_color", "black"), str):
        raise ValueError(f"{label}.outline_color must be a string")
    for key in ("bold", "italic", "underline"):
        if not isinstance(typography.get(key, False), bool):
            raise ValueError(f"{label}.{key} must be a boolean")


def _validate_range(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must contain [start, end]")
    start, end = value
    if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not isfinite(start) or not isfinite(end) or start < 0 or end <= start):
        raise ValueError(f"{label} must satisfy 0 <= start < end")
    return float(start), float(end)


def _placement_center(placement: Any, width: int | None, height: int | None,
                      canvas_width: int, canvas_height: int,
                      label: str, stacked: bool = False) -> tuple[float, float]:
    if isinstance(placement, str):
        if placement not in REGIONS:
            raise ValueError(f"{label} placement must be top, center, or bottom")
        x = canvas_width / 2
        if placement == "top":
            y = (height or 0) / 2
        elif placement == "bottom":
            y = canvas_height - (height or 0) / 2
        else:
            y = canvas_height / 2
    elif isinstance(placement, dict):
        allowed = {"y"} if stacked else {"x", "y"}
        coordinates = _object(placement, f"{label} placement", allowed)
        if stacked:
            if "y" not in coordinates or "x" in coordinates:
                raise ValueError(f"{label} stacked placement requires only y")
            x, y = canvas_width / 2, coordinates["y"]
        else:
            if set(coordinates) != {"x", "y"}:
                raise ValueError(f"{label} overlay placement requires x and y")
            x, y = coordinates["x"], coordinates["y"]
        if any(not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool)
               or not isfinite(coordinate) or coordinate < 0
               for coordinate in (x, y)):
            raise ValueError(f"{label} placement coordinates must be non-negative numbers")
    else:
        raise ValueError(f"{label} placement must be a region or coordinate object")

    if width is not None and height is not None:
        if width > canvas_width or height > canvas_height:
            raise ValueError(f"{label} dimensions exceed the output canvas")
        if (x - width / 2 < 0 or x + width / 2 > canvas_width
                or y - height / 2 < 0 or y + height / 2 > canvas_height):
            raise ValueError(f"{label} placement overflows the output canvas")
    return x, y


def _validate_caption_items(items: Any, label: str, stacked: bool,
                            collection: dict[str, Any], media_duration: float | None,
                            canvas_width: int, canvas_height: int) -> None:
    if not isinstance(items, list):
        raise ValueError(f"{label}.items must be a list")
    ranges = []
    for index, item_value in enumerate(items):
        item_label = f"{label}.items[{index}]"
        item_keys = {"text", "range", "typography", "transcript_segment_id"}
        if not stacked:
            item_keys.update({"placement", "dimensions"})
        item = _object(item_value, item_label, item_keys)
        if not isinstance(item.get("text"), str):
            raise ValueError(f"{item_label}.text must be a string")
        if "typography" in item:
            _validate_typography(item["typography"], f"{item_label}.typography")
        if stacked and set(item) - {"text", "range", "typography", "transcript_segment_id"}:
            raise ValueError(f"{item_label} may define only text, range, and typography")
        if "range" in item:
            start, end = _validate_range(item["range"], f"{item_label}.range")
            if media_duration is not None and end > media_duration:
                raise ValueError(f"{item_label}.range exceeds media duration")
            ranges.append((start, end))
        elif stacked and len(items) != 1:
            raise ValueError("multiple stacked items require explicit non-overlapping ranges")
        if not stacked:
            typography = item.get("typography", {})
            measured = measure_caption_dimensions(item["text"], typography)
            dimensions = item.get("dimensions")
            width = height = None
            if dimensions is not None:
                width, height = _positive_dimensions(dimensions, item_label)
                if measured["width"] > width or measured["height"] > height:
                    raise ValueError(f"{item_label} text exceeds explicit dimensions")
            else:
                width, height = measured["width"], measured["height"]
            _placement_center(item.get("placement", "center"), width, height,
                              canvas_width, canvas_height, item_label)

    if stacked:
        dimensions = collection.get("dimensions")
        width = height = None
        if dimensions is not None:
            width, height = _positive_dimensions(dimensions, f"{label} panel")
            padding = collection.get("panel", {}).get("padding", {})
            padding_x, padding_y = padding.get("left", 0), padding.get("top", 0)
            for index, item in enumerate(items):
                measured = measure_caption_dimensions(
                    item["text"], item.get("typography", {}))
                if (measured["width"] + 2 * padding_x > width
                        or measured["height"] + 2 * padding_y > height):
                    raise ValueError(
                        f"{label}.items[{index}] text exceeds explicit panel dimensions")
        elif items:
            padding = collection.get("panel", {}).get("padding", {})
            width = max(measure_caption_dimensions(
                item["text"], item.get("typography", {}))["width"]
                        for item in items) + 2 * padding.get("left", 0)
            height = max(measure_caption_dimensions(
                item["text"], item.get("typography", {}))["height"]
                         for item in items) + 2 * padding.get("top", 0)
        _placement_center(collection.get("placement", "center"), width, height,
                          canvas_width, canvas_height, label, stacked=True)
        ordered = sorted(ranges)
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] < previous[1]:
                raise ValueError("stacked caption item ranges must not overlap")


def validate_layout(layout: dict[str, Any] | None, source_width: int | None = None,
                    source_height: int | None = None,
                    media_duration: float | None = None,
                    canvas_width: int = 1080, canvas_height: int = 1920) -> None:
    if layout is None:
        return
    _object(layout, "layout", {"crop", "captions"})
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("output canvas dimensions must be positive")

    crop = layout.get("crop")
    if crop is not None:
        crop = _object(crop, "layout.crop", {"enabled", "source", "sizing", "composition"})
        enabled = crop.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("layout.crop.enabled must be a boolean")
        if enabled:
            source = _object(crop.get("source"), "crop source", {"x", "y", "width", "height"})
            width, height = _positive_dimensions(
                source, "crop source", {"x", "y", "width", "height"})
            x, y = source.get("x"), source.get("y")
            if (not isinstance(x, int) or isinstance(x, bool) or x < 0
                    or not isinstance(y, int) or isinstance(y, bool) or y < 0):
                raise ValueError("crop source coordinates must be non-negative integers")
            if (source_width is not None and source_height is not None
                    and (x + width > source_width or y + height > source_height)):
                raise ValueError("crop source rectangle exceeds source video dimensions")
            sizing = _object(crop.get("sizing"), "crop sizing", {"mode", "dimensions"})
            sizing_mode = sizing.get("mode", "fit")
            if sizing_mode not in {"fit", "stretch", "native"}:
                raise ValueError("crop sizing mode must be fit, stretch, or native")
            target_width, target_height = width, height
            if sizing_mode in {"fit", "stretch"}:
                target_width, target_height = _positive_dimensions(
                    sizing.get("dimensions"), "crop sizing")
            elif "dimensions" in sizing:
                raise ValueError("native crop sizing does not accept dimensions")
            composition = _object(
                crop.get("composition"), "crop composition", {"mode", "placement"})
            composition_mode = composition.get("mode", "overlay")
            if composition_mode not in {"overlay", "stacked"}:
                raise ValueError("crop composition mode must be overlay or stacked")
            _placement_center(composition.get("placement", "top"),
                              target_width, target_height, canvas_width,
                              canvas_height, "crop", stacked=composition_mode == "stacked")

    captions = layout.get("captions")
    if captions is not None:
        captions = _object(captions, "layout.captions", {"overlay", "stacked"})
        overlay = captions.get("overlay")
        if overlay is not None:
            overlay = _object(overlay, "captions.overlay", {"items"})
            _validate_caption_items(overlay.get("items", []), "captions.overlay",
                                   False, overlay, media_duration,
                                   canvas_width, canvas_height)
        stacked = captions.get("stacked")
        if stacked is not None:
            stacked = _object(stacked, "captions.stacked", {
                "placement", "dimensions", "panel", "items"})
            panel = stacked.get("panel", {})
            panel = _object(panel, "captions.stacked.panel", {"color", "padding"})
            if not isinstance(panel.get("color", "black"), str):
                raise ValueError("captions.stacked.panel.color must be a string")
            padding = _object(panel.get("padding", {}),
                              "captions.stacked.panel.padding", {"left", "top"})
            for key, value in padding.items():
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError(
                        f"captions.stacked.panel.padding.{key} must be non-negative")
            _validate_caption_items(stacked.get("items", []), "captions.stacked",
                                   True, stacked, media_duration,
                                   canvas_width, canvas_height)


def normalize_layout(layout: dict[str, Any] | None) -> dict[str, Any]:
    """Return a detached layout with minimal caption defaults materialized."""
    if layout is None:
        return {}
    normalized = deepcopy(layout)
    captions = normalized.get("captions")
    if not isinstance(captions, dict):
        return normalized
    for renderer in ("overlay", "stacked"):
        collection = captions.get(renderer)
        if not isinstance(collection, dict):
            continue
        if renderer == "overlay":
            collection.setdefault("items", [])
        else:
            collection.setdefault("placement", "center")
            panel = collection.setdefault("panel", {})
            panel.setdefault("color", "black")
            panel.setdefault("padding", {}).setdefault("left", 0)
            panel.setdefault("padding", {}).setdefault("top", 0)
            collection.setdefault("items", [])
        for item in collection.get("items", []):
            if not isinstance(item, dict):
                continue
            item.setdefault("typography", {})
            for key, value in CAPTION_DEFAULT_TYPOGRAPHY.items():
                item["typography"].setdefault(key, value)
            if renderer == "overlay":
                item.setdefault("placement", "center")
    return normalized


def measure_caption_dimensions(text: str, typography: dict[str, Any] | None = None,
                              padding_x: int = 8,
                              padding_y: int = 8) -> dict[str, int]:
    """Resolve a stable minimal text box from content and item typography."""
    size = (typography or {}).get("size", CAPTION_DEFAULT_TYPOGRAPHY["size"])
    lines = text.splitlines() or [""]
    width = max(1, max(len(line) for line in lines)) * size * 3 / 5
    height = len(lines) * size * 3 / 2
    return {
        "width": ceil(width) + padding_x * 2,
        "height": ceil(height) + padding_y * 2,
    }


def _resolve_region(placement: Any, width: int, height: int,
                    canvas_width: int, canvas_height: int,
                    stacked: bool = False) -> Any:
    if not isinstance(placement, str):
        return deepcopy(placement)
    if placement not in REGIONS:
        raise ValueError("placement must be top, center, or bottom")
    center_y = (height / 2 if placement == "top" else
                canvas_height - height / 2 if placement == "bottom" else
                canvas_height / 2)
    center_y = int(center_y)
    if stacked:
        return {"y": center_y}
    return {"x": int(canvas_width / 2), "y": center_y}


def resolve_layout_geometry(layout: dict[str, Any],
                            canvas_width: int = 1080,
                            canvas_height: int = 1920) -> dict[str, Any]:
    """Materialize named placements and omitted text/panel dimensions."""
    result = normalize_layout(layout)
    crop = result.get("crop") or {}
    if crop.get("enabled"):
        source = crop["source"]
        sizing = crop.get("sizing", {})
        dimensions = sizing.get("dimensions") or {
            "width": source["width"], "height": source["height"]}
        composition = crop.get("composition", {})
        stacked = composition.get("mode", "overlay") == "stacked"
        composition["placement"] = _resolve_region(
            composition.get("placement", "top"), dimensions["width"],
            dimensions["height"], canvas_width, canvas_height, stacked)

    captions = result.get("captions") or {}
    overlay = captions.get("overlay") or {}
    for item in overlay.get("items", []):
        typography = item.get("typography", {})
        item.setdefault("dimensions", measure_caption_dimensions(
            item.get("text", ""), typography))
        width, height = item["dimensions"]["width"], item["dimensions"]["height"]
        item["placement"] = _resolve_region(
            item.get("placement", "center"), width, height,
            canvas_width, canvas_height)

    stacked = captions.get("stacked") or {}
    items = stacked.get("items", [])
    padding = stacked.get("panel", {}).get("padding", {})
    padding_x, padding_y = padding.get("left", 0), padding.get("top", 0)
    if items and "dimensions" not in stacked:
        measured = [measure_caption_dimensions(
            item.get("text", ""), item.get("typography", {})) for item in items]
        stacked["dimensions"] = {
            "width": min(canvas_width, max(item["width"] for item in measured)
                         + 2 * padding_x),
            "height": min(canvas_height, max(item["height"] for item in measured)
                          + 2 * padding_y),
        }
    dimensions = stacked.get("dimensions", {"width": 0, "height": 0})
    stacked["placement"] = _resolve_region(
        stacked.get("placement", "center"), dimensions.get("width", 0),
        dimensions.get("height", 0), canvas_width, canvas_height, stacked=True)
    return result


def materialize_generated_captions(layout: dict[str, Any], renderer: str,
                                   segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace generated items in one renderer while preserving authored items."""
    if renderer not in {"overlay", "stacked"}:
        raise ValueError("subtitle renderer must be overlay or stacked")
    result = normalize_layout(layout)
    captions = result.get("captions")
    collection = captions.get(renderer) if isinstance(captions, dict) else None
    if not isinstance(collection, dict) or not isinstance(collection.get("items"), list):
        raise ValueError(f"selected captions.{renderer} collection must exist")
    authored = [item for item in collection["items"]
                if not (isinstance(item, dict) and "transcript_segment_id" in item)]
    generated = []
    for index, segment in enumerate(segments):
        segment_id = segment.get("id", segment.get("segment_id"))
        if segment_id is None:
            raise ValueError(f"transcript segment {index} requires a stable id")
        item = {
            "text": str(segment.get("text", "")),
            "range": [segment["start"], segment["end"]],
            "transcript_segment_id": str(segment_id),
        }
        typography = segment.get("typography", segment.get("typography_overrides"))
        if typography:
            item["typography"] = deepcopy(typography)
        if renderer == "overlay":
            item["placement"] = deepcopy(collection.get("placement", "center"))
        generated.append(item)
    collection["items"] = [*authored, *generated]
    return result
