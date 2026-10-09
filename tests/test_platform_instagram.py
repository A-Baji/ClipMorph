"""Instagram Reels adapter behavior with mocked HTTP.

The network seam is ``clipmorph.upload_pipeline.platforms.instagram.requests``
and the scheduling seam is the module's ``time`` binding, mirroring the
Facebook adapter suite: every case patches the HTTP call (and, for the polling
loop, a fake clock) and asserts the Graph API phase, payload, cadence, and
returned identifier without touching the network or sleeping for real.

Instagram publishes through Meta's resumable upload — a resumable container
plus a raw-bytes ``rupload`` transfer — so there is no Google Cloud Storage
staging surface to mock or clean up.
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from clipmorph.upload_pipeline.platforms.instagram import (
    InstagramUploadPipeline,
)

GET = "clipmorph.upload_pipeline.platforms.instagram.requests.get"
POST = "clipmorph.upload_pipeline.platforms.instagram.requests.post"
TIME = "clipmorph.upload_pipeline.platforms.instagram.time"
GRAPH_BASE = "https://graph.facebook.com"
RUPLOAD_BASE = "https://rupload.facebook.com/ig-api-upload"


def _response(payload):
    return SimpleNamespace(status_code=200, ok=True, reason="OK",
                           text="", json=lambda: payload)


def _pipeline(**kwargs):
    return InstagramUploadPipeline(
        facebook_app_id="app-id",
        facebook_app_secret="app-secret",
        facebook_page_id="page-1",
        facebook_access_token="page-token",
        **kwargs)


def _video(temp_dir, data=b"video-bytes"):
    path = Path(temp_dir) / "clip.mp4"
    path.write_bytes(data)
    return path


class _FakeClock:
    """A monotonic clock whose ``sleep`` advances the same time ``time`` reads.

    The polling loop schedules the next check from ``time.time`` and waits with
    ``time.sleep``; tying both to one counter keeps the schedule deterministic
    and instant.
    """

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _status_recorder(clock, statuses):
    """Return a ``requests.get`` side effect recording poll times.

    Each call appends ``clock.now`` and answers with the next status in
    ``statuses`` (clamped to the final one), so a test can both pin the cadence
    and drive the loop to a terminal state. A bare status string is wrapped
    into the container payload; a full payload dict passes through as-is.
    """
    poll_times = []

    def get(*args, **kwargs):
        poll_times.append(clock.now)
        index = min(len(poll_times) - 1, len(statuses) - 1)
        payload = statuses[index]
        if isinstance(payload, str):
            payload = {"status_code": payload, "id": "container-1"}
        return _response(payload)

    return get, poll_times


class InstagramCredentialTests(unittest.TestCase):
    def test_missing_meta_credentials_raise_a_clear_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError,
                                        "Missing required Facebook credentials"):
                InstagramUploadPipeline()

    def test_only_meta_credentials_are_required(self):
        """No GCS/GCP hosting surface survives on the adapter."""
        pipeline = _pipeline()
        for name in ("_authenticate_google", "_delete_video",
                     "gcs_bucket_name", "gcp_private_key",
                     "gcp_private_key_id", "gcp_client_email",
                     "gcp_client_id", "gcp_project_id"):
            self.assertFalse(hasattr(pipeline, name), name)


class InstagramPollingTests(unittest.TestCase):
    """A1/A2: terminal states, tiered cadence, and the hard wait cap."""

    def setUp(self):
        self.pipeline = _pipeline()
        self.pipeline.page_token = "page-token"

    def _wait(self, clock, statuses):
        get, poll_times = _status_recorder(clock, statuses)
        with patch(TIME, clock), patch(GET, side_effect=get):
            result = self.pipeline._wait_for_processing("container-1",
                                                        video_size_mb=1)
        return result, poll_times

    def test_first_poll_is_immediate_second_at_15s_then_60s_cadence(self):
        clock = _FakeClock()
        result, poll_times = self._wait(
            clock, ["IN_PROGRESS", "IN_PROGRESS", "IN_PROGRESS", "FINISHED"])

        self.assertTrue(result)
        self.assertEqual(poll_times, [0, 15, 75, 135])

    def test_finished_is_a_success_terminal(self):
        clock = _FakeClock()
        result, poll_times = self._wait(clock, ["FINISHED"])

        self.assertTrue(result)
        self.assertEqual(poll_times, [0])

    def test_published_is_a_success_terminal(self):
        clock = _FakeClock()
        result, poll_times = self._wait(clock, ["PUBLISHED"])

        self.assertTrue(result)
        self.assertEqual(poll_times, [0])

    def test_expired_raises_an_expiry_error_not_a_timeout(self):
        clock = _FakeClock()
        get, _ = _status_recorder(clock, ["EXPIRED"])
        with patch(TIME, clock), patch(GET, side_effect=get):
            with self.assertRaises(RuntimeError) as caught:
                self.pipeline._wait_for_processing("container-1",
                                                   video_size_mb=1)

        self.assertNotIsInstance(caught.exception, TimeoutError)
        self.assertIn("expired", str(caught.exception))
        self.assertIn("24 hours", str(caught.exception))

    def test_wait_cap_raises_a_dedicated_timeout_after_terminal_checks(self):
        clock = _FakeClock()
        get, poll_times = _status_recorder(clock, ["IN_PROGRESS"])
        with patch(TIME, clock), patch(GET, side_effect=get):
            with self.assertRaises(TimeoutError):
                self.pipeline._wait_for_processing("container-1",
                                                   video_size_mb=1)

        # The cap fires at 480s, after the last scheduled 60s poll at 435s.
        self.assertEqual(clock.now, 480)
        self.assertEqual(poll_times, [0, 15, 75, 135, 195, 255, 315, 375, 435])
        # The derived pacing stays bounded and terminates under the cadence.
        self.assertLessEqual(self.pipeline._percent,
                             self.pipeline.MAX_PROGRESS_DURING_PROCESSING)


class InstagramErrorTests(unittest.TestCase):
    """A4: a failed container is reported from the response, never a guess."""

    def test_error_with_no_detail_surfaces_the_raw_response_and_reference(self):
        pipeline = _pipeline()
        pipeline.page_token = "page-token"
        clock = _FakeClock()
        get, _ = _status_recorder(clock, [{"status_code": "ERROR",
                                           "id": "container-1"}])
        with patch(TIME, clock), patch(GET, side_effect=get):
            with self.assertRaises(RuntimeError) as caught:
                pipeline._wait_for_processing("container-1", video_size_mb=1)

        message = str(caught.exception)
        self.assertIn("{'status_code': 'ERROR', 'id': 'container-1'}", message)
        self.assertIn(pipeline.ERROR_CODES_REFERENCE, message)

    def test_error_with_no_detail_never_emits_the_speculative_cause_list(self):
        pipeline = _pipeline()
        pipeline.page_token = "page-token"
        clock = _FakeClock()
        get, _ = _status_recorder(clock, [{"status_code": "ERROR",
                                           "id": "container-1"}])
        with patch(TIME, clock), patch(GET, side_effect=get):
            with self.assertRaises(RuntimeError) as caught:
                pipeline._wait_for_processing("container-1", video_size_mb=1)

        message = str(caught.exception)
        self.assertNotIn("Common causes", message)
        self.assertNotIn("unsupported video format", message)

    def test_error_with_detail_reports_the_message_and_code(self):
        pipeline = _pipeline()
        pipeline.page_token = "page-token"
        clock = _FakeClock()
        get, _ = _status_recorder(clock, [
            {"status_code": "ERROR", "id": "container-1",
             "error": {"message": "Video upload failed", "code": 352}}])
        with patch(TIME, clock), patch(GET, side_effect=get):
            with self.assertRaises(RuntimeError) as caught:
                pipeline._wait_for_processing("container-1", video_size_mb=1)

        message = str(caught.exception)
        self.assertIn("Video upload failed", message)
        self.assertIn("Code: 352", message)


class InstagramResumableUploadTests(unittest.TestCase):
    """Meta's resumable path replaces the GCS staging round trip."""

    def setUp(self):
        self.pipeline = _pipeline()
        self.pipeline.page_token = "page-token"
        self.pipeline.ig_user_id = "ig-1"

    def test_container_creation_requests_a_resumable_reel(self):
        with patch(POST, return_value=_response({"id": "container-1"})) as post:
            container_id = self.pipeline._create_reel_container(
                "caption", share_to_feed=False, thumb_offset=1500,
                is_ai_generated=True)

        self.assertEqual(container_id, "container-1")
        self.assertEqual(post.call_args.args[0],
                         f"{GRAPH_BASE}/v23.0/ig-1/media")
        data = post.call_args.kwargs["data"]
        self.assertEqual(data["upload_type"], "resumable")
        self.assertEqual(data["media_type"], "REELS")
        self.assertEqual(data["access_token"], "page-token")
        self.assertEqual(data["share_to_feed"], "false")
        self.assertEqual(data["thumb_offset"], "1500")
        self.assertEqual(data["is_ai_generated"], "true")
        # The resumable path never hands Meta a public URL.
        self.assertNotIn("video_url", data)

    def test_upload_streams_bytes_to_the_meta_rupload_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = _video(temp_dir)
            size = video.stat().st_size
            with patch(POST, return_value=_response({"success": True})) as post:
                self.pipeline._upload_video("container-1", str(video))

        self.assertEqual(
            post.call_args.args[0],
            f"{RUPLOAD_BASE}/v23.0/container-1")
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "OAuth page-token")
        self.assertEqual(headers["offset"], "0")
        self.assertEqual(headers["file_size"], str(size))
        request_data = post.call_args.kwargs["data"]
        self.assertTrue(hasattr(request_data, "read"))

    def test_missing_video_file_raises_before_any_request(self):
        with patch(POST) as post:
            with self.assertRaises(FileNotFoundError):
                self.pipeline._upload_video("container-1", "missing.mp4")

        post.assert_not_called()

    def test_mid_transfer_failure_surfaces_after_exhausting_retries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = _video(temp_dir)
            with patch(POST, side_effect=requests.exceptions.ConnectionError(
                    "connection reset")) as post, patch("time.sleep"):
                with self.assertRaises(requests.exceptions.ConnectionError):
                    self.pipeline._upload_video("container-1", str(video))

        self.assertEqual(post.call_count, self.pipeline.MAX_RETRIES)


