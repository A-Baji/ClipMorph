import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from clipmorph.auth import auth_file_path, create_auth_template, load_auth_config
from clipmorph.auth import persist_auth_credential
from clipmorph.twitter_auth import TWITTER_REDIRECT_URI, authorize_twitter


class AuthConfigTests(unittest.TestCase):
    def test_twitter_authorization_reuses_exact_callback_uri(self):
        server = MagicMock()
        server.callback = {"state": ["state"], "code": ["code"]}
        response = type("TokenResponse", (), {
            "ok": True,
            "raise_for_status": lambda self: None,
            "json": lambda self: {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 7200,
            },
        })()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "auth.yaml").write_text(
                "twitter:\n  client_id: client\n  client_secret: secret\n",
                encoding="utf-8")
            with patch("clipmorph.twitter_auth._pkce_pair",
                       return_value=("verifier", "challenge")), \
                    patch("clipmorph.twitter_auth.secrets.token_urlsafe",
                          return_value="state"), \
                    patch("clipmorph.twitter_auth.HTTPServer",
                          return_value=server), \
                    patch("clipmorph.twitter_auth.webbrowser.open") as open_browser, \
                    patch("clipmorph.twitter_auth.requests.post",
                          return_value=response) as post:
                authorize_twitter(data_dir)

        auth_url = open_browser.call_args.args[0]
        self.assertEqual(parse_qs(urlparse(auth_url).query)["redirect_uri"],
                         [TWITTER_REDIRECT_URI])
        self.assertEqual(post.call_args.kwargs["data"]["redirect_uri"],
                         TWITTER_REDIRECT_URI)
        self.assertEqual(post.call_args.kwargs["auth"].username, "client")
        self.assertEqual(post.call_args.kwargs["auth"].password, "secret")

    def test_creates_auth_template_in_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = create_auth_template(temp_dir)

            self.assertEqual(path, Path(temp_dir) / "auth.yaml")
            content = path.read_text(encoding="utf-8")
            self.assertIn("youtube:", content)
            self.assertIn("refresh_token:", content)
            self.assertIn("gcs_bucket_name:", content)
            self.assertIn("gcp_private_key:", content)
            self.assertIn("open_id:", content)
            self.assertIn("client_id:", content)
            self.assertIn("hugging_face:", content)
            self.assertIn("twitter:", content)

    def test_existing_auth_file_is_backed_up_before_template_regeneration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.yaml"
            original = "youtube:\n  client_id: keep-this-safe\n"
            auth_path.write_text(original, encoding="utf-8")

            create_auth_template(temp_dir)

            self.assertEqual(
                (Path(temp_dir) / "auth.yaml.backup").read_text(encoding="utf-8"),
                original)
            self.assertIn("instagram:", auth_path.read_text(encoding="utf-8"))

    def test_existing_auth_file_generates_numbered_backup_when_needed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.yaml"
            auth_path.write_text("first: value\n", encoding="utf-8")
            backup_path = Path(temp_dir) / "auth.yaml.backup"
            backup_path.write_text("previous: backup\n", encoding="utf-8")
            (Path(temp_dir) / "auth.yaml.backup1").write_text(
                "older: backup\n", encoding="utf-8")

            create_auth_template(temp_dir)

            self.assertEqual(
                backup_path.read_text(encoding="utf-8"),
                "first: value\n")
            self.assertEqual(
                (Path(temp_dir) / "auth.yaml.backup1").read_text(encoding="utf-8"),
                "previous: backup\n")
            self.assertEqual(
                (Path(temp_dir) / "auth.yaml.backup2").read_text(encoding="utf-8"),
                "older: backup\n")
            self.assertIn("instagram:", auth_path.read_text(encoding="utf-8"))

    def test_loads_nested_platform_credentials_from_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "auth.yaml").write_text(
                "youtube:\n"
                "  client_id: youtube-id\n"
                "  client_secret: youtube-secret\n"
                "  refresh_token: youtube-refresh\n"
                "tiktok:\n"
                "  client_key: tiktok-key\n",
                encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                loaded = load_auth_config(data_dir)

                self.assertEqual(loaded["youtube"]["client_id"], "youtube-id")
                self.assertEqual(os.environ["GOOGLE_CLIENT_ID"], "youtube-id")
                self.assertEqual(os.environ["GOOGLE_REFRESH_TOKEN"],
                                 "youtube-refresh")
                self.assertEqual(os.environ["TIKTOK_CLIENT_KEY"], "tiktok-key")
            self.assertEqual(auth_file_path(data_dir), data_dir / "auth.yaml")

    def test_loads_instagram_gcp_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "auth.yaml").write_text(
                "instagram:\n"
                "  gcs_bucket_name: bucket\n"
                "  gcp_private_key_id: key-id\n"
                "  gcp_private_key: private-key\n"
                "  gcp_client_email: client@example.com\n"
                "  gcp_client_id: client-id\n"
                "  gcp_project_id: project-id\n",
                encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                load_auth_config(data_dir)

                self.assertEqual(os.environ["GCS_BUCKET_NAME"], "bucket")
                self.assertEqual(os.environ["GCP_PRIVATE_KEY_ID"], "key-id")
                self.assertEqual(os.environ["GCP_PRIVATE_KEY"], "private-key")
                self.assertEqual(os.environ["GCP_CLIENT_EMAIL"],
                                 "client@example.com")
                self.assertEqual(os.environ["GCP_CLIENT_ID"], "client-id")
                self.assertEqual(os.environ["GCP_PROJECT_ID"], "project-id")

    def test_loads_remaining_template_environment_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "auth.yaml").write_text(
                "tiktok:\n"
                "  access_token: tiktok-access\n"
                "  open_id: tiktok-open\n"
                "twitter:\n"
                "  client_id: twitter-id\n"
                "  client_secret: twitter-secret\n"
                "  oauth2_access_token: twitter-access\n"
                "  oauth2_refresh_token: twitter-refresh\n"
                "  oauth2_expires_at: '1234567890'\n"
                "hugging_face:\n"
                "  access_token: hf-token\n",
                encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                load_auth_config(data_dir)

                self.assertEqual(os.environ["TIKTOK_ACCESS_TOKEN"],
                                 "tiktok-access")
                self.assertEqual(os.environ["TIKTOK_OPEN_ID"], "tiktok-open")
                self.assertEqual(os.environ["TWITTER_CLIENT_ID"], "twitter-id")
                self.assertEqual(os.environ["TWITTER_CLIENT_SECRET"],
                                 "twitter-secret")
                self.assertEqual(os.environ["TWITTER_OAUTH2_ACCESS_TOKEN"],
                                 "twitter-access")
                self.assertEqual(os.environ["TWITTER_OAUTH2_REFRESH_TOKEN"],
                                 "twitter-refresh")
                self.assertEqual(os.environ["TWITTER_OAUTH2_EXPIRES_AT"],
                                 "1234567890")
                self.assertEqual(os.environ["HUGGING_FACE_ACCESS_TOKEN"],
                                 "hf-token")

    def test_existing_environment_credentials_take_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "auth.yaml").write_text(
                "youtube:\n  client_id: file-value\n", encoding="utf-8")

            with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "env-value"},
                            clear=True):
                load_auth_config(data_dir)

                self.assertEqual(os.environ["GOOGLE_CLIENT_ID"], "env-value")

    def test_auth_file_refresh_token_replaces_stale_environment_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "auth.yaml").write_text(
                "youtube:\n  refresh_token: file-token\n",
                encoding="utf-8")

            with patch.dict(os.environ, {"GOOGLE_REFRESH_TOKEN": "stale-token"},
                            clear=True):
                load_auth_config(data_dir)

                self.assertEqual(os.environ["GOOGLE_REFRESH_TOKEN"], "file-token")

    def test_persists_rotated_credential_to_active_auth_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "auth.yaml").write_text(
                "youtube:\n  refresh_token: old-token\n",
                encoding="utf-8")

            load_auth_config(data_dir)
            persist_auth_credential("youtube", "refresh_token", "new-token")

            self.assertIn(
                "refresh_token: new-token",
                (data_dir / "auth.yaml").read_text(encoding="utf-8"))
            self.assertIn(
                "refresh_token: old-token",
                (data_dir / "auth.yaml.backup").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()