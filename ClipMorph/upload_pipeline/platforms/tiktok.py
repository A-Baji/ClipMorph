from contextlib import contextmanager
import hashlib
import logging
import os
import random
import secrets
import time
import urllib.parse

import requests
from tqdm import tqdm


class TikTokUploadPipeline:
    """
    A pipeline class for handling TikTok video uploads, including authentication,
    video upload management, and progress tracking.
    """

    # Constants
    TIKTOK_AUTH_BASE_URL = "https://www.tiktok.com"
    TIKTOK_API_BASE_URL = "https://open.tiktokapis.com"
    TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

    # Video processing constants
    DEFAULT_PROCESSING_TIME_PER_MB = 10  # seconds
    MIN_PROCESSING_TIME = 15  # seconds
    MAX_PROGRESS_DURING_PROCESSING = 80  # don't complete progress bar during processing
    API_POLL_INTERVAL = 3  # seconds between status checks
    MIN_PROGRESS_INCREMENT = 2.0

    # Retry configuration
    MAX_RETRIES = 3
    RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

    def __init__(self,
                 tiktok_client_key=os.getenv("TIKTOK_CLIENT_KEY"),
                 tiktok_client_secret=os.getenv("TIKTOK_CLIENT_SECRET"),
                 tiktok_refresh_token=os.getenv("TIKTOK_REFRESH_TOKEN"),
                 redirect_uri="http://127.0.0.1:80/callback/",
                 scope="user.info.basic,video.upload,video.publish",
                 request_timeout=30,
                 upload_timeout=300):
        """Initialize the TikTok upload pipeline.
        
        Args:
            tiktok_client_key (str, optional): TikTok Client Key for authentication.
                Defaults to TIKTOK_CLIENT_KEY environment variable.
            tiktok_client_secret (str, optional): TikTok Client Secret for authentication.
                Defaults to TIKTOK_CLIENT_SECRET environment variable.
            tiktok_refresh_token (str, optional): TikTok Refresh Token for API access.
                Defaults to TIKTOK_REFRESH_TOKEN environment variable.
            redirect_uri (str, optional): OAuth redirect URI.
                Defaults to 'http://127.0.0.1:80/callback/'.
            scope (str, optional): TikTok API scopes for authentication.
                Defaults to 'user.info.basic,video.upload,video.publish'.
            request_timeout (int, optional): Timeout for HTTP requests in seconds.
                Defaults to 30 seconds.
            upload_timeout (int, optional): Timeout for video upload in seconds.
                Defaults to 300 seconds.
        """
        # TikTok credentials
        self.client_key = tiktok_client_key
        self.client_secret = tiktok_client_secret
        self.refresh_token = tiktok_refresh_token

        # Authentication configuration
        self.redirect_uri = redirect_uri
        self.scope = scope

        # Timeout configuration
        self.request_timeout = request_timeout
        self.upload_timeout = upload_timeout

        # Runtime state
        self.access_token = None

        # Progress bar configuration
        self.progress_allocations = {
            "authenticate": 5,  # 5%
            "validate_file": 5,  # 5%
            "initialize_upload": 10,  # 10%
            "video_upload": 70,  # 70% - spread over time
            "finalize": 10  # 10%
        }
        self.progress_bar = None

        # Validate required credentials
        if not all([self.client_key, self.client_secret]):
            raise ValueError(
                "Missing required TikTok credentials. Provide them as parameters "
                "or set them as environment variables: TIKTOK_CLIENT_KEY, "
                "TIKTOK_CLIENT_SECRET")

    def _retry_request(self, func, *args, max_retries=None, **kwargs):
        """Retry HTTP requests with exponential backoff and enhanced error messages."""
        if max_retries is None:
            max_retries = self.MAX_RETRIES

        for attempt in range(max_retries):
            try:
                response = func(*args, **kwargs)
                if hasattr(response, 'status_code') and not response.ok:
                    # Check if this is a retriable HTTP status code
                    if response.status_code in self.RETRIABLE_STATUS_CODES:
                        # Add helpful context to the error message
                        try:
                            error_data = response.json()
                            api_error = error_data.get('error',
                                                       {}).get('message', '')
                            if api_error:
                                response.reason = f"{response.reason}: {api_error}"
                        except:
                            pass

                        if attempt == max_retries - 1:
                            response.raise_for_status()

                        # Use exponential backoff with jitter for retriable errors
                        wait_time = (2**attempt) + random.uniform(0, 1)
                        logging.warning(
                            f"Retriable HTTP error {response.status_code} (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {wait_time:.1f}s: {response.reason}")
                        time.sleep(wait_time)
                        continue
                    else:
                        # Non-retriable HTTP error, fail immediately
                        response.raise_for_status()

                return response
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise e
                wait_time = (2**attempt) + random.uniform(0, 1)
                logging.warning(
                    f"Request failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time:.1f}s: {e}")
                time.sleep(wait_time)

    def _update_progress(self, step_name: str, description: str = ""):
        """Update the progress bar based on step completion."""
        if self.progress_bar and step_name in self.progress_allocations:
            increment = self.progress_allocations[step_name]
            if increment > 0:
                self.progress_bar.update(increment)
            if description:
                self.progress_bar.set_description(f"TikTok: {description}")

    def _generate_code_verifier(self, length=64):
        """Generate a PKCE code verifier."""
        chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
        return ''.join(secrets.choice(chars) for _ in range(length))

    def _generate_code_challenge(self, code_verifier):
        """Generate a PKCE code challenge from code verifier."""
        sha256 = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        return sha256.hex()

    def _generate_auth_url(self, code_challenge):
        """Generate TikTok OAuth authorization URL."""
        params = {
            "client_key": self.client_key,
            "response_type": "code",
            "scope": self.scope,
            "redirect_uri": self.redirect_uri,
            "state": "random_state_string",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        return f"{self.TIKTOK_AUTH_BASE_URL}/v2/auth/authorize/?" + urllib.parse.urlencode(
            params)

    def _exchange_code_for_token(self, auth_code, code_verifier):
        """Exchange authorization code for access token."""
        data = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = self._retry_request(requests.post,
                                       self.TIKTOK_TOKEN_URL,
                                       data=data,
                                       headers=headers,
                                       timeout=self.request_timeout)
        return response.json()

    def _refresh_access_token(self):
        """
        Refreshes the access token using the stored refresh token.
        Returns a valid access token.
        """
        if not self.refresh_token:
            if self.progress_bar:
                self.progress_bar.write(
                    "[TikTok] No refresh token found. Starting OAuth flow...")
            self.refresh_token = self.generate_refresh_token()
            if self.progress_bar:
                self.progress_bar.write(
                    "\nIMPORTANT: To skip the manual OAuth process in future runs, "
                    "set this refresh token in your environment:\n"
                    f"TIKTOK_REFRESH_TOKEN={self.refresh_token}\n")

        data = {
            'client_key': self.client_key,
            'client_secret': self.client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = self._retry_request(requests.post,
                                       self.TIKTOK_TOKEN_URL,
                                       data=data,
                                       headers=headers,
                                       timeout=self.request_timeout)

        resp_json = response.json()
        self.access_token = resp_json.get('access_token')

        if not self.access_token:
            raise RuntimeError("Failed to refresh access token")

        self._update_progress("authenticate", "Authenticated with TikTok")
        return self.access_token

    def _validate_video_file(self, video_path: str):
        """
        Validates the video file before upload.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Check file size (TikTok has specific limits)
        file_size = os.path.getsize(video_path)
        max_size = 500 * 1024 * 1024  # 500MB practical limit for TikTok
        if file_size > max_size:
            raise ValueError(
                f"Video file too large: {file_size / (1024**2):.1f}MB. "
                f"Maximum recommended size: {max_size / (1024**2):.1f}MB")

        # Check file extension
        valid_extensions = ['.mp4', '.mov', '.avi', '.webm', '.mkv']
        file_ext = os.path.splitext(video_path)[1].lower()
        if file_ext not in valid_extensions:
            raise ValueError(
                f"Unsupported video format: {file_ext}. "
                f"Supported formats: {', '.join(valid_extensions)}")

        self._update_progress("validate_file", "Video file validated")
        return file_size

    def _initialize_upload(self,
                           video_size: int,
                           title: str,
                           privacy_level: str = "SELF_ONLY"):
        """
        Initialize the upload and retrieve upload URL.
        """
        publish_endpoint = f'{self.TIKTOK_API_BASE_URL}/v2/post/publish/video/init/'
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json; charset=UTF-8'
        }
        post_data = {
            'post_info': {
                'privacy_level': privacy_level,
                'title': title
            },
            'source_info': {
                'source': 'FILE_UPLOAD',
                'video_size': video_size,
                'chunk_size': video_size,
                'total_chunk_count': 1
            }
        }

        response = self._retry_request(requests.post,
                                       publish_endpoint,
                                       json=post_data,
                                       headers=headers,
                                       timeout=self.request_timeout)

        data = response.json().get('data', {})
        upload_url = data.get('upload_url')
        publish_id = data.get('publish_id')

        if not upload_url:
            raise RuntimeError(
                'Failed to initialize video upload: No upload_url returned')

        self._update_progress("initialize_upload", "Upload initialized")
        return upload_url, publish_id

    def _upload_video_file(self, video_path: str, upload_url: str,
                           video_size: int):
        """
        Upload the video file to TikTok servers with progress tracking.
        """
        start_time = time.time()
        current_progress = self.progress_bar.n if self.progress_bar else 0

        # Calculate increment per update based on file size
        video_size_mb = video_size / (1024 * 1024)
        estimated_time = max(
            self.MIN_PROCESSING_TIME,
            video_size_mb * self.DEFAULT_PROCESSING_TIME_PER_MB)
        increment_per_update = max(
            self.MIN_PROGRESS_INCREMENT, self.MAX_PROGRESS_DURING_PROCESSING /
            (estimated_time / self.API_POLL_INTERVAL))

        with open(video_path, 'rb') as f:
            video_data = f.read()
            headers = {
                'Content-Type': 'video/mp4',
                'Content-Length': str(video_size),
                'Content-Range': f'bytes 0-{video_size-1}/{video_size}'
            }

            # Simulate progress during upload
            if self.progress_bar:
                elapsed = time.time() - start_time
                self.progress_bar.set_description(
                    f"TikTok: Uploading video... ({elapsed:.0f}s)")

                # Update progress gradually
                target_progress = current_progress + (
                    self.MAX_PROGRESS_DURING_PROCESSING * 0.8)
                if self.progress_bar.n < target_progress:
                    increment = min(target_progress - self.progress_bar.n,
                                    increment_per_update)
                    if increment > 0:
                        self.progress_bar.update(increment)

            response = self._retry_request(requests.put,
                                           upload_url,
                                           data=video_data,
                                           headers=headers,
                                           timeout=self.upload_timeout)

            self._update_progress("video_upload",
                                  "Video uploaded successfully")
            return True

    @contextmanager
    def _progress_context(self, total_progress, description="Starting upload"):
        """Context manager for progress bar to ensure proper cleanup."""
        progress_bar = tqdm(
            total=total_progress,
            desc=f"TikTok: {description}",
            unit="%",
            bar_format=
            "{l_bar}{bar}| {n_fmt}/{total_fmt}% [{elapsed}<{remaining}]",
            ncols=100,
            leave=True,
            position=0)
        self.progress_bar = progress_bar
        try:
            yield progress_bar
        finally:
            progress_bar.close()
            self.progress_bar = None

    def generate_refresh_token(self):
        """
        Generates a refresh token through OAuth2 PKCE flow.
        This should be run once to obtain the refresh token for future use.
        """
        if not all([self.client_key, self.client_secret]):
            raise ValueError(
                "Client Key and Client Secret are required for token generation"
            )

        # Generate PKCE values
        code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(code_verifier)

        # Step 1: Direct user to TikTok authorization URL
        auth_url = self._generate_auth_url(code_challenge)
        print("Open this URL in your browser and authorize the app:")
        print(auth_url)

        # Step 2: User pastes redirect URL after authorization
        redirected_url = input(
            "\nPaste the full redirect URL here after authorization: ").strip(
            )
        parsed = urllib.parse.urlparse(redirected_url)
        query = urllib.parse.parse_qs(parsed.query)
        auth_code = query.get("code", [None])[0]

        if not auth_code:
            raise ValueError("Authorization code not found in the URL")

        # Step 3: Exchange code for access token and refresh token
        token_response = self._exchange_code_for_token(auth_code,
                                                       code_verifier)

        refresh_token = token_response.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Failed to obtain refresh token")

        print("\nIMPORTANT: To skip the manual OAuth process in future runs, "
              "set this refresh token in your environment:")
        print(f"TIKTOK_REFRESH_TOKEN={refresh_token}")

        return refresh_token

    def run(self,
            video_path: str,
            title: str = "TikTok Upload",
            privacy_level: str = "SELF_ONLY"):
        """
        Main method to handle the complete TikTok video upload process.
        
        Args:
            video_path (str): Path to the video file to upload
            title (str): Title for the TikTok video
            privacy_level (str, optional): Privacy level for the video.
                Options: 'PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY'.
                Defaults to 'SELF_ONLY'.
                
        Returns:
            str: Publish ID of the uploaded video
        """
        # Validate privacy level
        valid_privacy_levels = [
            'PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY'
        ]
        if privacy_level not in valid_privacy_levels:
            raise ValueError(
                f"Invalid privacy level: {privacy_level}. "
                f"Must be one of: {', '.join(valid_privacy_levels)}")

        total_progress = sum(self.progress_allocations.values())
        publish_id = None

        with self._progress_context(total_progress, "Starting upload"):
            try:
                # Authenticate with TikTok
                if not self.access_token:
                    self._refresh_access_token()

                # Validate video file
                file_size = self._validate_video_file(video_path)

                # Initialize upload
                upload_url, publish_id = self._initialize_upload(
                    file_size, title, privacy_level)

                # Upload video file
                self._upload_video_file(video_path, upload_url, file_size)

                # Finalize
                self._update_progress("finalize", "Upload complete")

                # Complete progress bar
                remaining = total_progress - self.progress_bar.n
                if remaining > 0:
                    self.progress_bar.update(remaining)

                self.progress_bar.set_description("TikTok: Upload successful")

                if self.progress_bar:
                    self.progress_bar.write(
                        f"[TikTok] Successfully uploaded video with publish ID: {publish_id}"
                    )

            except Exception as e:
                if self.progress_bar:
                    self.progress_bar.write(f"[TikTok] Upload failed: {e}")
                    self.progress_bar.set_description("TikTok: Upload failed")
                raise

        return publish_id
