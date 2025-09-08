import logging
import os
import time
import urllib.parse
import webbrowser

from google.cloud import storage
from google.oauth2 import service_account
import requests

from .base import BaseUploadPipeline


class InstagramUploadPipeline(BaseUploadPipeline):
    """
    A pipeline class for handling Instagram Reels uploads, including authentication,
    temporary video hosting, and upload management.
    """

    # Constants
    FACEBOOK_GRAPH_BASE_URL = "https://graph.facebook.com"
    FACEBOOK_AUTH_BASE_URL = "https://www.facebook.com"
    GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
    GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
    GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"

    # Video processing constants
    DEFAULT_PROCESSING_TIME_PER_MB = 20  # seconds
    MIN_PROCESSING_TIME = 30  # seconds
    MAX_PROGRESS_DURING_PROCESSING = 80  # don't complete progress bar during processing
    API_POLL_INTERVAL = 5  # seconds between status checks
    MIN_PROGRESS_INCREMENT = 1.5

    def __init__(self,
                 facebook_app_id=os.getenv("FACEBOOK_APP_ID"),
                 facebook_app_secret=os.getenv("FACEBOOK_APP_SECRET"),
                 facebook_page_id=os.getenv("FACEBOOK_PAGE_ID"),
                 facebook_access_token=os.getenv("FACEBOOK_ACCESS_TOKEN"),
                 gcp_project_id=os.getenv("GCP_PROJECT_ID"),
                 gcp_private_key_id=os.getenv("GCP_PRIVATE_KEY_ID"),
                 gcp_private_key=os.getenv("GCP_PRIVATE_KEY"),
                 gcp_client_email=os.getenv("GCP_CLIENT_EMAIL"),
                 gcp_client_id=os.getenv("GCP_CLIENT_ID"),
                 gcs_bucket_name=os.getenv("GCS_BUCKET_NAME"),
                 redirect_uri='https://localhost/',
                 api_version='v23.0',
                 request_timeout=30,
                 processing_timeout=360,
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
            gcp_project_id (str, optional): Google Cloud Project ID.
                Defaults to GCP_PROJECT_ID environment variable.
            gcp_private_key_id (str, optional): Google Cloud Private Key ID.
                Defaults to GCP_PRIVATE_KEY_ID environment variable.
            gcp_private_key (str, optional): Google Cloud Private Key.
                Defaults to GCP_PRIVATE_KEY environment variable.
            gcp_client_email (str, optional): Google Cloud Client Email.
                Defaults to GCP_CLIENT_EMAIL environment variable.
            gcp_client_id (str, optional): Google Cloud Client ID.
                Defaults to GCP_CLIENT_ID environment variable.
            gcs_bucket_name (str, optional): Google Cloud Storage Bucket Name.
                Defaults to GCS_BUCKET_NAME environment variable.
            redirect_uri (str, optional): OAuth redirect URI.
                Defaults to 'https://localhost/'.
            request_timeout (int, optional): Timeout for HTTP requests in seconds.
                Defaults to 30 seconds.
            processing_timeout (int, optional): Timeout for video processing in seconds.
                Defaults to 120 seconds.
            auth_scopes (list, optional): List of Facebook authentication scopes.
                Defaults to basic Instagram and page management scopes.
        """
        # Facebook/Instagram credentials
        self.app_id = facebook_app_id
        self.app_secret = facebook_app_secret
        self.page_id = facebook_page_id
        self.access_token = facebook_access_token

        # Google Cloud credentials
        self.gcp_project_id = gcp_project_id
        self.gcp_private_key_id = gcp_private_key_id
        self.gcp_private_key = gcp_private_key
        self.gcp_client_email = gcp_client_email
        self.gcp_client_id = gcp_client_id
        self.gcs_bucket_name = gcs_bucket_name

        # Authentication configuration
        self.redirect_uri = redirect_uri
        self.api_version = api_version
        self.auth_scopes = auth_scopes

        # Timeout configuration
        self.request_timeout = request_timeout
        self.processing_timeout = processing_timeout

        # Runtime state
        self.google_creds = None
        self.page_token = None
        self.ig_user_id = None

        # Progress bar configuration (redistributed for smoother UX)
        self.progress_allocations = {
            "google_auth": 2,  # 2%
            "page_token": 3,  # 3%
            "ig_user_id": 3,  # 3%
            "video_upload": 5,  # 5%
            "create_container": 7,  # 7%
            "video_processing": 70,  # 70% - spread over time
            "publish_media": 8,  # 8% - reduced from 23%
            "cleanup": 2  # 2%
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

        if not all([
                self.gcp_project_id, self.gcp_private_key_id,
                self.gcp_private_key, self.gcp_client_email,
                self.gcp_client_id, self.gcs_bucket_name
        ]):
            raise ValueError(
                "Missing required Google Cloud credentials. Provide them as parameters "
                "or set them as environment variables: GCP_PROJECT_ID, GCP_PRIVATE_KEY_ID, "
                "GCP_PRIVATE_KEY, GCP_CLIENT_EMAIL, GCP_CLIENT_ID, GCS_BUCKET_NAME"
            )

        # Validate base class requirements
        self._validate_required_attributes()

    def _enhance_error_message(self, response):
        """Instagram-specific error message enhancement."""
        try:
            error_data = response.json()
            api_error = error_data.get('error', {}).get('message', '')
            if api_error:
                response.reason = f"{response.reason}: {api_error}"
        except:
            pass

    def _authenticate_google(self):
        """
        Authenticates with Google Cloud using the provided scopes.
        Returns a credentials object.
        """
        credentials_info = {
            "type":
            "service_account",
            "project_id":
            self.gcp_project_id,
            "private_key_id":
            self.gcp_private_key_id,
            "private_key":
            self.gcp_private_key.replace('\\n', '\n'),
            "client_email":
            self.gcp_client_email,
            "client_id":
            self.gcp_client_id,
            "auth_uri":
            self.GOOGLE_AUTH_URI,
            "token_uri":
            self.GOOGLE_TOKEN_URI,
            "auth_provider_x509_cert_url":
            self.GOOGLE_CERTS_URL,
            "client_x509_cert_url":
            f"https://www.googleapis.com/robot/v1/metadata/x509/{urllib.parse.quote(self.gcp_client_email)}",
        }
        self.google_creds = service_account.Credentials.from_service_account_info(
            credentials_info)
        self._update_progress("google_auth", "Authenticated with Google Cloud")
        return self.google_creds

    def get_user_access_token(self):
        """
        Guides user through browser-based OAuth to obtain a user access token.
        """
        oauth_url = (
            f"{self.FACEBOOK_AUTH_BASE_URL}/{self.api_version}/dialog/oauth"
            f"?client_id={self.app_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&scope={','.join(self.auth_scopes)}"
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
        logging.info(f"Access token: {response.json()['access_token']}")
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

    def _upload_video(self, video_path):
        """
        Uploads a video to Google Cloud Storage and makes it public.
        Returns the public URL to the uploaded video.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not self.google_creds:
            self._authenticate_google()

        destination_blob_name = os.path.basename(video_path)
        storage_client = storage.Client(credentials=self.google_creds)
        bucket = storage_client.bucket(self.gcs_bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(video_path)
        self._update_progress("video_upload",
                              "Video uploaded to cloud storage")
        return blob.public_url

    def _delete_video(self, video_path):
        """
        Deletes a video from Google Cloud Storage.
        """
        if not self.google_creds:
            self._authenticate_google()

        blob_name = os.path.basename(video_path)
        storage_client = storage.Client(credentials=self.google_creds)
        bucket = storage_client.bucket(self.gcs_bucket_name)
        blob = bucket.blob(blob_name)
        blob.delete()
        self._update_progress("cleanup", "Cleaned up temporary files")
        return True

    def _create_reel_container(self,
                               video_url,
                               caption,
                               share_to_feed=True,
                               thumb_offset=None):
        """
        Creates a media container for a Reel.
        """
        if not self.ig_user_id:
            self._get_ig_user_id()

        url = f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/{self.ig_user_id}/media"
        payload = {
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': self.page_token,
            'share_to_feed': 'true' if share_to_feed else 'false',
        }
        if thumb_offset is not None:
            payload['thumb_offset'] = str(thumb_offset)
        resp = self._retry_request(requests.post,
                                   url,
                                   data=payload,
                                   timeout=self.request_timeout)
        self._update_progress("create_container", "Created reel container")
        return resp.json()['id']

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

        # Update description to show completion
        if self.progress_bar:
            self.progress_bar.set_description("[Instagram] Cleaning up...")
        return resp.json()['id']

    def _wait_for_processing(self, creation_id, video_size_mb=0):
        """
        Polls the media container status until it's finished processing.
        """
        url = f"{self.FACEBOOK_GRAPH_BASE_URL}/{self.api_version}/{creation_id}?fields=status_code&access_token={self.page_token}"
        start = time.time()
        last_api_call = 0

        # Calculate increment per second based on expected processing time
        estimated_time = max(
            self.MIN_PROCESSING_TIME,
            video_size_mb * self.DEFAULT_PROCESSING_TIME_PER_MB)
        increment_per_check = max(
            self.MIN_PROGRESS_INCREMENT,
            self.MAX_PROGRESS_DURING_PROCESSING / estimated_time)

        current_progress = self.progress_bar.n if self.progress_bar else 0
        status = None

        while time.time() - start < self.processing_timeout:
            elapsed = time.time() - start

            # Only fetch API status every few seconds
            if elapsed - last_api_call >= self.API_POLL_INTERVAL:
                resp = self._retry_request(requests.get, url, timeout=10)
                media_status = resp.json()
                status = media_status.get('status_code')
                last_api_call = elapsed

            # Progressive updates based on video size and elapsed time
            target_progress = current_progress + min(
                elapsed * increment_per_check,
                self.MAX_PROGRESS_DURING_PROCESSING)

            # Update the timer description every second
            if self.progress_bar:
                self.progress_bar.set_description(
                    f"[Instagram] Processing video... ({elapsed:.0f}s)")

            # Only update progress if we haven't reached the cap
            if self.progress_bar and self.progress_bar.n < target_progress and self.progress_bar.n < self.MAX_PROGRESS_DURING_PROCESSING:
                increment = min(
                    increment_per_check, target_progress - self.progress_bar.n,
                    self.MAX_PROGRESS_DURING_PROCESSING - self.progress_bar.n)
                if increment > 0:
                    self.progress_bar.update(increment)

            if status == 'FINISHED':
                if self.progress_bar:
                    self.progress_bar.set_description(
                        "[Instagram] Publishing reel...")
                return True
            elif status == 'ERROR':
                # Try to get more detailed error info from various possible locations
                error_info = media_status.get('error', {})
                error_msg = media_status.get('message', '')
                error_type = media_status.get('error_type', '')
                
                if error_info or error_msg or error_type:
                    # We have some error details
                    details = []
                    if error_msg:
                        details.append(error_msg)
                    if error_type:
                        details.append(f"Type: {error_type}")
                    if error_info and isinstance(error_info, dict):
                        if 'message' in error_info:
                            details.append(error_info['message'])
                        if 'code' in error_info:
                            details.append(f"Code: {error_info['code']}")
                    
                    raise RuntimeError(f"Instagram video processing failed: {' | '.join(details)}")
                else:
                    # No specific error details - provide common causes
                    media_id = media_status.get('id', 'unknown')
                    raise RuntimeError(
                        f"Instagram video processing failed (ID: {media_id}). "
                        "Common causes: unsupported video format, file too large, invalid aspect ratio, or temporary Instagram API issue."
                    )

            time.sleep(1)

        raise TimeoutError("Timed out waiting for video processing.")

    def run(self,
            video_path,
            caption: str,
            share_to_feed: bool = True,
            thumb_offset: int = None):
        """
        Main method to handle the complete Instagram Reels upload process.
        
        Args:
            video_path (str): Path to the video file to upload
            caption (str): Caption for the Instagram Reel
            share_to_feed (bool, optional): Whether to share the reel to the main feed. 
                Defaults to True.
            thumb_offset (int, optional): Thumbnail offset in milliseconds.
                Defaults to None (auto-generated).
                
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
                # Initialize credentials if not already done
                if not self.google_creds:
                    self._authenticate_google()

                # Upload to temporary storage
                video_url = self._upload_video(video_path)

                # Get necessary tokens and IDs
                if not self.access_token:
                    self.progress_bar.write(
                        "[Instagram] No access token found. Starting OAuth flow..."
                    )
                    self.access_token = self._generate_long_lived_access_token(
                    )
                    self.progress_bar.write(
                        "\nIMPORTANT: To skip the manual OAuth process in future runs, "
                        "set this access token in your environment:\n"
                        f"FACEBOOK_ACCESS_TOKEN={self.access_token}\n")

                # Get necessary tokens and IDs
                if not self.page_token:
                    self._get_page_access_token()

                if not self.ig_user_id:
                    self._get_ig_user_id()

                # Create and process the reel
                creation_id = self._create_reel_container(
                    video_url, caption, share_to_feed, thumb_offset)

                try:
                    self._wait_for_processing(creation_id, video_size_mb=video_size_mb)
                    media_id = self._publish_media(creation_id)
                    upload_success = True
                except (TimeoutError, RuntimeError) as e:
                    failure_reason = str(e)
                except Exception as e:
                    failure_reason = f"Unexpected error during processing: {str(e)}"
                finally:
                    self._delete_video(video_path)

                # Handle progress bar completion based on success/failure
                if upload_success:
                    self._complete_progress_bar(True)
                else:
                    self._complete_progress_bar(False)
                    error_msg = failure_reason or "Instagram upload failed during video processing or publishing"
                    raise RuntimeError(error_msg)

            except Exception as e:
                self._complete_progress_bar(False)
                raise

        return media_id
