# audio_transcript.py
import re
from moviepy import VideoFileClip
import whisper

from clipmorph.generate_video import AUDIO_PATH, SRT_PATH


def extract_audio(input_path):
    clip = VideoFileClip(input_path)
    clip.audio.write_audiofile(AUDIO_PATH)
    clip.close()


def transcribe_audio(model='base.en'):
    model = whisper.load_model(model)
    result = model.transcribe(AUDIO_PATH,
                              word_timestamps=True,
                              fp16=False,
                              language='en')
    return result[
        'segments']  # Each segment contains text, start, end, and words with timings


def generate_srt(segments):

    def format_time(seconds):
        ms = int((seconds - int(seconds)) * 1000)
        h, m, s = int(seconds // 3600), int(
            (seconds % 3600) // 60), int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    with open(SRT_PATH, 'w', encoding='utf-8') as f:
        idx = 1
        for seg in segments:
            f.write(f"{idx}\n")
            f.write(
                f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
            f.write(f"{seg['text']}\n\n")
            idx += 1


def parse_srt():
    with open(SRT_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = re.compile(
        r"(\d+)\s+([\d:,]+) --> ([\d:,]+)\s+([\s\S]*?)(?=\n\d+\n|\Z)",
        re.MULTILINE)
    entries = []
    for match in pattern.finditer(content):
        start_str, end_str, text = match.group(2), match.group(3), match.group(
            4).strip().replace('\n', ' ')

        def srt_time_to_seconds(t):
            h, m, s_ms = t.split(':')
            s, ms = s_ms.split(',')
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        start = srt_time_to_seconds(start_str)
        end = srt_time_to_seconds(end_str)
        entries.append({'start': start, 'end': end, 'text': text})
    return entries
