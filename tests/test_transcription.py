import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from clipmorph.conversion_pipeline.convert import ConversionPipeline
from clipmorph.conversion_pipeline.transcribe import (
    TranscriptionPipeline,
    resolve_transcription_device,
    write_srt_file,
)


class TranscriptionConfigTests(unittest.TestCase):
    def test_conversion_does_not_forward_transcription_options_to_editor(self):
        runner = SimpleNamespace(
            validate_input_file=lambda _path: None,
            extract_audio=lambda _path: "audio.wav",
            cleanup_temp_files=lambda: None,
        )
        editor = MagicMock()
        editor.return_value.run.return_value = "output.mp4"
        pipeline = ConversionPipeline(
            "input.mp4",
            skip_subtitles=True,
            transcription_language="fr",
        )
        pipeline.ffmpeg_runner = runner

        with patch("clipmorph.conversion_pipeline.convert.EditingPipeline",
                       editor), patch.object(
                           ConversionPipeline,
                           "_validate_output",
                           return_value=1024,
                       ), patch(
                           "clipmorph.conversion_pipeline.convert.TranscriptionPipeline"
                       ) as transcription_type:
            self.assertEqual(pipeline.run(), "output.mp4")

        transcription_type.assert_not_called()
        self.assertNotIn("transcription_language",
                         editor.call_args.kwargs)

    def test_requested_device_falls_back_to_cpu(self):
        with patch("clipmorph.conversion_pipeline.transcribe.torch.cuda.is_available",
                   return_value=False):
            self.assertEqual(resolve_transcription_device("cuda"), "cpu")

    def test_transcription_pipeline_applies_requested_runtime_config(self):
        with patch("clipmorph.conversion_pipeline.transcribe.whisper.load_model") as load_model:
            pipeline = TranscriptionPipeline(
                "sample.wav",
                language="fr",
                model_name="tiny",
                device="cpu",
                compute_type="int8",
            )
            _ = pipeline._whisper_model
            load_model.assert_called_once_with("tiny", device="cpu")


class ReviewedTranscriptTests(unittest.TestCase):
    def test_word_annotations_replace_censored_text(self):
        pipeline = object.__new__(ConversionPipeline)
        segments = [{
            "text": "Say darn now",
            "words": [{"word": "darn", "censored": True, "replacement": "***"}],
        }]
        self.assertEqual(pipeline._apply_word_annotations(segments)[0]["text"],
                         "Say *** now")


class SubtitleArtifactTests(unittest.TestCase):
    def test_srt_writer_uses_explicit_job_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle_path = Path(temp_dir) / "job.srt"
            write_srt_file([{
                "start": 0,
                "end": 1,
                "text": "Hello",
            }], str(subtitle_path))
            self.assertTrue(subtitle_path.exists())
            self.assertIn("Hello", subtitle_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
