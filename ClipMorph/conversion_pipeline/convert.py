import logging
import os
import subprocess
import tempfile
from typing import List, Tuple

from better_profanity import profanity

from clipmorph.conversion_pipeline.edit import EditingPipeline
from clipmorph.conversion_pipeline.transcribe import TranscriptionPipeline
from clipmorph.conversion_pipeline.transcribe import write_srt_file
from clipmorph.ffmpeg import get_ffmpeg_paths


class ConversionPipeline:

    def __init__(self, input_path, no_subs=False, no_confirm=False, **kwargs):
        self.input_path = input_path
        self.no_subs = no_subs
        self.no_confirm = no_confirm
        self.kwargs = kwargs
        self.ffmpeg_path, self.ffprobe_path = get_ffmpeg_paths()
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

    def _create_temp_file(self, suffix='.wav'):
        """Create a temporary file and track it for cleanup"""
        temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(temp_fd)  # Close the file descriptor, we only need the path
        self.temp_files.append(temp_path)
        return temp_path

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

    def _extract_audio(self, input_path: str) -> str:
        """
        Extract audio from video file using ffmpeg
        
        Args:
            input_path: Path to the input video file
            
        Returns:
            Path to the extracted audio file
        """
        audio_temp = self._create_temp_file(suffix='.wav')

        cmd = [
            self.ffmpeg_path,
            '-i',
            input_path,
            '-vn',  # No video
            '-acodec',
            'pcm_s16le',  # Uncompressed WAV for quality
            '-ar',
            '44100',  # Sample rate
            '-ac',
            '2',  # Stereo
            '-y',
            audio_temp
        ]

        self._run_ffmpeg(cmd)
        return audio_temp

    def _detect_profanity(self, segments, custom_words=None):
        """Detect profanity in transcribed segments and return intervals to mute"""
        profanity.load_censor_words(custom_words, whitelist_words=["god"])
        profane_intervals = []
        for seg in segments:
            for word_info in seg['words']:
                if profanity.contains_profanity(word_info['word']):
                    profane_intervals.append(
                        (word_info['start'], word_info['end']))
        return profane_intervals

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
        if not intervals:
            # If no intervals to mute, just return a copy
            muted_temp = self._create_temp_file(suffix='.wav')
            cmd = [
                self.ffmpeg_path, '-i', audio_path, '-c', 'copy', '-y',
                muted_temp
            ]
            self._run_ffmpeg(cmd)
            return muted_temp

        muted_temp = self._create_temp_file(suffix='.wav')

        # Build volume filter with enable conditions for each mute interval
        volume_filters = []
        for start, end in intervals:
            # Create a condition to mute during this interval
            enable_condition = f"between(t,{start},{end})"
            volume_filters.append(f"volume=0:enable='{enable_condition}'")

        # Combine all volume filters
        filter_string = ','.join(volume_filters)

        cmd = [
            self.ffmpeg_path,
            '-i',
            audio_path,
            '-af',
            filter_string,
            '-c:a',
            'pcm_s16le',  # Keep as uncompressed WAV
            '-y',
            muted_temp
        ]

        self._run_ffmpeg(cmd)
        return muted_temp

    def _censor_subtitles(self, segments):
        """Censor profane words in subtitle segments."""
        for segment in segments:
            segment["text"] = profanity.censor(segment["text"])
        return segments

    def _log_subtitles(self, segments):
        """Log the generated subtitles for user review."""
        if not segments:
            logging.info("No subtitles were generated.")
            return

        print("\n" + "=" * 60)
        print(f"Generated {len(segments)} subtitle segments:")
        print("=" * 60)

        for i, segment in enumerate(segments[:20],
                                    1):  # Show first 20 segments
            start_time = segment.get('start', 0)
            end_time = segment.get('end', 0)
            text = segment.get('text', '').strip()

            # Format time as MM:SS
            start_min, start_sec = divmod(int(start_time), 60)
            end_min, end_sec = divmod(int(end_time), 60)

            print(
                f"{i:2d}. [{start_min:02d}:{start_sec:02d}-{end_min:02d}:{end_sec:02d}] {text}"
            )

        if len(segments) > 20:
            print(f"... and {len(segments) - 20} more segments")

        print("=" * 60)

    def _ask_subtitle_confirmation(self):
        """Ask user if they want to include subtitles in the video."""
        while True:
            response = input(
                "\nAdd these subtitles to the video? (y/n): ").strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
            else:
                print("Please enter 'y' for yes or 'n' for no.")

    def run(self):
        try:
            logging.info("Extracting audio from video...")
            audio_path = self._extract_audio(self.input_path)

            segments = []
            muted_audio_path = audio_path
            use_subtitles = False

            if not self.no_subs:
                logging.info("Transcribing audio...")
                try:
                    segments = TranscriptionPipeline(audio_path).run()

                    if segments:
                        # Log subtitles for user review
                        self._log_subtitles(segments)

                        # Ask for confirmation unless --no-confirm is set
                        if self.no_confirm:
                            use_subtitles = True
                            logging.info(
                                "Auto-confirming subtitle addition (--no-confirm flag)"
                            )
                        else:
                            use_subtitles = self._ask_subtitle_confirmation()

                        if use_subtitles:
                            logging.debug("Writing subtitles (.srt)...")
                            write_srt_file(segments)

                            logging.info("Detecting profanity in audio...")
                            intervals = self._detect_profanity(segments)

                            if intervals:
                                logging.info(
                                    "Muting profane audio segments...")
                                muted_audio_path = self._mute_audio(
                                    intervals, audio_path)
                            else:
                                logging.info(
                                    "No profanity detected, using original audio..."
                                )

                            logging.info("Censoring subtitles...")
                            segments = self._censor_subtitles(segments)
                        else:
                            logging.info(
                                "Skipping subtitle overlay as requested by user."
                            )
                            segments = [
                            ]  # Don't pass segments to editing pipeline
                    else:
                        logging.warning(
                            "No subtitles were generated from transcription.")

                except Exception as e:
                    logging.warning(
                        f"Transcription failed: {e}. Continuing without subtitles."
                    )
                    segments = []
            else:
                logging.info("Skipping transcription (--no-subs flag)")

            logging.info("Editing video...")

            # Pass the paths to EditingPipeline along with ffmpeg paths
            final_output = EditingPipeline(
                input_path=self.input_path,
                muted_audio=muted_audio_path,
                segments=segments if use_subtitles else [],
                ffmpeg_path=self.ffmpeg_path,
                ffprobe_path=self.ffprobe_path,
                **self.kwargs).run()

            # Simple output validation
            if not os.path.exists(final_output):
                raise RuntimeError("Output file was not created")

            file_size = os.path.getsize(final_output)
            if file_size < 1024:  # Less than 1KB
                raise RuntimeError(
                    "Output file is suspiciously small, likely corrupted")

            logging.info(
                f"✓ Generated {file_size // (1024*1024)}MB video: {final_output}"
            )
            return final_output

        except Exception as e:
            logging.error(f"An error occurred during conversion: {e}")
            raise
        finally:
            # Clean up temporary files
            self._cleanup_temp_files()
