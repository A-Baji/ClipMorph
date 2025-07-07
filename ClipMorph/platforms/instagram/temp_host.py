from google.cloud import storage
import os

GOOGLE_BUCKET_NAME = os.getenv("GOOGLE_BUCKET_NAME", "ig_reels_temp_host")


def upload_video(video_path, creds):
    """
    Uploads a video to Google Cloud Storage and makes it public.
    Returns the public URL to the uploaded video.
    """
    destination_blob_name = os.path.basename(video_path)
    storage_client = storage.Client(credentials=creds)
    bucket = storage_client.bucket(GOOGLE_BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(video_path)
    blob.make_public()
    return blob.public_url


def delete_video(video_path, creds):
    """
    Deletes a video from Google Cloud Storage.
    """
    blob_name = os.path.basename(video_path)
    storage_client = storage.Client(credentials=creds)
    bucket = storage_client.bucket(GOOGLE_BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.delete()
    return True
