import logging
import numpy as np
import webrtcvad
import librosa
import scipy.signal
import soundfile as sf

from moviepy import VideoFileClip
from clipmorph.generate_video import AUDIO_PATH, ENHANCED_AUDIO_PATH, VAD_AUDIO_PATH


def extract_audio(input_path):
    clip = VideoFileClip(input_path)
    clip.audio.write_audiofile(AUDIO_PATH)
    clip.close()


def enhance_dialogue():
    # Load audio
    y, sr = librosa.load(AUDIO_PATH, sr=16000)  # Whisper prefers 16kHz

    # Apply noise reduction
    y_denoised = scipy.signal.wiener(y)

    # Normalize audio levels
    y_normalized = librosa.util.normalize(y_denoised)

    # Apply high-pass filter to remove low-frequency noise
    order = 5  # Choose an appropriate filter order
    cutoff_freq = 80  # cutoff frequency in Hz

    b, a = scipy.signal.butter(order, cutoff_freq, btype='high', fs=sr)
    y_filtered = scipy.signal.lfilter(b, a, y_normalized)

    # Save preprocessed audio
    sf.write(ENHANCED_AUDIO_PATH, y_filtered, sr)


def apply_vad(aggressiveness=3):
    vad = webrtcvad.Vad(aggressiveness)

    # Load audio with 16-bit mono, 16kHz sample rate
    y, sr = librosa.load(ENHANCED_AUDIO_PATH, sr=16000, mono=True)
    y_int16 = (y * 32767).astype(np.int16)

    frame_duration_ms = 20  # WebRTC VAD supports 10, 20, or 30ms
    samples_per_frame = int(sr * frame_duration_ms / 1000)

    num_frames = len(y_int16) // samples_per_frame

    vad_mask = np.zeros(len(y_int16), dtype=bool)

    for i in range(num_frames):
        start = i * samples_per_frame
        end = start + samples_per_frame
        frame = y_int16[start:end]
        if len(frame) < samples_per_frame:
            break
        is_speech = vad.is_speech(frame.tobytes(), sample_rate=sr)
        vad_mask[start:end] = is_speech

    # Clean up mask by padding regions slightly (fade in/out tolerance)
    padded_mask = np.copy(vad_mask)
    padding = samples_per_frame  # ~20ms before and after
    speech_indices = np.flatnonzero(vad_mask)
    for idx in speech_indices:
        start = max(0, idx - padding)
        end = min(len(padded_mask), idx + padding)
        padded_mask[start:end] = True

    # Apply mask to mute non-speech regions
    y_vad = np.copy(y)
    y_vad[~padded_mask] = 0.0

    # Write back to WAV
    sf.write(VAD_AUDIO_PATH, y_vad, sr)
