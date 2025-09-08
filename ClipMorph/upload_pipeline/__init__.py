from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Dict

from .platforms import InstagramUploadPipeline
from .platforms import TikTokUploadPipeline
from .platforms import TwitterUploadPipeline
from .platforms import YouTubeUploadPipeline


class UploadPipeline:
    """
    Orchestrates parallel uploads to multiple social media platforms.
    
    This class intelligently maps common parameters across platforms:
    
    Common Parameters (shared across all 4 platforms):
    - title: Used as YouTube title and part of TikTok/Instagram/Twitter content
    - description: Used as YouTube description and part of TikTok/Instagram/Twitter content  
    - tags/keywords: Used as YouTube keywords and hashtags for TikTok/Instagram/Twitter content
    
    Platform-Specific Parameter Mapping:
    - YouTube: title, description, keywords (separate fields)
    - Instagram: caption (title + description + tags combined)
    - TikTok: title (title + description + tags combined)
    - Twitter: tweet_text (title + description + tags combined)
    
    Platform-Specific Overrides:
    Use {platform}_{parameter} format to override any platform parameter:
    - youtube_category: YouTube category (default: '20' - Gaming)
    - youtube_privacy_status: YouTube privacy ('public', 'unlisted', 'private')
    - instagram_share_to_feed: Instagram feed sharing (default: True)
    - instagram_thumb_offset: Instagram thumbnail offset (default: 0)
    - tiktok_privacy_level: TikTok privacy ('PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY')
    """

    def __init__(self,
                 youtube_enabled: bool = True,
                 instagram_enabled: bool = True,
                 tiktok_enabled: bool = True,
                 twitter_enabled: bool = True,
                 max_workers: int = 4):
        """
        Initialize the upload pipeline with platform configurations.
        
        Args:
            youtube_enabled: Whether to upload to YouTube
            instagram_enabled: Whether to upload to Instagram  
            tiktok_enabled: Whether to upload to TikTok
            twitter_enabled: Whether to upload to Twitter
            max_workers: Maximum number of parallel uploads
        """
        self.max_workers = max_workers
        self.enabled_platforms = {}

        # Initialize enabled platforms
        if youtube_enabled:
            try:
                self.enabled_platforms['YouTube'] = YouTubeUploadPipeline()
            except Exception as e:
                logging.warning(f"Failed to initialize YouTube pipeline: {e}")

        if instagram_enabled:
            try:
                self.enabled_platforms['Instagram'] = InstagramUploadPipeline()
            except Exception as e:
                logging.warning(
                    f"Failed to initialize Instagram pipeline: {e}")

        if tiktok_enabled:
            try:
                self.enabled_platforms['TikTok'] = TikTokUploadPipeline()
            except Exception as e:
                logging.warning(f"Failed to initialize TikTok pipeline: {e}")

        if twitter_enabled:
            try:
                self.enabled_platforms['Twitter'] = TwitterUploadPipeline()
            except Exception as e:
                logging.warning(f"Failed to initialize Twitter pipeline: {e}")

    def _smart_truncate_content(self, title: str, description: str, tags: list,
                                max_chars: int) -> str:
        """
        Smart truncate content prioritizing title > tags > description.
        
        Args:
            title: Content title
            description: Content description  
            tags: List of tags/keywords
            max_chars: Maximum character limit
            
        Returns:
            Truncated combined content
        """
        # Convert tags to hashtags
        hashtags = ' '.join([
            f"#{tag.strip('#').replace(' ', '')}" for tag in tags
            if tag.strip()
        ])

        # Always keep the title
        if len(title) >= max_chars:
            return title[:max_chars].strip()

        # Try title + hashtags
        title_tags = f"{title}\n\n{hashtags}".strip() if hashtags else title
        if len(title_tags) <= max_chars:
            # If we have room, try to add description
            if description:
                full_content = f"{title}\n\n{description}\n\n{hashtags}".strip(
                ) if hashtags else f"{title}\n\n{description}".strip()
                if len(full_content) <= max_chars:
                    return full_content
                else:
                    # Truncate description to fit
                    available_for_desc = max_chars - len(
                        title_tags) - 4  # 4 for "\n\n" separators
                    if available_for_desc > 10:  # Only add description if we have meaningful space
                        truncated_desc = description[:
                                                     available_for_desc].strip(
                                                     )
                        return f"{title}\n\n{truncated_desc}\n\n{hashtags}".strip(
                        ) if hashtags else f"{title}\n\n{truncated_desc}".strip(
                        )
            return title_tags
        else:
            # Truncate hashtags to fit with title
            available_for_tags = max_chars - len(title) - 4  # 4 for "\n\n"
            if available_for_tags > 5:  # Need space for at least one hashtag
                truncated_hashtags = hashtags[:available_for_tags].strip()
                return f"{title}\n\n{truncated_hashtags}".strip()
            else:
                return title

    def _map_common_parameters(self, platform_name: str, **kwargs) -> Dict:
        """
        Map common parameters to platform-specific parameter names.
        
        Args:
            platform_name: Name of the platform
            **kwargs: Common parameters
            
        Returns:
            Dictionary with platform-specific parameters
        """
        # Extract common parameters
        title = kwargs.get('title', 'Upload')
        description = kwargs.get('description', '')
        tags = kwargs.get('tags', kwargs.get('keywords',
                                             []))  # Support both names

        # Map to platform-specific parameters
        if platform_name == 'YouTube':
            # YouTube: 100 char title, 5000 char description, 500 char keywords
            yt_title = title[:100] if len(title) > 100 else title
            yt_description = description[:5000] if len(
                description) > 5000 else (description or 'Uploaded via API')
            yt_keywords = tags[:500] if isinstance(
                tags, str) else tags  # Keep as list for YouTube

            return {
                'title': yt_title,
                'description': yt_description,
                'keywords': yt_keywords,
                'privacy_status': 'public'  # Default, can be overridden
            }

        elif platform_name == 'Instagram':
            # Instagram: 2200 character limit for caption
            instagram_caption = self._smart_truncate_content(
                title, description, tags, 2200)
            return {
                'caption': instagram_caption,
                'share_to_feed': True  # Default, can be overridden
            }

        elif platform_name == 'TikTok':
            # TikTok: 4000 character limit for description
            tiktok_content = self._smart_truncate_content(
                title, description, tags, 4000)
            return {
                'title': tiktok_content,
                'privacy_level':
                'PUBLIC_TO_EVERYONE'  # Default, can be overridden
            }

        elif platform_name == 'Twitter':
            # Twitter: 280 character limit
            tweet_content = self._smart_truncate_content(
                title, description, tags, 280)
            return {'tweet_text': tweet_content}

        else:
            return {}

    def _upload_single_platform(self, platform_name: str, pipeline,
                                video_path: str, **kwargs) -> Dict:
        """
        Upload to a single platform and return results.
        
        Args:
            platform_name: Name of the platform
            pipeline: Platform upload pipeline instance
            video_path: Path to video file
            **kwargs: Common upload parameters
            
        Returns:
            Dictionary with platform name, success status, and result/error
        """
        try:
            # Map common parameters to platform-specific ones
            platform_params = self._map_common_parameters(
                platform_name, **kwargs)

            # Add platform-specific defaults and overrides
            if platform_name == 'YouTube':
                platform_params.setdefault('category',
                                           '22')  # Default: People & Blogs
            elif platform_name == 'Instagram':
                platform_params.setdefault('thumb_offset',
                                           0)  # Default: beginning of video

            # Add any platform-specific overrides from kwargs
            platform_specific_key = f"{platform_name.lower()}_"
            for key, value in kwargs.items():
                if key.startswith(platform_specific_key):
                    param_name = key[len(platform_specific_key):]
                    platform_params[param_name] = value

            # Call the platform's run method
            result = pipeline.run(video_path=video_path, **platform_params)

            return {
                'platform': platform_name,
                'success': True,
                'result': result,
                'error': None
            }

        except Exception as e:
            return {
                'platform': platform_name,
                'success': False,
                'result': None,
                'error': str(e)
            }

    def run(self, video_path: str, **platform_kwargs) -> Dict[str, Dict]:
        """
        Upload video to all enabled platforms in parallel.
        
        Args:
            video_path: Path to the video file to upload
            **platform_kwargs: Platform-specific parameters
            
        Returns:
            Dictionary mapping platform names to their upload results
        """
        if not self.enabled_platforms:
            logging.error(
                "No platforms are enabled or successfully initialized")
            return {}

        results = {}

        # Use ThreadPoolExecutor for parallel uploads
        with ThreadPoolExecutor(max_workers=min(
                self.max_workers, len(self.enabled_platforms))) as executor:
            # Submit all upload tasks
            future_to_platform = {
                executor.submit(self._upload_single_platform, platform_name, pipeline, video_path, **platform_kwargs):
                platform_name
                for platform_name, pipeline in self.enabled_platforms.items()
            }

            # Collect results as they complete
            for future in as_completed(future_to_platform):
                platform_name = future_to_platform[future]
                try:
                    result = future.result()
                    results[platform_name] = result

                    if result['success']:
                        logging.info(
                            f"{platform_name} upload completed successfully")
                    else:
                        logging.error(
                            f"{platform_name} upload failed: {result['error']}"
                        )

                except Exception as e:
                    results[platform_name] = {
                        'platform': platform_name,
                        'success': False,
                        'result': None,
                        'error': f"Future execution failed: {str(e)}"
                    }
                    logging.error(
                        f"{platform_name} upload failed with exception: {e}")

        return results
