import logging
import os

import cv2
import moviepy as mpy
from moviepy.video.fx import Crop
from moviepy.video.fx import Resize


class EditingPipeline:

    def __init__(self,
                 input_path,
                 output_dir="output/",
                 muted_audio=None,
                 segments=None,
                 include_cam=True,
                 cam_x=1420,
                 cam_y=790,
                 cam_width=480,
                 cam_height=270,
                 clip_height=1312):
        self.input_path = input_path
        self.output_dir = output_dir if output_dir.endswith(
            "/") else output_dir + "/"
        self.muted_audio = muted_audio
        self.segments = segments
        self.include_cam = include_cam
        self.cam_x = cam_x
        self.cam_y = cam_y
        self.cam_width = cam_width
        self.cam_height = cam_height
        self.clip_height = clip_height

    def _set_audio(self, clip: mpy.VideoFileClip, muted_audio):
        return clip.with_audio(muted_audio)

    def _process_camera_feed(self, clip, cam_x, cam_y, cam_width, cam_height,
                             crop_width):
        cam_feed = Crop(x1=cam_x, y1=cam_y, width=cam_width,
                        height=cam_height).apply(clip)
        cam_resized = Resize(width=crop_width).apply(cam_feed)
        cam_h = cam_resized.h
        if cam_h % 2 != 0:
            cam_resized = Resize((crop_width, cam_h + 1)).apply(cam_resized)
            cam_h = cam_resized.h
        return cam_resized, cam_h

    def _process_main_clip(self, clip, crop_height, cam_h, crop_width):
        main_clip = Resize(height=crop_height - cam_h).apply(clip)
        main_clip = Crop(width=crop_width,
                         height=main_clip.h,
                         x_center=main_clip.w // 2,
                         y_center=main_clip.h // 2).apply(main_clip)
        return main_clip

    def _blur_background(self, clip, crop_width, crop_height, cam_h,
                         main_clip):

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
        return final_video

    def _overlay_subtitles(self, final_video,
                           segments) -> mpy.CompositeVideoClip:
        subs = segments
        subtitle_clips = []

        for sub in subs:
            txt_clip = (mpy.TextClip(
                text=sub["text"],
                color="#ffffff",
                font=None,
                font_size=70,
                stroke_color="black",
                stroke_width=12,
                method="caption",
                size=(int(final_video.w * 0.8), None),
                text_align="center",
                horizontal_align="center",
                vertical_align="center",
                margin=(0, 50),
            ).with_start(sub["start"]).with_end(sub["end"]).with_position(
                ("center", int(final_video.h * 0.70))))

            subtitle_clips.append(txt_clip)

        final = mpy.CompositeVideoClip([final_video, *subtitle_clips])
        return final

    def run(self):
        try:
            logging.info("Loading video clip...")
            with mpy.VideoFileClip(self.input_path) as clip:
                filename = clip.filename.split("/")[-1].split("\\")[-1].split(
                    ".")[0]
                os.makedirs(self.output_dir, exist_ok=True)
                output_path = f"{self.output_dir}{filename}-converted.mp4"
                logging.info("Applying muted audio to the video...")
                clip = self._set_audio(clip, self.muted_audio)

                crop_width = 1080
                crop_height = 1920

                if self.include_cam:
                    logging.info("Processing camera feed...")
                    cam_resized, cam_h = self._process_camera_feed(
                        clip, self.cam_x, self.cam_y, self.cam_width,
                        self.cam_height, crop_width)
                else:
                    cam_h = crop_height - self.clip_height

                logging.info("Processing main clip...")
                main_clip = self._process_main_clip(clip, crop_height, cam_h,
                                                    crop_width)

                if not self.include_cam:
                    logging.info("Blurring background...")
                    composited_video = self._blur_background(
                        clip, crop_width, crop_height, cam_h, main_clip)
                else:
                    logging.info("Combining camera feed and main clip...")
                    composited_video = mpy.clips_array([[cam_resized],
                                                        [main_clip]])

                if self.segments:
                    logging.info("Overlaying subtitles...")
                    final_video: mpy.CompositeVideoClip = self._overlay_subtitles(
                        composited_video, self.segments)
                else:
                    logging.info("No subtitles provided, skipping overlay.")
                    final_video = composited_video

                logging.info("Writing final video to file...")
                final_video.write_videofile(output_path,
                                            codec="libx264",
                                            audio_codec="aac")
                final_video.close()

                return output_path
        except Exception as e:
            logging.error(f"An error occurred during video processing: {e}")
            raise
