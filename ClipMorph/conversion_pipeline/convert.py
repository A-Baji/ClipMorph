import logging
import os
from typing import List, Tuple

from better_profanity import profanity

from clipmorph.conversion_pipeline.edit import EditingPipeline
from clipmorph.conversion_pipeline.transcribe import TranscriptionPipeline
from clipmorph.conversion_pipeline.transcribe import write_srt_file
from clipmorph.ffmpeg import FFmpegError
from clipmorph.ffmpeg import FFmpegRunner


class ConversionPipeline:

    def __init__(self, input_path, no_subs=False, no_confirm=False, **kwargs):
        self.input_path = input_path
        self.no_subs = no_subs
        self.no_confirm = no_confirm
        self.kwargs = kwargs
        self.ffmpeg_runner = FFmpegRunner()
        self.segments = []

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

        for i, segment in enumerate(segments[:20], 1):
            start_time = segment.get('start', 0)
            end_time = segment.get('end', 0)
            text = segment.get('text', '').strip()
            speaker = segment.get('speaker', '')

            # Format time as MM:SS
            start_min, start_sec = divmod(int(start_time), 60)
            end_min, end_sec = divmod(int(end_time), 60)

            # Add speaker label if available
            speaker_label = f"{speaker}: " if speaker else ""

            print(
                f"{i:2d}. [{start_min:02d}:{start_sec:02d}-{end_min:02d}:{end_sec:02d}] {speaker_label}{text}"
            )

        if len(segments) > 20:
            print(f"... and {len(segments) - 20} more segments")

        print("=" * 60)

    def _ask_subtitle_confirmation(self):
        """Ask user if they want to include subtitles and select which ones to omit."""
        while True:
            response = input(
                "\nProceed with generated subtitles or select lines to omit? (y/n/select): "
            ).strip().lower()

            if response in ['n', 'no']:
                return False

            if response in ['y', 'yes']:
                return True

            if response == 'select':
                while True:
                    omit_input = input(
                        "\nEnter line numbers to omit (e.g., 1,3-5,7) or press Enter to keep all: "
                    ).strip()

                    if not omit_input:
                        return True

                    try:
                        # Parse the input string into a set of line numbers
                        omit_numbers = set()
                        for part in omit_input.split(','):
                            if '-' in part:
                                start, end = map(int, part.split('-'))
                                omit_numbers.update(range(start, end + 1))
                            else:
                                omit_numbers.add(int(part))

                        # Validate line numbers are in range
                        invalid_numbers = [
                            i for i in omit_numbers
                            if i < 1 or i > len(self.segments)
                        ]
                        if invalid_numbers:
                            print(
                                f"Invalid line numbers: {', '.join(map(str, invalid_numbers))}."
                            )
                            print(
                                f"Please enter numbers between 1 and {len(self.segments)}."
                            )
                            continue

                        # Mark segments for removal
                        for i in sorted(omit_numbers, reverse=True):
                            del self.segments[i - 1]

                        logging.info(
                            f"Omitted {len(omit_numbers)} subtitle segments")
                        print("\nUpdated subtitles:")
                        self._log_subtitles(self.segments)
                        return True

                    except ValueError:
                        print(
                            "Invalid format. Please use numbers and ranges (e.g., 1,3-5,7)"
                        )
                        continue

            print(
                "Please enter 'y' for yes, 'n' for no, or 'select' to choose lines to omit."
            )

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

            segments = []
            muted_audio_path = audio_path
            use_subtitles = False

            if not self.no_subs:
                logging.info("Transcribing audio...")
                try:
                    self.segments = TranscriptionPipeline(audio_path).run()

                    if self.segments:
                        # Log subtitles for user review
                        self._log_subtitles(self.segments)

                        # Ask for confirmation unless --no-confirm is set
                        if self.no_confirm:
                            use_subtitles = True
                            logging.info(
                                "Auto-confirming subtitle addition (--no-confirm flag)"
                            )
                        else:
                            use_subtitles = self._ask_subtitle_confirmation()

                        if use_subtitles:
                            logging.info("Processing subtitles...")
                            write_srt_file(self.segments)

                            logging.info("Detecting profanity in audio...")
                            intervals = self._detect_profanity(self.segments)

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
                            self.segments = self._censor_subtitles(
                                self.segments)
                        else:
                            logging.info(
                                "Skipping subtitle overlay as requested by user."
                            )
                            self.segments = []
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

            # Pass FFmpeg runner to editing pipeline
            final_output = EditingPipeline(
                input_path=self.input_path,
                muted_audio=muted_audio_path,
                segments=self.segments if use_subtitles else [],
                ffmpeg_runner=self.ffmpeg_runner,
                **self.kwargs).run()

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
