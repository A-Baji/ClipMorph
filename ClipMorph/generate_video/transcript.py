import gc
import logging
import os
import re
from typing import Any, Dict, List

import torch
import whisper
import whisperx

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

LOGIC_CHECK_PROMPT = """
Analyze each transcript segment and classify as either player commentary (YES) or not player commentary (NO).
Exclude:
- In-game NPC dialogue, system messages, and announcers, which typicially use formal language
- Nonsensical or garbled text due to poor audio quality
- Background noise transcriptions
- Menu sounds or UI interactions

Return only a JSON array of booleans matching the input order.

Segments to analyze:
"""

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def get_transcription_segments(audio_path: str) -> List[Dict[str, Any]]:
    model = whisper.load_model("large-v3", device=DEVICE)
    audio = whisperx.load_audio(audio_path)
    try:
        result = model.transcribe(
            audio,
            word_timestamps=True,
            task='transcribe',
            language='en',
            initial_prompt=GAMING_PROMPT,
            temperature=0.0,  # Deterministic output
            beam_size=5,
            best_of=5,
            patience=1.0,
            condition_on_previous_text=True,
            suppress_tokens=[-1],
            no_speech_threshold=0.7,
            logprob_threshold=-1.0,
            compression_ratio_threshold=2.6)
        return result['segments']
    finally:
        del model
        gc.collect()


def align_segments(segments: List[Dict[str, Any]],
                   audio_path: str) -> List[Dict[str, Any]]:
    audio = whisperx.load_audio(audio_path)
    model_a, metadata = whisperx.load_align_model(language_code="en",
                                                  device=DEVICE)
    try:
        aligned = whisperx.align(segments,
                                 model_a,
                                 metadata,
                                 audio,
                                 DEVICE,
                                 return_char_alignments=False)
        return aligned['segments']
    finally:
        del model_a
        gc.collect()


def diarize_assign_speakers(aligned_segments: List[Dict[str, Any]],
                            audio_path: str) -> List[Dict[str, Any]]:
    hf_token = os.getenv("HUGGING_FACE_ACCESS_TOKEN")
    if not hf_token:
        logging.warning(
            "HUGGING_FACE_ACCESS_TOKEN not set, skipping diarization.")
        return aligned_segments
    diarizer = whisperx.diarize.DiarizationPipeline(use_auth_token=hf_token,
                                                    device=DEVICE)
    audio = whisperx.load_audio(audio_path)
    try:
        diarize_segs = diarizer(audio)
        result = whisperx.diarize.assign_word_speakers(
            diarize_segs, {"segments": aligned_segments})
        return result["segments"]
    finally:
        del diarizer
        gc.collect()


def group_words_into_phrases(
        aligned_segments: List[Dict[str, Any]],
        max_gap: float = 0.2,
        end_padding: float = 0.175) -> List[Dict[str, Any]]:
    output = []
    for seg in aligned_segments:
        words = seg["words"] if "words" in seg else []
        if not words:
            continue
        sub_start = words[0]["start"]
        sub_end = words[0]["end"]
        sub_words = [words[0]["word"]]
        speaker = words[0].get("speaker", seg.get("speaker", ""))
        for prev, curr in zip(words, words[1:]):
            gap = curr["start"] - prev["end"]
            if gap > max_gap:
                output.append({
                    "start": sub_start,
                    "end": sub_end + end_padding,
                    "text": " ".join(sub_words),
                    "speaker": speaker,
                    "words": words
                })
                sub_start = curr["start"]
                sub_words = [curr["word"]]
            else:
                sub_words.append(curr["word"])
            sub_end = curr["end"]
        if sub_words:
            output.append({
                "start": sub_start,
                "end": sub_end + end_padding,
                "text": " ".join(sub_words),
                "speaker": speaker,
                "words": words
            })
    return output


def filter_gaming_content(
        phrases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Use Canary-Qwen-2.5B LLM to filter out non-player, bad, or game-dialogue segments
    try:
        import nemo.collections.speechlm2 as slm
        model = slm.models.SALM.from_pretrained(
            "nvidia/canary-qwen-2.5b").eval()
        texts = [p["text"] for p in phrases]
        segment_list = "\n".join(f"{i+1}. \"{text}\""
                                 for i, text in enumerate(texts))
        prompt = [{
            "role": "user",
            "content": f"{LOGIC_CHECK_PROMPT}\n{segment_list}"
        }]
        answer_ids = model.generate(prompts=[prompt],
                                    max_new_tokens=512,
                                    temperature=0.0,
                                    do_sample=False)
        response = model.tokenizer.ids_to_text(answer_ids[0].cpu()).strip()
        import json

        # Try extracting a JSON array from LLM response
        json_start = response.find('[')
        json_end = response.rfind(']') + 1
        if json_start >= 0 and json_end > json_start:
            json_str = response[json_start:json_end]
            keep_flags = json.loads(json_str)
            if len(keep_flags) == len(phrases):
                result = [
                    phrase for phrase, keep in zip(phrases, keep_flags) if keep
                ]
                print(result)
                return result
        logging.warning(
            "LLM filtering fallback, returning unfiltered phrases.")
        return phrases
    except Exception as e:
        logging.error(f"Content filtering failed: {e}")
        return phrases


def transcribe_audio():
    logging.info("Transcribing audio into segments...")
    segments = get_transcription_segments(AUDIO_PATH)

    logging.info("Aligning segments with audio...")
    aligned_segments = align_segments(segments, AUDIO_PATH)
    if not aligned_segments:
        logging.warning(
            "Failed to align segments. This usually means the transcription contained invalid/incorrect speech segments."
        )
        return []

    logging.info("Diarizing and assigning speakers to segments...")
    diarized_segments = diarize_assign_speakers(aligned_segments, AUDIO_PATH)

    logging.info("Grouping words into phrases...")
    phrase_segments = group_words_into_phrases(diarized_segments)

    logging.info("Filtering out gaming content segments...")
    filtered_segments = filter_gaming_content(phrase_segments)
    return filtered_segments


def write_srt_file(phrases: List[Dict[str, Any]]):

    def format_timestamp(seconds: float) -> str:
        ms = int((seconds - int(seconds)) * 1000)
        h, m, s = int(seconds // 3600), int(
            (seconds % 3600) // 60), int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(SRT_PATH, "w", encoding="utf-8") as f:
        for idx, phrase in enumerate(phrases, 1):
            f.write(f"{idx}\n")
            f.write(
                f"{format_timestamp(phrase['start'])} --> {format_timestamp(phrase['end'])}\n"
            )
            if phrase.get("speaker"):
                f.write(f"{phrase['speaker']}: {phrase['text']}\n\n")
            else:
                f.write(f"{phrase['text']}\n\n")


def parse_srt() -> List[Dict[str, Any]]:
    """Parse existing SRT file back into segments"""
    if not os.path.exists(SRT_PATH):
        return []

    with open(SRT_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = re.compile(
        r"(\d+)\s+([\d:,]+) --> ([\d:,]+)\s+([\s\S]*?)(?=\n\d+\n|\Z)",
        re.MULTILINE)

    entries = []
    for match in pattern.finditer(content):
        start_str, end_str, text = match.group(2), match.group(3), match.group(
            4).strip().replace('\n', ' ')

        def srt_time_to_seconds(t: str) -> float:
            h, m, s_ms = t.split(':')
            s, ms = s_ms.split(',')
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        start = srt_time_to_seconds(start_str)
        end = srt_time_to_seconds(end_str)
        entries.append({'start': start, 'end': end, 'text': text})

    return entries
