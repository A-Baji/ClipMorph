import logging
import os
from clipmorph.generate_video import AUDIO_PATH, CENSORED_AUDIO_PATH, SRT_PATH
from clipmorph.generate_video.censor import detect_profanity, mute_audio
from clipmorph.generate_video.convert import convert_to_short_form
from clipmorph.generate_video.subtitles import generate_srt, replace_audio_and_overlay_subs
from clipmorph.generate_video.transcript import extract_audio, transcribe_audio
from clipmorph.utils import delete_file


def conversion_pipeline(args):
    input_path = args.input_path
    file_name = os.path.splitext(os.path.basename(input_path))[0]
    final_output = f"{file_name}-final.mp4"

    logging.info("Converting video to short-form format...")

    # 1. Extract audio and transcribe
    extract_audio(input_path)
    segments = transcribe_audio()

    # 2. Detect and mute cursewords
    intervals = detect_profanity(segments)
    mute_audio(intervals)

    delete_file(AUDIO_PATH)

    # 3. Generate subtitles
    generate_srt(segments)

    # 4. Convert video to short-form format (no audio replacement yet)
    convert_to_short_form(input_path=input_path,
                          include_cam=args.include_cam,
                          cam_x=args.cam_x,
                          cam_y=args.cam_y,
                          cam_width=args.cam_width,
                          cam_height=args.cam_height)

    # 5. Replace audio and overlay/attach subtitles
    replace_audio_and_overlay_subs(final_output)

    delete_file(CENSORED_AUDIO_PATH)
    delete_file(SRT_PATH)

    logging.info(f"Saved converted video to {final_output}")

    return final_output