class InstagramRunFlowTests(unittest.TestCase):
    """Success path still creates, uploads, polls, and publishes."""

    def test_success_path_reaches_poll_and_publish(self):
        pipeline = _pipeline()
        pipeline.page_token = "page-token"
        pipeline.ig_user_id = "ig-1"
        posts = [
            _response({"id": "container-1"}),  # create resumable container
            _response({"success": True}),      # rupload binary transfer
            _response({"id": "media-1"}),      # media_publish
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            video = _video(temp_dir)
            with patch(POST, side_effect=posts) as post, \
                    patch(GET, return_value=_response(
                        {"status_code": "FINISHED"})):
                result = pipeline.run(str(video), "caption")

        self.assertEqual(result, "media-1")
        start, binary, publish = post.call_args_list
        self.assertEqual(start.args[0], f"{GRAPH_BASE}/v23.0/ig-1/media")
        self.assertEqual(start.kwargs["data"]["upload_type"], "resumable")
        self.assertEqual(binary.args[0], f"{RUPLOAD_BASE}/v23.0/container-1")
        self.assertEqual(binary.kwargs["headers"]["Authorization"],
                         "OAuth page-token")
        self.assertEqual(publish.kwargs["data"]["creation_id"], "container-1")


class InstagramAiDisclosureTests(unittest.TestCase):
    """A5: ``is_ai_generated`` is opt-in and omitted by default."""

    def setUp(self):
        self.pipeline = _pipeline()
        self.pipeline.ig_user_id = "ig-1"
        self.pipeline.page_token = "page-token"

    def _container_data(self, **kwargs):
        with patch(POST, return_value=_response({"id": "container-1"})) as post:
            self.pipeline._create_reel_container("caption", **kwargs)
        return post.call_args.kwargs["data"]

    def test_disclosure_is_omitted_by_default(self):
        data = self._container_data()

        self.assertNotIn("is_ai_generated", data)

    def test_disclosure_is_sent_as_a_string_when_enabled(self):
        data = self._container_data(is_ai_generated=True)

        self.assertEqual(data["is_ai_generated"], "true")

    def test_run_forwards_the_disclosure_flag_to_the_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = _video(temp_dir)
            with patch.object(self.pipeline, "_upload_video"), \
                    patch.object(self.pipeline, "_get_page_access_token"), \
                    patch.object(self.pipeline, "_get_ig_user_id"), \
                    patch.object(self.pipeline, "_create_reel_container",
                                 return_value="container-1") as create, \
                    patch.object(self.pipeline, "_wait_for_processing",
                                 return_value=True), \
                    patch.object(self.pipeline, "_publish_media",
                                 return_value="media-1"):
                result = self.pipeline.run(str(video), "caption",
                                           is_ai_generated=True)

        self.assertEqual(result, "media-1")
        create.assert_called_once()
        self.assertIs(create.call_args.args[3], True)


if __name__ == "__main__":
    unittest.main()
