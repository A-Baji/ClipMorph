import moviepy as mpy
from moviepy.video.fx import Crop, Resize

def process_streaming_video(input_path, output_path, include_cam=True):
    clip = mpy.VideoFileClip(input_path)
    
    crop_width = 1080
    crop_height = 1920
    
    if include_cam:
        # Extract camera feed from bottom right
        camera_x1 = 1420
        camera_y1 = 790
        camera_width = 480
        camera_height = 270

        # Crop the camera feed
        camera_feed = Crop(
            x1=camera_x1,
            y1=camera_y1,
            width=camera_width,
            height=camera_height
        )
        camera_feed = camera_feed.apply(clip)
        
        # Resize camera feed to match crop width
        camera_resized = Resize(width=crop_width)
        camera_resized = camera_resized.apply(camera_feed)
        cam_height = camera_resized.h
    else:
        cam_height = 607

    # Resize the clip to fit under the camera feed
    clip_resized = Resize(height=crop_height - cam_height)
    clip_resized = clip_resized.apply(clip)
    
    # Crop the clip
    clip_cropped = Crop(
        width=crop_width,
        height=clip_resized.h,
        x_center=clip_resized.w // 2,
        y_center=clip_resized.h // 2
    )
    clip_cropped = clip_cropped.apply(clip_resized)
    
    if include_cam:
        # Stack clips vertically: camera on top, clip below
        final_video = mpy.clips_array([[camera_resized], [clip_cropped]])
    else:
        final_video = clip_cropped
    
    # Write the result
    final_video.write_videofile(output_path, codec='libx264', audio_codec='aac')
    
    # Clean up
    clip.close()

# Usage
process_streaming_video("test.mp4", "output_shortform.mp4", False)
