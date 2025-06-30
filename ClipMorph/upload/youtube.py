from clipmorph.auth.youtube import authenticate_youtube

def upload_to_youtube(video_path):
    authenticate_youtube()
    print(f"[YouTube] Uploading {video_path} to YouTube Shorts... (placeholder)")
    # Placeholder: actual upload logic would go here
