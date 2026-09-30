import logging
import os
from typing import List, Tuple

from clipmorph.conversion_pipeline.edit import EditingPipeline
from clipmorph.ffmpeg import FFmpegError
from clipmorph.ffmpeg import FFmpegRunner
from clipmorph.job import source_sha256
from clipmorph.transcript import load_edit_session


class ConversionPipeline:

    def __init__(self, input_path, skip_subtitles=False, **kwargs):
        self.input_path = input_path
        self.skip_subtitles = skip_subtitles
        self.kwargs = kwargs
        self.reviewed_transcript_path = kwargs.get('reviewed_transcript_path')
        self.ffmpeg_runner = FFmpegRunner()
        self.segments = []
        self.warnings = []

    def _mute_audio(self, intervals: List[Tuple[float, float]],
                    audio_path: str) -> str:
        """
        Mute specific intervals in an audio file using ffmpeg
        
        Args:
            intervals: List of (start_time, end_time) tuples in seconds to mute
            audio_path: Path to the input audio file
            
        Returns:
            Path to the muted audio file
        """
        output_path = self.ffmpeg_runner.create_temp_file('.wav')

        if not intervals:
            # If no intervals to mute, just copy
            cmd = [
                self.ffmpeg_runner.config.ffmpeg_path, '-i', audio_path, '-c',
                'copy', '-y', output_path
            ]
            self.ffmpeg_runner.run_ffmpeg(cmd)
            return output_path

        # Build volume filter with enable conditions for each mute interval
        volume_filters = []
        for start, end in intervals:
            enable_condition = f"between(t,{start},{end})"
            volume_filters.append(f"volume=0:enable='{enable_condition}'")

        filter_string = ','.join(volume_filters)

        cmd = [
            self.ffmpeg_runner.config.ffmpeg_path, '-i', audio_path, '-af',
            filter_string, '-c:a', 'pcm_s16le', '-y', output_path
        ]

        self.ffmpeg_runner.run_ffmpeg(cmd)
        return output_path

    def _apply_word_annotations(self, segments):
        """Apply saved per-word replacements without changing segment timing."""
        for segment in segments:
            text = segment.get("text", "")
            for word in segment.get("words", []):
                if not word.get("censored"):
                    continue
                original = str(word.get("word", "")).strip()
                replacement = word.get("replacement", "***")
                if original:
                    text = text.replace(original, str(replacement), 1)
            segment["text"] = text
        return segments

    def _load_reviewed_segments(self):
        session = load_edit_session(self.reviewed_transcript_path)
        if session["source_sha256"] != source_sha256(self.input_path):
            raise ValueError("Reviewed transcript source does not match input video")
        return session["segments"]

    def _validate_output(self, output_path: str):
        """Validate the generated output file."""
        if not os.path.exists(output_path):
            raise FFmpegError("Output file was not created")

        file_size = os.path.getsize(output_path)
        if file_size < 1024:  # Less than 1KB
            raise FFmpegError(
                "Output file is suspiciously small, likely corrupted")

        # Validate it's a proper video file
        try:
            self.ffmpeg_runner.get_video_info(output_path)
        except FFmpegError:
            raise FFmpegError("Generated file is not a valid video")

        return file_size

    def run(self):
        try:
            # Validate input file first
            logging.info("Validating input file...")
            self.ffmpeg_runner.validate_input_file(self.input_path)

            logging.info("Extracting audio from video...")
            audio_path = self.ffmpeg_runner.extract_audio(self.input_path)

            muted_audio_path = audio_path

            if self.skip_subtitles:
                logging.info("Skipping subtitles (conversion.subtitles.skip)")
            else:
                if not self.reviewed_transcript_path:
                    raise ValueError(
                        "conversion.subtitles is enabled but no reviewed "
                        "transcript session exists; the pipeline takes "
                        "transcripts only from the transcript checkpoint "
                        "(never transcribes audio itself)")
                logging.info("Loading reviewed transcript edit session...")
                self.segments = self._load_reviewed_segments()
                self.segments = self._apply_word_annotations(self.segments)
                intervals = [
                    (word["start"], word["end"])
                    for segment in self.segments
                    for word in segment.get("words", [])
                    if word.get("censored") and
                    isinstance(word.get("start"), (int, float)) and
                    isinstance(word.get("end"), (int, float))
                ]
                if intervals:
                    muted_audio_path = self._mute_audio(intervals, audio_path)

            logging.info("Editing video...")

            editing_option_names = {
                "output_dir",
                "layout",
            }
            editing_options = {
                key: value
                for key, value in self.kwargs.items()
                if key in editing_option_names
            }

            final_output = EditingPipeline(
                input_path=self.input_path,
                muted_audio=muted_audio_path,
                segments=[],
                ffmpeg_runner=self.ffmpeg_runner,
                **editing_options).run()

            # Validate output
            file_size = self._validate_output(final_output)

            logging.info(
                f"✓ Generated {file_size // (1024*1024)}MB video: {final_output}"
            )
            return final_output

        except FFmpegError as e:
            logging.error(f"FFmpeg error: {e}")
            raise
        except Exception as e:
            logging.error(f"Conversion failed: {e}")
            raise
        finally:
            # Clean up temporary files
            self.ffmpeg_runner.cleanup_temp_files()
