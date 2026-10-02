import os
import requests
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import yaml

from clipmorph import auth as auth_module
from clipmorph.service import JobService
from clipmorph.upload_pipeline.platforms.tiktok import TikTokUploadPipeline
from clipmorph.upload_pipeline.platforms.twitter import TwitterUploadPipeline


class AuthPersistenceTests(unittest.TestCase):
    def test_job_service_loads_workspace_auth_and_persists_to_it(self):
        """CLI-built services load auth.yaml once and stays bound to it.

        Regexes do not appear in a path: the tokens the workspace stores are
        visible to uploads, and tokens the OAuth flow issues are persisted
        back into the SAME workspace file (#226) instead of the default
        data dir.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            auth_path = data_dir / "auth.yaml"
            auth_path.write_text(
                "auth_schema_version: 2\n"
                "youtube:\n"
                "    client_id: id\n"
                "    client_secret: secret\n"
                "    refresh_token: refreshed\n",
                encoding="utf-8")

            with patch.dict(os.environ):
                os.environ.pop("GOOGLE_REFRESH_TOKEN", None)
                service = JobService(data_dir)
                try:
                    self.assertEqual(
                        os.environ.get("GOOGLE_REFRESH_TOKEN"), "refreshed")
                    self.assertEqual(
                        auth_module.active_auth_file_path(), auth_path)

                    auth_module.persist_auth_credential(
                        "youtube", "refresh_token", "rotated")
                    persisted = yaml.safe_load(
                        auth_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        persisted["youtube"]["refresh_token"], "rotated")
                finally:
                    service.close()

    def test_service_default_launch_loads_auth_from_its_data_dir(self):
        """A service without an auth.yaml leaves no token env behind."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ):
                os.environ.pop("TWITTER_OAUTH2_ACCESS_TOKEN", None)
                service = JobService(Path(temp_dir))
                try:
                    self.assertIsNone(
                        os.environ.get("TWITTER_OAUTH2_ACCESS_TOKEN"))
                finally:
                    service.close()

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

    def test_twitter_refreshes_at_upload_time_when_the_stored_expiry_is_empty(self):
        """An unreadable `oauth2_expires_at` must not send a stale token.

        An auth.yaml written before expiry tracking stored `''`, so the
        freshness guard was skipped and the upload answered 401 while a valid
        refresh token was persisted.
        """
        with patch.dict(os.environ, {
                "TWITTER_OAUTH2_ACCESS_TOKEN": "",
                "TWITTER_OAUTH2_EXPIRES_AT": "",
                "TWITTER_OAUTH2_REFRESH_TOKEN": "refresh-token",
        }, clear=False), \
                patch("clipmorph.upload_pipeline.platforms.twitter."
                      "refresh_twitter_access_token",
                      return_value={"oauth2_access_token": "fresh-access",
                                    "oauth2_expires_at": "4102444800"}) as refresh:
            pipeline = TwitterUploadPipeline(
                twitter_client_id="client-id",
                twitter_client_secret="client-secret",
                twitter_oauth2_access_token="stale-access")
            pipeline._authenticate()

        refresh.assert_called_once()
        self.assertEqual(pipeline.access_token, "fresh-access")
        self.assertEqual(pipeline.expires_at, 4102444800)
        self.assertIsNotNone(pipeline.oauth_session)

    def test_twitter_refresh_is_attempted_when_the_access_token_is_absent(self):
        """A stored refresh token without an access token refreshes, not raises."""
        with patch.dict(os.environ, {
                "TWITTER_OAUTH2_ACCESS_TOKEN": "",
                "TWITTER_OAUTH2_REFRESH_TOKEN": "",
                "TWITTER_OAUTH2_EXPIRES_AT": "",
        }, clear=False), \
                patch("clipmorph.upload_pipeline.platforms.twitter."
                      "refresh_twitter_access_token",
                      return_value={"oauth2_access_token": "fresh-access",
                                    "oauth2_expires_at": "4102444800"}) as refresh:
            pipeline = TwitterUploadPipeline(
                twitter_client_id="client-id",
                twitter_client_secret="client-secret",
                twitter_oauth2_refresh_token="refresh-token")
            pipeline._authenticate()

        refresh.assert_called_once()
        self.assertEqual(pipeline.access_token, "fresh-access")

    def test_twitter_create_tweet_stays_on_v2_without_fallback(self):
        pipeline = TwitterUploadPipeline(
            twitter_client_id="client-id",
            twitter_client_secret="client-secret",
            twitter_oauth2_access_token="access-token",
            twitter_oauth2_refresh_token="refresh-token")
        pipeline.oauth_session = MagicMock()
        pipeline.oauth_session.post.return_value = SimpleNamespace(
            status_code=200,
            ok=True,
            reason="OK",
            json=lambda: {"data": {"id": "tweet-1"}},
            raise_for_status=lambda: None)

        self.assertEqual(pipeline._create_tweet("text", "media-1"), "tweet-1")
        self.assertEqual(
            pipeline.oauth_session.post.call_args.kwargs["json"],
            {"text": "text", "media": {"media_ids": ["media-1"]}})

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


class InstagramLoginDialogTests(unittest.TestCase):
    """The Meta login dialog URL branches on the FL4B Configuration.

    A Facebook Login for Business app authorizes through a Configuration
    (`config_id` has replaced `scope`), so the dialog URL must carry the
    stored Configuration ID and no scope list at all.
    """

    @staticmethod
    def _pipeline(config_id):
        from clipmorph.upload_pipeline.platforms.instagram import (
            InstagramUploadPipeline,
        )
        return InstagramUploadPipeline(
            facebook_app_id="app-id",
            facebook_app_secret="app-secret",
            facebook_page_id="page-id",
            facebook_access_token="page-token",
            facebook_config_id=config_id,
            gcp_project_id="project",
            gcp_private_key_id="key-id",
            gcp_private_key="private-key",
            gcp_client_email="uploader@example.iam.gserviceaccount.com",
            gcp_client_id="gcp-client-id",
            gcs_bucket_name="bucket")

    def _login_dialog_url(self, pipeline):
        """Drive the interactive flow with the network mocked out."""
        with patch("clipmorph.upload_pipeline.platforms.instagram."
                   "webbrowser.open") as open_browser, \
                patch("builtins.input", return_value="redirect-code"), \
                patch("clipmorph.upload_pipeline.platforms.instagram."
                      "requests.get",
                      return_value=SimpleNamespace(
                          ok=True,
                          json=lambda: {"access_token": "issued-token"})):
            pipeline.get_user_access_token()
        return open_browser.call_args.args[0]

    def test_fl4b_config_id_replaces_the_scope_parameter(self):
        pipeline = self._pipeline("config-123")
        url = self._login_dialog_url(pipeline)

        self.assertIn("dialog/oauth?client_id=app-id", url)
        self.assertIn("redirect_uri=https://localhost/", url)
        self.assertIn("config_id=config-123", url)
        self.assertIn("response_type=code", url)
        self.assertNotIn("scope=", url)

    def test_without_a_config_id_the_scope_url_is_unchanged(self):
        pipeline = self._pipeline(None)
        url = self._login_dialog_url(pipeline)

        self.assertIn(
            "&scope=instagram_basic,pages_show_list,pages_read_engagement,"
            "pages_manage_posts,instagram_content_publish"
            "&response_type=code", url)
        self.assertNotIn("config_id=", url)


if __name__ == "__main__":
    unittest.main()
