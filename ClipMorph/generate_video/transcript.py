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
    return result['segments']


def generate_srt(segments):

    def format_time(seconds):
        ms = int((seconds - int(seconds)) * 1000)
        h, m, s = int(seconds // 3600), int(
            (seconds % 3600) // 60), int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    with open(SRT_PATH, 'w', encoding='utf-8') as f:
        idx = 1
        for seg in segments:
            for i in range(0, len(seg['words']), 3):
                words = seg['words'][i:i + 3]
                f.write(f"{idx}\n")
                f.write(
                    f"{format_time(words[0]['start'])} --> {format_time(words[-1]['end'])}\n"
                )
                f.write(f"{''.join(w['word'] for w in words)}\n\n")
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
