# Handles CLI argument parsing, user prompts, and workflow orchestration

import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Convert and upload a video to short-form platforms.")
    parser.add_argument("input_path", help="Path to the input video file.")
    parser.add_argument("--no-confirm", "-y", action="store_true", help="Bypass upload confirmation prompt.")
    parser.add_argument("--clean", "-c", action="store_true", help="Delete original video after upload.")
    parser.add_argument("--no-cam", dest="include_cam", action="store_false", help="Exclude the camera feed from the output.")
    parser.add_argument("--cam-x", type=int, default=1420, help="Top left x coordinate of camera feed.")
    parser.add_argument("--cam-y", type=int, default=790, help="Top left y coordinate of camera feed.")
    parser.add_argument("--cam-width", type=int, default=480, help="Width in pixels of camera feed.")
    parser.add_argument("--cam-height", type=int, default=270, help="Height in pixels of camera feed.")
    return parser.parse_args()
