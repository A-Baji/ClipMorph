import math
import os
import requests

from clipmorph.platforms.tiktok.auth import refresh_access_token


def get_optimal_tiktok_chunk_size(video_size_bytes):
    """
    Calculates the optimal chunk size for TikTok video uploads based on file size,
    adhering to TikTok's Content Posting API rules.

    Args:
        video_size_bytes: The size of the video file in bytes (integer).

    Returns:
        The calculated chunk size in bytes (integer).
    """

    MIN_CHUNK_SIZE_MB = 5
    MAX_CHUNK_SIZE_MB = 64
    MIN_CHUNK_SIZE_BYTES = MIN_CHUNK_SIZE_MB * 1024 * 1024
    MAX_CHUNK_SIZE_BYTES = MAX_CHUNK_SIZE_MB * 1024 * 1024

    if video_size_bytes < MIN_CHUNK_SIZE_BYTES or MAX_CHUNK_SIZE_BYTES > video_size_bytes:
        return video_size_bytes

    optimal_chunk_size = MAX_CHUNK_SIZE_BYTES

    total_chunks = math.floor(video_size_bytes / optimal_chunk_size)

    MAX_TOTAL_CHUNKS = 1000
    if total_chunks > MAX_TOTAL_CHUNKS:
        optimal_chunk_size = math.ceil(video_size_bytes / MAX_TOTAL_CHUNKS)
        optimal_chunk_size = max(optimal_chunk_size, MIN_CHUNK_SIZE_BYTES)

    total_chunks = math.floor(video_size_bytes / optimal_chunk_size)

    return optimal_chunk_size


def get_video_info(video_path):
    """
    Get the file size and calculate chunk information.
    """
    video_size = os.path.getsize(video_path)
    chunk_size = get_optimal_tiktok_chunk_size(video_size)
    total_chunk_count = max(1, (video_size + chunk_size - 1) // chunk_size)
    return video_size, chunk_size, total_chunk_count


def initialize_upload(access_token,
                      video_size,
                      chunk_size,
                      total_chunk_count,
                      title="Tiktok Upload"):
    """
    Initialize the upload and retrieve upload_id and upload_url.
    """
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
            'chunk_size': chunk_size,
            'total_chunk_count': total_chunk_count
        }
    }
    response = requests.post(publish_endpoint, json=post_data, headers=headers)
    print(response.json())
    response.raise_for_status()

    data = response.json().get('data', {})
    upload_url = data.get('upload_url')
    if not upload_url:
        raise Exception('Failed to initialize video upload')
    return upload_url


def send_to_server(video_path, upload_url, total_chunk_count, chunk_size,
                   video_size):
    with open(video_path, 'rb') as f:
        for chunk_index in range(total_chunk_count):
            start_byte = chunk_index * chunk_size
            end_byte = min(start_byte + chunk_size, video_size) - 1
            chunk_data = f.read(end_byte - start_byte + 1)
            headers = {
                'Content-Type': 'video/mp4',
                'Content-Length': str(end_byte - start_byte + 1),
                'Content-Range': f'bytes {start_byte}-{end_byte}/{video_size}'
            }
            response = requests.put(upload_url,
                                    data=chunk_data,
                                    headers=headers)
            response.raise_for_status()


def upload_to_tiktok(video_path):
    """
    Orchestrate the upload process using the modular functions.
    """
    access_token = refresh_access_token()
    video_size, chunk_size, total_chunk_count = get_video_info(video_path)
    upload_url = initialize_upload(access_token, video_size, chunk_size,
                                   total_chunk_count)
    send_to_server(video_path, upload_url, total_chunk_count, chunk_size,
                   video_size)
