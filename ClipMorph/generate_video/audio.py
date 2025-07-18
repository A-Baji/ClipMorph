from moviepy import VideoFileClip
from clipmorph.generate_video import AUDIO_PATH, ENHANCED_AUDIO_PATH, VAD_AUDIO_PATH


def extract_audio(input_path):
    clip = VideoFileClip(input_path)
    clip.audio.write_audiofile(AUDIO_PATH)
    clip.close()
