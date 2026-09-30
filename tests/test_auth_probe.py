"""Per-platform credential health probe behavior.

Every case mocks the network and platform boundaries at the probe module
edge, mirroring the mocked patterns in ``tests/test_oauth.py``. The fake
token ``secret-token-123`` is woven through the mocks so each failure case
can assert the redaction discipline: the token never appears in any detail.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from clipmorph.auth_probe import probe_credentials

FAKE_TOKEN = "secret-token-123"

# A fully populated credential environment so every platform reads as
# configured; individual cases delete or override the keys they exercise.
ALL_CREDENTIALS = {
    "GOOGLE_CLIENT_ID": "google-client-id",
    "GOOGLE_CLIENT_SECRET": "google-client-secret",
    "GOOGLE_REFRESH_TOKEN": FAKE_TOKEN,
    "FACEBOOK_APP_ID": "fb-app-id",
    "FACEBOOK_APP_SECRET": "fb-app-secret",
    "FACEBOOK_PAGE_ID": "123456789",
    "FACEBOOK_ACCESS_TOKEN": FAKE_TOKEN,
    "GCS_BUCKET_NAME": "clipmorph-test-bucket",
    "GCP_PROJECT_ID": "gcp-project",
    "GCP_PRIVATE_KEY_ID": "key-id",
    "GCP_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "GCP_CLIENT_EMAIL": "uploader@gcp-project.iam.gserviceaccount.com",
    "GCP_CLIENT_ID": "gcp-client-id",
    "TIKTOK_CLIENT_KEY": "tiktok-key",
    "TIKTOK_CLIENT_SECRET": "tiktok-secret",
    "TIKTOK_REFRESH_TOKEN": FAKE_TOKEN,
    "TWITTER_CLIENT_ID": "twitter-client-id",
    "TWITTER_CLIENT_SECRET": "twitter-client-secret",
    "TWITTER_OAUTH2_ACCESS_TOKEN": FAKE_TOKEN,
    "TWITTER_OAUTH2_REFRESH_TOKEN": FAKE_TOKEN,
    "TWITTER_OAUTH2_EXPIRES_AT": "4102444800",
    "HUGGING_FACE_ACCESS_TOKEN": FAKE_TOKEN,
}

YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def _without(*keys):
    return {key: value for key, value in ALL_CREDENTIALS.items()
            if key not in keys}


class YouTubeProbeTests(unittest.TestCase):
    def test_ok_refreshes_the_upload_scope_token(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.auth_probe.Credentials") as credentials_cls, \
                patch("clipmorph.auth_probe.Request"), \
                patch("clipmorph.upload_pipeline.platforms.youtube."
                      "YouTubeUploadPipeline") as pipeline_cls:
            pipeline_cls.YOUTUBE_UPLOAD_SCOPE = YOUTUBE_SCOPE
            pipeline_cls.GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
            result = probe_credentials(["youtube"])

        self.assertEqual(result["youtube"]["probe"], "ok")
        self.assertTrue(result["youtube"]["configured"])
        self.assertEqual(result["youtube"]["detail"], "refresh token accepted")
        credentials_cls.assert_called_once()
        self.assertEqual(credentials_cls.call_args.kwargs["scopes"], [YOUTUBE_SCOPE])
        self.assertEqual(credentials_cls.call_args.kwargs["token_uri"],
                         "https://oauth2.googleapis.com/token")
        credentials_cls.return_value.refresh.assert_called_once()

    def test_failure_is_masked(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.auth_probe.Credentials") as credentials_cls, \
                patch("clipmorph.auth_probe.Request"), \
                patch("clipmorph.upload_pipeline.platforms.youtube."
                      "YouTubeUploadPipeline"):
            credentials_cls.return_value.refresh.side_effect = Exception(
                f"invalid_grant: refresh_token={FAKE_TOKEN}")
            result = probe_credentials(["youtube"])

        self.assertEqual(result["youtube"]["probe"], "failed")
        self.assertNotIn(FAKE_TOKEN, result["youtube"]["detail"])
        self.assertIn("[REDACTED]", result["youtube"]["detail"])

    def test_missing_refresh_token_is_unavailable(self):
        env = _without("GOOGLE_REFRESH_TOKEN")
        with patch.dict(os.environ, env, clear=True), \
                patch("clipmorph.auth_probe.Credentials") as credentials_cls:
            result = probe_credentials(["youtube"])

        self.assertEqual(result["youtube"]["probe"], "unavailable")
        self.assertEqual(result["youtube"]["detail"], "incomplete credentials")
        credentials_cls.assert_not_called()


class InstagramProbeTests(unittest.TestCase):
    def _pipeline(self, pipeline_cls):
        pipeline = pipeline_cls.return_value
        pipeline.api_version = "v23.0"
        pipeline.page_id = "123456789"
        pipeline.access_token = FAKE_TOKEN
        pipeline.gcs_bucket_name = "clipmorph-test-bucket"
        pipeline.google_creds = MagicMock()
        return pipeline

    def test_ok_merges_graph_and_gcs_subchecks(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.instagram."
                      "InstagramUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get, \
                patch("google.cloud.storage.Client") as client_cls:
            self._pipeline(pipeline_cls)
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"id": "123456789"}
            client_cls.return_value.bucket.return_value.exists.return_value = True
            result = probe_credentials(["instagram"])

        self.assertEqual(result["instagram"]["probe"], "ok")
        self.assertIn("graph api ok", result["instagram"]["detail"])
        self.assertIn("gcs bucket ok", result["instagram"]["detail"])

    def test_graph_failure_is_masked(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.instagram."
                      "InstagramUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get, \
                patch("google.cloud.storage.Client") as client_cls:
            self._pipeline(pipeline_cls)
            get.return_value.status_code = 403
            get.return_value.text = f"access_token={FAKE_TOKEN} rejected"
            client_cls.return_value.bucket.return_value.exists.return_value = True
            result = probe_credentials(["instagram"])

        self.assertEqual(result["instagram"]["probe"], "failed")
        self.assertNotIn(FAKE_TOKEN, result["instagram"]["detail"])
        self.assertIn("[REDACTED]", result["instagram"]["detail"])
        self.assertIn("gcs bucket ok", result["instagram"]["detail"])

    def test_page_id_mismatch_fails_the_graph_subcheck(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.instagram."
                      "InstagramUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get, \
                patch("google.cloud.storage.Client") as client_cls:
            self._pipeline(pipeline_cls)
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"id": "a-different-page"}
            client_cls.return_value.bucket.return_value.exists.return_value = True
            result = probe_credentials(["instagram"])

        self.assertEqual(result["instagram"]["probe"], "failed")
        self.assertIn("page id mismatch", result["instagram"]["detail"])


class TikTokProbeTests(unittest.TestCase):
    def test_ok_returns_user_info(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.tiktok."
                      "TikTokUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get:
            pipeline_cls.return_value.refresh_token = FAKE_TOKEN
            pipeline_cls.return_value._refresh_access_token.return_value = "access"
            get.return_value.status_code = 200
            result = probe_credentials(["tiktok"])

        self.assertEqual(result["tiktok"]["probe"], "ok")
        self.assertEqual(result["tiktok"]["detail"], "user info returned")

    def test_401_refreshes_once_and_retries(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.tiktok."
                      "TikTokUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get:
            pipeline = pipeline_cls.return_value
            pipeline.refresh_token = FAKE_TOKEN
            pipeline._refresh_access_token.side_effect = ["access", "access-2"]
            get.side_effect = [MagicMock(status_code=401), MagicMock(status_code=200)]
            result = probe_credentials(["tiktok"])

        self.assertEqual(result["tiktok"]["probe"], "ok")
        self.assertEqual(pipeline._refresh_access_token.call_count, 2)
        self.assertEqual(get.call_count, 2)

    def test_missing_refresh_token_is_unavailable(self):
        env = _without("TIKTOK_REFRESH_TOKEN")
        with patch.dict(os.environ, env, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.tiktok."
                      "TikTokUploadPipeline") as pipeline_cls:
            pipeline_cls.return_value.refresh_token = None
            result = probe_credentials(["tiktok"])

        self.assertEqual(result["tiktok"]["probe"], "unavailable")
        self.assertEqual(result["tiktok"]["detail"],
                         "interactive authorization required; run clipmorph auth set tiktok")


class TwitterProbeTests(unittest.TestCase):
    def test_ok_returns_user_info(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.auth_probe.requests.Session") as session_cls:
            session_cls.return_value.get.return_value.status_code = 200
            result = probe_credentials(["twitter"])

        self.assertEqual(result["twitter"]["probe"], "ok")
        self.assertEqual(result["twitter"]["detail"], "user info returned")

    def test_401_refreshes_and_retries(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.auth_probe.requests.Session") as session_cls, \
                patch("clipmorph.auth_probe.refresh_twitter_access_token") as refresh:
            session = session_cls.return_value
            session.get.side_effect = [MagicMock(status_code=401),
                                        MagicMock(status_code=200)]
            refresh.return_value = {"oauth2_access_token": "new-token"}
            result = probe_credentials(["twitter"])

        self.assertEqual(result["twitter"]["probe"], "ok")
        self.assertEqual(session.get.call_count, 2)
        refresh.assert_called_once()

    def test_refresh_failure_reports_token_expired(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.auth_probe.requests.Session") as session_cls, \
                patch("clipmorph.auth_probe.refresh_twitter_access_token") as refresh:
            session_cls.return_value.get.return_value.status_code = 401
            refresh.side_effect = Exception(f"refresh_token={FAKE_TOKEN} rejected")
            result = probe_credentials(["twitter"])

        self.assertEqual(result["twitter"]["probe"], "failed")
        self.assertEqual(result["twitter"]["detail"],
                         "token expired; rerun clipmorph auth twitter")
        self.assertNotIn(FAKE_TOKEN, result["twitter"]["detail"])


class FacebookProbeTests(unittest.TestCase):
    def _pipeline(self, pipeline_cls):
        pipeline = pipeline_cls.return_value
        pipeline.api_version = "v23.0"
        pipeline.page_id = "123456789"
        pipeline.access_token = FAKE_TOKEN
        return pipeline

    def test_ok_reports_page_and_reels_capability(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.facebook."
                      "FacebookUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get:
            self._pipeline(pipeline_cls)
            get.return_value.status_code = 200
            get.return_value.json.return_value = {
                "id": "123456789", "tasks": ["CREATE_CONTENT", "MANAGE"]}
            result = probe_credentials(["facebook"])

        self.assertEqual(result["facebook"]["probe"], "ok")
        self.assertIn("reels capability granted", result["facebook"]["detail"])

    def test_ok_without_publish_task_notes_unconfirmed_capability(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.facebook."
                      "FacebookUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get:
            self._pipeline(pipeline_cls)
            get.return_value.status_code = 200
            get.return_value.json.return_value = {
                "id": "123456789", "tasks": ["ANALYZE"]}
            result = probe_credentials(["facebook"])

        self.assertEqual(result["facebook"]["probe"], "ok")
        self.assertIn("reels capability not confirmed",
                      result["facebook"]["detail"])

    def test_graph_failure_is_masked(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.facebook."
                      "FacebookUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get:
            self._pipeline(pipeline_cls)
            get.return_value.status_code = 403
            get.return_value.text = f"access_token={FAKE_TOKEN} rejected"
            result = probe_credentials(["facebook"])

        self.assertEqual(result["facebook"]["probe"], "failed")
        self.assertNotIn(FAKE_TOKEN, result["facebook"]["detail"])
        self.assertIn("[REDACTED]", result["facebook"]["detail"])

    def test_page_id_mismatch_fails(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.facebook."
                      "FacebookUploadPipeline") as pipeline_cls, \
                patch("clipmorph.auth_probe.requests.get") as get:
            self._pipeline(pipeline_cls)
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"id": "a-different-page"}
            result = probe_credentials(["facebook"])

        self.assertEqual(result["facebook"]["probe"], "failed")
        self.assertIn("page id mismatch", result["facebook"]["detail"])

    def test_incomplete_credentials_are_unavailable(self):
        env = _without("FACEBOOK_ACCESS_TOKEN")
        with patch.dict(os.environ, env, clear=True), \
                patch("clipmorph.upload_pipeline.platforms.facebook."
                      "FacebookUploadPipeline",
                      side_effect=ValueError("missing credentials")):
            result = probe_credentials(["facebook"])

        self.assertEqual(result["facebook"]["probe"], "unavailable")
        self.assertEqual(result["facebook"]["detail"],
                         "incomplete credentials")


class ProbeRoutingTests(unittest.TestCase):
    def test_hugging_face_is_always_unavailable(self):
        with patch.dict(os.environ, ALL_CREDENTIALS, clear=True):
            result = probe_credentials(["hugging_face"])

        self.assertTrue(result["hugging_face"]["configured"])
        self.assertEqual(result["hugging_face"]["probe"], "unavailable")
        self.assertEqual(result["hugging_face"]["detail"],
                         "no read-only probe implemented")

    def test_unconfigured_platform_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            result = probe_credentials(["youtube"])

        self.assertFalse(result["youtube"]["configured"])
        self.assertEqual(result["youtube"]["probe"], "unavailable")
        self.assertEqual(result["youtube"]["detail"], "not configured")

    def test_every_platform_gets_a_record(self):
        with patch.dict(os.environ, {}, clear=True):
            result = probe_credentials(
                ["youtube", "instagram", "tiktok", "twitter", "facebook",
                 "hugging_face"])

        self.assertEqual(set(result),
                         {"youtube", "instagram", "tiktok", "twitter",
                          "facebook", "hugging_face"})
        for record in result.values():
            self.assertEqual(record["probe"], "unavailable")


if __name__ == "__main__":
    unittest.main()
