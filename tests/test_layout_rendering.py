import unittest

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
                "placement": {"mode": "stretch", "region": "top",
                              "dimensions": {"width": 1080, "height": 608}},
            },
            "caption": {
                "enabled": True,
                "mode": "background",
                "text": "Hello",
                "region": "top",
            },
        }
        pipeline.ffmpeg_runner = runner
        pipeline._apply_layout("input.mp4", "output.mp4")

        command = runner.commands[0]
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("crop=320:240:20:20", filter_graph)
        self.assertIn("scale=1080:608", filter_graph)
        self.assertIn("drawbox", filter_graph)
        self.assertIn("drawtext", filter_graph)
        self.assertIn("-map", command)


if __name__ == "__main__":
    unittest.main()
