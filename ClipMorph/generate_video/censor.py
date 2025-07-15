import librosa
import soundfile as sf
from better_profanity import profanity

from clipmorph.generate_video import AUDIO_PATH


def detect_profanity(segments, custom_words=None):
    profanity.load_censor_words(custom_words)
    profane_intervals = []
    for seg in segments:
        for word_info in seg['words']:
            if profanity.contains_profanity(word_info['word']):
                profane_intervals.append(
                    (word_info['start'], word_info['end']))
    return profane_intervals


def mute_audio(intervals, output_path):
    y, sr = librosa.load(AUDIO_PATH, sr=None)
    for start, end in intervals:
        start_sample = int(start * sr)
        end_sample = int(end * sr)
        y[start_sample:end_sample] = 0
    sf.write(output_path, y, sr)
