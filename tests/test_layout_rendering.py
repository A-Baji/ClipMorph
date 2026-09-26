import unittest
import inspect
from pathlib import Path
from unittest.mock import patch

from clipmorph.conversion_pipeline.edit import EditingPipeline


class FakeConfig:
    ffmpeg_path = "ffmpeg"


class FakeRunner:
    config = FakeConfig()

    def __init__(self):
        self.commands = []

    def run_ffmpeg(self, command):
        self.commands.append(command)


class LayoutRenderingTests(unittest.TestCase):
    def test_layout_renderer_builds_crop_and_caption_filter_graph(self):
        runner = FakeRunner()
        pipeline = EditingPipeline.__new__(EditingPipeline)
        pipeline.layout = {
            "crop": {
                "enabled": True,
                "source": {"x": 20, "y": 20, "width": 320, "height": 240},
                "sizing": {"mode": "stretch",
                           "dimensions": {"width": 1080, "height": 608}},
                "composition": {"mode": "overlay", "placement": "top"},
            },
            "captions": {"stacked": {
                "placement": "top",
                "dimensions": {"width": 900, "height": 180},
                "panel": {"color": "black",
                          "padding": {"left": 20, "top": 12}},
                "items": [{
                    "text": "Hello",
                    "range": [0, 2],
                    "typography": {"underline": True},
                }],
            }},
        }
        pipeline.ffmpeg_runner = runner
        pipeline._apply_layout("input.mp4", "output.mp4")

        command = runner.commands[0]
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("crop=320:240:20:20", filter_graph)
        self.assertIn("scale=1080:608", filter_graph)
        self.assertIn("drawbox", filter_graph)
        self.assertIn("stacked_caption_0_underline", filter_graph)
        self.assertIn("drawtext", filter_graph)
        self.assertIn("y=304.0-overlay_h/2", filter_graph)
        self.assertIn("y=90.0-180/2+12", filter_graph)
        self.assertIn("-map", command)

    def test_layout_renderer_uses_named_bottom_caption_region_and_styles(self):
        runner = FakeRunner()
        pipeline = EditingPipeline.__new__(EditingPipeline)
        pipeline.layout = {
            "captions": {"overlay": {"items": [{
                "placement": "bottom",
                "dimensions": {"width": 900, "height": 180},
                "typography": {"size": 42, "color": "yellow"},
                "text": "Bottom line",
            }]}}
        }
        pipeline.ffmpeg_runner = runner
        pipeline._apply_layout("input.mp4", "output.mp4")
        filter_graph = runner.commands[0][runner.commands[0].index(
            "-filter_complex") + 1]
        self.assertIn("y=1830", filter_graph)
        self.assertIn("fontsize=42", filter_graph)
        self.assertIn("fontcolor=yellow", filter_graph)

    def test_layout_renderer_applies_bold_italic_and_underline_typography(self):
        runner = FakeRunner()
        pipeline = EditingPipeline.__new__(EditingPipeline)
        pipeline.layout = {"captions": {"overlay": {"items": [{
            "text": "Styled",
            "range": [1, 3],
            "typography": {
                "size": 40,
                "color": "cyan",
                "bold": True,
                "italic": True,
                "underline": True,
            },
        }]}}}
        pipeline.ffmpeg_runner = runner

        with patch("clipmorph.conversion_pipeline.edit.Path.is_file",
                   return_value=False):
            pipeline._apply_layout("input.mp4", "output.mp4")

        filter_graph = runner.commands[0][runner.commands[0].index(
            "-filter_complex") + 1]
        self.assertIn("font='Sans|Bold Italic'", filter_graph)
        self.assertIn("drawbox=", filter_graph)
        self.assertIn("color=cyan:t=fill", filter_graph)
        self.assertIn("enable='between(t,1,3)'", filter_graph)

    def test_windows_renderer_uses_matching_system_font_variant(self):
        runner = FakeRunner()
        pipeline = EditingPipeline.__new__(EditingPipeline)
        pipeline.layout = {"captions": {"overlay": {"items": [{
            "text": "Styled",
            "typography": {"bold": True, "italic": True},
        }]}}}
        pipeline.ffmpeg_runner = runner

        with patch("platform.system", return_value="Windows"), patch(
                       "clipmorph.conversion_pipeline.edit.Path.is_file",
                       return_value=True):
            pipeline._apply_layout("input.mp4", "output.mp4")

        filter_graph = runner.commands[0][runner.commands[0].index(
            "-filter_complex") + 1]
        font_path = (Path("C:/Windows") / "Fonts" / "segoeuiz.ttf")
        self.assertIn(
            f"fontfile='{EditingPipeline._escape_text(font_path)}'", filter_graph)
        self.assertNotIn("font='Sans|", filter_graph)

    def test_editing_pipeline_has_no_camera_flags(self):
        parameters = inspect.signature(EditingPipeline.__init__).parameters
        self.assertFalse({"include_cam", "cam_x", "cam_y", "cam_width",
                          "cam_height"} & set(parameters))

    def test_stacked_crop_reserves_centered_layout_flow(self):
        runner = FakeRunner()
        pipeline = EditingPipeline.__new__(EditingPipeline)
        pipeline.layout = {"crop": {
            "enabled": True,
            "source": {"x": 0, "y": 0, "width": 320, "height": 400},
            "sizing": {"mode": "native"},
            "composition": {"mode": "stacked", "placement": "center"},
        }}
        pipeline.ffmpeg_runner = runner

        pipeline._apply_layout("input.mp4", "output.mp4")

        graph = runner.commands[0][runner.commands[0].index("-filter_complex") + 1]
        self.assertIn("crop=1080:760:0:0[stack_top]", graph)
        self.assertIn("crop=1080:760:0:1160[stack_bottom]", graph)
        self.assertIn("vstack=inputs=3", graph)


if __name__ == "__main__":
    unittest.main()
