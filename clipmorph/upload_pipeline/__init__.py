from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from threading import Lock
from functools import partial
from typing import Any, Dict

from tqdm import tqdm

from clipmorph.platforms import build_platform_default_config
from clipmorph.policy import build_platform_metadata
from clipmorph.policy import validate_artifact

from .platforms import FacebookUploadPipeline
from .platforms import InstagramUploadPipeline
from .platforms import TikTokUploadPipeline
from .platforms import TwitterUploadPipeline
from .platforms import YouTubeUploadPipeline


class UploadPipeline:
    """
    Orchestrates parallel uploads to multiple social media platforms.

    This class maps the common upload parameters onto each platform's adapter
    and executes the uploads. Platform knowledge stays in the owning modules:
    `policy.build_platform_metadata` composes the content fields, and
    `platforms.build_platform_default_config` supplies the plain per-platform
    defaults that are folded into them here.

    Common Parameters (shared across all 4 platforms):
    - title: YouTube title and part of TikTok/Instagram/Twitter content
    - description: YouTube description and part of TikTok/Instagram/Twitter content
    - tags: YouTube keywords and hashtags for TikTok/Instagram/Twitter content

    Platform-Specific Parameter Mapping (owned by clipmorph.policy):
    - YouTube: title, description, keywords (separate fields)
    - Instagram: caption (title + hashtags + description combined)
    - TikTok: title (title + hashtags + description combined)
    - Twitter: tweet_text (title + hashtags + description combined)
    - Facebook: description (title + hashtags + description combined)

    Platform-Specific Overrides:
    Use {platform}_{parameter} format to override any platform parameter:
    - youtube_category: YouTube category (default: see clipmorph.platforms)
    - youtube_privacy_status: YouTube privacy ('public', 'unlisted', 'private')
    - instagram_share_to_feed: Instagram feed sharing (default: True)
    - instagram_thumb_offset: Instagram thumbnail offset (default: 0)
    - tiktok_privacy_level: TikTok privacy ('PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY')
    - facebook_content_kind: Facebook target ('reel' default, or 'video')
    """

    def __init__(self,
                 youtube: bool = False,
                 instagram: bool = False,
                 tiktok: bool = False,
                 twitter: bool = False,
                 facebook: bool = False,
                 max_workers: int = 4,
                 progress_callback=None):
        """
        Initialize the upload pipeline with platform configurations.

        Args:
            youtube: Whether to upload to YouTube
            instagram: Whether to upload to Instagram
            tiktok: Whether to upload to TikTok
            twitter: Whether to upload to Twitter
            facebook: Whether to upload to Facebook
            max_workers: Maximum number of parallel uploads
            progress_callback: Optional callable invoked with
                ``(platform_name, percent)`` after each adapter step update;
                ``None`` keeps the default CLI behavior untouched
        """
        self.max_workers = max_workers
        self._progress_callback = progress_callback
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

        if facebook:
            try:
                self.enabled_platforms['Facebook'] = FacebookUploadPipeline()
            except Exception as e:
                self._record_initialization_error('Facebook', e)

    def _record_initialization_error(self, platform_name: str, error: Exception):
        message = (f"Unable to initialize {platform_name}: {error}. "
                   "Check its credentials and platform configuration.")
        self.initialization_errors[platform_name] = message
        logging.warning(message)

    def _build_combined_progress_bar(self):
        """Create one thread-safe CLI bar fed by per-platform step percents.

        Returns ``(bar, callback)``; adapters report through the callback as
        ``(platform_name, percent)`` at each step, so the shared bar advances
        by each platform's own delta and a postfix lists every percent. Bar
        writes happen under one lock: tqdm is not thread-safe by itself. The
        bar is created with ``disable=None``, so tqdm suppresses it when stderr
        is not a terminal (server logs, redirected output) and the caller's
        progress callback remains the only progress surface there.
        """
        bar = tqdm(
            total=100 * len(self.enabled_platforms),
            # Name the platforms: one bar covers one artifact binding, so the
            # count is this binding's platforms, not the whole job's.
            desc=("Uploading: " + ", ".join(self.enabled_platforms)),
            unit="%",
            bar_format="{l_bar}{bar}| {percentage:3.0f}% "
                       "[{elapsed}<{remaining}] {postfix}",
            ncols=100,
            leave=True,
            position=0,
            disable=None)
        percents = {name: 0 for name in self.enabled_platforms}
        lock = Lock()

        def report(platform_name, percent):
            delta = max(0, percent - percents.get(platform_name, 0))
            with lock:
                percents[platform_name] = percent
                bar.update(delta)
                bar.set_postfix_str(
                    " | ".join(f"{name} {percent_value}%"
                               for name, percent_value in percents.items()))

        return bar, report

    @staticmethod
    def _bar_write(bar, message: str, level: int = logging.INFO) -> None:
        """Print a message above ``bar``, or log it when there is no bar.

        Logging to the same stream a live bar redraws on produces the
        interleaved, half-overwritten lines a parallel run otherwise shows, so
        outcomes go through the bar's writer while it is open.
        """
        if bar is not None:
            bar.write(message)
        else:
            logging.log(level, message)

    def _report_to_bar_and_callback(self, bar_callback, platform_name: str,
                                    external_callback, percent: int) -> None:
        """Feed one adapter's percent into the combined bar and the caller.

        ``bar_callback`` is the combined bar's ``(platform_name, percent)``
        reporter; ``external_callback`` may be ``None``.
        """
        bar_callback(platform_name, percent)
        if external_callback is not None:
            external_callback(platform_name, percent)

    def _map_common_parameters(self, platform_name: str, title: str,
                               **kwargs) -> Dict:
        """
        Map common parameters to platform-specific parameter names.

        Content composition is owned by ``clipmorph.policy``; the per-platform
        defaults from ``clipmorph.platforms`` are folded in here, then the
        legacy ``{platform}_{parameter}`` overrides are applied last so an
        explicit request still wins. This is the single place where upload
        kwargs become the keyword arguments an adapter's ``run`` consumes.

        Args:
            platform_name: Display name of the platform (registry key casing)
            title: Content title
            **kwargs: Common parameters and platform-specific overrides

        Returns:
            Dictionary with platform-specific parameters
        """
        platform = platform_name.lower()
        # Extract common parameters with proper defaults
        description = kwargs.get('description', '') or ''
        tags = kwargs.get('tags', kwargs.get('keywords', [])) or []
        platform_params = dict(build_platform_metadata(
            platform, {'title': title, 'description': description,
                       'tags': tags}))

        # Add the plain per-platform defaults; composed values always win
        for key, value in build_platform_default_config().get(
                platform, {}).items():
            platform_params.setdefault(key, value)

        # Add any platform-specific overrides from kwargs
        platform_specific_key = f"{platform}_"
        for key, value in kwargs.items():
            if key.startswith(platform_specific_key):
                param_name = key[len(platform_specific_key):]
                platform_params[param_name] = value

        return platform_params

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
            # Map common parameters, fold in the per-platform defaults, and
            # apply the platform-specific overrides in one place
            platform_params = self._map_common_parameters(
                platform_name, title, **kwargs)

            # Wire the orchestrator's progress callback onto the adapter so
            # each step update during run forwards (platform_name, percent).
            # A callback the orchestrator already installed (the combined
            # multi-platform bar, which also forwards to the caller's
            # callback) is left alone.
            if self._progress_callback and pipeline.progress_callback is None:
                pipeline.progress_callback = (
                    lambda percent, _name=platform_name:
                    self._progress_callback(_name, percent))

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
                elif platform_name == 'Twitter' \
                        and not getattr(pipeline, "oauth_session", None):
                    pipeline._authenticate()
            except Exception as error:
                results[platform_name] = {
                    'platform': platform_name,
                    'success': False,
                    'result': None,
                    'error': str(error),
                }
                del self.enabled_platforms[platform_name]
                # This failure never reaches the worker-thread reporting, so
                # log it here or the user sees no reason for the skip.
                logging.error(
                    f"{platform_name} authentication failed: {error}")

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

        # Multiple parallel CLI progress bars overwrite each other, so every
        # platform reports into ONE combined bar: total = 100% per platform,
        # postfix shows each platform's percent. The caller's progress callback
        # only records percents (live web progress); it does not draw, so it
        # must not suppress the bar. Both are fed from one per-adapter hook.
        external_callback = self._progress_callback
        combined_bar = None
        if len(self.enabled_platforms) > 1:
            combined_bar, combined_callback = (
                self._build_combined_progress_bar())
            for platform_name, pipeline in self.enabled_platforms.items():
                pipeline.progress_callback = partial(
                    self._report_to_bar_and_callback,
                    combined_callback, platform_name, external_callback)
                pipeline._suppress_cli_progress = True

        # Use ThreadPoolExecutor for parallel uploads
        try:
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

                        if result['success']:
                            # A quiet console between errors looks hung during a
                            # parallel run: say every platform's final outcome.
                            # Through the bar, so the message is not overwritten
                            # by the next redraw.
                            self._bar_write(
                                combined_bar,
                                f"{platform_name} upload completed")
                        else:
                            self._bar_write(
                                combined_bar,
                                f"{platform_name} upload failed: "
                                f"{result['error']}", logging.ERROR)

                    except Exception as e:
                        results[platform_name] = {
                            'platform': platform_name,
                            'success': False,
                            'result': None,
                            'error': f"Future execution failed: {str(e)}"
                        }
                        self._bar_write(
                            combined_bar,
                            f"{platform_name} upload failed with exception: {e}",
                            logging.ERROR)
        finally:
            if combined_bar is not None:
                combined_bar.close()

        return results
