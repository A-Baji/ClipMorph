from functools import cached_property
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


class TranscriptionPipeline:
    """Class to manage all models for transcription pipeline."""

    def __init__(self, audio_path: str = AUDIO_PATH):
        self.audio_path = audio_path

    @cached_property
    def _audio(self):
        """Load audio file on first access."""
        if not os.path.exists(self.audio_path):
            raise FileNotFoundError(f"Audio file not found: {self.audio_path}")
        logging.info(f"Loading audio file: {self.audio_path}")
        return whisper.load_audio(self.audio_path)

    @cached_property
    def _whisper_model(self):
        """Load Whisper model on first access."""
        logging.info("Loading Whisper large-v3 model...")
        return whisper.load_model("large-v3", device=DEVICE)

    @cached_property
    def _align_model_data(self):
        """Load alignment model and metadata on first access."""
        logging.info("Loading alignment model...")
        model, metadata = whisperx.load_align_model(language_code="en",
                                                    device=DEVICE)
        return {"model": model, "metadata": metadata}

    @cached_property
    def _diarization_model(self):
        """Load diarization model on first access."""
        hf_token = os.getenv("HUGGING_FACE_ACCESS_TOKEN")
        if not hf_token:
            logging.warning(
                "HUGGING_FACE_ACCESS_TOKEN not set, diarization unavailable.")
            return None

        logging.info("Loading diarization model...")
        return whisperx.diarize.DiarizationPipeline(use_auth_token=hf_token,
                                                    device=DEVICE)

    @cached_property
    def _llm_model(self):
        """Load LLM model on first access."""
        try:
            logging.info("Loading Canary-Qwen-2.5B model...")
            import nemo.collections.speechlm2 as slm
            return slm.models.SALM.from_pretrained(
                "nvidia/canary-qwen-2.5b").eval()
        except Exception as e:
            logging.error(f"Failed to load LLM model: {e}")
            return None

    def _get_transcription_segments(self) -> List[Dict[str, Any]]:
        """Get transcription segments using cached Whisper model."""
        result = self._whisper_model.transcribe(
            self._audio,
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

    def _align_segments(
            self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Align segments using cached alignment model."""
        align_data = self._align_model_data
        aligned = whisperx.align(segments,
                                 align_data["model"],
                                 align_data["metadata"],
                                 self._audio,
                                 DEVICE,
                                 return_char_alignments=False)
        return aligned['segments']

    def _diarize_assign_speakers(
            self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Diarize and assign speakers using cached diarization model."""
        diarizer = self._diarization_model
        if not diarizer:
            logging.warning(
                "Diarization model not available, skipping speaker assignment."
            )
            return segments
        diarize_segs = diarizer(self._audio)
        result = whisperx.diarize.assign_word_speakers(diarize_segs,
                                                       {"segments": segments})
        return result["segments"]

    def _filter_gaming_content(
            self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter gaming content using cached LLM model."""
        model = self._llm_model
        if not model:
            logging.warning(
                "LLM model not available, returning unfiltered phrases.")
            return segments

        try:
            texts = [p["text"] for p in segments]
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
                if len(keep_flags) == len(segments):
                    result = [
                        phrase for phrase, keep in zip(segments, keep_flags)
                        if keep
                    ]
                    return result

            logging.warning(
                "LLM filtering fallback, returning unfiltered phrases.")
            return segments
        except Exception as e:
            logging.error(f"Content filtering failed: {e}")
            return segments

    def _group_words_into_phrases(
            self,
            segments: List[Dict[str, Any]],
            max_gap: float = 0.2,
            end_padding: float = 0.5,
            max_words_per_segment: int = 4) -> List[Dict[str, Any]]:
        """Group words into phrases."""
        output = []
        num_segments = len(segments)
        for i, seg in enumerate(segments):
            words = seg.get("words", [])
            if not words:
                continue
            sub_start = words[0]["start"]
            sub_end = words[0]["end"]
            sub_words = [words[0]]
            speaker = words[0].get("speaker", seg.get("speaker", ""))
            segments_buffer = []

            for prev, curr in zip(words, words[1:]):
                gap = curr["start"] - prev["end"]
                if gap > max_gap or len(sub_words) >= max_words_per_segment:
                    segments_buffer.append({
                        "start": sub_start,
                        "end": sub_end,
                        "words": sub_words.copy(),
                        "speaker": speaker,
                    })
                    sub_start = curr["start"]
                    sub_end = curr["end"]
                    sub_words = [curr]
                else:
                    sub_words.append(curr)
                    sub_end = curr["end"]

            if sub_words:
                segments_buffer.append({
                    "start": sub_start,
                    "end": sub_end,
                    "words": sub_words.copy(),
                    "speaker": speaker,
                })

            next_orig_start = None
            if i + 1 < num_segments:
                next_seg_words = segments[i + 1].get("words", [])
                if next_seg_words:
                    next_orig_start = next_seg_words[0]["start"]

            for j, new_seg in enumerate(segments_buffer):
                this_end = new_seg["end"]

                if j + 1 < len(segments_buffer):
                    next_start = segments_buffer[j + 1]["start"]
                else:
                    next_start = next_orig_start

                actual_pad = end_padding
                if next_start is not None:
                    seg_gap_time = next_start - this_end
                    if seg_gap_time < end_padding:
                        actual_pad = max(0.0, 0.5 * seg_gap_time)
                else:
                    actual_pad = end_padding

                seg_out = {
                    "start": new_seg["start"],
                    "end": new_seg["end"] + actual_pad,
                    "text": " ".join(w["word"] for w in new_seg["words"]),
                    "speaker": new_seg["speaker"],
                    "words": new_seg["words"],
                }
                output.append(seg_out)

        return output

    def _cleanup(self):
        """Clean up GPU memory and cached models."""
        for attr in [
                '_audio', '_whisper_model', '_align_model_data',
                '_diarization_model', '_llm_model'
        ]:
            try:
                delattr(self, attr)
            except AttributeError:
                pass
        torch.cuda.empty_cache()
        gc.collect()

    def transcribe(self) -> List[Dict[str, Any]]:
        try:
            logging.info("Transcribing audio into segments...")
            segments = self._get_transcription_segments()

            logging.info("Aligning segments with audio...")
            aligned_segments = self._align_segments(segments)
            if not aligned_segments:
                logging.warning("Failed to align segments; invalid segments.")
                return []

            logging.info("Diarizing and assigning speakers to segments...")
            diarized_segments = self._diarize_assign_speakers(aligned_segments)

            logging.info("Filtering out gaming content segments...")
            filtered_segments = self._filter_gaming_content(diarized_segments)

            logging.info("Grouping words into phrases...")
            phrase_segments = self._group_words_into_phrases(filtered_segments)

            return phrase_segments
        finally:
            self._cleanup()


def write_srt_file(phrases: List[Dict[str, Any]]):
    """Write SRT file."""

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
    """Parse existing SRT file back into segments."""
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
