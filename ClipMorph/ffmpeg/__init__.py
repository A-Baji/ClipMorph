import json
import logging
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple


class FFmpegError(Exception):
    """Custom exception for FFmpeg-related errors."""
    pass


class FFmpegConfig:
    """Centralized FFmpeg configuration and path management."""

    _instance = None
    _ffmpeg_path = None
    _ffprobe_path = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_paths()
        return cls._instance

    def _initialize_paths(self):
        """Initialize FFmpeg and FFprobe paths."""
        # Try bundled binaries first (project includes them)
        bundled_paths = self._get_bundled_paths()

        # Check if bundled binaries exist
        if (os.path.exists(bundled_paths['ffmpeg'])
                and os.path.exists(bundled_paths['ffprobe'])):
            self._ffmpeg_path = bundled_paths['ffmpeg']
            self._ffprobe_path = bundled_paths['ffprobe']
        else:
            # Fall back to system PATH if bundled binaries not found
            self._ffmpeg_path = shutil.which('ffmpeg')
            self._ffprobe_path = shutil.which('ffprobe')

        # Validate paths
        self._validate_binaries()

        # Set environment variables for other libraries
        self._configure_environment()

    def _get_bundled_paths(self) -> Dict[str, str]:
        """Get bundled FFmpeg binary paths."""
        root_dir = Path(__file__).parent.parent
        system = platform.system().lower()
        if system == 'darwin':
            system = 'mac'

        ffmpeg_dir = root_dir / 'ffmpeg' / system
        exe_ext = '.exe' if system == 'windows' else ''

        return {
            'ffmpeg': str(ffmpeg_dir / f'ffmpeg{exe_ext}'),
            'ffprobe': str(ffmpeg_dir / f'ffprobe{exe_ext}')
        }

    def _validate_binaries(self):
        """Validate that FFmpeg binaries are functional."""
        for name, path in [('ffmpeg', self._ffmpeg_path),
                           ('ffprobe', self._ffprobe_path)]:
            if not path or not Path(path).exists():
                raise FFmpegError(f"{name} binary not found at: {path}")

            try:
                result = subprocess.run([path, "-version"],
                                        capture_output=True,
                                        text=True,
                                        timeout=10,
                                        check=True)
                logging.debug(f"{name} version check passed")
            except (subprocess.SubprocessError,
                    subprocess.TimeoutExpired) as e:
                raise FFmpegError(f"{name} binary validation failed: {e}")

    def _configure_environment(self):
        """Configure environment variables for FFmpeg."""
        os.environ["FFMPEG_BINARY"] = self._ffmpeg_path
        os.environ["FFPROBE_BINARY"] = self._ffprobe_path

        # Add FFmpeg directory to PATH
        ffmpeg_dir = str(Path(self._ffmpeg_path).parent)
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ[
                "PATH"] = f"{ffmpeg_dir}{os.pathsep}{os.environ.get('PATH', '')}"

    @property
    def ffmpeg_path(self) -> str:
        return self._ffmpeg_path

    @property
    def ffprobe_path(self) -> str:
        return self._ffprobe_path

    def get_paths(self) -> Tuple[str, str]:
        """Get FFmpeg and FFprobe paths as tuple (backward compatibility)."""
        return self._ffmpeg_path, self._ffprobe_path


