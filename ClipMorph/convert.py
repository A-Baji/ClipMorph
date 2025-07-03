import moviepy as mpy
from moviepy.video.fx import Crop, Resize
import cv2


def convert_to_short_form(input_path,
                          include_cam=True,
                          cam_x=1420,
                          cam_y=790,
                          cam_width=480,
                          cam_height=270,
                          clip_height=1312):
    with mpy.VideoFileClip(input_path) as clip:
        output_path = f"./{clip.filename.split('.')[0]}-SF.mp4"

        crop_width = 1080
        crop_height = 1920

        if include_cam:
            cam_feed = Crop(x1=cam_x,
                            y1=cam_y,
                            width=cam_width,
                            height=cam_height).apply(clip)
            cam_resized = Resize(width=crop_width).apply(cam_feed)
            cam_h = cam_resized.h
        else:
            cam_h = crop_height - clip_height

        main_clip = Resize(height=crop_height - cam_h).apply(clip)
        main_clip = Crop(width=crop_width,
                         height=main_clip.h,
                         x_center=main_clip.w // 2,
                         y_center=main_clip.h // 2).apply(main_clip)

        if not include_cam:

            def blur_frame(get_frame, t):
                frame = get_frame(t)
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                blurred_bgr = cv2.GaussianBlur(frame_bgr, (51, 51), sigmaX=0)
                return cv2.cvtColor(blurred_bgr, cv2.COLOR_BGR2RGB)

            bg_full = Resize(height=crop_height).apply(clip)
            bg_blur = bg_full.transform(blur_frame)
            bg_blur_cropped = Crop(width=crop_width,
                                   height=crop_height,
                                   x_center=bg_full.w // 2,
                                   y_center=bg_full.h // 2).apply(bg_blur)

            bg_h = cam_h // 2
            bg_blur_top = Crop(x1=0, y1=0, width=crop_width,
                               height=bg_h).apply(bg_blur_cropped)
            bg_blur_bot = Crop(x1=0,
                               y1=bg_h + main_clip.h,
                               width=crop_width,
                               height=bg_h).apply(bg_blur_cropped)
            final_video = mpy.clips_array([[bg_blur_top], [main_clip],
                                           [bg_blur_bot]])
        else:
            final_video = mpy.clips_array([[cam_resized], [main_clip]])

        final_video.write_videofile(output_path,
                                    codec='libx264',
                                    audio_codec='aac')
        return output_path
