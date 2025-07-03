import moviepy as mpy
from moviepy.video.fx import Crop, Resize
import cv2

def convert_to_short_form(
    input_path,
    include_cam=True,
    cam_x=1420,
    cam_y=790,
    cam_width=480,
    cam_height=270
):
    clip = mpy.VideoFileClip(input_path)
    output_path = f"./{clip.filename.split('.')[0]}-SF.mp4"

    crop_width = 1080
    crop_height = 1920
    
    if include_cam:
        # Extract cam feed from bottom right
        cam_feed = Crop(
            x1=cam_x,
            y1=cam_y,
            width=cam_width,
            height=cam_height
        ).apply(clip)
        
        # Resize cam feed to match crop width
        cam_resized = Resize(width=crop_width).apply(cam_feed)
        cam_height = cam_resized.h
    else:
        cam_height = 608

    # Resize the clip to fit under the cam feed
    clip_resized = Resize(height=crop_height - cam_height).apply(clip)
    
    # Crop the clip
    clip_cropped = Crop(
        width=crop_width,
        height=clip_resized.h,
        x_center=clip_resized.w // 2,
        y_center=clip_resized.h // 2
    ).apply(clip_resized)

    if not include_cam:
        def blur_frame(get_frame, t):
            frame = get_frame(t)
            # Convert RGB (MoviePy) to BGR (OpenCV)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            # Apply Gaussian blur; kernel size must be odd and positive
            blurred_bgr = cv2.GaussianBlur(frame_bgr, (51, 51), sigmaX=0)
            # Convert back to RGB for MoviePy
            blurred_rgb = cv2.cvtColor(blurred_bgr, cv2.COLOR_BGR2RGB)
            return blurred_rgb
        
        clip_resized = Resize(height=crop_height).apply(clip)

        bg_blur = clip_resized.transform(blur_frame)

        bg_blur = Crop(
            width=crop_width,
            height=crop_height,
            x_center=clip_resized.w // 2,
            y_center=clip_resized.h // 2
        ).apply(bg_blur)

        bg_blur_top = Crop(
            x1=0,
            y1=0,
            width=crop_width,
            height=cam_height // 2
        ).apply(bg_blur)

        bg_blur_bot = Crop(
            x1=0,
            y1=cam_height // 2 + clip_cropped.h,
            width=crop_width,
            height=cam_height // 2
        ).apply(bg_blur)
    
    if include_cam:
        final_video = mpy.clips_array([[cam_resized], [clip_cropped]])
    else:
        final_video = mpy.clips_array([[bg_blur_top], [clip_cropped], [bg_blur_bot]])

    # Write the result
    final_video.write_videofile(output_path, codec='libx264', audio_codec='aac')
    
    # Clean up
    clip.close()

    return output_path