class FFmpegRunner:
    """Centralized FFmpeg command execution with proper error handling."""

    def __init__(self):
        self.config = FFmpegConfig()
        self.temp_files = []

    def create_temp_file(self, suffix: str = '.mp4') -> str:
        """Create a temporary file and track it for cleanup."""
        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(temp_fd)
        self.temp_files.append(temp_path)
        return temp_path

    def cleanup_temp_files(self):
        """Clean up all tracked temporary files."""
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except OSError:
                pass
        self.temp_files.clear()

    def run_ffmpeg(
            self,
            cmd: List[str],
            timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """
        Run FFmpeg command with comprehensive error handling.
        
        Args:
            cmd: Complete FFmpeg command as list
            timeout: Optional timeout in seconds
            
        Returns:
            CompletedProcess result
            
        Raises:
            FFmpegError: If command fails with user-friendly error message
        """
        if not cmd or cmd[0] != self.config.ffmpeg_path:
            raise FFmpegError("Invalid FFmpeg command")

        logging.debug(f"Running FFmpeg: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd,
                                    capture_output=True,
                                    text=True,
                                    timeout=timeout,
                                    check=True)
            return result

        except subprocess.TimeoutExpired:
            raise FFmpegError(
                f"FFmpeg operation timed out after {timeout} seconds")

        except subprocess.CalledProcessError as e:
            error_message = self._parse_ffmpeg_error(e.stderr)
            raise FFmpegError(f"FFmpeg failed: {error_message}")

    def run_ffprobe(self, cmd: List[str]) -> Dict[str, Any]:
        """
        Run FFprobe command and return parsed JSON output.
        
        Args:
            cmd: Complete FFprobe command as list
            
        Returns:
            Parsed JSON output as dictionary
        """
        if not cmd or cmd[0] != self.config.ffprobe_path:
            raise FFmpegError("Invalid FFprobe command")

        try:
            result = subprocess.run(cmd,
                                    capture_output=True,
                                    text=True,
                                    timeout=30,
                                    check=True)
            return json.loads(result.stdout)

        except subprocess.TimeoutExpired:
            raise FFmpegError("FFprobe operation timed out")

        except subprocess.CalledProcessError as e:
            raise FFmpegError(f"FFprobe failed: {e.stderr.strip()}")

        except json.JSONDecodeError as e:
            raise FFmpegError(f"Failed to parse FFprobe output: {e}")

    def _parse_ffmpeg_error(self, stderr: str) -> str:
        """Extract meaningful error message from FFmpeg stderr."""
        if not stderr:
            return "Unknown error (no error output)"

        lines = stderr.strip().split('\n')

        # Common error patterns to look for
        error_patterns = [
            "No such file or directory",
            "Invalid data found",
            "does not contain any stream",
            "Permission denied",
            "Disk full",
            "could not find codec",
            "Invalid argument",
        ]

        # Look for lines containing error patterns
        for line in reversed(lines):
            line_lower = line.lower()
            if any(pattern.lower() in line_lower
                   for pattern in error_patterns):
                return line.strip()

        # Look for lines starting with error indicators
        for line in reversed(lines):
            if any(
                    line.startswith(prefix)
                    for prefix in ['Error:', '[error]', 'ffmpeg:']):
                return line.strip()

        # Fall back to last non-empty line
        for line in reversed(lines):
            if line.strip():
                return line.strip()

        return "Unknown FFmpeg error"

    def get_video_info(self, video_path: str) -> Dict[str, Any]:
        """Get comprehensive video information using FFprobe."""
        cmd = [
            self.config.ffprobe_path, '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', video_path
        ]

        return self.run_ffprobe(cmd)

    def extract_audio(self, input_path: str, output_path: str = None) -> str:
        """Extract audio from video file."""
        if not output_path:
            output_path = self.create_temp_file('.wav')

        cmd = [
            self.config.ffmpeg_path,
            '-i',
            input_path,
            '-vn',  # No video
            '-acodec',
            'pcm_s16le',
            '-ar',
            '44100',
            '-ac',
            '2',
            '-y',
            output_path
        ]

        self.run_ffmpeg(cmd)
        return output_path

    def validate_input_file(self, file_path: str):
        """Validate that input file exists and is a valid media file."""
        if not os.path.exists(file_path):
            raise FFmpegError(f"Input file does not exist: {file_path}")

        if os.path.getsize(file_path) == 0:
            raise FFmpegError(f"Input file is empty: {file_path}")

        try:
            info = self.get_video_info(file_path)
            if not info.get('streams'):
                raise FFmpegError(f"No valid streams found in: {file_path}")
        except FFmpegError:
            raise FFmpegError(f"Invalid or corrupted media file: {file_path}")


# Convenience functions for backward compatibility
def get_ffmpeg_paths() -> Tuple[str, str]:
    """Get FFmpeg and FFprobe paths (backward compatibility)."""
    config = FFmpegConfig()
    return config.get_paths()


def configure_ffmpeg():
    """Initialize FFmpeg configuration."""
    try:
        config = FFmpegConfig()
        logging.info(f"FFmpeg configured: {config.ffmpeg_path}")
    except FFmpegError as e:
        logging.error(f"Failed to configure FFmpeg: {e}")
        raise
