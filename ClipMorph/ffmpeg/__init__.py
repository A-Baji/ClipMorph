import os
from pathlib import Path
import platform
import subprocess


def get_ffmpeg_paths():
    """Get platform-specific FFmpeg binary paths."""
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


def configure_ffmpeg():
    """Configure FFmpeg for all dependencies."""
    paths = get_ffmpeg_paths()

    # Set environment variables
    os.environ["FFMPEG_BINARY"] = paths['ffmpeg']
    os.environ["FFPROBE_BINARY"] = paths['ffprobe']

    # Additional environment variables for other libraries
    os.environ[
        "PATH"] = f"{os.path.dirname(paths['ffmpeg'])};{os.environ['PATH']}"

    # Test FFmpeg availability
    try:
        subprocess.run([paths['ffmpeg'], "-version"],
                       capture_output=True,
                       check=True)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise RuntimeError(f"FFmpeg not properly configured: {e}")
