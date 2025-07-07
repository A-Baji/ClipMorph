import time
import random
import logging
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from clipmorph.platforms.youtube.auth import authenticate_google
from googleapiclient.discovery import build

MAX_RETRIES = 3
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]


def resumable_upload(request):
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            logging.info("[YouTube] Uploading file...")
            status, response = request.next_chunk()
            if response is not None:
                if 'id' in response:
                    logging.info(
                        f"[YouTube] Video id '{response['id']}' was successfully uploaded."
                    )
                else:
                    logging.error(
                        f"[YouTube] The upload failed with an unexpected response: {response}"
                    )
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = f"A retriable HTTP error {e.resp.status} occurred:\n{e.content}"
            else:
                raise
        except Exception as e:
            error = f"A retriable error occurred: {e}"
        if error is not None:
            logging.warning(error)
            retry += 1
            if retry > MAX_RETRIES:
                logging.error("[YouTube] No longer attempting to retry.")
                break
            max_sleep = 2**retry
            sleep_seconds = random.random() * max_sleep
            logging.info(
                f"[YouTube] Sleeping {sleep_seconds:.2f} seconds and then retrying..."
            )
            time.sleep(sleep_seconds)
            error = None


def upload_to_youtube(video_path,
                      title="YouTube Shorts Upload",
                      description="Uploaded via API",
                      category="22",
                      keywords="",
                      privacy_status="private"):
    """
    Uploads a video to YouTube using the Data API v3.
    Args:
        video_path (str): Path to the video file.
        title (str): Video title.
        description (str): Video description.
        category (str): Numeric video category (default: 22 for People & Blogs).
        keywords (str): Comma-separated keywords.
        privacy_status (str): 'public', 'private', or 'unlisted'.
    """
    creds = authenticate_google(
        ["https://www.googleapis.com/auth/youtube.upload"])
    youtube = build("youtube", "v3", credentials=creds)
    tags = [k.strip() for k in keywords.split(",")
            if k.strip()] if keywords else None
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': category
        },
        'status': {
            'privacyStatus': privacy_status
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=','.join(body.keys()),
                                      body=body,
                                      media_body=media)
    resumable_upload(request)
