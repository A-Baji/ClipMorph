from abc import ABC, abstractmethod
from contextlib import contextmanager
import logging
import random
import time
from typing import Any, Callable

import requests
from tqdm import tqdm


class BaseUploadPipeline(ABC):
    """
    Abstract base class for upload pipelines providing common functionality
    for retry logic, progress tracking, and progress bar management.
    """
    
    # Default retry configuration (can be overridden by subclasses)
    MAX_RETRIES = 3
    RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
    
    def __init__(self, **kwargs):
        """Initialize base pipeline with common attributes."""
        # Progress bar configuration (must be set by subclasses)
        if not hasattr(self, 'progress_allocations'):
            self.progress_allocations = {}
        if not hasattr(self, 'progress_bar'):
            self.progress_bar = None
        
        # Platform name (must be set by subclasses)
        if not hasattr(self, 'platform_name'):
            self.platform_name = "Unknown"
        
    def _retry_request(self, func: Callable, *args, max_retries=None, **kwargs) -> Any:
        """
        Retry HTTP requests with exponential backoff and enhanced error messages.
        
        This method provides a generic retry mechanism that works with different
        types of API responses and exceptions across platforms.
        
        Args:
            func: The function to retry
            *args: Arguments to pass to the function
            max_retries: Maximum number of retries (defaults to self.MAX_RETRIES)
            **kwargs: Keyword arguments to pass to the function
            
        Returns:
            The result of the successful function call
            
        Raises:
            The last exception encountered if all retries fail
        """
        if max_retries is None:
            max_retries = self.MAX_RETRIES

        last_exception = None
        
        for attempt in range(max_retries):
            try:
                response = func(*args, **kwargs)
                
                # Handle HTTP response objects (requests library)
                if hasattr(response, 'status_code') and hasattr(response, 'ok') and not response.ok:
                    if response.status_code in self.RETRIABLE_STATUS_CODES:
                        # Add helpful context to the error message
                        self._enhance_error_message(response)
                        
                        if attempt == max_retries - 1:
                            response.raise_for_status()
                        
                        # Use exponential backoff with jitter for retriable errors
                        wait_time = (2**attempt) + random.uniform(0, 1)
                        logging.warning(
                            f"Retriable HTTP error {response.status_code} (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {wait_time:.1f}s: {getattr(response, 'reason', 'Unknown error')}"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        # Non-retriable HTTP error, fail immediately
                        response.raise_for_status()
                        
                # Handle Google API HttpError (YouTube)
                elif hasattr(response, 'resp') and hasattr(response.resp, 'status'):
                    if response.resp.status in self.RETRIABLE_STATUS_CODES:
                        if attempt == max_retries - 1:
                            raise response
                        wait_time = (2**attempt) + random.uniform(0, 1)
                        logging.warning(
                            f"Retriable HTTP error {response.resp.status} (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {wait_time:.1f}s: {response}"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        raise response
                
                # If we get here, the request was successful
                return response
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt == max_retries - 1:
                    raise e
                wait_time = (2**attempt) + random.uniform(0, 1)
                logging.warning(
                    f"Request failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time:.1f}s: {e}"
                )
                time.sleep(wait_time)
                
            except Exception as e:
                last_exception = e
                if attempt == max_retries - 1:
                    raise e
                wait_time = (2**attempt) + random.uniform(0, 1)
                logging.warning(
                    f"API call failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time:.1f}s: {e}"
                )
                time.sleep(wait_time)
        
        # This shouldn't be reached, but just in case
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError("Unexpected error in retry logic")

    def _enhance_error_message(self, response):
        """
        Enhance error messages by extracting API-specific error details.
        This method can be overridden by subclasses for platform-specific error parsing.
        
        Args:
            response: HTTP response object to enhance
        """
        try:
            error_data = response.json()
            
            # Generic error message extraction (works for most APIs)
            api_error = None
            
            # Try common error message patterns
            if 'error' in error_data:
                if isinstance(error_data['error'], dict):
                    api_error = error_data['error'].get('message', '')
                elif isinstance(error_data['error'], str):
                    api_error = error_data['error']
            elif 'errors' in error_data and error_data['errors']:
                # Twitter-style errors array
                api_error = error_data['errors'][0].get('message', '')
            elif 'message' in error_data:
                api_error = error_data['message']
            
            if api_error:
                response.reason = f"{getattr(response, 'reason', 'HTTP Error')}: {api_error}"
        except:
            # If we can't parse the error, just continue
            pass

    def _update_progress(self, step_name: str, description: str = ""):
        """
        Update the progress bar based on step completion.
        
        Args:
            step_name: Name of the step (must exist in self.progress_allocations)
            description: Optional description to show in progress bar
        """
        if self.progress_bar and step_name in self.progress_allocations:
            increment = self.progress_allocations[step_name]
            if increment > 0:
                self.progress_bar.update(increment)
            if description:
                self.progress_bar.set_description(f"{self.platform_name}: {description}")

    @contextmanager
    def _progress_context(self, total_progress: int, description: str = "Starting upload"):
        """
        Context manager for progress bar to ensure proper cleanup.
        
        Args:
            total_progress: Total progress value (usually 100)
            description: Initial description for the progress bar
            
        Yields:
            tqdm progress bar object
        """
        progress_bar = tqdm(
            total=total_progress,
            desc=f"{self.platform_name}: {description}",
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

    @abstractmethod
    def run(self, *args, **kwargs):
        """
        Main method to handle the complete upload process.
        Must be implemented by subclasses.
        
        Returns:
            Platform-specific identifier (e.g., media_id, video_id, tweet_id)
        """
        pass

    def _validate_required_attributes(self):
        """
        Validate that required attributes are set by subclasses.
        Should be called during initialization.
        """
        if not self.progress_allocations:
            raise ValueError(f"{self.__class__.__name__} must set progress_allocations")
        
        if self.platform_name == "Unknown":
            raise ValueError(f"{self.__class__.__name__} must set platform_name")
            
        # Validate progress allocations sum to reasonable total
        total = sum(self.progress_allocations.values())
        if not (90 <= total <= 110):  # Allow some flexibility
            logging.warning(f"Progress allocations sum to {total}%, expected around 100%")

    def _complete_progress_bar(self, success: bool = True):
        """
        Complete the progress bar, ensuring it reaches 100% on success.
        
        Args:
            success: Whether the operation was successful
        """
        if not self.progress_bar:
            return
            
        if success:
            # Complete to 100% only on success
            total_progress = sum(self.progress_allocations.values())
            remaining = total_progress - self.progress_bar.n
            if remaining > 0:
                self.progress_bar.update(remaining)
            self.progress_bar.set_description(f"{self.platform_name}: Upload complete")
        else:
            # Show error state without completing to 100%
            self.progress_bar.set_description(f"{self.platform_name}: Upload failed")