import gc
import os
import re
import tempfile

import nemo.collections.speechlm2 as slm
import soundfile as sf
import torch
import whisperx
from whisperx.diarize import assign_word_speakers
from whisperx.diarize import DiarizationPipeline

from clipmorph.generate_video import AUDIO_PATH
from clipmorph.generate_video import SRT_PATH

GAMING_PROMPT = """
This is gaming commentary containing:
- Gaming terminology and slang
- Casual conversation between players
- Expressions of frustration or excitement
- Player usernames and game-specific terms
- In-game dialogue that should be ignored
- Phrases and words that have been cut off and should be displayed with a dash, e.g., "What the f-", NOT "What the f -"
- Exclamatory words or phrases that should be displayed in all caps, e.g., "WHAT", "WOW" or "NO WAY".
- Profanity that should NOT be censored.
"""


def transcribe_audio():
    """
    Transcribe audio using WhisperX preprocessing + NVIDIA Canary-Qwen-2.5B transcription
    with speaker diarization, with automatic device detection.
    """

    # Automatic device detection
    DEVICE = "cuda" if torch.cuda.is_available(
    ) else "mps" if torch.backends.mps.is_available() else "cpu"

    # 1. Load and preprocess audio using WhisperX
    sr = 16000
    audio = whisperx.load_audio(AUDIO_PATH, sr)

    # 2. Load NVIDIA Canary-Qwen-2.5B model
    print("Loading NVIDIA Canary-Qwen-2.5B model...")
    model = slm.models.SALM.from_pretrained("nvidia/canary-qwen-2.5b").to(
        DEVICE).eval()

    # 3. Save preprocessed audio to temporary file for Canary model
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
        sf.write(tmp_file.name, audio, sr)
        temp_audio_path = tmp_file.name

    # 4. Transcribe with Canary-Qwen-2.5B using official method
    prompt = [{
        "role": "user",
        "content":
        f"Transcribe the following gaming commentary: {model.audio_locator_tag}\n\n{GAMING_PROMPT}",
        "audio": [temp_audio_path]
    }]

    answer_ids = model.generate(prompts=[prompt],
                                max_new_tokens=896,
                                temperature=0.3,
                                do_sample=False)

    transcription = model.tokenizer.ids_to_text(answer_ids[0].cpu()).strip()

    # 5. Release Canary model to free memory
    del model
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()

    # 6. Clean up temporary file
    os.unlink(temp_audio_path)

    # 7. Create segments structure for alignment
    print("Loading WhisperX alignment model for word-level timestamps...")
    model_a, metadata = whisperx.load_align_model(language_code="en",
                                                  device=DEVICE)

    # Create pseudo-segments for alignment
    pseudo_segments = [{
        "start": 0.0,
        "end": len(audio) / sr,
        "text": transcription
    }]

    result_aligned = whisperx.align(pseudo_segments,
                                    model_a,
                                    metadata,
                                    audio,
                                    DEVICE,
                                    return_char_alignments=False)

    # 8. Release alignment model
    del model_a
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()

    # 9. Get Hugging Face token for diarization
    hf_token = os.getenv("HUGGING_FACE_ACCESS_TOKEN")
    if not hf_token:
        raise RuntimeError(
            "HUGGING_FACE_ACCESS_TOKEN environment variable is not set")

    # 10. Load improved diarization pipeline (pyannote 3.x)
    print("Loading speaker diarization model...")
    try:
        # Try newer pyannote speaker-diarization-3.1 for better performance
        from pyannote.audio import Pipeline
        diarize_model = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
        diarize_model.to(DEVICE)
        diarize_segments = diarize_model({"audio": AUDIO_PATH})
    except:
        # Fallback to WhisperX diarization pipeline
        diarize_model = DiarizationPipeline(use_auth_token=hf_token,
                                            device=DEVICE)
        diarize_segments = diarize_model(audio)

    # 11. Assign speakers to aligned segments
    print("Assigning speakers to segments...")
    result_final = assign_word_speakers(diarize_segments, result_aligned)

    # 12. Release diarization model
    del diarize_model
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()

    return result_final["segments"]


def generate_srt(segments):

    def format_time(seconds):
        ms = int((seconds - int(seconds)) * 1000)
        h, m, s = int(seconds // 3600), int(
            (seconds % 3600) // 60), int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    with open(SRT_PATH, 'w', encoding='utf-8') as f:
        idx = 1
        for seg in segments:
            speaker = seg['speaker']
            words_per_sub = 4
            for i in range(0, len(seg['words']), words_per_sub):
                words = seg['words'][i:i + words_per_sub]
                import json
                print(json.dumps(words, indent=4))
                f.write(f"{idx}\n")
                f.write(
                    f"{format_time(words[0]['start'])} --> {format_time(words[-1]['end'])}\n"
                )
                f.write(f"{speaker}: {' '.join(w['word'] for w in words)}\n\n")
                idx += 1
            # f.write(f"{idx}\n")
            # f.write(
            #     f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
            # f.write(f"{speaker}: {seg['text']}\n\n")
            # idx += 1


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
