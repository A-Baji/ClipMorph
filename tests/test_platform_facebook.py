"""Facebook Page Reel / Page video adapter behavior with mocked HTTP.

The network seam is ``clipmorph.upload_pipeline.platforms.facebook.requests``,
mirroring the TikTok and Twitter mock patterns: every case patches the HTTP
call and asserts the Graph API phase, payload, and returned identifier without
touching the network.
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clipmorph.upload_pipeline.platforms.facebook import FacebookUploadPipeline

POST = "clipmorph.upload_pipeline.platforms.facebook.requests.post"


def _response(payload):
    return SimpleNamespace(status_code=200, ok=True, reason="OK",
                           text="", json=lambda: payload)


def _pipeline(**kwargs):
    return FacebookUploadPipeline(
        facebook_app_id="app-id",
        facebook_app_secret="app-secret",
        facebook_page_id="page-1",
        facebook_access_token="page-token",
        **kwargs)


class FacebookCredentialTests(unittest.TestCase):
    def test_missing_credentials_raise_a_clear_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError,
                                        "Missing required Facebook credentials"):
                FacebookUploadPipeline()

    def test_reads_the_shared_meta_environment_keys(self):
        env = {
            "FACEBOOK_APP_ID": "env-app",
            "FACEBOOK_APP_SECRET": "env-secret",
            "FACEBOOK_PAGE_ID": "env-page",
            "FACEBOOK_ACCESS_TOKEN": "env-token",
        }
        with patch.dict(os.environ, env, clear=True):
            pipeline = FacebookUploadPipeline()

        self.assertEqual(pipeline.app_id, "env-app")
        self.assertEqual(pipeline.page_id, "env-page")
        self.assertEqual(pipeline.access_token, "env-token")


class FacebookInitializationTests(unittest.TestCase):
    def test_reel_initialization_requests_the_start_phase(self):
        pipeline = _pipeline()
        with patch(POST, return_value=_response({
                "video_id": "v1", "upload_url": "https://rupload.example/v1"})) as post:
            result = pipeline._initialize_reel("page-1", "token")

        self.assertEqual(result, ("v1", "https://rupload.example/v1"))
        self.assertEqual(post.call_args.args[0],
                         "https://graph.facebook.com/v23.0/page-1/video_reels")
        self.assertEqual(post.call_args.kwargs["data"]["upload_phase"], "start")

    def test_video_initialization_requests_start_with_file_size(self):
        pipeline = _pipeline()
        with patch(POST, return_value=_response({
                "upload_session_id": "s1", "video_id": "v1",
                "start_offset": "0", "end_offset": "10"})) as post:
            result = pipeline._initialize_video("page-1", "token", 10)

        self.assertEqual(result, ("s1", "v1", 0, 10))
        self.assertEqual(post.call_args.args[0],
                         "https://graph.facebook.com/v23.0/page-1/videos")
        data = post.call_args.kwargs["data"]
        self.assertEqual(data["upload_phase"], "start")
        self.assertEqual(data["file_size"], 10)


class FacebookUploadTests(unittest.TestCase):
    def _video(self, temp_dir, name="clip.mp4", data=b"video-bytes"):
        path = Path(temp_dir) / name
        path.write_bytes(data)
        return path

    def test_reel_upload_streams_the_file_to_the_session_url(self):
        pipeline = _pipeline()
        with tempfile.TemporaryDirectory() as temp_dir:
            video = self._video(temp_dir)
            size = video.stat().st_size
            with patch(POST, return_value=_response({"success": True})) as post:
                pipeline._upload_reel(str(video), "https://rupload.example/v1",
                                      "token", size)

        request_data = post.call_args.kwargs["data"]
        self.assertFalse(isinstance(request_data, bytes))
        self.assertTrue(hasattr(request_data, "read"))
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "OAuth token")
        self.assertEqual(headers["offset"], "0")
        self.assertEqual(headers["file_size"], str(size))

    def test_video_chunks_follow_the_returned_offsets(self):
        pipeline = _pipeline()
        responses = [
            _response({"start_offset": "5", "end_offset": "10"}),
            _response({"start_offset": "10", "end_offset": "10"}),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            video = self._video(temp_dir, data=b"0123456789")
            with patch(POST, side_effect=responses) as post:
                pipeline._upload_chunks(str(video), "page-1", "token", "s1",
                                        0, 5, 10)

        self.assertEqual(post.call_count, 2)
        first = post.call_args_list[0].kwargs
        self.assertEqual(first["data"]["upload_phase"], "transfer")
        self.assertEqual(first["data"]["upload_session_id"], "s1")
        self.assertEqual(first["data"]["start_offset"], 0)
        self.assertIn("video_file_chunk", first["files"])


class FacebookFinishTests(unittest.TestCase):
    def test_reel_finish_publishes_with_state_and_description(self):
        pipeline = _pipeline()
        with patch(POST, return_value=_response({"success": True})) as post:
            result = pipeline._finish_reel(
                "v1", "page-1", "token", "caption text", "PUBLISHED",
                ["111", "222"])

        self.assertEqual(result, "v1")
        data = post.call_args.kwargs["data"]
        self.assertEqual(data["upload_phase"], "finish")
        self.assertEqual(data["video_id"], "v1")
        self.assertEqual(data["video_state"], "PUBLISHED")
        self.assertEqual(data["description"], "caption text")
        self.assertEqual(data["content_tags"], "111,222")

    def test_video_finish_returns_the_published_id(self):
        pipeline = _pipeline()
        with patch(POST, return_value=_response({"id": "published-9"})) as post:
            result = pipeline._finish_video("s1", "page-1", "token", "caption",
                                            "v1", None)

        self.assertEqual(result, "published-9")
        data = post.call_args.kwargs["data"]
        self.assertEqual(data["upload_session_id"], "s1")
        self.assertEqual(data["description"], "caption")
        self.assertNotIn("content_tags", data)


class FacebookRunTests(unittest.TestCase):
    def _video(self, temp_dir):
        path = Path(temp_dir) / "clip.mp4"
        path.write_bytes(b"video")
        return path

    def test_run_dispatches_the_reel_kind(self):
        pipeline = _pipeline()
        with tempfile.TemporaryDirectory() as temp_dir:
            video = self._video(temp_dir)
            with patch.object(pipeline, "_initialize_reel",
                              return_value=("v1", "url")) as init, \
                    patch.object(pipeline, "_upload_reel") as upload, \
                    patch.object(pipeline, "_finish_reel",
                                 return_value="v1") as finish:
                result = pipeline.run(str(video), "caption")

        self.assertEqual(result, "v1")
        init.assert_called_once_with("page-1", "page-token")
        upload.assert_called_once()
        finish.assert_called_once()

    def test_run_dispatches_the_video_kind(self):
        pipeline = _pipeline()
        with tempfile.TemporaryDirectory() as temp_dir:
            video = self._video(temp_dir)
            with patch.object(pipeline, "_initialize_video",
                              return_value=("s1", "v1", 0, 5)) as init, \
                    patch.object(pipeline, "_upload_chunks") as chunks, \
                    patch.object(pipeline, "_finish_video",
                                 return_value="published-9") as finish:
                result = pipeline.run(str(video), "caption",
                                      content_kind="video")

        self.assertEqual(result, "published-9")
        init.assert_called_once_with("page-1", "page-token", 5)
        chunks.assert_called_once()
        finish.assert_called_once()

    def test_run_rejects_an_unknown_content_kind(self):
        pipeline = _pipeline()
        with self.assertRaisesRegex(ValueError,
                                    "Invalid Facebook content kind"):
            pipeline.run("video.mp4", "caption", content_kind="story")


class FacebookErrorTests(unittest.TestCase):
    def test_error_message_includes_the_api_code(self):
        pipeline = _pipeline()
        response = SimpleNamespace(
            reason="Forbidden",
            json=lambda: {"error": {"message": "Permission denied",
                                    "code": 200}})

        pipeline._enhance_error_message(response)

        self.assertIn("Permission denied", response.reason)
        self.assertIn("code=200", response.reason)

    def test_unsupported_extension_is_rejected_before_any_request(self):
        pipeline = _pipeline()
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "clip.gif"
            video.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError,
                                        "Unsupported video format"):
                pipeline._validate_video_file(str(video))


if __name__ == "__main__":
    unittest.main()
