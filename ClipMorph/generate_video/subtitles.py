from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip
import re

from clipmorph.generate_video import SRT_PATH, CENSORED_AUDIO_PATH


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


def replace_audio_and_overlay_subs(input_path, output_path):
    video = VideoFileClip(input_path)
    audio = AudioFileClip(CENSORED_AUDIO_PATH)
    video = video.with_audio(audio)

    subs = parse_srt(SRT_PATH)
    subtitle_clips = []
    for sub in subs:
        txt_clip = (TextClip(text=sub['text'],
                             font_size=36,
                             color='white',
                             stroke_color='black',
                             stroke_width=2,
                             method='caption',
                             size=(int(video.w * 0.9),
                                   None)).with_start(sub['start']).with_end(
                                       sub['end']).with_position(
                                           ('center', 'bottom')))
        subtitle_clips.append(txt_clip)

    final = CompositeVideoClip([video, *subtitle_clips])
    final.write_videofile(output_path, codec='libx264', audio_codec='aac')
    video.close()
    audio.close()
    final.close()
