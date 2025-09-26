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

    def __init__(self, input_path, **kwargs):
        self.input_path = input_path
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

    def run(self):
        try:
            logging.info("Extracting audio from video...")
            audio_path = self._extract_audio(self.input_path)

            logging.info("Transcribing audio...")
            segments = TranscriptionPipeline(audio_path).run()

            muted_audio_path = None
            if not segments:
                logging.warning(
                    "Failed to transcribe audio. No subtitles will be generated and profanity will not be censored."
                )
                # Use original audio when no transcription/muting needed
                muted_audio_path = audio_path
            else:
                logging.debug("Generating subtitles (.srt)...")
                write_srt_file(segments)

                logging.info("Detecting profanity in audio...")
                intervals = self._detect_profanity(segments)

                if intervals:
                    logging.info("Muting profane audio segments...")
                    muted_audio_path = self._mute_audio(intervals, audio_path)
                else:
                    logging.info(
                        "No profanity detected, using original audio...")
                    muted_audio_path = audio_path

                logging.info("Censoring subtitles...")
                segments = self._censor_subtitles(segments)

            logging.info("Editing video...")
            # Pass the paths to EditingPipeline along with ffmpeg paths
            final_output = EditingPipeline(input_path=self.input_path,
                                           muted_audio=muted_audio_path,
                                           segments=segments,
                                           ffmpeg_path=self.ffmpeg_path,
                                           ffprobe_path=self.ffprobe_path,
                                           **self.kwargs).run()

            logging.info(f"Saved converted video to {final_output}")

            return final_output

        except Exception as e:
            logging.error(f"An error occurred during conversion: {e}")
            raise
        finally:
            # Clean up temporary files
            self._cleanup_temp_files()
