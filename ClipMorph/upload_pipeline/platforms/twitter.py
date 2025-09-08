from contextlib import contextmanager
import logging
import os
import random
import time
from typing import Optional

import requests
from requests_oauthlib import OAuth1Session
import tweepy
from tqdm import tqdm


class TwitterUploadPipeline:
    """
    A pipeline class for handling Twitter/X video uploads, including authentication,
    video upload management, and progress tracking.
    """

    # Constants
    TWITTER_API_BASE_URL = "https://api.twitter.com"
    TWITTER_UPLOAD_BASE_URL = "https://upload.twitter.com"
    
    # Video processing constants
    DEFAULT_PROCESSING_TIME_PER_MB = 8  # seconds
    MIN_PROCESSING_TIME = 10  # seconds
    MAX_PROGRESS_DURING_PROCESSING = 80  # don't complete progress bar during processing
    API_POLL_INTERVAL = 5  # seconds between status checks
    MIN_PROGRESS_INCREMENT = 2.0

    # Retry configuration
    MAX_RETRIES = 3
    RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

    def __init__(self,
                 twitter_api_key=os.getenv("TWITTER_API_KEY"),
                 twitter_api_key_secret=os.getenv("TWITTER_API_KEY_SECRET"),
                 twitter_access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
                 twitter_access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET"),
                 twitter_bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
                 request_timeout=30,
                 processing_timeout=300,
                 max_processing_retries=30):
        """Initialize the Twitter upload pipeline.
        
        Args:
            twitter_api_key (str, optional): Twitter API Key for authentication.
                Defaults to TWITTER_API_KEY environment variable.
            twitter_api_key_secret (str, optional): Twitter API Key Secret for authentication.
                Defaults to TWITTER_API_KEY_SECRET environment variable.
            twitter_access_token (str, optional): Twitter Access Token for API access.
                Defaults to TWITTER_ACCESS_TOKEN environment variable.
            twitter_access_token_secret (str, optional): Twitter Access Token Secret for API access.
                Defaults to TWITTER_ACCESS_TOKEN_SECRET environment variable.
            twitter_bearer_token (str, optional): Twitter Bearer Token for API access.
                Defaults to TWITTER_BEARER_TOKEN environment variable.
            request_timeout (int, optional): Timeout for HTTP requests in seconds.
                Defaults to 30 seconds.
            processing_timeout (int, optional): Timeout for video processing in seconds.
                Defaults to 300 seconds.
            max_processing_retries (int, optional): Maximum retries for processing status checks.
                Defaults to 30 retries.
        """
        # Twitter credentials
        self.api_key = twitter_api_key
        self.api_key_secret = twitter_api_key_secret
        self.access_token = twitter_access_token
        self.access_token_secret = twitter_access_token_secret
        self.bearer_token = twitter_bearer_token
        
        # Configuration
        self.request_timeout = request_timeout
        self.processing_timeout = processing_timeout
        self.max_processing_retries = max_processing_retries
        
        # Runtime state
        self.api = None
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
        
        # Validate required credentials
        if not all([self.api_key, self.api_key_secret, self.access_token, 
                   self.access_token_secret, self.bearer_token]):
            raise ValueError(
                "Missing required Twitter credentials. Provide them as parameters "
                "or set them as environment variables: TWITTER_API_KEY, "
                "TWITTER_API_KEY_SECRET, TWITTER_ACCESS_TOKEN, "
                "TWITTER_ACCESS_TOKEN_SECRET, TWITTER_BEARER_TOKEN")

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
                            api_error = error_data.get('errors', [{}])[0].get('message', '')
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
                            f"retrying in {wait_time:.1f}s: {response.reason}"
                        )
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
                    f"retrying in {wait_time:.1f}s: {e}"
                )
                time.sleep(wait_time)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                wait_time = (2**attempt) + random.uniform(0, 1)
                logging.warning(
                    f"API call failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time:.1f}s: {e}"
                )
                time.sleep(wait_time)

    def _update_progress(self, step_name: str, description: str = ""):
        """Update the progress bar based on step completion."""
        if self.progress_bar and step_name in self.progress_allocations:
            increment = self.progress_allocations[step_name]
            if increment > 0:
                self.progress_bar.update(increment)
            if description:
                self.progress_bar.set_description(f"Twitter: {description}")

    def _authenticate(self):
        """
        Authenticates with Twitter API using provided credentials.
        Returns authenticated API and client objects.
        """
        auth = tweepy.OAuth1UserHandler(
            self.api_key, self.api_key_secret, 
            self.access_token, self.access_token_secret
        )
        self.api = tweepy.API(auth)
        
        self.client = tweepy.Client(
            bearer_token=self.bearer_token,
            consumer_key=self.api_key,
            consumer_secret=self.api_key_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret
        )
        
        # Create OAuth session for status checking
        self.oauth_session = OAuth1Session(
            self.api_key,
            client_secret=self.api_key_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret
        )
        
        self._update_progress("authenticate", "Authenticated with Twitter")
        return self.api, self.client

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
        def upload_with_retry():
            return self.api.media_upload(video_path, media_category="tweet_video")
        
        media = self._retry_request(upload_with_retry)
        media_id = media.media_id_string
        
        self._update_progress("media_upload", f"Media uploaded (ID: {media_id})")
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
            video_size_mb * self.DEFAULT_PROCESSING_TIME_PER_MB
        )
        increment_per_update = max(
            self.MIN_PROGRESS_INCREMENT,
            self.MAX_PROGRESS_DURING_PROCESSING / (estimated_time / self.API_POLL_INTERVAL)
        )
        
        current_progress = self.progress_bar.n if self.progress_bar else 0
        
        while (processing_state != "succeeded" and 
               retry_count < self.max_processing_retries and
               time.time() - start_time < self.processing_timeout):
            
            elapsed = time.time() - start_time
            
            # Update progress description with elapsed time
            if self.progress_bar:
                self.progress_bar.set_description(
                    f"Twitter: Processing video... ({elapsed:.0f}s)"
                )
            
            status_url = f"{self.TWITTER_UPLOAD_BASE_URL}/1.1/media/upload.json?command=STATUS&media_id={media_id}"
            
            def get_status():
                return self.oauth_session.get(status_url)
            
            try:
                response = self._retry_request(get_status)
                media_status = response.json()
                processing_info = media_status.get("processing_info")
                
                if processing_info and processing_info.get("state"):
                    processing_state = processing_info["state"]
                    
                    if processing_state == "succeeded":
                        if self.progress_bar:
                            self.progress_bar.set_description("Twitter: Video processed successfully")
                        break
                    elif processing_state == "failed":
                        error = processing_info.get("error", {})
                        raise RuntimeError(
                            f"Video processing failed: {error.get('message', 'Unknown error')}"
                        )
                    else:
                        # Update progress gradually during processing
                        target_progress = current_progress + min(
                            elapsed * (increment_per_update / self.API_POLL_INTERVAL),
                            self.MAX_PROGRESS_DURING_PROCESSING
                        )
                        
                        if (self.progress_bar and 
                            self.progress_bar.n < target_progress and 
                            self.progress_bar.n < current_progress + self.MAX_PROGRESS_DURING_PROCESSING):
                            increment = min(
                                increment_per_update,
                                target_progress - self.progress_bar.n
                            )
                            if increment > 0:
                                self.progress_bar.update(increment)
                        
                        check_after_secs = processing_info.get("check_after_secs", self.API_POLL_INTERVAL)
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
                raise RuntimeError("Video processing failed or exceeded retry limit")
        
        self._update_progress("video_processing", "Video processing completed")
        return True

    def _create_tweet(self, text: str, media_id: str):
        """
        Create a tweet with the uploaded video.
        """
        def create_with_retry():
            return self.client.create_tweet(text=text, media_ids=[media_id])
        
        response = self._retry_request(create_with_retry)
        tweet_id = response.data['id']
        
        self._update_progress("create_tweet", "Tweet created successfully")
        return tweet_id

    @contextmanager
    def _progress_context(self, total_progress, description="Starting upload"):
        """Context manager for progress bar to ensure proper cleanup."""
        progress_bar = tqdm(
            total=total_progress,
            desc=f"Twitter: {description}",
            unit="%",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}% [{elapsed}<{remaining}]",
            ncols=100,
            leave=True,
            position=0
        )
        self.progress_bar = progress_bar
        try:
            yield progress_bar
        finally:
            progress_bar.close()
            self.progress_bar = None

    def run(self, video_path: str, tweet_text: str = "Twitter/X Upload"):
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
                if not self.api or not self.client:
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
                remaining = total_progress - self.progress_bar.n
                if remaining > 0:
                    self.progress_bar.update(remaining)

                self.progress_bar.set_description("Twitter: Upload successful")

                if self.progress_bar:
                    self.progress_bar.write(
                        f"[Twitter] Successfully posted tweet with ID: {tweet_id}"
                    )

            except Exception as e:
                if self.progress_bar:
                    self.progress_bar.write(f"[Twitter] Upload failed: {e}")
                    self.progress_bar.set_description("Twitter: Upload failed")
                raise

        return tweet_id