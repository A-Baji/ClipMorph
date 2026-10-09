import logging
import mimetypes
import os
import time
import webbrowser

import requests

from .base import BaseUploadPipeline


class InstagramUploadPipeline(BaseUploadPipeline):
    """
    A pipeline class for handling Instagram Reels uploads, including
    authentication and Meta's resumable container upload.
    """

    # Constants
    FACEBOOK_GRAPH_BASE_URL = "https://graph.facebook.com"
    FACEBOOK_AUTH_BASE_URL = "https://www.facebook.com"
    # Meta's resumable video host. The container id returned by the Graph
    # `/media` call forms the upload path, so a render is streamed straight
    # from disk with no publicly reachable URL (and no external object
    # storage) in between.
    INSTAGRAM_RUPLOAD_BASE_URL = "https://rupload.facebook.com"

    # Video processing constants
    DEFAULT_PROCESSING_TIME_PER_MB = 20  # seconds
    MIN_PROCESSING_TIME = 30  # seconds
    MAX_PROGRESS_DURING_PROCESSING = 80  # don't complete progress bar during processing
    # Tiered status polling: check immediately, again shortly after to catch a
    # fast encode, then on Meta's recommended once-per-minute cadence.
    API_FIRST_POLL_DELAY = 0  # first check fires immediately
    API_SECOND_POLL_DELAY = 15  # seconds before the second check
    API_POLL_INTERVAL = 60  # seconds between later checks
    MIN_PROGRESS_INCREMENT = 1.5
    # Meta's error-codes reference, surfaced when a container fails without a
    # usable detail instead of guessing a cause.
    ERROR_CODES_REFERENCE = (
        "https://developers.facebook.com/documentation/instagram-platform/"
        "instagram-graph-api/reference/error-codes")

    def __init__(self,
                 facebook_app_id=os.getenv("FACEBOOK_APP_ID"),
                 facebook_app_secret=os.getenv("FACEBOOK_APP_SECRET"),
                 facebook_page_id=os.getenv("FACEBOOK_PAGE_ID"),
                 facebook_access_token=os.getenv("FACEBOOK_ACCESS_TOKEN"),
                 facebook_config_id=os.getenv("FACEBOOK_CONFIG_ID"),
                 redirect_uri='https://localhost/',
                 api_version='v23.0',
                 request_timeout=30,
                 upload_timeout=600,
                 processing_timeout=480,
                 auth_scopes=[
                     'instagram_basic', 'pages_show_list',
                     'pages_read_engagement', 'pages_manage_posts',
                     'instagram_content_publish'
                 ]):
        """Initialize the Instagram upload pipeline.

        Args:
            facebook_app_id (str, optional): Facebook App ID for authentication.
                Defaults to FACEBOOK_APP_ID environment variable.
            facebook_app_secret (str, optional): Facebook App Secret for authentication.
                Defaults to FACEBOOK_APP_SECRET environment variable.
            facebook_page_id (str, optional): Facebook Page ID linked to Instagram account.
                Defaults to FACEBOOK_PAGE_ID environment variable.
            facebook_access_token (str, optional): Facebook Access Token for API calls.
                Defaults to FACEBOOK_ACCESS_TOKEN environment variable.
            facebook_config_id (str, optional): Facebook Login for Business
                Configuration ID. Defaults to FACEBOOK_CONFIG_ID environment
                variable. When set it replaces the scope list in the login
                dialog URL (docs/AUTHENTICATION.md, Meta FL4B).
            redirect_uri (str, optional): OAuth redirect URI.
                Defaults to 'https://localhost/'.
            api_version (str, optional): Graph API version. Defaults to
                'v23.0'.
            request_timeout (int, optional): Timeout for HTTP requests in seconds.
                Defaults to 30 seconds.
            upload_timeout (int, optional): Timeout for the binary resumable
                transfer in seconds. Defaults to 600 seconds, matching the
                Facebook adapter's transfer bound.
            processing_timeout (int, optional): Timeout for video processing in seconds.
                Defaults to 480 seconds.
            auth_scopes (list, optional): List of Facebook authentication scopes.
                Defaults to basic Instagram and page management scopes.
        """
        # Facebook/Instagram credentials (the shared Meta app and user token)
        self.app_id = facebook_app_id
        self.app_secret = facebook_app_secret
        self.page_id = facebook_page_id
        self.access_token = facebook_access_token
        self.config_id = facebook_config_id

        # Authentication configuration
        self.redirect_uri = redirect_uri
        self.api_version = api_version
        self.auth_scopes = auth_scopes

        # Timeout configuration
        self.request_timeout = request_timeout
        self.upload_timeout = upload_timeout
        self.processing_timeout = processing_timeout

        # Runtime state
        self.page_token = None
        self.ig_user_id = None

        # Progress bar configuration (redistributed for smoother UX)
        self.progress_allocations = {
            "page_token": 3,  # 3%
            "ig_user_id": 3,  # 3%
            "create_container": 7,  # 7%
            "video_upload": 7,  # 7% - resumable binary transfer
            "video_processing": 70,  # 70% - spread over time
            "publish_media": 10,  # 10%
        }
        self.progress_bar = None

        # Set platform name for base class
        self.platform_name = "Instagram"

        # Initialize base class
        super().__init__()

        # Validate required credentials
        if not all([self.app_id, self.app_secret, self.page_id]):
            raise ValueError(
                "Missing required Facebook credentials. Provide them as parameters "
                "or set them as environment variables: FACEBOOK_APP_ID, "
                "FACEBOOK_APP_SECRET, FACEBOOK_PAGE_ID")

        # Validate base class requirements
        self._validate_required_attributes()

    def _enhance_error_message(self, response):
        """Instagram-specific error message enhancement."""
        try:
            error_data = response.json()
            api_error = error_data.get('error', {}).get('message', '')
            if api_error:
                response.reason = f"{response.reason}: {api_error}"
        except:  # noqa: E722 - preserve the original best-effort parsing
            pass

    def get_user_access_token(self):
        """
        Guides user through browser-based OAuth to obtain a user access token.
        """
        if self.config_id:
            # Facebook Login for Business: the Configuration (token type,
            # assets, permissions) grants the access, so the dialog is invoked
            # with config_id and scope is omitted entirely.
            login_params = f"config_id={self.config_id}"
        else:
            login_params = f"scope={','.join(self.auth_scopes)}"
        oauth_url = (
            f"{self.FACEBOOK_AUTH_BASE_URL}/{self.api_version}/dialog/oauth"
            f"?client_id={self.app_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&{login_params}"
            f"&response_type=code")
        print("Open this URL in your browser and authorize the app:")
        print(oauth_url)
        webbrowser.open(oauth_url)
        code = input(
            "Paste the 'code' parameter from the redirect URL here: ").strip()

        # Exchange code for access token
        token_url = (
            f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/oauth/access_token"
            f"?client_id={self.app_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&client_secret={self.app_secret}"
            f"&code={code}")
        resp = self._retry_request(requests.get,
                                   token_url,
                                   timeout=self.request_timeout)
        data = resp.json()
        return data['access_token']

    def _generate_long_lived_access_token(self):
        """Generates a long-lived access token from a short-lived one."""
        response = self._retry_request(
            requests.get,
            f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": self.get_user_access_token()
            },
            timeout=self.request_timeout)
        logging.info("Long-lived Instagram access token generated.")
        return response.json()["access_token"]

    def _get_page_access_token(self):
        """
        Exchanges a user access token for a page access token.
        """
        url = f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/{self.page_id}?fields=access_token&access_token={self.access_token}"
        resp = self._retry_request(requests.get,
                                   url,
                                   timeout=self.request_timeout)
        self.page_token = resp.json()['access_token']
        self._update_progress("page_token", "Got page access token")
        return self.page_token

    def _get_ig_user_id(self):
        """
        Gets the Instagram user ID connected to a Facebook Page.
        """
        if not self.page_token:
            self._get_page_access_token()

        url = f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/{self.page_id}?fields=instagram_business_account&access_token={self.page_token}"
        resp = self._retry_request(requests.get,
                                   url,
                                   timeout=self.request_timeout)
        self.ig_user_id = resp.json()['instagram_business_account']['id']
        self._update_progress("ig_user_id", "Got Instagram user ID")
        return self.ig_user_id

    @staticmethod
    def _media_type(video_path: str) -> str:
        return mimetypes.guess_type(video_path)[0] or "video/mp4"

    def _create_reel_container(self,
                               caption,
                               share_to_feed=True,
                               thumb_offset=None,
                               is_ai_generated=False):
        """Create a resumable Reels container and return its id.

        ``upload_type=resumable`` is Meta's documented local-file path: the
        response's container id forms the ``rupload`` URL the bytes are
        streamed to in :meth:`_upload_video`, so no publicly reachable video
        URL is required.
        """
        if not self.ig_user_id:
            self._get_ig_user_id()

        url = f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/{self.ig_user_id}/media"
        payload = {
            'media_type': 'REELS',
            'upload_type': 'resumable',
            'caption': caption,
            'access_token': self.page_token,
            'share_to_feed': 'true' if share_to_feed else 'false',
        }
        if thumb_offset is not None:
            payload['thumb_offset'] = str(thumb_offset)
        if is_ai_generated:
            # Meta's AI-content self-disclosure flag. Omitted entirely when
            # false, which is Meta's documented default; sent as the same
            # form-encoded string the other boolean options use.
            payload['is_ai_generated'] = 'true'
        resp = self._retry_request(requests.post,
                                   url,
                                   data=payload,
                                   timeout=self.request_timeout)
        self._update_progress("create_container", "Created reel container")
        return resp.json()['id']

    def _upload_video(self, container_id, video_path):
        """Stream the local video bytes to Meta's resumable upload host.

        Meta's resumable upload takes the raw bytes at
        ``/ig-api-upload/<API_VERSION>/<CONTAINER_ID>`` with ``offset`` and
        ``file_size`` headers, replacing the previous Cloud Storage staging
        path. The stream is reopened per attempt so a retried transfer starts
        at byte zero, matching the Facebook adapter's reel transfer.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        file_size = os.path.getsize(video_path)
        upload_url = (f"{self.INSTAGRAM_RUPLOAD_BASE_URL}/ig-api-upload/"
                      f"{self.api_version}/{container_id}")
        headers = {
            "Authorization": f"OAuth {self.page_token}",
            "offset": "0",
            "file_size": str(file_size),
            "Content-Type": self._media_type(video_path),
        }

        def upload_stream():
            # Reopen the stream for each retry so a failed request starts at
            # byte zero (the resumable upload is a single bounded transfer).
            with open(video_path, "rb") as video_stream:
                return requests.post(upload_url,
                                     data=video_stream,
                                     headers=headers,
                                     timeout=self.upload_timeout)

        self._retry_request(upload_stream)
        self._update_progress("video_upload", "Video uploaded to Meta")

    def _publish_media(self, creation_id):
        """
        Publishes the media container to Instagram as a Reel.
        """
        # Update progress immediately when starting publish
        self._update_progress("publish_media", "Publishing reel to Instagram")

        if not self.ig_user_id:
            self._get_ig_user_id()

        url = f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/{self.ig_user_id}/media_publish"
        payload = {'creation_id': creation_id, 'access_token': self.page_token}
        resp = self._retry_request(requests.post,
                                   url,
                                   data=payload,
                                   timeout=self.request_timeout)

        if self.progress_bar:
            self.progress_bar.set_description("[Instagram] Published")
        return resp.json()['id']

    def _processing_error_message(self, media_status):
        """Describe a failed container from the response, never a guess.

        Meta returns structured error payloads, so a failed container is
        reported from what the response actually contained. When it carried no
        usable detail the raw response is surfaced verbatim and the reader is
        pointed at Meta's error-codes reference instead of a speculative cause
        list.
        """
        details = []
        error_info = media_status.get('error')
        if isinstance(error_info, dict):
            if error_info.get('message'):
                details.append(str(error_info['message']))
            if error_info.get('code') is not None:
                details.append(f"Code: {error_info['code']}")
        elif error_info:
            details.append(str(error_info))
        if media_status.get('message'):
            details.append(str(media_status['message']))
        if media_status.get('error_type'):
            details.append(f"Type: {media_status['error_type']}")

        media_id = media_status.get('id', 'unknown')
        if details:
            return (f"Instagram video processing failed (ID: {media_id}): "
                    f"{' | '.join(details)}")
        return (f"Instagram video processing failed (ID: {media_id}). "
                f"Response: {media_status}. See Meta's error codes reference: "
                f"{self.ERROR_CODES_REFERENCE}")

    def _wait_for_processing(self, creation_id, video_size_mb=0):
        """
        Polls the media container status until it reaches a terminal state.

        The cadence follows Meta's guidance: the first check fires immediately,
        the second after ``API_SECOND_POLL_DELAY`` seconds to catch a fast
        encode, and every later check ``API_POLL_INTERVAL`` seconds apart. The
        wait is bounded by ``processing_timeout``; a container that never leaves
        ``IN_PROGRESS`` raises ``TimeoutError`` only after every terminal status
        has been checked, so a container that finished on the last poll is
        never misreported as a timeout.
        """
        url = f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/{creation_id}?fields=status_code&access_token={self.page_token}"
        start = time.time()
        next_poll_at = self.API_FIRST_POLL_DELAY
        poll_count = 0

        # Progress rate (percent per second) derived from the expected
        # processing time; the floor keeps the bar moving for small files. The
        # elapsed-based target is bounded by MAX_PROGRESS_DURING_PROCESSING, so
        # the pacing terminates with the loop under any cadence.
        estimated_time = max(
            self.MIN_PROCESSING_TIME,
            video_size_mb * self.DEFAULT_PROCESSING_TIME_PER_MB)
        progress_per_second = max(
            self.MIN_PROGRESS_INCREMENT,
            self.MAX_PROGRESS_DURING_PROCESSING / estimated_time)

        current_progress = (self.progress_bar.n if self.progress_bar
                            else self._progress_seen)
        status = None
        media_status = {}

        while True:
            elapsed = time.time() - start

            # Fetch the API status only when the next tier is due.
            if elapsed >= next_poll_at:
                resp = self._retry_request(requests.get, url, timeout=10)
                media_status = resp.json()
                status = media_status.get('status_code')
                poll_count += 1
                if poll_count == 1:
                    next_poll_at = self.API_SECOND_POLL_DELAY
                else:
                    next_poll_at = elapsed + self.API_POLL_INTERVAL

            # Progressive updates based on video size and elapsed time
            target_progress = current_progress + min(
                elapsed * progress_per_second,
                self.MAX_PROGRESS_DURING_PROCESSING)

            # Update the timer description
            if self.progress_bar:
                self.progress_bar.set_description(
                    f"[Instagram] Processing video... ({elapsed:.0f}s)")

            # Only update progress if we haven't reached the cap
            if self.progress_bar and self.progress_bar.n < target_progress and self.progress_bar.n < self.MAX_PROGRESS_DURING_PROCESSING:
                increment = min(
                    target_progress - self.progress_bar.n,
                    self.MAX_PROGRESS_DURING_PROCESSING - self.progress_bar.n)
                if increment > 0:
                    self.progress_bar.update(increment)
            else:
                # No bar of its own (the orchestrator owns one): report
                # through the callback so the shared bar still moves while
                # Instagram is processing the reel.
                self._advance_progress(target_progress)

            # Terminal states. FINISHED is ready to publish; PUBLISHED is
            # already done; EXPIRED and ERROR are failures with their own
            # messages. Only IN_PROGRESS (or an absent status) keeps polling.
            if status == 'FINISHED':
                if self.progress_bar:
                    self.progress_bar.set_description(
                        "[Instagram] Publishing reel...")
                return True
            if status == 'PUBLISHED':
                if self.progress_bar:
                    self.progress_bar.set_description(
                        "[Instagram] Reel already published")
                return True
            if status == 'EXPIRED':
                media_id = media_status.get('id', 'unknown')
                raise RuntimeError(
                    f"Instagram container expired before it was published "
                    f"(ID: {media_id}). A container must be published within "
                    "24 hours of creation; create it again and publish "
                    "promptly.")
            if status == 'ERROR':
                raise RuntimeError(self._processing_error_message(media_status))

            # Check the wait cap only after every terminal status above, so a
            # container that finished on the last poll is never reported as a
            # timeout.
            if elapsed >= self.processing_timeout:
                raise TimeoutError(
                    "Timed out waiting for Instagram video processing.")

            # Sleep exactly until the next poll (or the cap, whichever comes
            # first) instead of spinning every second between checks.
            wait = min(next_poll_at, self.processing_timeout) - elapsed
            if wait > 0:
                time.sleep(wait)

    def run(self,
            video_path,
            caption: str,
            share_to_feed: bool = True,
            thumb_offset: "int | None" = None,
            is_ai_generated: bool = False):
        """
        Main method to handle the complete Instagram Reels upload process.

        Args:
            video_path (str): Path to the video file to upload
            caption (str): Caption for the Instagram Reel
            share_to_feed (bool, optional): Whether to share the reel to the main feed.
                Defaults to True.
            thumb_offset (int, optional): Thumbnail offset in milliseconds.
                Defaults to None (auto-generated).
            is_ai_generated (bool, optional): Self-disclose that the reel was
                created with AI. Defaults to False, which omits the field.

        Returns:
            str: Media ID of the uploaded reel
        """
        # Get video file size for progress estimation
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        video_size_mb = os.path.getsize(video_path) / (1024 * 1024)

        total_progress = sum(self.progress_allocations.values())
        upload_success = False
        media_id = None
        failure_reason = None

        with self._progress_context(total_progress, "Starting upload"):
            try:
                # Resolve the shared Meta token and the Instagram identity
                if not self.access_token:
                    self._bar_write(
                        "[Instagram] No access token found. Starting OAuth flow..."
                    )
                    self.access_token = self._generate_long_lived_access_token(
                    )
                    self._bar_write(
                        "\nInstagram access token generated. Store it securely in "
                        "FACEBOOK_ACCESS_TOKEN; it is not displayed by ClipMorph.\n")

                if not self.page_token:
                    self._get_page_access_token()

                if not self.ig_user_id:
                    self._get_ig_user_id()

                # Create the resumable container, then stream the bytes to
                # Meta's upload host (no public URL or object storage needed).
                creation_id = self._create_reel_container(
                    caption, share_to_feed, thumb_offset, is_ai_generated)
                self._upload_video(creation_id, video_path)

                try:
                    self._wait_for_processing(creation_id, video_size_mb=video_size_mb)
                    media_id = self._publish_media(creation_id)
                    upload_success = True
                except (TimeoutError, RuntimeError) as e:
                    failure_reason = str(e)
                except Exception as e:
                    failure_reason = f"Unexpected error during processing: {str(e)}"

                # Handle progress bar completion based on success/failure
                if upload_success:
                    self._complete_progress_bar(True)
                else:
                    self._complete_progress_bar(False)
                    error_msg = failure_reason or "Instagram upload failed during video processing or publishing"
                    raise RuntimeError(error_msg)

            except Exception:
                self._complete_progress_bar(False)
                raise

        return media_id
