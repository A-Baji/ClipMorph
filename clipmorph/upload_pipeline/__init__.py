from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from typing import Any, Dict

from clipmorph.platforms import build_platform_default_config
from clipmorph.policy import validate_artifact

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
                 youtube: bool = False,
                 instagram: bool = False,
                 tiktok: bool = False,
                 twitter: bool = False,
                 max_workers: int = 4):
        """
        Initialize the upload pipeline with platform configurations.
        
        Args:
            youtube: Whether to upload to YouTube
            instagram: Whether to upload to Instagram  
            tiktok: Whether to upload to TikTok
            twitter: Whether to upload to Twitter
            max_workers: Maximum number of parallel uploads
        """
        self.max_workers = max_workers
        self.enabled_platforms: Dict[str, Any] = {}
        self.initialization_errors: Dict[str, str] = {}

        # Initialize enabled platforms
        if youtube:
            try:
                self.enabled_platforms['YouTube'] = YouTubeUploadPipeline()
            except Exception as e:
                self._record_initialization_error('YouTube', e)

        if instagram:
            try:
                self.enabled_platforms['Instagram'] = InstagramUploadPipeline()
            except Exception as e:
                self._record_initialization_error('Instagram', e)

        if tiktok:
            try:
                self.enabled_platforms['TikTok'] = TikTokUploadPipeline()
            except Exception as e:
                self._record_initialization_error('TikTok', e)

        if twitter:
            try:
                self.enabled_platforms['Twitter'] = TwitterUploadPipeline()
            except Exception as e:
                self._record_initialization_error('Twitter', e)

    def _record_initialization_error(self, platform_name: str, error: Exception):
        message = (f"Unable to initialize {platform_name}: {error}. "
                   "Check its credentials and platform configuration.")
        self.initialization_errors[platform_name] = message
        logging.warning(message)

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
        hashtags = ''
        if tags:
            hashtags = ' '.join([
                f"#{tag.strip('#').replace(' ', '')}" for tag in tags
                if tag.strip()
            ])

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

    def _map_common_parameters(self, platform_name: str, title: str,
                               **kwargs) -> Dict:
        """
        Map common parameters to platform-specific parameter names.
        
        Args:
            platform_name: Name of the platform
            **kwargs: Common parameters
            
        Returns:
            Dictionary with platform-specific parameters
        """
        # Extract common parameters with proper defaults
        description = kwargs.get('description', '') or ''
        tags = kwargs.get('tags', kwargs.get('keywords', [])) or []
        platform_defaults = build_platform_default_config()

        # Map to platform-specific parameters
        if platform_name == 'YouTube':
            # YouTube: 100 char title, 5000 char description, 500 char keywords
            yt_title = title[:100] if title and len(title) > 100 else title
            yt_description = description[:5000] if description and len(
                description) > 5000 else (description or 'Uploaded via API')
            yt_keywords = tags[:500] if isinstance(
                tags, str) else tags  # Keep as list for YouTube
            yt_defaults = platform_defaults['youtube']

            return {
                'title': yt_title,
                'description': yt_description,
                'keywords': yt_keywords,
                'privacy_status': yt_defaults.get('privacy_status', 'public'),
                'category': yt_defaults.get('category', '22'),
            }

        elif platform_name == 'Instagram':
            # Instagram: 2200 character limit for caption
            instagram_caption = self._smart_truncate_content(
                title, description, tags, 2200)
            ig_defaults = platform_defaults['instagram']
            return {
                'caption': instagram_caption,
                'share_to_feed': ig_defaults.get('share_to_feed', True),
                'thumb_offset': ig_defaults.get('thumb_offset', 0),
            }

        elif platform_name == 'TikTok':
            # TikTok: 4000 character limit for description
            tiktok_content = self._smart_truncate_content(
                title, description, tags, 4000)
            tk_defaults = platform_defaults['tiktok']
            return {
                'title': tiktok_content,
                'privacy_level': tk_defaults.get('privacy_level', 'PUBLIC_TO_EVERYONE'),
            }

        elif platform_name == 'Twitter':
            # Twitter: 280 character limit
            tweet_content = self._smart_truncate_content(
                title, description, tags, 280)
            return {'tweet_text': tweet_content}

        else:
            return {}

    def _upload_single_platform(self, platform_name: str, pipeline,
                                video_path: str, title: str, **kwargs) -> Dict:
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
            started_at = datetime.now(timezone.utc).isoformat()
            artifact_metadata = kwargs.pop("artifact_metadata", None)
            account_capabilities = kwargs.pop("account_capabilities", None)
            if artifact_metadata is not None:
                decision = validate_artifact(
                    platform_name, artifact_metadata, {"title": title},
                    account_capabilities)
                if decision.blockers:
                    return {
                        'platform': platform_name,
                        'success': False,
                        'result': None,
                        'error': "; ".join(decision.blockers),
                        'status': 'blocked',
                        'policy_version': decision.policy_version,
                        'warnings': decision.warnings,
                        'transformations': decision.transformations,
                        'started_at': started_at,
                        'completed_at': datetime.now(timezone.utc).isoformat(),
                    }
            # Map common parameters to platform-specific ones
            platform_params = self._map_common_parameters(
                platform_name, title, **kwargs)

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
                'error': None,
                'started_at': started_at,
                'completed_at': datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            return {
                'platform': platform_name,
                'success': False,
                'result': None,
                'error': str(e),
                'started_at': started_at,
                'completed_at': datetime.now(timezone.utc).isoformat(),
            }

    def _prepare_interactive_authentication(self, results: Dict[str, Dict]):
        """Complete console-based auth flows before worker threads start."""
        for platform_name, pipeline in list(self.enabled_platforms.items()):
            try:
                if platform_name == 'YouTube' and not pipeline.credentials:
                    pipeline._authenticate()
                elif platform_name == 'TikTok' \
                        and getattr(pipeline, "access_token", None) is None:
                    pipeline._refresh_access_token()
            except Exception as error:
                results[platform_name] = {
                    'platform': platform_name,
                    'success': False,
                    'result': None,
                    'error': str(error),
                }
                del self.enabled_platforms[platform_name]

    def run(self, video_path: str, title: str,
            **platform_kwargs) -> Dict[str, Dict]:
        """
        Upload video to all enabled platforms in parallel.
        
        Args:
            video_path: Path to the video file to upload
            **platform_kwargs: Platform-specific parameters
            
        Returns:
            Dictionary mapping platform names to their upload results
        """
        if not self.enabled_platforms and not self.initialization_errors:
            logging.error("No platforms were requested")
            return {}

        results = {
            platform: {
                'platform': platform,
                'success': False,
                'result': None,
                'error': error,
            }
            for platform, error in self.initialization_errors.items()
        }

        if not self.enabled_platforms:
            return results

        self._prepare_interactive_authentication(results)
        if not self.enabled_platforms:
            return results

        # Use ThreadPoolExecutor for parallel uploads
        with ThreadPoolExecutor(max_workers=min(
                self.max_workers, len(self.enabled_platforms))) as executor:
            # Submit all upload tasks
            future_to_platform = {
                executor.submit(self._upload_single_platform, platform_name, pipeline, video_path, title, **platform_kwargs):
                platform_name
                for platform_name, pipeline in self.enabled_platforms.items()
            }

            # Collect results as they complete
            for future in as_completed(future_to_platform):
                platform_name = future_to_platform[future]
                try:
                    result = future.result()
                    results[platform_name] = result

                    if not result['success']:
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
