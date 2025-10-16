# ClipMorph

A powerful CLI tool for converting gaming videos into short-form content and automatically uploading to YouTube Shorts, Instagram Reels, TikTok, and Twitter/X.

## Features

- **Intelligent Video Processing**
  - Automatic audio transcription with speaker diarization
  - Profanity detection and censoring (audio muting + subtitle filtering)
  - Multi-speaker subtitle overlays with color coding
  - Camera feed extraction and placement
  - Vertical format optimization (9:16 aspect ratio)
  - Blurred background support

- **Multi-Platform Upload**
  - Parallel uploads to YouTube, Instagram, TikTok, and Twitter
  - Platform-specific parameter mapping
  - Progress tracking with detailed status updates
  - Automatic retry logic with exponential backoff

- **Flexible Configuration**
  - Command-line arguments
  - YAML/JSON config files
  - Environment variable support

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Credits

- Created by Adib Baji
- Uses Whisper for transcription
- Uses PyAnnote for speaker diarization
- FFmpeg for video processing