import os
import re
import whisperx
import torch
import whisperx.diarize
from clipmorph.generate_video import SRT_PATH, VAD_AUDIO_PATH, AUDIO_PATH

GAMING_PROMPT = """
This is gaming commentary containing:
- Gaming terminology and slang
- Casual conversation between players
- Expressions of frustration or excitement
- Player usernames and game-specific terms
- Phrases and words that get cut off and should be displayed with a dash, e.g., "What the f-", NOT "What the f -"
- Exclamatory words or phrases that should be displayed in all caps, e.g., "WHAT", "WOW" or "NO WAY".
- Profanity that should NOT be censored.
"""


def transcribe_audio(model_size="large-v3"):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    model = whisperx.load_model(model_size,
                                device=device,
                                compute_type=compute_type,
                                language="en",
                                asr_options={"initial_prompt": GAMING_PROMPT})

    result = model.transcribe(AUDIO_PATH, batch_size=16)

    model_a, metadata = whisperx.load_align_model(language_code="en",
                                                  device=device)
    result_aligned = whisperx.align(result["segments"], model_a, metadata,
                                    AUDIO_PATH, device)

    hf_token = os.environ.get("HUGGING_FACE_ACCESS_TOKEN")
    if not hf_token:
        raise RuntimeError(
            "HUGGING_FACE_ACCESS_TOKEN environment variable is not set")

    diarize_pipeline = whisperx.diarize.DiarizationPipeline(
        use_auth_token=hf_token, device=device)
    diarize_df = diarize_pipeline(AUDIO_PATH)

    segments_with_speakers = whisperx.diarize.assign_word_speakers(
        diarize_df, result_aligned)

    return segments_with_speakers['segments']


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
                f.write(f"{' '.join(w['word'] for w in words)}\n\n")
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
