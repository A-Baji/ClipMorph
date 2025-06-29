import moviepy as mpy
from moviepy.video.fx import Crop, Resize

def process_streaming_video(input_path, output_path):
    # Load the original video
    clip = mpy.VideoFileClip(input_path)
    
    # Main content crop (9:16 aspect ratio)
    crop_width = int(clip.h * 9 / 16)  # ~608px for 1080p
    crop_height = clip.h
    
    # Crop the main content (excluding the camera area)
    # Adjust x_offset to avoid the camera in bottom right
    # camera_exclusion_width = 300  # Approximate width to exclude camera area
    available_width = clip.w#- camera_exclusion_width
    x_center = available_width // 2
    
    main_cropped = Crop(
        width=crop_width,
        height=crop_height,
        x_center=x_center,
        y_center=clip.h // 2
    )
    main_cropped = main_cropped.apply(clip)
    
    # Extract camera feed from bottom right
    # Adjust these coordinates based on your actual camera position
    camera_width = 280
    camera_height = 210
    camera_x = clip.w - camera_width - 20  # 20px from right edge
    camera_y = clip.h - camera_height - 20  # 20px from bottom
    
    camera_feed = Crop(
        width=camera_width,
        height=camera_height,
        x_center=camera_x + camera_width//2,
        y_center=camera_y + camera_height//2
    )
    camera_feed = camera_feed.apply(clip)
    
    # Resize camera feed for top overlay (make it smaller)
    camera_resized = Resize(width=180)
    camera_resized = camera_resized.apply(camera_feed)
    
    # Position camera at top center of the cropped video
    cam_final_x = crop_width//2 - camera_resized.w//2
    cam_final_y = 20
    
    # Composite the main video with camera overlay
    final_video = mpy.CompositeVideoClip([
        main_cropped,
        # camera_resized.with_position((cam_final_x, cam_final_y))
    ])
    
    # Write the result
    final_video.write_videofile(output_path, codec='libx264', audio_codec='aac')
    
    # Clean up
    clip.close()

# Usage
process_streaming_video("input_video.mp4", "output_shortform.mp4")
