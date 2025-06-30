import moviepy as mpy
from moviepy.video.fx import Crop, Resize

def process_streaming_video(input_path, output_path):
    # Load the original video
    clip = mpy.VideoFileClip(input_path)
    
    # Main content crop (9:16 aspect ratio)
    crop_width = int(clip.h * 9 / 16)  # ~608px for 1080p
    crop_height = clip.h
    
    # Crop the main content (excluding the camera area)
    available_width = clip.w
    x_center = available_width // 2
    
    main_cropped = Crop(
        width=crop_width,
        height=crop_height,
        x_center=x_center,
        y_center=clip.h // 2
    )
    main_cropped = main_cropped.apply(clip)
    
    # Extract camera feed from bottom right
    camera_x1 = 1420
    camera_y1 = 790
    camera_width = 480
    camera_height = 270

    camera_feed = Crop(
        x1=camera_x1,
        y1=camera_y1,
        width=camera_width,
        height=camera_height
    )
    camera_feed = camera_feed.apply(clip)
    
    # Resize camera feed for top overlay
    camera_resized = Resize(width=crop_width)
    camera_resized = camera_resized.apply(camera_feed)
    
    # Composite the main video with camera overlay
    final_video = mpy.CompositeVideoClip([
        main_cropped,
        camera_resized.with_position(("center", "top"))
    ])
    
    # Write the result
    final_video.write_videofile(output_path, codec='libx264', audio_codec='aac')
    
    # Clean up
    clip.close()

# Usage
process_streaming_video("input_video.mp4", "output_shortform.mp4")
