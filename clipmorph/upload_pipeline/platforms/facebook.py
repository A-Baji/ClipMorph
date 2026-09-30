import mimetypes
import os

import requests

from .base import BaseUploadPipeline


class FacebookUploadPipeline(BaseUploadPipeline):
    """Direct-multipart Facebook Page Reels and Page video uploads.

    Facebook shares Instagram's Meta app and Page token, so this adapter has no
    credential block of its own: it reads the same ``FACEBOOK_*`` environment
    keys Instagram populates (see ``docs/AUTHENTICATION.md``). Transport only:
    the post text arrives already composed and bounded by
    ``clipmorph.policy``.

    ``content_kind`` selects the endpoint family. ``"reel"`` drives the
    two-phase ``/{page_id}/video_reels`` flow (start, binary upload to the
    returned ``rupload`` URL, finish with ``video_state``); ``"video"`` drives
    the resumable ``/{page_id}/videos`` flow (start, chunked transfer, finish).
    Both publish immediately; existing-post detection is not implemented in
    v1, consistent with the other direct-post adapters.
    """

    # Graph endpoints (VERIFY: resolved against Meta Graph API v23.0 docs).
    FACEBOOK_GRAPH_BASE_URL = "https://graph.facebook.com"
    FACEBOOK_RUPLOAD_BASE_URL = "https://rupload.facebook.com"

    CONTENT_KINDS = ("reel", "video")
    # VERIFY: Meta accepts mp4, mov, mkv, avi, and wmv for Reels and Page
    # videos; H.264/HEVC is the codec guidance the capability rule records.
    VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".wmv")

    def __init__(self,
                 facebook_app_id=None,
                 facebook_app_secret=None,
                 facebook_page_id=None,
                 facebook_access_token=None,
                 api_version="v23.0",
                 request_timeout=30,
                 upload_timeout=600):
        """Initialize the Facebook upload pipeline.

        Args:
            facebook_app_id (str, optional): Meta App ID. Defaults to
                ``FACEBOOK_APP_ID``.
            facebook_app_secret (str, optional): Meta App Secret. Defaults to
                ``FACEBOOK_APP_SECRET``.
            facebook_page_id (str, optional): Page id to publish to. Defaults
                to ``FACEBOOK_PAGE_ID``.
            facebook_access_token (str, optional): Page access token. Defaults
                to ``FACEBOOK_ACCESS_TOKEN``.
            api_version (str, optional): Graph API version. Defaults to
                ``v23.0``, matching the shared Meta app.
            request_timeout (int, optional): Timeout for control requests.
            upload_timeout (int, optional): Timeout for the binary transfer.
        """
        # Facebook/Meta credentials shared with the Instagram adapter.
        self.app_id = (facebook_app_id if facebook_app_id is not None else
                       os.getenv("FACEBOOK_APP_ID"))
        self.app_secret = (facebook_app_secret if facebook_app_secret is not None
                           else os.getenv("FACEBOOK_APP_SECRET"))
        self.page_id = (facebook_page_id if facebook_page_id is not None else
                        os.getenv("FACEBOOK_PAGE_ID"))
        self.access_token = (facebook_access_token
                             if facebook_access_token is not None else
                             os.getenv("FACEBOOK_ACCESS_TOKEN"))

        # Configuration
        self.api_version = api_version
        self.request_timeout = request_timeout
        self.upload_timeout = upload_timeout

        # Progress bar configuration (initialize / transfer / publish split,
        # mirroring the other direct-upload adapters).
        self.progress_allocations = {
            "authenticate": 5,  # 5%
            "validate_file": 5,  # 5%
            "initialize_upload": 15,  # 15%
            "video_upload": 70,  # 70%
            "publish": 5,  # 5%
        }
        self.progress_bar = None

        # Set platform name for base class
        self.platform_name = "Facebook"

        # Initialize base class
        super().__init__()

        # Validate required credentials
        if not all([self.app_id, self.app_secret, self.page_id,
                    self.access_token]):
            raise ValueError(
                "Missing required Facebook credentials. Provide them as "
                "parameters or set the shared Meta variables: FACEBOOK_APP_ID, "
                "FACEBOOK_APP_SECRET, FACEBOOK_PAGE_ID, FACEBOOK_ACCESS_TOKEN")

        # Validate base class requirements
        self._validate_required_attributes()

    def _enhance_error_message(self, response):
        """Facebook-specific error message enhancement."""
        try:
            error = response.json().get("error", {})
            message = error.get("message", "")
            if message:
                response.reason = f"{response.reason}: {message}"
            code = error.get("code")
            if code is not None:
                response.reason = f"{response.reason} (code={code})"
        except Exception:
            pass

    def _validate_video_file(self, video_path: str) -> int:
        """Validate the local video before opening an upload session."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        file_size = os.path.getsize(video_path)
        if file_size <= 0:
            raise ValueError(f"Video file is empty: {video_path}")

        file_ext = os.path.splitext(video_path)[1].lower()
        if file_ext not in self.VIDEO_EXTENSIONS:
            raise ValueError(
                f"Unsupported video format: {file_ext}. "
                f"Supported formats: {', '.join(self.VIDEO_EXTENSIONS)}")

        self._update_progress("validate_file", "Video file validated")
        return file_size

    def _media_type(self, video_path: str) -> str:
        return mimetypes.guess_type(video_path)[0] or "video/mp4"

    def _initialize_reel(self, page_id: str, access_token: str) -> tuple[str, str]:
        """Open a Reels upload session and return ``(video_id, upload_url)``."""
        url = (f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/"
               f"{page_id}/video_reels")
        response = self._retry_request(
            requests.post,
            url,
            data={"upload_phase": "start", "access_token": access_token},
            timeout=self.request_timeout)
        payload = response.json()
        video_id = payload.get("video_id")
        upload_url = payload.get("upload_url")
        if not video_id or not upload_url:
            raise RuntimeError(
                "Failed to initialize Facebook reel upload: "
                "no upload session returned")
        self._update_progress("initialize_upload", "Reel upload initialized")
        return str(video_id), str(upload_url)

    def _initialize_video(self, page_id: str, access_token: str,
                          file_size: int) -> tuple[str, str, int, int]:
        """Open a resumable Page video session.

        Returns ``(upload_session_id, video_id, start_offset, end_offset)``.
        """
        url = (f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/"
               f"{page_id}/videos")
        response = self._retry_request(
            requests.post,
            url,
            data={"upload_phase": "start", "file_size": file_size,
                  "access_token": access_token},
            timeout=self.request_timeout)
        payload = response.json()
        session_id = payload.get("upload_session_id")
        if not session_id:
            raise RuntimeError(
                "Failed to initialize Facebook video upload: "
                "no upload session returned")
        self._update_progress("initialize_upload", "Video upload initialized")
        return (str(session_id), str(payload.get("video_id") or ""),
                int(payload.get("start_offset", 0)),
                int(payload.get("end_offset", file_size)))

    def _upload_reel(self, video_path: str, upload_url: str,
                     access_token: str, file_size: int) -> None:
        """Stream the reel binary to the session's ``rupload`` URL."""
        headers = {
            "Authorization": f"OAuth {access_token}",
            "offset": "0",
            "file_size": str(file_size),
            "Content-Type": self._media_type(video_path),
        }

        def upload_stream():
            # Reopen the stream for each retry so a failed request starts at
            # byte zero (the reels upload is a single bounded transfer).
            with open(video_path, "rb") as video_stream:
                return requests.post(upload_url, data=video_stream,
                                     headers=headers,
                                     timeout=self.upload_timeout)

        self._retry_request(upload_stream)
        self._update_progress("video_upload", "Reel uploaded")

    def _upload_chunks(self, video_path: str, page_id: str, access_token: str,
                       session_id: str, start_offset: int, end_offset: int,
                       file_size: int) -> None:
        """Transfer the resumable Page video in the windows Meta returns."""
        url = (f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/"
               f"{page_id}/videos")
        media_type = self._media_type(video_path)
        offset, end = start_offset, end_offset
        uploaded = 0

        with open(video_path, "rb") as video_stream:
            while end > offset:
                length = end - offset
                video_stream.seek(offset)
                chunk = video_stream.read(length)

                def transfer(chunk=chunk, offset=offset):
                    return requests.post(
                        url,
                        data={"upload_phase": "transfer",
                              "upload_session_id": session_id,
                              "start_offset": offset,
                              "access_token": access_token},
                        files={"video_file_chunk": (
                            os.path.basename(video_path), chunk, media_type)},
                        timeout=self.upload_timeout)

                response = self._retry_request(transfer)
                payload = response.json()
                uploaded += len(chunk)
                next_offset = int(payload.get("start_offset", offset + len(chunk)))
                next_end = int(payload.get("end_offset", file_size))
                if next_offset <= offset:
                    # Guard against a stalled session: stop rather than loop.
                    break
                offset, end = next_offset, next_end
                if self.progress_bar and file_size:
                    self.progress_bar.set_description(
                        f"[Facebook] Uploading video... "
                        f"({uploaded * 100 // file_size}%)")

        self._update_progress("video_upload", "Video uploaded")

    def _finish_reel(self, video_id: str, page_id: str, access_token: str,
                     description: str, video_state: str,
                     content_tags) -> str:
        """Publish the uploaded reel and return its id."""
        url = (f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/"
               f"{page_id}/video_reels")
        data = {
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": video_state,
            "description": description,
            "access_token": access_token,
        }
        tags = self._format_content_tags(content_tags)
        if tags:
            data["content_tags"] = tags
        self._retry_request(requests.post, url, data=data,
                            timeout=self.request_timeout)
        self._update_progress("publish", "Reel published")
        return video_id

    def _finish_video(self, session_id: str, page_id: str, access_token: str,
                      description: str, video_id: str, content_tags) -> str:
        """Close the upload session and publish the Page video."""
        url = (f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/"
               f"{page_id}/videos")
        data = {
            "upload_phase": "finish",
            "upload_session_id": session_id,
            "description": description,
            "access_token": access_token,
        }
        tags = self._format_content_tags(content_tags)
        if tags:
            data["content_tags"] = tags
        response = self._retry_request(requests.post, url, data=data,
                                       timeout=self.request_timeout)
        payload = response.json()
        self._update_progress("publish", "Video published")
        return str(payload.get("id") or video_id)

    @staticmethod
    def _format_content_tags(content_tags) -> str:
        if not content_tags:
            return ""
        if isinstance(content_tags, str):
            return content_tags
        return ",".join(str(tag) for tag in content_tags)

    def run(self,
            video_path: str,
            description: str,
            content_kind: str = "reel",
            page_id: str | None = None,
            access_token: str | None = None,
            content_tags=None,
            video_state: str = "PUBLISHED"):
        """Upload one video to a Facebook Page as a Reel or a Page video.

        Args:
            video_path (str): Local video to upload.
            description (str): Composed post text from ``clipmorph.policy``.
            content_kind (str, optional): ``"reel"`` (default) or ``"video"``.
            page_id (str, optional): Override the configured Page id.
            access_token (str, optional): Override the configured Page token.
            content_tags (list | str, optional): Tagged Page ids.
            video_state (str, optional): Reel finish state (default
                ``PUBLISHED``; ``DRAFT`` is also accepted by the API).

        Returns:
            str: The published video id.
        """
        if content_kind not in self.CONTENT_KINDS:
            raise ValueError(
                f"Invalid Facebook content kind: {content_kind}. "
                f"Must be one of: {', '.join(self.CONTENT_KINDS)}")

        page = page_id or self.page_id
        token = access_token or self.access_token
        if not page or not token:
            raise ValueError(
                "Facebook upload requires a page id and access token")

        total_progress = sum(self.progress_allocations.values())
        result_id = None

        with self._progress_context(total_progress, "Starting upload"):
            try:
                self._update_progress(
                    "authenticate", "Using shared Meta Page token")
                file_size = self._validate_video_file(video_path)

                if content_kind == "reel":
                    video_id, upload_url = self._initialize_reel(page, token)
                    self._upload_reel(video_path, upload_url, token, file_size)
                    result_id = self._finish_reel(
                        video_id, page, token, description, video_state,
                        content_tags)
                else:
                    session_id, video_id, start_offset, end_offset = (
                        self._initialize_video(page, token, file_size))
                    self._upload_chunks(
                        video_path, page, token, session_id, start_offset,
                        end_offset, file_size)
                    result_id = self._finish_video(
                        session_id, page, token, description, video_id,
                        content_tags)

                self._complete_progress_bar(True)

            except Exception:
                self._complete_progress_bar(False)
                raise

        return result_id
