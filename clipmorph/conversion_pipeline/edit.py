import logging
import os
import uuid
from typing import Any, Dict, List

from clipmorph.ffmpeg import FFmpegError
from clipmorph.ffmpeg import FFmpegRunner
from clipmorph.job import default_output_dir, resolve_output_dir


class EditingPipeline:

    def __init__(self,
                 input_path,
                 output_dir=None,
                 muted_audio=None,
                 segments=None,
                 include_cam=True,
                 cam_x=1420,
                 cam_y=790,
                 cam_width=480,
                 cam_height=270,
                 clip_height=1312,
                 layout=None,
                 ffmpeg_runner=None):
        self.input_path = input_path
        self.output_dir = str(resolve_output_dir(
            output_dir, default_output_dir().parent)) + "/"
        self.muted_audio = muted_audio
        self.segments = segments
        self.include_cam = include_cam
        self.cam_x = cam_x
        self.cam_y = cam_y
        self.cam_width = cam_width
        self.cam_height = cam_height
        self.clip_height = clip_height
        self.layout = layout
        self.ffmpeg_runner = ffmpeg_runner or FFmpegRunner()

    def _get_video_info(self, video_path: str) -> Dict[str, Any]:
        """Get video information using ffprobe"""
        return self.ffmpeg_runner.get_video_info(video_path)

    def _set_audio(self, input_path: str, muted_audio_path: str,
                   output_path: str) -> None:
        """Replace audio in video using ffmpeg"""
        if muted_audio_path and muted_audio_path != input_path:
            # When using a different audio file (muted version)
            cmd = [
                self.ffmpeg_runner.config.ffmpeg_path, '-i', input_path, '-i',
                muted_audio_path, '-c:v', 'copy', '-c:a', 'aac', '-map',
                '0:v:0', '-map', '1:a:0', '-shortest', '-y', output_path
            ]
        else:
            # When using original audio, just copy both streams
            cmd = [
                self.ffmpeg_runner.config.ffmpeg_path, '-i', input_path,
                '-c:v', 'copy', '-c:a', 'aac', '-y', output_path
            ]
        self.ffmpeg_runner.run_ffmpeg(cmd)

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
            self.ffmpeg_runner.config.ffmpeg_path, '-i', input_path, '-vf',
            f'crop={cam_width}:{cam_height}:{cam_x}:{cam_y},scale={crop_width}:{resize_height}',
            '-c:a', 'copy', '-y', output_path
        ]
        self.ffmpeg_runner.run_ffmpeg(cmd)
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
            self.ffmpeg_runner.config.ffmpeg_path, '-i', input_path, '-vf',
            f'scale={scaled_width}:{main_height},crop={crop_width}:{main_height}:{crop_x}:0',
            '-c:a', 'copy', '-y', output_path
        ]
        self.ffmpeg_runner.run_ffmpeg(cmd)

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

        # Calculate center crop coordinates
        scale_factor = crop_height / orig_height
        scaled_width = int(orig_width * scale_factor)
        crop_x_center = max(0, (scaled_width - crop_width) // 2)

        # Create the full blurred and cropped background first
        blur_temp = self.ffmpeg_runner.create_temp_file()

        cmd = [
            self.ffmpeg_runner.config.ffmpeg_path, '-i', input_path, '-vf',
            f'scale=-1:{crop_height},gblur=sigma=10,crop={crop_width}:{crop_height}:{crop_x_center}:0',
            '-c:a', 'copy', '-y', blur_temp
        ]
        self.ffmpeg_runner.run_ffmpeg(cmd)

        # Now extract top and bottom sections from the blurred background
        # and combine with the main clip
        main_height = crop_height - (2 * bg_h)

        filter_complex = f"""
        [0:v]crop={crop_width}:{bg_h}:0:0[top];
        [0:v]crop={crop_width}:{bg_h}:0:{bg_h + main_height}[bottom];
        [top][1:v][bottom]vstack=inputs=3[v]
        """

        cmd = [
            self.ffmpeg_runner.config.ffmpeg_path, '-i', blur_temp, '-i',
            main_clip_path, '-filter_complex',
            filter_complex.strip(), '-map', '[v]', '-map', '0:a?', '-c:a',
            'copy', '-y', output_path
        ]
        self.ffmpeg_runner.run_ffmpeg(cmd)

    def _combine_clips_vertical(self, clip1_path: str, clip2_path: str,
                                output_path: str) -> None:
        """Combine two clips vertically while preserving audio"""
        cmd = [
            self.ffmpeg_runner.config.ffmpeg_path, '-i', clip1_path, '-i',
            clip2_path, '-filter_complex', '[0:v][1:v]vstack=inputs=2[v]',
            '-map', '[v]', '-map', '0:a', '-c:a', 'copy', '-y', output_path
        ]
        self.ffmpeg_runner.run_ffmpeg(cmd)

    def _overlay_subtitles(self, input_path: str, output_path: str,
                           segments: List[Dict]) -> None:
        """Overlay subtitles using ffmpeg subtitles filter"""
        # If no segments or empty list, just copy
        if not segments:
            cmd = [
                self.ffmpeg_runner.config.ffmpeg_path, '-i', input_path, '-c',
                'copy', '-y', output_path
            ]
            self.ffmpeg_runner.run_ffmpeg(cmd)
            return

        # Filter out invalid segments
        valid_segments = []
        for seg in segments:
            text = (seg.get('text') or '').strip()
            try:
                start = float(seg.get('start', 0))
                end = float(seg.get('end', 0))
                speaker = seg.get('speaker', 'default')
                if text and start is not None and end is not None:
                    valid_segments.append({
                        'text': text,
                        'start': start,
                        'end': end,
                        'speaker': speaker
                    })
            except (TypeError, ValueError):
                continue

        if not valid_segments:
            cmd = [
                self.ffmpeg_runner.config.ffmpeg_path, '-i', input_path, '-c',
                'copy', '-y', output_path
            ]
            self.ffmpeg_runner.run_ffmpeg(cmd)
            return

        def _format_timestamp(seconds: float) -> str:
            # SRT needs "hh:mm:ss,mmm"
            total_ms = int(round(seconds * 1000))
            ms = total_ms % 1000
            s = (total_ms // 1000) % 60
            m = (total_ms // 60000) % 60
            h = total_ms // 3600000
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        COLOR_PALETTE = [
            '#00BFFF',  # Deep Sky Blue
            '#FFD700',  # Gold
            '#32CD32',  # Lime Green
            '#FF4500',  # Orange Red
            '#7B68EE',  # Medium Slate Blue
            '#FF69B4',  # Hot Pink
            '#FFA500',  # Orange
            '#ADFF2F',  # Green Yellow
            '#40E0D0',  # Turquoise
            '#FFFFFF'  # White (default)
        ]

        # Get unique speakers from segments and sort for consistent colors
        speakers = sorted(
            {seg['speaker']
             for seg in valid_segments if seg.get('speaker')})

        # Create color mapping for speakers
        speaker_colors = {}
        for idx, speaker in enumerate(speakers):
            if idx < len(COLOR_PALETTE) - 1:
                speaker_colors[speaker] = COLOR_PALETTE[idx]
            else:
                speaker_colors[speaker] = COLOR_PALETTE[-1]  # Default to white

        # Create an SRT file using validated segments with color tags
        srt_temp = self.ffmpeg_runner.create_temp_file(suffix='.srt')
        with open(srt_temp, 'w', encoding='utf-8') as f:
            for idx, seg in enumerate(valid_segments, 1):
                start_ts = _format_timestamp(seg['start'])
                end_ts = _format_timestamp(seg['end'])
                speaker = seg.get('speaker', 'default')
                color = speaker_colors.get(speaker, COLOR_PALETTE[-1])

                f.write(f"{idx}\n")
                f.write(f"{start_ts} --> {end_ts}\n")
                # Add color formatting to each line
                for line in seg['text'].splitlines():
                    f.write(f'<font color="{color}">{line}</font>\n')
                f.write("\n")
        # Get path to Roboto font
        font_path = os.path.join(os.path.dirname(__file__), '..', 'resources',
                                 'fonts', 'roboto', 'Roboto-Bold.ttf')
        # Normalize path for ffmpeg
        font_path = os.path.abspath(font_path).replace('\\', '/').replace(
            ':', '\\:')

        subtitle_style = (
            f'Fontfile={font_path},'  # Use embedded font file
            'Fontname=Roboto,'  # Font family name
            'Fontsize=18,'  # Font size
            'PrimaryColour=&Hffffff,'  # Text color (white)
            'OutlineColour=&H000000,'  # Outline color (black)
            'BackColour=&H80000000,'  # Background color (semi-transparent)
            'Bold=1,'  # Bold text
            'Outline=1,'  # Outline width
            'Shadow=1,'  # Shadow size
            'Blur=0.6,'  # Add slight blur for anti-aliasing
            'MarginV=40,'  # Vertical margin from bottom
            'Spacing=0.2'  # Add slight spacing between letters
        )

        # Build safe path for ffmpeg subtitles filter with lanczos scaling
        abs_path = os.path.abspath(srt_temp)
        ff_path = abs_path.replace('\\', '/').replace(':', '\\:')

        # Combine subtitle overlay with lanczos scaling
        vf_expr = (
            f"scale=flags=lanczos,subtitles='{ff_path}':force_style='{subtitle_style}',"
            "scale=flags=lanczos"  # Second scale pass for final refinement
        )

        cmd = [
            self.ffmpeg_runner.config.ffmpeg_path,
            '-i',
            input_path,
            '-vf',
            vf_expr,
            '-c:v',
            'libx264',  # Use H.264 codec
            '-preset',
            'slow',  # Higher quality preset
            '-crf',
            '18',  # Higher quality CRF (lower = better)
            '-c:a',
            'copy',  # Copy audio stream
            '-y',
            output_path
        ]

        self.ffmpeg_runner.run_ffmpeg(cmd)

    def _apply_layout(self, input_path: str, output_path: str) -> None:
        """Apply composable crop and caption layers to the vertical canvas."""
        layout = self.layout or {}
        crop = layout.get("crop") or {}
        caption = layout.get("caption") or {}
        filters = ["[0:v]null[base]"]
        current = "base"

        def region_y(region: str, height: int) -> str:
            if region == "bottom":
                return f"1920-{height}"
            if region == "center":
                return f"(1920-{height})/2"
            return "0"

        if crop.get("enabled"):
            source = crop["source"]
            placement = crop.get("placement", {})
            mode = placement.get("mode", "fit")
            if mode == "none":
                crop_size = f"{source['width']}:{source['height']}"
            elif mode == "stretch":
                dimensions = placement["dimensions"]
                crop_size = f"{dimensions['width']}:{dimensions['height']}"
            else:
                crop_size = "1080:-2"
            crop_height = source["height"] if mode == "none" else (
                placement.get("dimensions", {}).get("height", 608))
            crop_y = region_y(placement.get("region", "top"), crop_height)
            filters.append(
                f"[0:v]crop={source['width']}:{source['height']}:{source['x']}:{source['y']},"
                f"scale={crop_size}[crop]")
            if placement.get("mode", "fit") == "none":
                filters.append(f"[base][crop]overlay=(W-w)/2:{crop_y}[withcrop]")
            else:
                filters.append(f"[base][crop]overlay=(W-w)/2:{crop_y}[withcrop]")
            current = "withcrop"

        if caption.get("enabled"):
            text_items = caption.get("items")
            if text_items is None:
                text_items = [{"text": caption.get("text", ""), "range": [0, None]}]
            for index, item in enumerate(text_items):
                text = str(item.get("text", "")).replace("'", "\\'").replace(":", "\\:")
                start, end = item["range"]
                enable = f":enable='gte(t,{start})'"
                if end is not None:
                    enable = f":enable='between(t,{start},{end})'"
                if caption.get("mode", "overlay") == "background":
                    dimensions = caption.get("dimensions", {})
                    panel_width = dimensions.get("width", 1080)
                    panel_height = dimensions.get("height", 608)
                    panel = caption.get("panel", {})
                    panel_color = panel.get("color", "black")
                    panel_opacity = panel.get("opacity", 0.65)
                    padding = caption.get("padding", {})
                    padding_x = padding.get("left", 64)
                    padding_y = padding.get("top", 48)
                    text_style = caption.get("typography", {})
                    font_size = text_style.get("size", 64)
                    font_color = text_style.get("color", "white")
                    font_file = text_style.get("font_file")
                    font_option = f":fontfile='{font_file}'" if font_file else ""
                    panel_y = region_y(caption.get("region", "top"), panel_height)
                    filters.append(
                        f"[{current}]drawbox=x=(iw-{panel_width})/2:y={panel_y}:w={panel_width}:h={panel_height}:"
                        f"color={panel_color}@{panel_opacity}:t=fill[panel{index}];"
                        f"[panel{index}]drawtext=text='{text}':x=(w-text_w)/2:y={panel_y}+{padding_y}:"
                        f"fontsize={font_size}:fontcolor={font_color}{font_option}{enable}[caption{index}]")
                else:
                    text_style = caption.get("typography", {})
                    font_size = text_style.get("size", 64)
                    font_color = text_style.get("color", "white")
                    font_file = text_style.get("font_file")
                    font_option = f":fontfile='{font_file}'" if font_file else ""
                    overlay_height = caption.get("dimensions", {}).get("height", 120)
                    caption_y = region_y(caption.get("region", "top"), overlay_height)
                    filters.append(
                        f"[{current}]drawtext=text='{text}':x=(w-text_w)/2:y={caption_y}:"
                        f"fontsize={font_size}:fontcolor={font_color}{font_option}:borderw=3:bordercolor=black{enable}[caption{index}]")
                current = f"caption{index}"
        filters[-1] += f"[{current}]" if not filters[-1].endswith(f"[{current}]") else ""
        cmd = [
            self.ffmpeg_runner.config.ffmpeg_path, "-i", input_path,
            "-filter_complex", ";".join(filters), "-map", f"[{current}]",
            "-map", "0:a?", "-c:v", "libx264", "-c:a", "copy", "-y", output_path,
        ]
        self.ffmpeg_runner.run_ffmpeg(cmd)

    def run(self):
        try:
            logging.info("Starting video processing...")

            # Extract filename for output
            filename = os.path.splitext(os.path.basename(self.input_path))[0]
            os.makedirs(self.output_dir, exist_ok=True)
            output_path = f"{self.output_dir}{filename}-converted.mp4"
            if os.path.exists(output_path):
                output_path = (
                    f"{self.output_dir}{filename}-converted-{uuid.uuid4().hex[:8]}.mp4")

            # Set audio
            logging.info("Applying audio to the video...")
            audio_temp = self.ffmpeg_runner.create_temp_file()
            self._set_audio(self.input_path, self.muted_audio, audio_temp)

            crop_width = 1080
            crop_height = 1920

            if self.include_cam:
                # Process camera feed
                logging.info("Processing camera feed...")
                cam_temp = self.ffmpeg_runner.create_temp_file()
                cam_h = self._process_camera_feed(audio_temp, cam_temp,
                                                  self.cam_x, self.cam_y,
                                                  self.cam_width,
                                                  self.cam_height, crop_width)
            else:
                cam_h = crop_height - self.clip_height

            # Process main clip
            logging.info("Processing main clip...")
            main_temp = self.ffmpeg_runner.create_temp_file()
            self._process_main_clip(audio_temp, main_temp, crop_height, cam_h,
                                    crop_width)

            # Combine or blur
            if not self.include_cam:
                logging.info("Blurring background...")
                composited_temp = self.ffmpeg_runner.create_temp_file()
                self._blur_background(audio_temp, composited_temp, crop_width,
                                      crop_height, cam_h, main_temp)
            else:
                logging.info("Combining camera feed and main clip...")
                composited_temp = self.ffmpeg_runner.create_temp_file()
                self._combine_clips_vertical(cam_temp, main_temp,
                                             composited_temp)

            if self.layout:
                logging.info("Applying composable layout...")
                layout_temp = self.ffmpeg_runner.create_temp_file()
                self._apply_layout(composited_temp, layout_temp)
                composited_temp = layout_temp

            # Add subtitles
            if self.segments:
                logging.info("Overlaying subtitles...")
                final_temp = self.ffmpeg_runner.create_temp_file()
                self._overlay_subtitles(composited_temp, final_temp,
                                        self.segments)
            else:
                logging.info("No subtitles provided, skipping overlay.")
                final_temp = composited_temp

            # Final encode with proper codec settings
            logging.info("Writing final video to file...")
            cmd = [
                self.ffmpeg_runner.config.ffmpeg_path,
                '-i',
                final_temp,
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
            self.ffmpeg_runner.run_ffmpeg(cmd)

            logging.info(f"Video processing completed: {output_path}")
            return output_path

        except FFmpegError as e:
            logging.error(f"Video processing failed: {e}")
            raise
        except Exception as e:
            logging.error(f"An error occurred during video processing: {e}")
            raise
        finally:
            # Clean up is handled by the FFmpegRunner in the conversion pipeline
            pass
