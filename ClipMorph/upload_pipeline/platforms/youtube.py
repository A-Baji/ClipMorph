import logging
import os
import random
import time
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .base import BaseUploadPipeline

# Suppress Google library verbose logging
logging.getLogger('googleapiclient.discovery').setLevel(logging.WARNING)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.WARNING)
logging.getLogger('google.auth').setLevel(logging.WARNING)


class YouTubeUploadPipeline(BaseUploadPipeline):
    """
    A pipeline class for handling YouTube Shorts uploads, including authentication,
    video upload management, and progress tracking.
    """

    # Constants
    GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
    GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
    YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

    # Video processing constants
    DEFAULT_PROCESSING_TIME_PER_MB = 15  # seconds
    MIN_PROCESSING_TIME = 20  # seconds
    MAX_PROGRESS_DURING_PROCESSING = 85  # don't complete progress bar during processing
    API_POLL_INTERVAL = 2  # seconds between status checks
    MIN_PROGRESS_INCREMENT = 2.0

    # Retry configuration
    MAX_RETRIES = 3
    RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

    def __init__(self,
                 google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
                 google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                 google_refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
                 api_service_name="youtube",
                 api_version="v3",
                 request_timeout=30,
                 upload_timeout=600,
                 chunk_size=-1):
        """Initialize the YouTube upload pipeline.
        
        Args:
            google_client_id (str, optional): Google OAuth Client ID for authentication.
                Defaults to GOOGLE_CLIENT_ID environment variable.
            google_client_secret (str, optional): Google OAuth Client Secret for authentication.
                Defaults to GOOGLE_CLIENT_SECRET environment variable.
            google_refresh_token (str, optional): Google OAuth Refresh Token for API access.
                Defaults to GOOGLE_REFRESH_TOKEN environment variable.
            api_service_name (str, optional): YouTube API service name.
                Defaults to 'youtube'.
            api_version (str, optional): YouTube API version for requests.
                Defaults to 'v3'.
            request_timeout (int, optional): Timeout for HTTP requests in seconds.
                Defaults to 30 seconds.
            upload_timeout (int, optional): Timeout for video upload in seconds.
                Defaults to 600 seconds.
            chunk_size (int, optional): Upload chunk size in bytes. -1 for entire file upload.
                Defaults to -1.
        """
        # Google credentials
        self.client_id = google_client_id
        self.client_secret = google_client_secret
        self.refresh_token = google_refresh_token

        # API configuration
        self.api_service_name = api_service_name
        self.api_version = api_version
        self.chunk_size = chunk_size

        # Timeout configuration
        self.request_timeout = request_timeout
        self.upload_timeout = upload_timeout

        # Runtime state
        self.credentials = None
        self.youtube_service = None

        # Progress bar configuration
        self.progress_allocations = {
            "authenticate": 5,  # 5%
            "validate_file": 5,  # 5%
            "prepare_upload": 10,  # 10%
            "video_upload": 70,  # 70% - spread over time
            "finalize": 10  # 10%
        }
        self.progress_bar = None

        # Set platform name for base class
        self.platform_name = "YouTube"

        # Initialize base class
        super().__init__()

        # Validate required credentials
        if not all([self.client_id, self.client_secret]):
            raise ValueError(
                "Missing required Google OAuth credentials. Provide them as parameters "
                "or set them as environment variables: GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET")

        # Validate base class requirements
        self._validate_required_attributes()

    def _enhance_error_message(self, response):
        """YouTube-specific error message enhancement for HttpError."""
        # YouTube HttpError objects have different structure
        # The base class will handle this automatically

    def _authenticate(self):
        """
        Authenticates with Google using OAuth2 credentials.
        Automatically generates a new refresh token if missing or invalid.
        Returns a valid credentials object.
        """
        # If no refresh token, check environment again and generate if needed
        if not self.refresh_token:
            # Check environment variable again in case it was set after initialization
            self.refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

        if not self.refresh_token:
            if self.progress_bar:
                self.progress_bar.write(
                    "[YouTube] No refresh token found. Starting OAuth flow...")
            self.refresh_token = self.generate_refresh_token()

        self.credentials = Credentials(None,
                                       refresh_token=self.refresh_token,
                                       token_uri=self.GOOGLE_TOKEN_URI,
                                       client_id=self.client_id,
                                       client_secret=self.client_secret,
                                       scopes=[self.YOUTUBE_UPLOAD_SCOPE])

        if not self.credentials.valid:
            if self.credentials.refresh_token:
                try:
                    self.credentials.refresh(Request())
                except Exception as e:
                    # If refresh fails, generate a new token
                    if self.progress_bar:
                        self.progress_bar.write(
                            f"[YouTube] Refresh token expired or invalid. Generating new token... ({e})"
                        )
                    self.refresh_token = self.generate_refresh_token()

                    # Create new credentials with the fresh token
                    self.credentials = Credentials(
                        None,
                        refresh_token=self.refresh_token,
                        token_uri=self.GOOGLE_TOKEN_URI,
                        client_id=self.client_id,
                        client_secret=self.client_secret,
                        scopes=[self.YOUTUBE_UPLOAD_SCOPE])
                    self.credentials.refresh(Request())
            else:
                # Generate new token if credentials are completely invalid
                if self.progress_bar:
                    self.progress_bar.write(
                        "[YouTube] Invalid credentials. Generating new refresh token..."
                    )
                self.refresh_token = self.generate_refresh_token()

                # Create new credentials with the fresh token
                self.credentials = Credentials(
                    None,
                    refresh_token=self.refresh_token,
                    token_uri=self.GOOGLE_TOKEN_URI,
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    scopes=[self.YOUTUBE_UPLOAD_SCOPE])
                self.credentials.refresh(Request())

        self.youtube_service = build(self.api_service_name,
                                     self.api_version,
                                     credentials=self.credentials)

        self._update_progress("authenticate", "Authenticated with YouTube")
        return self.credentials

    def _validate_video_file(self, video_path: str):
        """
        Validates the video file before upload.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Check file size (YouTube has a 256GB limit, but let's be practical)
        file_size = os.path.getsize(video_path)
        max_size = 2 * 1024 * 1024 * 1024  # 2GB practical limit
        if file_size > max_size:
            raise ValueError(
                f"Video file too large: {file_size / (1024**3):.1f}GB. "
                f"Maximum recommended size: {max_size / (1024**3):.1f}GB")

        # Check file extension
        valid_extensions = [
            '.mp4', '.mov', '.avi', '.wmv', '.flv', '.webm', '.mkv'
        ]
        file_ext = os.path.splitext(video_path)[1].lower()
        if file_ext not in valid_extensions:
            raise ValueError(
                f"Unsupported video format: {file_ext}. "
                f"Supported formats: {', '.join(valid_extensions)}")

        self._update_progress("validate_file", "Video file validated")
        return file_size

    def _prepare_upload_request(self, video_path: str, title: str,
                                description: str, category: str,
                                keywords: List[str], privacy_status: str):
        """
        Prepares the upload request with metadata and media upload object.
        """
        tags = [k.strip() for k in keywords if k.strip()] if keywords else None

        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': category
            },
            'status': {
                'privacyStatus': privacy_status
            }
        }

        media = MediaFileUpload(video_path,
                                chunksize=self.chunk_size,
                                resumable=True)

        request = self.youtube_service.videos().insert(part=','.join(
            body.keys()),
                                                       body=body,
                                                       media_body=media)

        self._update_progress("prepare_upload", "Upload request prepared")
        return request

    def _execute_resumable_upload(self, request, video_size_mb: float):
        """
        Executes the resumable upload with progress tracking.
        """
        response = None
        error = None
        retry = 0
        start_time = time.time()

        # Calculate progress increment based on file size
        estimated_time = max(
            self.MIN_PROCESSING_TIME,
            video_size_mb * self.DEFAULT_PROCESSING_TIME_PER_MB)
        increment_per_update = max(
            self.MIN_PROGRESS_INCREMENT, self.MAX_PROGRESS_DURING_PROCESSING /
            (estimated_time / self.API_POLL_INTERVAL))

        current_progress = self.progress_bar.n if self.progress_bar else 0

        while response is None:
            try:
                elapsed = time.time() - start_time

                # Update progress description with elapsed time
                if self.progress_bar:
                    self.progress_bar.set_description(
                        f"[YouTube] Uploading video... ({elapsed:.0f}s)")

                status, response = request.next_chunk()

                # Update progress based on upload status
                if status:
                    progress_percent = status.progress(
                    ) * self.MAX_PROGRESS_DURING_PROCESSING
                    target_progress = current_progress + progress_percent

                    if self.progress_bar and self.progress_bar.n < target_progress:
                        increment = min(target_progress - self.progress_bar.n,
                                        increment_per_update)
                        if increment > 0:
                            self.progress_bar.update(increment)

                if response is not None:
                    if 'id' in response:
                        return response['id']
                    else:
                        raise RuntimeError(
                            f"Upload failed with unexpected response: {response}"
                        )

            except HttpError as e:
                if e.resp.status in self.RETRIABLE_STATUS_CODES:
                    error = f"Retriable HTTP error {e.resp.status}: {e.content}"
                else:
                    raise e
            except Exception as e:
                error = f"Retriable error occurred: {e}"

            if error is not None:
                logging.warning(f"[YouTube] {error}")
                retry += 1
                if retry > self.MAX_RETRIES:
                    raise RuntimeError(
                        f"Upload failed after {self.MAX_RETRIES} retries. Last error: {error}"
                    )

                max_sleep = 2**retry
                sleep_seconds = random.uniform(0, max_sleep)
                logging.info(
                    f"[YouTube] Retrying in {sleep_seconds:.1f} seconds...")
                time.sleep(sleep_seconds)
                error = None

    def generate_refresh_token(self):
        """
        Generates a refresh token through OAuth2 flow.
        This should be run once to obtain the refresh token for future use.
        """
        if not all([self.client_id, self.client_secret]):
            raise ValueError(
                "Client ID and Client Secret are required for token generation"
            )

        scopes = [self.YOUTUBE_UPLOAD_SCOPE]

        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id":
                    self.client_id,
                    "client_secret":
                    self.client_secret,
                    "redirect_uris":
                    ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                    "auth_uri":
                    self.GOOGLE_AUTH_URI,
                    "token_uri":
                    self.GOOGLE_TOKEN_URI
                }
            }, scopes)

        creds = flow.run_local_server(port=0, prompt='select_account')

        # Show the setup message whenever a new token is generated
        if self.progress_bar:
            self.progress_bar.write(
                "\nIMPORTANT: To skip the manual OAuth process in future runs, "
                "set this refresh token in your environment:\n"
                f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}\n")

        return creds.refresh_token

    def run(
            self,
            video_path: str,
            title: str = "YouTube Shorts Upload",
            description: str = "Uploaded via API",
            category: str = "20",  # Gaming
            keywords: Optional[List[str]] = None,
            privacy_status: str = "public"):
        """
        Main method to handle the complete YouTube upload process.
        
        Args:
            video_path (str): Path to the video file to upload
            title (str): Video title
            description (str): Video description  
            category (str): Numeric video category (default: 22 for People & Blogs)
            keywords (List[str], optional): List of keywords/tags for the video
            privacy_status (str): 'public', 'private', or 'unlisted'
            
        Returns:
            str: Video ID of the uploaded video
        """
        if keywords is None:
            keywords = []

        # Validate privacy status
        valid_privacy = ['public', 'private', 'unlisted']
        if privacy_status not in valid_privacy:
            raise ValueError(f"Invalid privacy status: {privacy_status}. "
                             f"Must be one of: {', '.join(valid_privacy)}")

        total_progress = sum(self.progress_allocations.values())
        video_id = None

        with self._progress_context(total_progress, "Starting upload"):
            try:
                # Authenticate with Google
                if not self.credentials:
                    self._authenticate()

                # Validate video file
                file_size = self._validate_video_file(video_path)
                video_size_mb = file_size / (1024 * 1024)

                # Prepare upload request
                request = self._prepare_upload_request(video_path, title,
                                                       description, category,
                                                       keywords,
                                                       privacy_status)

                # Execute upload
                video_id = self._execute_resumable_upload(
                    request, video_size_mb)

                # Finalize
                self._update_progress("finalize", "Upload complete")

                # Complete progress bar
                self._complete_progress_bar(True)

            except Exception as e:
                if self.progress_bar:
                    self.progress_bar.write(f"[YouTube] Upload failed: {e}")
                self._complete_progress_bar(False)
                raise

        return video_id
