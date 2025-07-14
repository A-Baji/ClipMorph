# audio_transcript.py
from moviepy import VideoFileClip
import whisper  # or use vosk


def extract_audio(input_path, output_audio_path):
    clip = VideoFileClip(input_path)
    clip.audio.write_audiofile(output_audio_path)
    clip.close()


def transcribe_audio(audio_path, model='base.en'):
    model = whisper.load_model(model)
    result = model.transcribe(audio_path, word_timestamps=True, fp16=False)
    return result[
        'segments']  # Each segment contains text, start, end, and words with timings
