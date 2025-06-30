import argparse
import moviepy as mpy
from moviepy.video.fx import Crop, Resize

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
        )
        cam_feed = cam_feed.apply(clip)
        
        # Resize cam feed to match crop width
        cam_resized = Resize(width=crop_width)
        cam_resized = cam_resized.apply(cam_feed)
        cam_height = cam_resized.h
    else:
        cam_height = 607

    # Resize the clip to fit under the cam feed
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
        # Stack clips vertically: cam on top, clip below
        final_video = mpy.clips_array([[cam_resized], [clip_cropped]])
    else:
        final_video = clip_cropped
    
    # Write the result
    final_video.write_videofile(output_path, codec='libx264', audio_codec='aac')
    
    # Clean up
    clip.close()


def main():
    parser = argparse.ArgumentParser(description="Convert a streaming video into short-form content.")
    parser.add_argument("input_path", help="Path to the input video file.")
    parser.add_argument("--no-cam", dest="include_cam", action="store_false", help="Exclude the camera feed from the output.")
    parser.add_argument("--cam-x", type=int, default=1420, help="Top left x coordinate of camera feed.")
    parser.add_argument("--cam-y", type=int, default=790, help="Top left y coordinate of camera feed.")
    parser.add_argument("--cam-width", type=int, default=480, help="Width in pixels of camera feed.")
    parser.add_argument("--cam-height", type=int, default=270, help="Height in pixels of camera feed.")
    args = parser.parse_args()

    convert_to_short_form(
        input_path=args.input_path,
        include_cam=args.include_cam,
        cam_x=args.cam_x,
        cam_y=args.cam_y,
        cam_width=args.cam_width,
        cam_height=args.cam_height
    )


if __name__ == "__main__":
    main()
