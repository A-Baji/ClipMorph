import logging
import os
import time
import urllib.parse
import webbrowser

from google.cloud import storage
from google.oauth2 import service_account
import requests


class InstagramUploadPipeline:
    """
    A pipeline class for handling Instagram Reels uploads, including authentication,
    temporary video hosting, and upload management.
    """

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
        self.auth_scopes = auth_scopes

        # Runtime state
        self.google_creds = None
        self.page_token = None
        self.ig_user_id = None

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
            "https://accounts.google.com/o/oauth2/auth",
            "token_uri":
            "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url":
            "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url":
            f"https://www.googleapis.com/robot/v1/metadata/x509/{urllib.parse.quote(self.gcp_client_email)}",
        }
        self.google_creds = service_account.Credentials.from_service_account_info(
            credentials_info)
        return self.google_creds

    def _get_user_access_token(self):
        """
        Guides user through browser-based OAuth to obtain a user access token.
        """
        oauth_url = (f"https://www.facebook.com/v23.0/dialog/oauth"
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
        token_url = (f"https://graph.facebook.com/v23.0/oauth/access_token"
                     f"?client_id={self.app_id}"
                     f"&redirect_uri={self.redirect_uri}"
                     f"&client_secret={self.app_secret}"
                     f"&code={code}")
        resp = requests.get(token_url)
        resp.raise_for_status()
        data = resp.json()
        return data['access_token']

    def _generate_long_lived_access_token(self):
        """Generates a long-lived access token from a short-lived one."""
        response = requests.get(
            "https://graph.facebook.com/v23.0/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": self.get_user_access_token()
            })
        logging.info(f"Access token: {response.json()['access_token']}")
        return response.json()["access_token"]

    def _get_page_access_token(self):
        """
        Exchanges a user access token for a page access token.
        """
        url = f"https://graph.facebook.com/v23.0/{self.page_id}?fields=access_token&access_token={self.access_token}"
        resp = requests.get(url)
        resp.raise_for_status()
        self.page_token = resp.json()['access_token']
        return self.page_token

    def _get_ig_user_id(self):
        """
        Gets the Instagram user ID connected to a Facebook Page.
        """
        if not self.page_token:
            self.get_page_access_token()

        url = f"https://graph.facebook.com/v23.0/{self.page_id}?fields=instagram_business_account&access_token={self.page_token}"
        resp = requests.get(url)
        resp.raise_for_status()
        self.ig_user_id = resp.json()['instagram_business_account']['id']
        return self.ig_user_id

    def _upload_video(self, video_path):
        """
        Uploads a video to Google Cloud Storage and makes it public.
        Returns the public URL to the uploaded video.
        """
        import os  # Import locally to avoid polluting global namespace

        if not self.google_creds:
            self.authenticate_google()

        destination_blob_name = os.path.basename(video_path)
        storage_client = storage.Client(credentials=self.google_creds)
        bucket = storage_client.bucket(self.gcs_bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(video_path)
        return blob.public_url

    def _delete_video(self, video_path):
        """
        Deletes a video from Google Cloud Storage.
        """
        import os  # Import locally to avoid polluting global namespace

        if not self.google_creds:
            self.authenticate_google()

        blob_name = os.path.basename(video_path)
        storage_client = storage.Client(credentials=self.google_creds)
        bucket = storage_client.bucket(self.gcs_bucket_name)
        blob = bucket.blob(blob_name)
        blob.delete()
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
            self.get_ig_user_id()

        url = f"https://graph.facebook.com/v23.0/{self.ig_user_id}/media"
        payload = {
            'media_type': 'REELS',
            'video_url': video_url,
            'caption': caption,
            'access_token': self.page_token,
            'share_to_feed': 'true' if share_to_feed else 'false',
        }
        if thumb_offset is not None:
            payload['thumb_offset'] = str(thumb_offset)
        resp = requests.post(url, data=payload)
        resp.raise_for_status()
        return resp.json()['id']

    def _publish_media(self, creation_id):
        """
        Publishes the media container to Instagram as a Reel.
        """
        if not self.ig_user_id:
            self.get_ig_user_id()

        url = f"https://graph.facebook.com/v23.0/{self.ig_user_id}/media_publish"
        payload = {'creation_id': creation_id, 'access_token': self.page_token}
        resp = requests.post(url, data=payload)
        resp.raise_for_status()
        return resp.json()['id']

    def _wait_for_processing(self, creation_id, timeout=120):
        """
        Polls the media container status until it's finished processing.
        """
        url = f"https://graph.facebook.com/v23.0/{creation_id}?fields=status_code&access_token={self.page_token}"
        start = time.time()
        while time.time() - start < timeout:
            resp = requests.get(url)
            resp.raise_for_status()
            status = resp.json().get('status_code')
            if status == 'FINISHED':
                return True
            elif status == 'ERROR':
                logging.error(f"Video processing failed: {resp.json()}")
                return False
            time.sleep(5)
        raise TimeoutError("Timed out waiting for video processing.")

    def run(self, video_path, caption="Uploaded via API"):
        """
        Main method to handle the complete Instagram Reels upload process.
        """
        logging.info("[Instagram] Starting Instagram Reels upload...")

        # Initialize credentials if not already done
        if not self.google_creds:
            self._authenticate_google()
        logging.info(
            "[Instagram] Authenticated to Cloud Storage with Google for temporary video hosting."
        )

        # Upload to temporary storage
        video_url = self._upload_video(video_path)
        logging.info(
            f"[Instagram] Uploaded video to temporary host: {video_url}")

        # Get necessary tokens and IDs
        if not self.access_token:
            logging.info(
                "[Instagram] No access token found. Starting OAuth flow...")
            self.access_token = self._generate_long_lived_access_token()
            print(
                "\nIMPORTANT: To skip the manual OAuth process in future runs, "
                "set this access token in your environment:\n"
                f"FACEBOOK_ACCESS_TOKEN={self.access_token}\n")

        # Get necessary tokens and IDs
        if not self.page_token:
            self._get_page_access_token()
        logging.info("[Instagram] Fetched Instagram page access token.")

        if not self.ig_user_id:
            self._get_ig_user_id()
        logging.info(
            f"[Instagram] Fetched Instagram user ID: {self.ig_user_id}")

        # Create and process the reel
        creation_id = self._create_reel_container(video_url, caption)
        logging.info(
            f"[Instagram] Created Instagram Reel container with ID: {creation_id}"
        )

        try:
            logging.info("[Instagram] Processing video...")
            if self._wait_for_processing(creation_id):
                logging.info(
                    "[Instagram] Video processing finished. Publishing Reel..."
                )
                media_id = self._publish_media(creation_id)
                logging.info(
                    f"[Instagram] Published Reel with media ID: {media_id}")
            else:
                logging.error(
                    "[Instagram] Video processing failed or returned error status."
                )
        except TimeoutError as e:
            logging.error(
                f"[Instagram] Timeout while waiting for video processing: {e}")
        except Exception as e:
            logging.error(
                f"[Instagram] Unexpected error during Instagram upload: {e}")
        finally:
            self._delete_video(video_path)
            logging.info("[Instagram] Cleaned up temporary hosted video.")
