import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clipmorph.__main__ import main
from clipmorph.batch import BatchProcessor
from clipmorph.cli import build_platform_default_config, summarize_runtime_configuration
from clipmorph.preflight import PreflightError, PreflightValidator
from clipmorph.conversion_pipeline.transcribe import TranscriptionPipeline, resolve_transcription_device, write_srt_file
from clipmorph.job import JobManifest
from clipmorph.upload_pipeline import UploadPipeline
from clipmorph.upload_pipeline.platforms.tiktok import TikTokUploadPipeline


class FakeFFmpegRunner:
    def get_video_info(self, _input_path):
        return {
            "format": {"duration": "12.5"},
            "streams": [{
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
            }],
        }


class CliInitializationTests(unittest.TestCase):
    def test_init_creates_template_without_configuring_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "clipmorph.yaml"
            with patch.object(sys, "argv", [
                    "clipmorph", "--init", "--config-path", str(config_path)
            ]), patch("clipmorph.__main__.configure_ffmpeg") as configure:
                main()

            self.assertTrue(config_path.exists())
            self.assertIn("general:", config_path.read_text(encoding="utf-8"))
            configure.assert_not_called()

    def test_init_backs_up_existing_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "clipmorph.yaml"
            config_path.write_text("old: true\n", encoding="utf-8")

            with patch.object(sys, "argv", [
                    "clipmorph", "--init", "--config-path", str(config_path)
            ]):
                main()

            backup_path = Path(f"{config_path}.backup")
            self.assertEqual(backup_path.read_text(encoding="utf-8"),
                             "old: true\n")
            self.assertIn("general:", config_path.read_text(encoding="utf-8"))


class PreflightTests(unittest.TestCase):
    def test_rejects_camera_crop_outside_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.mp4"
            input_path.write_bytes(b"video")
            with self.assertRaises(PreflightError):
                PreflightValidator(FakeFFmpegRunner()).validate(
                    input_path=str(input_path),
                    output_dir=temp_dir,
                    no_conversion=False,
                    no_upload=True,
                    enabled_platforms=[],
                    title=None,
                    cam_x=1800,
                    cam_y=0,
                    cam_width=480,
                    cam_height=270,
                    platform_overrides=None)

    def test_returns_credential_warnings_without_uploading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.mp4"
            input_path.write_bytes(b"video")
            with patch.dict(os.environ, {
                    "GOOGLE_CLIENT_ID": "",
                    "GOOGLE_CLIENT_SECRET": "",
            }):
                warnings = PreflightValidator(FakeFFmpegRunner()).validate(
                    input_path=str(input_path),
                    output_dir=temp_dir,
                    no_conversion=True,
                    no_upload=False,
                    enabled_platforms=["youtube"],
                    title="A title",
                    cam_x=0,
                    cam_y=0,
                    cam_width=1,
                    cam_height=1,
                    platform_overrides=None)
            self.assertTrue(any("youtube" in warning for warning in warnings))


class UploadPipelineTests(unittest.TestCase):
    def test_initialization_failure_remains_in_results(self):
        with patch("clipmorph.upload_pipeline.YouTubeUploadPipeline",
                   side_effect=ValueError("missing credentials")):
            pipeline = UploadPipeline(youtube=True)

        results = pipeline.run("video.mp4", "A title")
        self.assertIn("YouTube", results)
        self.assertFalse(results["YouTube"]["success"])
        self.assertIn("missing credentials", results["YouTube"]["error"])


class OAuthTests(unittest.TestCase):
    def test_tiktok_pkce_uses_base64url_s256(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret")
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        self.assertEqual(
            pipeline._generate_code_challenge(verifier),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")

    def test_tiktok_auth_url_carries_generated_state(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret")
        url = pipeline._generate_auth_url("challenge", "state-value")
        self.assertIn("state=state-value", url)

    def test_tiktok_upload_passes_file_stream_to_http_client(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret")
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "video.mp4"
            video_path.write_bytes(b"video")
            with patch("clipmorph.upload_pipeline.platforms.tiktok.requests.put") as put:
                put.return_value = SimpleNamespace(status_code=200, ok=True)
                pipeline._upload_video_file(str(video_path), "https://upload", 5)

            request_data = put.call_args.kwargs["data"]
            self.assertFalse(isinstance(request_data, bytes))
            self.assertTrue(hasattr(request_data, "read"))


class ArtifactIsolationTests(unittest.TestCase):
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

    def test_job_manifest_persists_source_hash_and_platform_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            jobs_dir = Path(temp_dir) / "jobs"
            manifest = JobManifest.create(str(source), {"dry_run": False},
                                          str(jobs_dir))
            manifest.record_platform("YouTube", {"success": True},
                                    str(jobs_dir))
            loaded = JobManifest.load(manifest.job_id, str(jobs_dir))
            self.assertEqual(loaded.source_sha256, manifest.source_sha256)
            self.assertTrue(loaded.platforms["YouTube"]["success"])

    def test_manifest_keeps_mixed_platforms_as_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            manifest = JobManifest.create(str(source), {}, temp_dir)
            manifest.record_platform("YouTube", {"success": False}, temp_dir)
            manifest.record_platform("TikTok", {"success": True}, temp_dir)
            self.assertEqual(manifest.status, "partial_failure")


class ConfigDefaultsTests(unittest.TestCase):
    def test_runtime_defaults_are_centralized_and_consistent(self):
        defaults = build_platform_default_config()
        self.assertEqual(defaults["youtube"]["category"], "22")
        self.assertEqual(defaults["youtube"]["privacy_status"], "public")
        self.assertEqual(defaults["instagram"]["share_to_feed"], True)
        self.assertEqual(defaults["tiktok"]["privacy_level"], "PUBLIC_TO_EVERYONE")

    def test_dry_run_reports_effective_platform_values(self):
        summary = summarize_runtime_configuration({
            "youtube_privacy_status": "private",
            "youtube_category": "20",
            "tiktok_privacy_level": "SELF_ONLY",
        })
        self.assertEqual(summary["youtube"]["privacy_status"], "private")
        self.assertEqual(summary["youtube"]["category"], "20")
        self.assertEqual(summary["tiktok"]["privacy_level"], "SELF_ONLY")


class TranscriptionConfigTests(unittest.TestCase):
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


class BatchProcessorTests(unittest.TestCase):
    def test_batch_processor_deduplicates_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dir_path = Path(temp_dir)
            first = dir_path / "first.mp4"
            second = dir_path / "second.mp4"
            first.write_bytes(b"video")
            second.write_bytes(b"video")

            with patch.object(BatchProcessor, "_process_single_item",
                             side_effect=[
                                 {"input": str(first), "status": "failed", "reason": "failed"},
                                 {"input": str(second), "status": "processed", "hash": "hash-value"},
                             ]):
                results = BatchProcessor(input_path=str(dir_path),
                                         max_workers=2,
                                         max_upload_workers=2,
                                         max_ffmpeg_workers=2,
                                         max_cpu_workers=2,
                                         max_gpu_workers=2)._process_directory()

            self.assertEqual(results["total_items"], 2)
            self.assertEqual(results["processed"], 1)
            self.assertEqual(results["failed"], 1)


if __name__ == "__main__":
    unittest.main()
