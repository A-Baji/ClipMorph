# audio_transcript.py
from moviepy import VideoFileClip
import whisper

from clipmorph.generate_video import AUDIO_PATH


def extract_audio(input_path):
    clip = VideoFileClip(input_path)
    clip.audio.write_audiofile(AUDIO_PATH)
    clip.close()


def transcribe_audio(model='base.en'):
    model = whisper.load_model(model)
    result = model.transcribe(AUDIO_PATH, word_timestamps=True, fp16=False)
    return result[
        'segments']  # Each segment contains text, start, end, and words with timings
