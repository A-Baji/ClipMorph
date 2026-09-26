import os
import requests
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from clipmorph.__main__ import main
from clipmorph.batch import BatchProcessor
from clipmorph.cli import build_platform_default_config, run_cli
from clipmorph.cli import summarize_runtime_configuration
from clipmorph.workflow import execute_job
from clipmorph.job import default_data_dir
from clipmorph.preflight import PreflightError, PreflightValidator
from clipmorph.service import CancellationToken
from clipmorph.conversion_pipeline.transcribe import TranscriptionPipeline, resolve_transcription_device, write_srt_file
from clipmorph.conversion_pipeline.convert import ConversionPipeline
from clipmorph.job import JobManifest
from clipmorph.service import JobService
from clipmorph.upload_pipeline import UploadPipeline
from clipmorph.upload_pipeline.platforms.tiktok import TikTokUploadPipeline
from clipmorph.upload_pipeline.platforms.twitter import TwitterUploadPipeline
from clipmorph.policy import validate_artifact


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
    def test_init_writes_app_yaml_and_auth_in_selected_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            with patch.object(sys, "argv", [
                    "clipmorph", "--data-dir", str(data_dir), "init"]):
                main()

            self.assertTrue((data_dir / "app.yml").exists())
            self.assertTrue((data_dir / "auth.yaml").exists())

    def test_init_config_path_writes_adjacent_auth_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yml"
            with patch.object(sys, "argv", [
                    "clipmorph", "init", "--config-path", str(config_path)
            ]):
                main()

            self.assertTrue(config_path.exists())
            self.assertTrue((Path(temp_dir) / "auth.yaml").exists())

    def test_init_does_not_replace_existing_app_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yml"
            config_path.write_text("existing: true\n", encoding="utf-8")
            with patch.object(sys, "argv", [
                    "clipmorph", "init", "--config-path", str(config_path)
            ]):
                main()

            self.assertEqual(config_path.read_text(encoding="utf-8"), "existing: true\n")


class JobCommandPersistenceTests(unittest.TestCase):
    def test_cli_data_dir_persists_updated_manifest_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "custom-data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "input.mp4"
            source.write_bytes(b"video")

            with patch.object(sys, "argv", [
                    "clipmorph", "--data-dir", str(data_dir),
                "job", "create", str(source)
            ]), patch("clipmorph.workflow.execute_job"):
                main()

            manifests = list((data_dir / "jobs").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            loaded = JobManifest.load(manifests[0].parent.name, str(data_dir / "jobs"))
            self.assertEqual(loaded.status, "queued")
            self.assertEqual(loaded.configuration["general"]["source"], "input.mp4")


class JobCommandPersistenceTests(unittest.TestCase):
    def test_cli_data_dir_persists_updated_manifest_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "custom-data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "input.mp4"
            source.write_bytes(b"video")

            with patch.object(sys, "argv", [
                    "clipmorph", "--data-dir", str(data_dir),
                "job", "create", str(source)
            ]), patch("clipmorph.workflow.execute_job"):
                main()

            manifests = list((data_dir / "jobs").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            loaded = JobManifest.load(manifests[0].parent.name, str(data_dir / "jobs"))
            self.assertEqual(loaded.status, "queued")
            self.assertEqual(loaded.configuration["general"]["source"], "input.mp4")


class PreflightTests(unittest.TestCase):
    def test_rejects_layout_crop_outside_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.mp4"
            input_path.write_bytes(b"video")
            with self.assertRaises(PreflightError):
                PreflightValidator(FakeFFmpegRunner()).validate(
                    input_path=str(input_path),
                    output_dir=temp_dir,
                    conversion={"skip": False},
                    upload={"skip": True},
                    enabled_platforms=[],
                    title="clip",
                    layout={"crop": {
                        "enabled": True,
                        "source": {"x": 1800, "y": 0,
                                   "width": 320, "height": 240},
                        "sizing": {"mode": "native"},
                        "composition": {"mode": "overlay", "placement": "top"},
                    }})

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
                    conversion={"skip": True},
                    upload={"skip": False},
                    enabled_platforms=["youtube"],
                    title="A title",
                    layout={})
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

    def test_interactive_authentication_is_prepared_before_parallel_uploads(self):
        pipeline = UploadPipeline()
        tiktok = MagicMock()
        tiktok.access_token = None
        pipeline.enabled_platforms = {"TikTok": tiktok}
        results = {}

        pipeline._prepare_interactive_authentication(results)

        tiktok._refresh_access_token.assert_called_once_with()
        self.assertEqual(results, {})

    def test_platform_policy_blocks_known_incompatible_artifact(self):
        decision = validate_artifact("instagram", {
            "duration": 2,
            "width": 1080,
            "height": 1920,
            "video_codec": "h264",
            "file_size": 1000,
        }, {"title": "caption"})
        self.assertFalse(decision.allowed)
        self.assertIn("duration", decision.blockers[0])

    def test_platform_policy_warns_on_unknown_rules_without_blocking(self):
        decision = validate_artifact("tiktok", {"duration": 10}, {"title": "caption"})
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.warnings)


