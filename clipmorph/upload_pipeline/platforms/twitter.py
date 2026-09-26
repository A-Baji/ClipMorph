import logging
import mimetypes
import os
import time

import requests

from clipmorph.twitter_auth import authorize_twitter, refresh_twitter_access_token
from .base import BaseUploadPipeline


class TwitterUploadPipeline(BaseUploadPipeline):
    """
    A pipeline class for handling Twitter/X video uploads, including authentication,
    video upload management, and progress tracking.
    """

    # Constants
    TWITTER_API_BASE_URL = "https://api.x.com"
    TWITTER_UPLOAD_BASE_URL = "https://api.x.com/2/media/upload"
    MEDIA_CHUNK_SIZE = 5 * 1024 * 1024

    # Video processing constants
    DEFAULT_PROCESSING_TIME_PER_MB = 8  # seconds
    MIN_PROCESSING_TIME = 10  # seconds
    MAX_PROGRESS_DURING_PROCESSING = 80  # don't complete progress bar during processing
    API_POLL_INTERVAL = 5  # seconds between status checks
    MIN_PROGRESS_INCREMENT = 2.0

    def __init__(self,
                 twitter_client_id=None,
                 twitter_client_secret=None,
                 twitter_oauth2_access_token=None,
                 twitter_oauth2_refresh_token=None,
                 twitter_oauth2_expires_at=None,
                 data_dir=None,
                 request_timeout=30,
                 processing_timeout=300,
                 max_processing_retries=30):
        """Initialize the Twitter upload pipeline.
        
        Args:
            twitter_client_id (str, optional): X OAuth2 client ID.
            twitter_client_secret (str, optional): X OAuth2 client secret.
            twitter_oauth2_access_token (str, optional): X OAuth2 user token.
            twitter_oauth2_refresh_token (str, optional): X OAuth2 refresh token.
            twitter_oauth2_expires_at (str, optional): OAuth2 access-token expiry epoch.
            request_timeout (int, optional): Timeout for HTTP requests in seconds.
                Defaults to 30 seconds.
            processing_timeout (int, optional): Timeout for video processing in seconds.
                Defaults to 300 seconds.
            max_processing_retries (int, optional): Maximum retries for processing status checks.
                Defaults to 30 retries.
        """
        # Twitter credentials
        self.client_id = twitter_client_id or os.getenv("TWITTER_CLIENT_ID")
        self.client_secret = twitter_client_secret or os.getenv("TWITTER_CLIENT_SECRET")
        self.access_token = (twitter_oauth2_access_token or
                     os.getenv("TWITTER_OAUTH2_ACCESS_TOKEN"))
        self.refresh_token = (twitter_oauth2_refresh_token or
                      os.getenv("TWITTER_OAUTH2_REFRESH_TOKEN"))
        expiry = twitter_oauth2_expires_at or os.getenv("TWITTER_OAUTH2_EXPIRES_AT")
        self.expires_at = int(expiry) if expiry and str(expiry).isdigit() else 0
        self.data_dir = data_dir

        # Configuration
        self.request_timeout = request_timeout
        self.processing_timeout = processing_timeout
        self.max_processing_retries = max_processing_retries

        # Runtime state
        self.client = None
        self.oauth_session = None

        # Progress bar configuration
        self.progress_allocations = {
            "authenticate": 5,  # 5%
            "validate_file": 5,  # 5%
            "media_upload": 20,  # 20%
            "video_processing": 60,  # 60% - spread over time
            "create_tweet": 10  # 10%
        }
        self.progress_bar = None

        # Set platform name for base class
        self.platform_name = "Twitter"

        # Initialize base class
        super().__init__()

        # Validate required credentials
        if not all([self.client_id, self.client_secret]):
            raise ValueError(
            "Missing X OAuth2 client credentials. Provide TWITTER_CLIENT_ID "
            "and TWITTER_CLIENT_SECRET or run `clipmorph auth twitter`.")

        # Validate base class requirements
        self._validate_required_attributes()

    def _enhance_error_message(self, response):
        """Twitter-specific error message enhancement."""
        try:
            error_data = response.json()
            # Twitter uses 'errors' array format
            api_error = error_data.get('errors', [{}])[0].get('message', '')
            if not api_error and isinstance(error_data.get('error'), dict):
                api_error = error_data['error'].get('detail', '')
                reason = error_data['error'].get('reason', '')
                if reason:
                    api_error = f"{api_error} ({reason})"
            if not api_error:
                api_error = error_data.get('detail', '')
            if api_error:
                response.reason = f"{response.reason}: {api_error}"
        except:
            pass

    def _authenticate(self):
        """Authenticate the X API v2 session with an OAuth2 user token."""
        if not self.access_token and not self.refresh_token:
            if self.progress_bar:
                self.progress_bar.write(
                    "[Twitter] No OAuth2 user token found. Starting authorization flow..."
                )
            authorize_twitter(self.data_dir)
            self.access_token = os.getenv("TWITTER_OAUTH2_ACCESS_TOKEN")
            self.refresh_token = os.getenv("TWITTER_OAUTH2_REFRESH_TOKEN")
            expiry = os.getenv("TWITTER_OAUTH2_EXPIRES_AT")
            self.expires_at = int(expiry) if expiry and expiry.isdigit() else 0

        if self.expires_at and self.expires_at <= int(time.time()) + 60:
            try:
                values = refresh_twitter_access_token(self.data_dir)
            except requests.exceptions.HTTPError:
                if self.progress_bar:
                    self.progress_bar.write(
                        "[Twitter] Refresh token rejected. Starting authorization flow..."
                    )
                authorize_twitter(self.data_dir)
                values = {
                    "oauth2_access_token": os.getenv("TWITTER_OAUTH2_ACCESS_TOKEN"),
                    "oauth2_refresh_token": os.getenv("TWITTER_OAUTH2_REFRESH_TOKEN"),
                    "oauth2_expires_at": os.getenv("TWITTER_OAUTH2_EXPIRES_AT"),
                }
            self.access_token = values["oauth2_access_token"]
            self.refresh_token = values.get("oauth2_refresh_token", self.refresh_token)
            self.expires_at = int(values["oauth2_expires_at"])
        if not self.access_token:
            raise ValueError("X OAuth2 user access token is unavailable")

        self.oauth_session = requests.Session()
        self.oauth_session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
        })
        self.client = self.oauth_session

        self._update_progress("authenticate", "Authenticated with Twitter")
        return self.oauth_session, self.client

    def _validate_video_file(self, video_path: str):
        """
        Validates the video file before upload.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Check file size (Twitter has a 512MB limit)
        file_size = os.path.getsize(video_path)
        max_size = 512 * 1024 * 1024  # 512MB limit for Twitter
        if file_size > max_size:
            raise ValueError(
                f"Video file too large: {file_size / (1024**2):.1f}MB. "
                f"Maximum size: {max_size / (1024**2):.1f}MB")

        # Check file extension
        valid_extensions = ['.mp4', '.mov', '.avi', '.webm', '.mkv']
        file_ext = os.path.splitext(video_path)[1].lower()
        if file_ext not in valid_extensions:
            raise ValueError(
                f"Unsupported video format: {file_ext}. "
                f"Supported formats: {', '.join(valid_extensions)}")

        self._update_progress("validate_file", "Video file validated")
        return file_size

    def _upload_media(self, video_path: str):
        """
        Upload video media to Twitter and return media ID.
        """

        total_bytes = os.path.getsize(video_path)
        media_type = mimetypes.guess_type(video_path)[0] or "video/mp4"

        def initialize_upload():
                return self.oauth_session.post(
                f"{self.TWITTER_UPLOAD_BASE_URL}/initialize",
                json={
                    "media_type": media_type,
                    "total_bytes": total_bytes,
                    "media_category": "tweet_video",
                },
                timeout=self.request_timeout)

        initialize_response = self._retry_request(initialize_upload)
        media_id = initialize_response.json()["data"]["id"]

        with open(video_path, "rb") as video_file:
            segment_index = 0
            while True:
                chunk = video_file.read(self.MEDIA_CHUNK_SIZE)
                if not chunk:
                    break

                def append_upload(chunk=chunk, segment_index=segment_index):
                    return self.oauth_session.post(
                        f"{self.TWITTER_UPLOAD_BASE_URL}/{media_id}/append",
                        data={"segment_index": str(segment_index)},
                        files={
                            "media": (os.path.basename(video_path), chunk,
                                       media_type)
                        },
                        timeout=self.request_timeout)

                self._retry_request(append_upload)
                segment_index += 1

        def finalize_upload():
            return self.oauth_session.post(
                f"{self.TWITTER_UPLOAD_BASE_URL}/{media_id}/finalize",
                timeout=self.request_timeout)

        self._retry_request(finalize_upload)

        self._update_progress("media_upload",
                              f"Media uploaded (ID: {media_id})")
        return media_id

    def _wait_for_processing(self, media_id: str, video_size_mb: float):
        """
        Wait for video processing to complete with progress tracking.
        """
        processing_state = None
        retry_count = 0
        start_time = time.time()

        # Calculate progress increment based on file size
        estimated_time = max(
            self.MIN_PROCESSING_TIME,
            video_size_mb * self.DEFAULT_PROCESSING_TIME_PER_MB)
        increment_per_update = max(
            self.MIN_PROGRESS_INCREMENT, self.MAX_PROGRESS_DURING_PROCESSING /
            (estimated_time / self.API_POLL_INTERVAL))

        current_progress = self.progress_bar.n if self.progress_bar else 0

        while (processing_state != "succeeded"
               and retry_count < self.max_processing_retries
               and time.time() - start_time < self.processing_timeout):

            elapsed = time.time() - start_time

            # Update progress description with elapsed time
            if self.progress_bar:
                self.progress_bar.set_description(
                    f"[Twitter Processing video... ({elapsed:.0f}s)")

            status_url = (
                f"{self.TWITTER_UPLOAD_BASE_URL}?command=STATUS&media_id={media_id}"
            )

            def get_status():
                return self.oauth_session.get(status_url, timeout=self.request_timeout)

            try:
                response = self._retry_request(get_status)
                media_status = response.json()
                media_data = media_status.get("data", media_status)
                processing_info = media_data.get("processing_info")

                if processing_info and processing_info.get("state"):
                    processing_state = processing_info["state"]

                    if processing_state == "succeeded":
                        if self.progress_bar:
                            self.progress_bar.set_description(
                                "[Twitter] Video processed successfully")
                        break
                    elif processing_state == "failed":
                        error = processing_info.get("error", {})
                        raise RuntimeError(
                            f"Video processing failed: {error.get('message', 'Unknown error')}"
                        )
                    else:
                        # Update progress gradually during processing
                        target_progress = current_progress + min(
                            elapsed *
                            (increment_per_update / self.API_POLL_INTERVAL),
                            self.MAX_PROGRESS_DURING_PROCESSING)

                        if (self.progress_bar
                                and self.progress_bar.n < target_progress
                                and self.progress_bar.n < current_progress +
                                self.MAX_PROGRESS_DURING_PROCESSING):
                            increment = min(
                                increment_per_update,
                                target_progress - self.progress_bar.n)
                            if increment > 0:
                                self.progress_bar.update(increment)

                        check_after_secs = processing_info.get(
                            "check_after_secs", self.API_POLL_INTERVAL)
                        time.sleep(check_after_secs)
                        retry_count += 1
                else:
                    # No processing info available yet
                    time.sleep(self.API_POLL_INTERVAL)
                    retry_count += 1

            except Exception as e:
                logging.warning(f"Error checking processing status: {e}")
                time.sleep(self.API_POLL_INTERVAL)
                retry_count += 1

        if processing_state != "succeeded":
            if time.time() - start_time >= self.processing_timeout:
                raise TimeoutError("Video processing timed out")
            else:
                raise RuntimeError(
                    "Video processing failed or exceeded retry limit")

        self._update_progress("video_processing", "Video processing completed")
        return True

    def _create_tweet(self, text: str, media_id: str):
        """
        Create a tweet with the uploaded video.
        """

        def create_with_retry():
            return self.oauth_session.post(
                f"{self.TWITTER_API_BASE_URL}/2/tweets",
                json={"text": text, "media": {"media_ids": [media_id]}},
                timeout=self.request_timeout)

        response = self._retry_request(create_with_retry)
        tweet_id = response.json()["data"]["id"]

        self._update_progress("create_tweet", "Tweet created successfully")
        return tweet_id

    def run(self, video_path: str, tweet_text: str):
        """
        Main method to handle the complete Twitter video upload process.
        
        Args:
            video_path (str): Path to the video file to upload
            tweet_text (str): Text content for the tweet
                
        Returns:
            str: Tweet ID of the posted tweet
        """
        total_progress = sum(self.progress_allocations.values())
        tweet_id = None

        with self._progress_context(total_progress, "Starting upload"):
            try:
                # Authenticate with Twitter
                if not self.oauth_session:
                    self._authenticate()

                # Validate video file
                file_size = self._validate_video_file(video_path)
                video_size_mb = file_size / (1024 * 1024)

                # Upload media
                media_id = self._upload_media(video_path)

                # Wait for processing to complete
                self._wait_for_processing(media_id, video_size_mb)

                # Create tweet with media
                tweet_id = self._create_tweet(tweet_text, media_id)

                # Complete progress bar
                self._complete_progress_bar(True)

            except Exception:
                self._complete_progress_bar(False)
                raise

        return tweet_id
