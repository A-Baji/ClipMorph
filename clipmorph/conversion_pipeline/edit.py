"""Render vertical video canvases using the canonical crop/caption layout."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import uuid
from typing import Any

from clipmorph.ffmpeg import FFmpegRunner
from clipmorph.job import default_output_dir, resolve_output_dir
from clipmorph.layout import measure_caption_dimensions


CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
AUTO_COLORS = ["white", "yellow", "cyan", "lime", "orange", "magenta"]


class EditingPipeline:
    def __init__(self, input_path: str, output_dir: str | Path | None = None,
                 muted_audio: str | None = None, segments=None,
                 layout: dict[str, Any] | None = None, ffmpeg_runner=None):
        self.input_path = input_path
        self.output_dir = resolve_output_dir(
            output_dir, default_output_dir().parent)
        self.muted_audio = muted_audio
        self.segments = segments or []
        self.layout = layout or {}
        self.ffmpeg_runner = ffmpeg_runner or FFmpegRunner()

    @staticmethod
    def _escape_text(text: Any) -> str:
        value = str(text).replace("\\", "\\\\")
        for character in (":", "'", "%", ",", "[", "]", ";"):
            value = value.replace(character, f"\\{character}")
        return value.replace("\n", "\\n")

    @staticmethod
    def _range_enable(item: dict[str, Any]) -> str:
        timing = item.get("range")
        if timing is None:
            return ""
        start, end = timing
        return f":enable='between(t,{start},{end})'"

    @staticmethod
    def _estimated_dimensions(item: dict[str, Any]) -> tuple[int, int]:
        dimensions = item.get("dimensions")
        if isinstance(dimensions, dict):
            return dimensions["width"], dimensions["height"]
        dimensions = measure_caption_dimensions(
            str(item.get("text", "")), item.get("typography", {}))
        return dimensions["width"], dimensions["height"]

    @staticmethod
    def _font_style_option(typography: dict[str, Any]) -> str:
        if typography.get("font_file"):
            return ""
        styles = []
        if typography.get("bold"):
            styles.append("Bold")
        if typography.get("italic"):
            styles.append("Italic")
        return f":font='Sans|{' '.join(styles)}'" if styles else ""

    @staticmethod
    def _system_font_file(typography: dict[str, Any]) -> str | None:
        style = (bool(typography.get("bold")), bool(typography.get("italic")))
        system = platform.system()
        if system == "Windows":
            filenames = {
                (False, False): ("segoeui.ttf", "arial.ttf"),
                (True, False): ("segoeuib.ttf", "arialbd.ttf"),
                (False, True): ("segoeuii.ttf", "ariali.ttf"),
                (True, True): ("segoeuiz.ttf", "arialbi.ttf"),
            }[style]
            fonts_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            candidates = [fonts_dir / name for name in filenames]
        elif system == "Darwin":
            names = {
                (False, False): "Arial.ttf",
                (True, False): "Arial Bold.ttf",
                (False, True): "Arial Italic.ttf",
                (True, True): "Arial Bold Italic.ttf",
            }
            candidates = [Path("/System/Library/Fonts/Supplemental") / names[style]]
        elif system == "Linux":
            names = {
                (False, False): ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"),
                (True, False): ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"),
                (False, True): ("DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf"),
                (True, True): ("DejaVuSans-BoldOblique.ttf", "LiberationSans-BoldItalic.ttf"),
            }[style]
            directories = (
                Path("/usr/share/fonts/truetype/dejavu"),
                Path("/usr/share/fonts/dejavu"),
                Path("/usr/share/fonts/truetype/liberation2"),
                Path("/usr/share/fonts/truetype/liberation"),
            )
            candidates = [directory / name for directory in directories for name in names]
        else:
            candidates = []
        return next((str(candidate) for candidate in candidates
                     if candidate.is_file()), None)

    @staticmethod
    def _underline_filter(filters: list[str], current: str, label: str,
                          text: str, typography: dict[str, Any], color: str,
                          x: str, y: str, enable: str) -> str:
        if not typography.get("underline"):
            return current
        font_size = typography.get("size", 64)
        text_width = measure_caption_dimensions(
            text, typography, padding_x=0, padding_y=0)["width"]
        thickness = max(1, font_size // 20)
        underline_label = f"{label}_underline"
        filters.append(
            f"[{current}]drawbox=x={x}:y={y}:w={text_width}:h={thickness}:"
            f"color={color}:t=fill{enable}[{underline_label}]")
        return underline_label

    @staticmethod
    def _region_center(placement: Any, width: int, height: int,
                       stacked: bool = False) -> tuple[str, str]:
        if isinstance(placement, dict):
            x = "540" if stacked else str(placement["x"])
            return x, str(placement["y"])
        x = "540"
        if placement == "top":
            y = str(height / 2)
        elif placement == "bottom":
            y = str(CANVAS_HEIGHT - height / 2)
        else:
            y = str(CANVAS_HEIGHT / 2)
        return x, y

    def _base_filter(self) -> str:
        return (f"[0:v]scale={CANVAS_WIDTH}:{CANVAS_HEIGHT}:"
                "force_original_aspect_ratio=increase,"
                f"crop={CANVAS_WIDTH}:{CANVAS_HEIGHT},setsar=1[base]")

    def _crop_filters(self, filters: list[str], current: str) -> str:
        crop = self.layout.get("crop") or {}
        if not crop.get("enabled"):
            return current
        source = crop["source"]
        sizing = crop.get("sizing", {})
        mode = sizing.get("mode", "fit")
        composition = crop.get("composition", {})
        composition_mode = composition.get("mode", "overlay")
        placement = composition.get("placement", "top")
        crop_filter = (
            f"[0:v]crop={source['width']}:{source['height']}:{source['x']}:{source['y']}")
        if mode in {"fit", "stretch"}:
            dimensions = sizing["dimensions"]
            width, height = dimensions["width"], dimensions["height"]
            if mode == "fit":
                crop_filter += (
                    f",scale={width}:{height}:force_original_aspect_ratio=decrease"
                    f",pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
            else:
                crop_filter += f",scale={width}:{height}"
        else:
            width, height = source["width"], source["height"]
        crop_filter += f",setsar=1[crop_layer]"
        filters.append(crop_filter)

        if composition_mode == "stacked":
            crop_center_y = (height / 2 if placement == "top" else
                             CANVAS_HEIGHT - height / 2 if placement == "bottom" else
                             CANVAS_HEIGHT / 2)
            if isinstance(placement, dict):
                crop_center_y = placement["y"]
            top_height = int(crop_center_y - height / 2)
            bottom_y = int(crop_center_y + height / 2)
            bottom_height = CANVAS_HEIGHT - bottom_y
            filters.append(
                f"[crop_layer]pad={CANVAS_WIDTH}:{height}:(ow-iw)/2:0:color=black[crop_band]")
            if top_height > 0:
                filters.append(f"[{current}]crop={CANVAS_WIDTH}:{top_height}:0:0[stack_top]")
            if bottom_height > 0:
                filters.append(
                    f"[{current}]crop={CANVAS_WIDTH}:{bottom_height}:0:{bottom_y}[stack_bottom]")
            pieces = []
            if top_height > 0:
                pieces.append("[stack_top]")
            pieces.append("[crop_band]")
            if bottom_height > 0:
                pieces.append("[stack_bottom]")
            filters.append(f"{''.join(pieces)}vstack=inputs={len(pieces)}[{current}_stacked]")
            return f"{current}_stacked"

        center_x, center_y = self._region_center(placement, width, height)
        filters.append(
            f"[{current}][crop_layer]overlay=x={center_x}-overlay_w/2:"
            f"y={center_y}-overlay_h/2[{current}_crop]")
        return f"{current}_crop"

    def _caption_filters(self, filters: list[str], current: str) -> str:
        captions = self.layout.get("captions") or {}
        index = 0
        for item in captions.get("overlay", {}).get("items", []):
            width, height = self._estimated_dimensions(item)
            center_x, center_y = self._region_center(
                item.get("placement", "center"), width, height)
            typography = item.get("typography", {})
            font_size = typography.get("size", 64)
            color = typography.get("color") or AUTO_COLORS[index % len(AUTO_COLORS)]
            font_file = typography.get("font_file") or self._system_font_file(typography)
            font_option = f":fontfile='{self._escape_text(font_file)}'" if font_file else ""
            if not font_file:
                font_option += self._font_style_option(typography)
            outline = typography.get("outline_color", "black")
            style = f":fontsize={font_size}:fontcolor={color}{font_option}:borderw=3:bordercolor={outline}"
            text = self._escape_text(item.get("text", ""))
            label = f"caption_{index}"
            text_width = measure_caption_dimensions(
                item.get("text", ""), typography, padding_x=0, padding_y=0)["width"]
            current = self._underline_filter(
                filters, current, label, item.get("text", ""), typography,
                color, f"{center_x}-{text_width}/2",
                f"{center_y}+{font_size}*0.4", self._range_enable(item))
            filters.append(
                f"[{current}]drawtext=text='{text}':x={center_x}-text_w/2:"
                f"y={center_y}-text_h/2{style}{self._range_enable(item)}[{label}]")
            current = label
            index += 1

        stacked = captions.get("stacked", {})
        items = stacked.get("items", [])
        if not items:
            return current
        first_width, first_height = self._estimated_dimensions(items[0])
        width, height = stacked.get("dimensions", {}).get(
            "width", first_width), stacked.get("dimensions", {}).get(
                "height", first_height)
        padding = stacked.get("panel", {}).get("padding", {})
        padding_x, padding_y = padding.get("left", 0), padding.get("top", 0)
        placement = stacked.get("placement", "center")
        _center_x, center_y = self._region_center(
            placement, width, height, stacked=True)
        panel_color = stacked.get("panel", {}).get("color", "black")
        for item_index, item in enumerate(items):
            label = f"stacked_panel_{item_index}"
            text_label = f"stacked_caption_{item_index}"
            enable = self._range_enable(item)
            filters.append(
                f"[{current}]drawbox=x=(iw-{width})/2:y={center_y}-{height}/2:"
                f"w={width}:h={height}:color={panel_color}:t=fill{enable}[{label}]")
            typography = item.get("typography", {})
            font_size = typography.get("size", 64)
            color = typography.get("color") or AUTO_COLORS[(index + item_index) % len(AUTO_COLORS)]
            font_file = typography.get("font_file") or self._system_font_file(typography)
            font_option = f":fontfile='{self._escape_text(font_file)}'" if font_file else ""
            if not font_file:
                font_option += self._font_style_option(typography)
            outline = typography.get("outline_color", "black")
            text = self._escape_text(item.get("text", ""))
            text_width = measure_caption_dimensions(
                item.get("text", ""), typography, padding_x=0, padding_y=0)["width"]
            current = self._underline_filter(
                filters, label, text_label, item.get("text", ""),
                typography, color, f"(iw-{text_width})/2",
                f"{center_y}-{height}/2+{padding_y}+{font_size}*1.2", enable)
            filters.append(
                f"[{current}]drawtext=text='{text}':x=(w-text_w)/2:"
                f"y={center_y}-{height}/2+{padding_y}{enable}:fontsize={font_size}:"
                f"fontcolor={color}{font_option}:borderw=3:bordercolor={outline}"
                f"[{text_label}]")
            current = text_label
        return current

    def _apply_layout(self, input_path: str, output_path: str) -> None:
        filters = [self._base_filter()]
        current = self._crop_filters(filters, "base")
        current = self._caption_filters(filters, current)
        command = [
            self.ffmpeg_runner.config.ffmpeg_path,
            "-i", input_path,
            "-filter_complex", ";".join(filters),
            "-map", f"[{current}]", "-map", "0:a?",
            "-c:v", "libx264", "-c:a", "copy", "-y", output_path,
        ]
        self.ffmpeg_runner.run_ffmpeg(command)

    def run(self) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(self.input_path).stem
        output_path = self.output_dir / f"{stem}-converted-{uuid.uuid4().hex[:8]}.mp4"
        self._apply_layout(self.input_path, str(output_path))
        if not output_path.exists():
            raise RuntimeError("Video output was not created")
        if output_path.stat().st_size < 1024:
            raise RuntimeError("Video output is suspiciously small")
        return str(output_path)