class OAuthTests(unittest.TestCase):
    def test_tiktok_video_init_includes_brand_content_toggle(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret")
        response = MagicMock()
        response.json.return_value = {
            "data": {"upload_url": "https://upload.example", "publish_id": "publish-id"}
        }

        with patch.object(pipeline, "_retry_request", return_value=response) as request:
            result = pipeline._initialize_upload(123, "A title")

        self.assertEqual(result, ("https://upload.example", "publish-id"))
        request.assert_called_once()
        self.assertFalse(request.call_args.kwargs["json"]["post_info"][
            "brand_content_toggle"])

    def test_tiktok_http_error_includes_api_code_and_log_id(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret")
        response = MagicMock()
        response.reason = "Forbidden"
        response.json.return_value = {
            "error": {
                "code": "scope_not_authorized",
                "message": "video.publish is not authorized",
                "log_id": "log-123",
            }
        }

        pipeline._enhance_error_message(response)

        self.assertIn("scope_not_authorized", response.reason)
        self.assertIn("log-123", response.reason)

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

    def test_tiktok_pipeline_reads_persisted_credentials_at_construction(self):
        with patch.dict(os.environ, {
                "TIKTOK_CLIENT_KEY": "client",
                "TIKTOK_CLIENT_SECRET": "secret",
                "TIKTOK_REFRESH_TOKEN": "persisted-refresh-token",
        }, clear=True):
            pipeline = TikTokUploadPipeline()

        self.assertEqual(pipeline.refresh_token, "persisted-refresh-token")

    def test_tiktok_authorization_opens_in_default_browser(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret")
        with patch("clipmorph.upload_pipeline.platforms.tiktok.webbrowser.open") as open_browser, \
                patch("builtins.input", return_value="http://127.0.0.1:80/callback/?code=code&state=state"), \
                patch.object(pipeline, "_exchange_code_for_token", return_value={
                    "refresh_token": "refresh"}), \
                patch.object(pipeline, "_generate_code_challenge", return_value="challenge"), \
                patch("secrets.token_urlsafe", return_value="state"):
            pipeline.generate_refresh_token()

        open_browser.assert_called_once()

    def test_tiktok_authorization_reports_token_exchange_error(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret")
        with patch("clipmorph.upload_pipeline.platforms.tiktok.webbrowser.open"), \
            patch("builtins.input", return_value=(
                "http://127.0.0.1:80/callback/?code=code&state=state")), \
                patch.object(pipeline, "_exchange_code_for_token", return_value={
                    "error": "invalid_grant",
                    "error_description": "Authorization code has expired",
                }), \
                patch.object(pipeline, "_generate_code_challenge", return_value="challenge"), \
                patch("secrets.token_urlsafe", return_value="state"):
            with self.assertRaisesRegex(
                    RuntimeError, "Authorization code has expired"):
                pipeline.generate_refresh_token()

    def test_tiktok_refresh_falls_back_to_interactive_authorization(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret",
            tiktok_refresh_token="expired")
        refreshed = {"access_token": "new-access", "refresh_token": "new-refresh"}
        with patch.object(pipeline, "generate_refresh_token", return_value="new-refresh") as generate, \
                patch.object(pipeline, "_retry_request") as retry_request:
            accepted = MagicMock()
            accepted.json.return_value = refreshed
            retry_request.side_effect = [requests.exceptions.HTTPError("expired"), accepted]

            self.assertEqual(pipeline._refresh_access_token(), "new-access")

        generate.assert_called_once_with()

    def test_tiktok_refresh_falls_back_on_json_token_error(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret",
            tiktok_refresh_token="expired")
        rejected = MagicMock()
        rejected.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Refresh token expired",
        }
        accepted = MagicMock()
        accepted.json.return_value = {"access_token": "new-access"}
        with patch.object(pipeline, "generate_refresh_token", return_value="new-refresh") as generate, \
                patch.object(pipeline, "_retry_request", side_effect=[rejected, accepted]):
            self.assertEqual(pipeline._refresh_access_token(), "new-access")

        generate.assert_called_once_with()

    def test_tiktok_accepts_nested_token_exchange_response(self):
        pipeline = TikTokUploadPipeline(
            tiktok_client_key="client",
            tiktok_client_secret="secret")
        token_response = SimpleNamespace(json=lambda: {
            "data": {
                "access_token": "access",
                "refresh_token": "refresh",
            }
        })
        with patch.object(pipeline, "_retry_request", return_value=token_response):
            with patch("clipmorph.upload_pipeline.platforms.tiktok.webbrowser.open"), \
                patch("builtins.input", return_value=(
                    "http://127.0.0.1:80/callback/?code=code&state=state")), \
                    patch("secrets.token_urlsafe", return_value="state"), \
                    patch.object(pipeline, "_generate_code_challenge", return_value="challenge"):
                self.assertEqual(pipeline.generate_refresh_token(), "refresh")

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

    def test_twitter_upload_requires_oauth2_user_token(self):
        TwitterUploadPipeline(
            twitter_client_id="client-id",
            twitter_client_secret="client-secret",
            twitter_oauth2_access_token="access-token",
            twitter_oauth2_refresh_token="refresh-token")

    def test_twitter_authenticates_interactively_when_user_token_is_missing(self):
        with patch.dict(os.environ, {
                "TWITTER_OAUTH2_ACCESS_TOKEN": "",
                "TWITTER_OAUTH2_REFRESH_TOKEN": "",
                "TWITTER_OAUTH2_EXPIRES_AT": "",
        }, clear=False), \
                patch("clipmorph.upload_pipeline.platforms.twitter.authorize_twitter") as authorize:
            pipeline = TwitterUploadPipeline(
                twitter_client_id="client-id",
                twitter_client_secret="client-secret")
            with patch.dict(os.environ, {
                    "TWITTER_OAUTH2_ACCESS_TOKEN": "access-token",
                    "TWITTER_OAUTH2_REFRESH_TOKEN": "refresh-token",
                    "TWITTER_OAUTH2_EXPIRES_AT": "4102444800",
            }, clear=False):
                pipeline._authenticate()

        authorize.assert_called_once_with(None)
        self.assertIsNotNone(pipeline.oauth_session)

    def test_twitter_media_upload_uses_v2_chunked_oauth2_flow(self):
        pipeline = TwitterUploadPipeline(
            twitter_client_id="client-id",
            twitter_client_secret="client-secret",
            twitter_oauth2_access_token="access-token",
            twitter_oauth2_refresh_token="refresh-token")
        pipeline.oauth_session = MagicMock()
        response = lambda payload=None: SimpleNamespace(
            status_code=200,
            ok=True,
            reason="OK",
            json=lambda: payload or {},
            raise_for_status=lambda: None)
        initialize = response({"data": {"id": "media-id"}})
        finalize = response()
        append = response()
        pipeline.oauth_session.post.side_effect = [
            initialize, append, append, finalize
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "video.mp4"
            video_path.write_bytes(b"a" * (pipeline.MEDIA_CHUNK_SIZE + 1))
            with patch.object(pipeline, "_update_progress"):
                self.assertEqual(pipeline._upload_media(str(video_path)),
                                 "media-id")

        calls = pipeline.oauth_session.post.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertTrue(calls[0].args[0].endswith("/initialize"))
        self.assertEqual(calls[0].kwargs["json"]["media_category"],
                         "tweet_video")
        self.assertEqual(calls[1].kwargs["data"]["segment_index"], "0")
        self.assertEqual(calls[2].kwargs["data"]["segment_index"], "1")
        self.assertTrue(calls[1].args[0].endswith("/media-id/append"))
        self.assertTrue(calls[3].args[0].endswith("/finalize"))

    def test_twitter_media_upload_polls_v2_status_until_succeeded(self):
        pipeline = TwitterUploadPipeline(
            twitter_client_id="client-id",
            twitter_client_secret="client-secret",
            twitter_oauth2_access_token="access-token",
            twitter_oauth2_refresh_token="refresh-token")
        pipeline.oauth_session = MagicMock()
        statuses = []
        for state in ("pending", "in_progress", "succeeded"):
            statuses.append(SimpleNamespace(
                status_code=200,
                ok=True,
                reason="OK",
                json=lambda state=state: {
                    "data": {"processing_info": {"state": state}}
                },
                raise_for_status=lambda: None))
        pipeline.oauth_session.get.side_effect = statuses
        pipeline.progress_bar = None

        with patch("clipmorph.upload_pipeline.platforms.twitter.time.sleep"):
            self.assertTrue(pipeline._wait_for_processing("media-id", 1))

        self.assertEqual(pipeline.oauth_session.get.call_count, 3)
        status_url = pipeline.oauth_session.get.call_args_list[0].args[0]
        self.assertIn("api.x.com/2/media/upload?command=STATUS", status_url)


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
            self.assertEqual(loaded.schema_version, 2)
            self.assertEqual(loaded.source_sha256, manifest.source_sha256)
            self.assertTrue(loaded.platforms["YouTube"]["success"])

    def test_manifest_persists_step_and_artifact_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            artifact = Path(temp_dir) / "converted.mp4"
            manifest = JobManifest.create(str(source), {}, temp_dir)
            manifest.set_step("conversion", "running", temp_dir)
            manifest.set_artifact(str(artifact), temp_dir)
            loaded = JobManifest.load(manifest.job_id, temp_dir)

            self.assertEqual(loaded.steps["conversion"]["status"], "running")
            artifact = loaded.artifacts[loaded.current_artifact_id]
            self.assertEqual(artifact["source_sha256"], manifest.source_sha256)

    def test_rerender_artifacts_are_immutable_revisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            first = Path(temp_dir) / "first.mp4"
            second = Path(temp_dir) / "second.mp4"
            first.write_bytes(b"first revision")
            second.write_bytes(b"second revision")
            manifest = JobManifest.create(str(source), {}, temp_dir)

            manifest.set_artifact(str(first), temp_dir)
            first_id = manifest.current_artifact_id
            manifest.set_artifact(str(second), temp_dir)
            loaded = JobManifest.load(manifest.job_id, temp_dir)

            self.assertEqual(len(loaded.artifacts), 2)
            self.assertEqual(loaded.artifacts[first_id]["state"], "superseded")
            self.assertEqual(loaded.artifacts[loaded.current_artifact_id]["state"], "current")
            self.assertNotEqual(loaded.artifacts[first_id]["sha256"],
                                loaded.artifacts[loaded.current_artifact_id]["sha256"])


class JobServiceTests(unittest.TestCase):
    def test_service_persists_completed_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "data" / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "input.mp4"
            source.write_bytes(b"video")
            service = JobService(Path(temp_dir) / "data")

            def complete_job(job, _token):
                for stage in ("transcript", "conversion", "upload"):
                    checkpoint = job.checkpoints[stage]
                    if checkpoint["status"] == "skipped":
                        continue
                    checkpoint = job.transition_checkpoint(
                        stage, "running", checkpoint["revision"], service.jobs_dir)
                    job.transition_checkpoint(
                        stage, "completed", checkpoint["revision"], service.jobs_dir)

            try:
                manifest = service.create_job(
                    str(source), {}, complete_job)
                service._futures[manifest.job_id].result(timeout=2)
                self.assertEqual(service.get_job(manifest.job_id).status,
                                 "completed")
            finally:
                service.close()

    def test_service_cancels_queued_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "data" / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "input.mp4"
            source.write_bytes(b"video")
            service = JobService(Path(temp_dir) / "data")
            try:
                manifest = service.create_job(str(source), {})
                cancelled = service.cancel_job(manifest.job_id)
                self.assertEqual(cancelled.status, "cancelled")
            finally:
                service.close()

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


class JobCommandTests(unittest.TestCase):
    def test_init_writes_app_yaml_and_auth_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            result = run_cli(["--data-dir", str(data_dir), "init"])

            self.assertEqual(result, 0)
            self.assertTrue((data_dir / "app.yml").exists())
            self.assertTrue((data_dir / "auth.yaml").exists())
            self.assertFalse((data_dir / "clipmorph.yaml").exists())

    def test_job_create_dry_run_uses_service_and_writes_no_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "A clip.mp4").write_bytes(b"video")

            result = run_cli([
                "--data-dir", str(data_dir), "job", "create", str(source_dir),
                "--dry-run",
            ])

            self.assertEqual(result, 0)
            self.assertFalse((data_dir / "jobs").exists())

    def test_upload_review_edits_update_the_pending_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {})
            checkpoint = manifest.checkpoints["upload"]
            manifest.transition_checkpoint(
                "upload", "awaiting_review", checkpoint["revision"], service.jobs_dir)
            service.close()
            edit_path = Path(temp_dir) / "upload.yml"
            edit_path.write_text(
                "content:\n  title: Reviewed title\n", encoding="utf-8")

            result = run_cli([
                "--data-dir", str(data_dir), "job", "review", manifest.job_id,
                "upload", "--edits", str(edit_path),
            ])

            self.assertEqual(result, 0)
            saved = JobManifest.load(manifest.job_id, data_dir / "jobs")
            self.assertEqual(
                saved.configuration["upload"]["content"]["title"],
                "Reviewed title")


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
