import os
import requests
import logging

from clipmorph.platforms.tiktok.auth import refresh_access_token


def get_video_size(video_path):
    """
    Get the file size and calculate chunk information.
    """
    try:
        video_size = os.path.getsize(video_path)
    except OSError as e:
        logging.error(f"Failed to get video size for {video_path}: {e}")
        raise

    return video_size


def initialize_upload(access_token, video_size, title="Tiktok Upload"):
    """
    Initialize the upload and retrieve upload_id and upload_url.
    """
    logging.info("[TikTok] Initializing upload session...")
    publish_endpoint = 'https://open.tiktokapis.com/v2/post/publish/video/init/'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json; charset=UTF-8'
    }
    post_data = {
        'post_info': {
            'privacy_level': 'SELF_ONLY',
            'title': title
        },
        'source_info': {
            'source': 'FILE_UPLOAD',
            'video_size': video_size,
            'chunk_size': video_size,
            'total_chunk_count': 1
        }
    }
    response = requests.post(publish_endpoint, json=post_data, headers=headers)
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        logging.error(
            f"[TikTok] Failed to initialize upload: {e} | Response: {response.text}"
        )
        raise

    data = response.json().get('data', {})
    upload_url = data.get('upload_url')
    if not upload_url:
        logging.error(
            "[TikTok] Failed to initialize video upload: No upload_url returned."
        )
        raise Exception('Failed to initialize video upload')
    logging.info(f"[TikTok] Received upload URL.")
    return upload_url


def send_to_server(video_path, upload_url, video_size):
    logging.info(f"[TikTok] Sending video to Tiktok servers...")
    with open(video_path, 'rb') as f:
        video_data = f.read()
        headers = {
            'Content-Type': 'video/mp4',
            'Content-Length': str(video_size),
            'Content-Range': f'bytes 0-{video_size-1}/{video_size}'
        }
        response = requests.put(upload_url, data=video_data, headers=headers)
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        logging.error(
            f"[TikTok] Failed to upload video: {e} | Response: {response.text}"
        )
        raise


def upload_to_tiktok(video_path):
    """
    Orchestrate the upload process using the modular functions.
    """
    logging.info("[TikTok] Starting TikTok upload...")
    access_token = refresh_access_token()
    logging.info("[TikTok] Refreshed access token.")
    video_size = get_video_size(video_path)
    upload_url = initialize_upload(access_token, video_size)
    send_to_server(video_path, upload_url, video_size)
    logging.info("[TikTok] Upload complete.")
