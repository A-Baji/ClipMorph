import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List


class EditingPipeline:

    def __init__(self,
                 input_path,
                 output_dir="output/",
                 muted_audio=None,
                 segments=None,
                 include_cam=True,
                 cam_x=1420,
                 cam_y=790,
                 cam_width=480,
                 cam_height=270,
                 clip_height=1312,
                 ffmpeg_path="ffmpeg",
                 ffprobe_path="ffprobe"):
        self.input_path = input_path
        self.output_dir = output_dir if output_dir.endswith(
            "/") else output_dir + "/"
        self.muted_audio = muted_audio
        self.segments = segments
        self.include_cam = include_cam
        self.cam_x = cam_x
        self.cam_y = cam_y
        self.cam_width = cam_width
        self.cam_height = cam_height
        self.clip_height = clip_height
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.temp_files = []

    def _cleanup_temp_files(self):
        """Clean up temporary files created during processing"""
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except OSError:
                pass
        self.temp_files.clear()

    def _create_temp_file(self, suffix='.mp4'):
        """Create a temporary file and track it for cleanup"""
        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(temp_fd)  # Close the file descriptor, we only need the path
        self.temp_files.append(temp_path)
        return temp_path

    def _get_video_info(self, video_path: str) -> Dict[str, Any]:
        """Get video information using ffprobe"""
        cmd = [
            self.ffprobe_path, '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', video_path
        ]

        try:
            result = subprocess.run(cmd,
                                    capture_output=True,
                                    text=True,
                                    check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            logging.error(f"Error getting video info for {video_path}: {e}")
            logging.error(f"FFprobe stderr: {e.stderr}")
            raise
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing ffprobe output: {e}")
            raise

    def _run_ffmpeg(self, cmd: List[str]) -> None:
        """Run ffmpeg command with error handling"""
        try:
            result = subprocess.run(cmd,
                                    capture_output=True,
                                    text=True,
                                    check=True)
            logging.debug(f"FFmpeg command succeeded: {' '.join(cmd)}")
        except subprocess.CalledProcessError as e:
            logging.error(f"FFmpeg command failed: {' '.join(cmd)}")
            logging.error(f"Error output: {e.stderr}")
            raise

    def _set_audio(self, input_path: str, muted_audio_path: str,
                   output_path: str) -> None:
        """Replace audio in video using ffmpeg"""
        if muted_audio_path and muted_audio_path != input_path:
            # When using a different audio file (muted version)
            cmd = [
                self.ffmpeg_path, '-i', input_path, '-i', muted_audio_path,
                '-c:v', 'copy', '-c:a', 'aac', '-map', '0:v:0', '-map',
                '1:a:0', '-shortest', '-y', output_path
            ]
        else:
            # When using original audio, just copy both streams
            cmd = [
                self.ffmpeg_path, '-i', input_path, '-c:v', 'copy', '-c:a',
                'aac', '-y', output_path
            ]
        self._run_ffmpeg(cmd)

    def _process_camera_feed(self, input_path: str, output_path: str,
                             cam_x: int, cam_y: int, cam_width: int,
                             cam_height: int, crop_width: int) -> int:
        """Process camera feed: crop and resize"""
        # Ensure even dimensions for codec compatibility
        if cam_height % 2 != 0:
            cam_height += 1

        # Calculate resize height maintaining aspect ratio
        aspect_ratio = cam_width / cam_height
        resize_height = int(crop_width / aspect_ratio)
        if resize_height % 2 != 0:
            resize_height += 1

        cmd = [
            self.ffmpeg_path, '-i', input_path, '-vf',
            f'crop={cam_width}:{cam_height}:{cam_x}:{cam_y},scale={crop_width}:{resize_height}',
            '-c:a', 'copy', '-y', output_path
        ]
        self._run_ffmpeg(cmd)
        return resize_height

    def _process_main_clip(self, input_path: str, output_path: str,
                           crop_height: int, cam_h: int,
                           crop_width: int) -> None:
        """Process main clip: resize and crop"""
        main_height = crop_height - cam_h
        if main_height % 2 != 0:
            main_height += 1

        # Get video info to calculate center crop
        video_info = self._get_video_info(input_path)
        video_stream = next(s for s in video_info['streams']
                            if s['codec_type'] == 'video')
        orig_width = int(video_stream['width'])
        orig_height = int(video_stream['height'])

        # Calculate scale to fit height, then crop width to center
        scale_factor = main_height / orig_height
        scaled_width = int(orig_width * scale_factor)

        # Ensure even width
        if scaled_width % 2 != 0:
            scaled_width += 1

        crop_x = max(0, (scaled_width - crop_width) // 2)

        cmd = [
            self.ffmpeg_path, '-i', input_path, '-vf',
            f'scale={scaled_width}:{main_height},crop={crop_width}:{main_height}:{crop_x}:0',
            '-c:a', 'copy', '-y', output_path
        ]
        self._run_ffmpeg(cmd)

    def _blur_background(self, input_path: str, output_path: str,
                         crop_width: int, crop_height: int, cam_h: int,
                         main_clip_path: str) -> None:
        """Create blurred background and combine with main clip"""
        bg_h = cam_h // 2
        if bg_h % 2 != 0:
            bg_h += 1

        # Get video info for centering
        video_info = self._get_video_info(input_path)
        video_stream = next(s for s in video_info['streams']
                            if s['codec_type'] == 'video')
        orig_width = int(video_stream['width'])
        orig_height = int(video_stream['height'])

        # Calculate center crop coordinates - this matches MoviePy's logic exactly
        scale_factor = crop_height / orig_height
        scaled_width = int(orig_width * scale_factor)
        crop_x_center = max(0, (scaled_width - crop_width) // 2)

        # Create the full blurred and cropped background first
        blur_temp = self._create_temp_file()

        cmd = [
            self.ffmpeg_path, '-i', input_path, '-vf',
            f'scale=-1:{crop_height},gblur=sigma=10,crop={crop_width}:{crop_height}:{crop_x_center}:0',
            '-c:a', 'copy', '-y', blur_temp
        ]
        self._run_ffmpeg(cmd)

        # Now extract top and bottom sections from the blurred background
        # and combine with the main clip
        main_height = crop_height - (2 * bg_h)

        filter_complex = f"""
        [0:v]crop={crop_width}:{bg_h}:0:0[top];
        [0:v]crop={crop_width}:{bg_h}:0:{bg_h + main_height}[bottom];
        [top][1:v][bottom]vstack=inputs=3[v]
        """

        cmd = [
            self.ffmpeg_path, '-i', blur_temp, '-i', main_clip_path,
            '-filter_complex',
            filter_complex.strip(), '-map', '[v]', '-map', '0:a?', '-c:a',
            'copy', '-y', output_path
        ]
        self._run_ffmpeg(cmd)

    def _combine_clips_vertical(self, clip1_path: str, clip2_path: str,
                                output_path: str) -> None:
        """Combine two clips vertically while preserving audio"""
        cmd = [
            self.ffmpeg_path,
            '-i',
            clip1_path,
            '-i',
            clip2_path,
            # Complex filter to stack videos vertically
            '-filter_complex',
            '[0:v][1:v]vstack=inputs=2[v]',
            # Map video output from filter
            '-map',
            '[v]',
            # Map audio from first input (camera feed)
            '-map',
            '0:a',
            # Copy audio codec
            '-c:a',
            'copy',
            '-y',
            output_path
        ]
        self._run_ffmpeg(cmd)

    def _overlay_subtitles(self, input_path: str, output_path: str,
                           segments: List[Dict]) -> None:
        """Overlay subtitles using ffmpeg subtitles filter (handles Windows paths)."""
        # If no segments or empty list, just copy
        if not segments:
            cmd = [
                self.ffmpeg_path, '-i', input_path, '-c', 'copy', '-y',
                output_path
            ]
            self._run_ffmpeg(cmd)
            return

        # Filter out invalid segments
        valid_segments = []
        for seg in segments:
            text = (seg.get('text') or '').strip()
            try:
                start = float(seg.get('start', 0))
                end = float(seg.get('end', 0))
                if text and start is not None and end is not None:
                    valid_segments.append({
                        'text': text,
                        'start': start,
                        'end': end
                    })
            except (TypeError, ValueError):
                continue

        if not valid_segments:
            cmd = [
                self.ffmpeg_path, '-i', input_path, '-c', 'copy', '-y',
                output_path
            ]
            self._run_ffmpeg(cmd)
            return

        def _format_timestamp(seconds: float) -> str:
            # SRT needs "hh:mm:ss,mmm"
            total_ms = int(round(seconds * 1000))
            ms = total_ms % 1000
            s = (total_ms // 1000) % 60
            m = (total_ms // 60000) % 60
            h = total_ms // 3600000
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        # Create an SRT file using validated segments
        srt_temp = self._create_temp_file(suffix='.srt')
        with open(srt_temp, 'w', encoding='utf-8') as f:
            for idx, seg in enumerate(valid_segments, 1):
                start_ts = _format_timestamp(seg['start'])
                end_ts = _format_timestamp(seg['end'])
                f.write(f"{idx}\n")
                f.write(f"{start_ts} --> {end_ts}\n")
                # escape any stray newlines already in text
                for line in seg['text'].splitlines():
                    f.write(f"{line}\n")
                f.write("\n")

        # Build safe path for ffmpeg subtitles filter
        abs_path = os.path.abspath(srt_temp)
        # Use forward slashes (safer)
        ff_path = abs_path.replace('\\', '/')

        # Escape colon characters (so C:/ doesn't get treated as option separators)
        # e.g. "C:/Users/..." -> "C\: /Users/..." (single backslash before colon)
        # Note: ffmpeg expects backslash as escape within filter expr.
        ff_path_escaped = ff_path.replace(':', '\\:')

        # For extra safety wrap in single quotes inside the filter expression.
        vf_expr = f"subtitles='{ff_path_escaped}'"

        cmd = [
            self.ffmpeg_path, '-i', input_path, '-vf', vf_expr, '-c:a', 'copy',
            '-y', output_path
        ]

        self._run_ffmpeg(cmd)

    def run(self):
        try:
            logging.info("Starting video processing with ffmpeg...")

            # Extract filename for output
            filename = os.path.splitext(os.path.basename(self.input_path))[0]
            os.makedirs(self.output_dir, exist_ok=True)
            output_path = f"{self.output_dir}{filename}-converted.mp4"

            # Step 1: Set audio
            logging.info("Applying audio to the video...")
            audio_temp = self._create_temp_file()
            self._set_audio(self.input_path, self.muted_audio, audio_temp)

            crop_width = 1080
            crop_height = 1920

            if self.include_cam:
                # Process camera feed
                logging.info("Processing camera feed...")
                cam_temp = self._create_temp_file()
                cam_h = self._process_camera_feed(audio_temp, cam_temp,
                                                  self.cam_x, self.cam_y,
                                                  self.cam_width,
                                                  self.cam_height, crop_width)
            else:
                cam_h = crop_height - self.clip_height

            # Process main clip
            logging.info("Processing main clip...")
            main_temp = self._create_temp_file()
            self._process_main_clip(audio_temp, main_temp, crop_height, cam_h,
                                    crop_width)

            # Combine or blur
            if not self.include_cam:
                logging.info("Blurring background...")
                composited_temp = self._create_temp_file()
                self._blur_background(audio_temp, composited_temp, crop_width,
                                      crop_height, cam_h, main_temp)
            else:
                logging.info("Combining camera feed and main clip...")
                composited_temp = self._create_temp_file()
                self._combine_clips_vertical(cam_temp, main_temp,
                                             composited_temp)

            # Add subtitles
            if self.segments:
                logging.info("Overlaying subtitles...")
                final_temp = self._create_temp_file()
                self._overlay_subtitles(composited_temp, final_temp,
                                        self.segments)
            else:
                logging.info("No subtitles provided, skipping overlay.")
                final_temp = composited_temp

            # Final encode with proper codec settings
            logging.info("Writing final video to file...")
            cmd = [
                self.ffmpeg_path,
                '-i',
                final_temp,
                # Ensure we map all streams
                '-map',
                '0',  # Map all streams from input
                '-c:v',
                'libx264',
                '-preset',
                'medium',
                '-crf',
                '23',
                '-c:a',
                'aac',
                '-b:a',
                '128k',
                '-movflags',
                '+faststart',
                '-y',
                output_path
            ]
            self._run_ffmpeg(cmd)

            logging.info(f"Video processing completed: {output_path}")
            return output_path

        except Exception as e:
            logging.error(f"An error occurred during video processing: {e}")
            raise
        finally:
            # Clean up temporary files
            self._cleanup_temp_files()
