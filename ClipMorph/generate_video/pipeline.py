import logging
import os
from clipmorph.generate_video import AUDIO_PATH, CENSORED_AUDIO_PATH, SRT_PATH
from clipmorph.generate_video.audio import extract_audio
from clipmorph.generate_video.transcript import transcribe_audio, generate_srt
from clipmorph.generate_video.censor import detect_profanity, mute_audio
from clipmorph.generate_video.convert import convert_to_short_form
from clipmorph.utils import delete_file


def conversion_pipeline(args):
    input_path = args.input_path

    logging.info("[Audio 1/1] Extracting audio from video...")
    extract_audio(input_path)

    logging.info("[Subtitles 1/2] Transcribing audio...")
    segments = transcribe_audio()
    logging.info("[Subtitles 2/2] Generating subtitles (.srt)...")
    generate_srt(segments)

    logging.info("[Profanity 1/3] Detecting profanity in audio...")
    intervals = detect_profanity(segments)
    logging.info("[Profanity 2/3] Muting profane audio segments...")
    mute_audio(intervals)
    logging.info("[Profanity 3/3] Censoring subtitles...")
    # TODO: Censor subtitles
    delete_file(AUDIO_PATH)

    logging.info(
        "[Editing 1/1] Converting video to short-form format and overlaying subtitles..."
    )
    final_output = convert_to_short_form(input_path=input_path,
                                         include_cam=args.include_cam,
                                         cam_x=args.cam_x,
                                         cam_y=args.cam_y,
                                         cam_width=args.cam_width,
                                         cam_height=args.cam_height)
    delete_file(CENSORED_AUDIO_PATH)
    delete_file(SRT_PATH)

    logging.info(f"Saved converted video to {final_output}")

    return final_output
