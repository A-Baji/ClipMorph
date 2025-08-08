import logging
import tempfile

from better_profanity import profanity
import librosa
from moviepy import AudioFileClip
from moviepy import VideoFileClip
import soundfile as sf

from clipmorph.pipeline.edit import convert_to_short_form
from clipmorph.pipeline.transcribe import TranscriptionPipeline
from clipmorph.pipeline.transcribe import write_srt_file


class ConversionPipeline:

    def __init__(self, input_path, **kwargs):
        self.input_path = input_path
        self.kwargs = kwargs

    def _extract_audio(self, input_path):
        clip = VideoFileClip(input_path)
        return clip.audio

    def _detect_profanity(self, segments, custom_words=None):
        profanity.load_censor_words(custom_words, whitelist_words=["god"])
        profane_intervals = []
        for seg in segments:
            for word_info in seg['words']:
                if profanity.contains_profanity(word_info['word']):
                    profane_intervals.append(
                        (word_info['start'], word_info['end']))
        return profane_intervals

    def _mute_audio(self, intervals,
                    audio_clip: AudioFileClip) -> AudioFileClip:
        src_path = audio_clip.reader.filename
        y, sr = librosa.load(src_path, sr=None)

        for start, end in intervals:
            start_idx = int(start * sr)
            end_idx = int(end * sr)
            y[start_idx:end_idx] = 0

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        sf.write(tmp.name, y, sr)
        tmp.close()

        return AudioFileClip(tmp.name)

    def run(self):
        logging.info("Extracting audio from video...")
        audio = self._extract_audio(self.input_path)

        logging.info("Transcribing audio...")
        segments = TranscriptionPipeline(audio).run()

        if not segments:
            logging.warning(
                "Failed to transcribe audio. No subtitles will be generated and profanity will not be censored."
            )
        else:
            logging.debug("Generating subtitles (.srt)...")
            write_srt_file(segments)

            logging.info("Detecting profanity in audio...")
            intervals = self._detect_profanity(segments)

            logging.info("Muting profane audio segments...")
            muted_audio = self._mute_audio(intervals, audio)

            logging.info("Censoring subtitles...")
            # TODO: Censor subtitles

        logging.info(
            "Converting video to short-form format and overlaying subtitles..."
        )
        final_output = convert_to_short_form(input_path=self.input_path,
                                             muted_audio=muted_audio,
                                             segments=segments,
                                             **self.kwargs)

        logging.info(f"Saved converted video to {final_output}")

        return final_output
