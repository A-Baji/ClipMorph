import logging
import requests
import time

from clipmorph.platforms.instagram.auth import get_page_access_token, get_ig_user_id
from clipmorph.platforms.instagram.temp_host import upload_video, delete_video, authenticate_google


def create_reel_container(ig_user_id,
                          video_url,
                          caption,
                          access_token,
                          share_to_feed=True,
                          thumb_offset=None):
    """
    Creates a media container for a Reel.
    """
    url = f"https://graph.facebook.com/v23.0/{ig_user_id}/media"
    payload = {
        'media_type': 'REELS',
        'video_url': video_url,
        'caption': caption,
        'access_token': access_token,
        'share_to_feed': 'true' if share_to_feed else 'false',
    }
    if thumb_offset is not None:
        payload['thumb_offset'] = str(thumb_offset)
    resp = requests.post(url, data=payload)
    resp.raise_for_status()
    return resp.json()['id']


def publish_media(ig_user_id, creation_id, access_token):
    """
    Publishes the media container to Instagram as a Reel.
    """
    url = f"https://graph.facebook.com/v23.0/{ig_user_id}/media_publish"
    payload = {'creation_id': creation_id, 'access_token': access_token}
    resp = requests.post(url, data=payload)
    resp.raise_for_status()
    return resp.json()['id']


def wait_for_processing(creation_id, access_token, timeout=120):
    """
    Polls the media container status until it's finished processing.
    """
    url = f"https://graph.facebook.com/v23.0/{creation_id}?fields=status_code&access_token={access_token}"
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(url)
        resp.raise_for_status()
        status = resp.json().get('status_code')
        if status == 'FINISHED':
            return True
        elif status == 'ERROR':
            logging.error(f"Video processing failed: {resp.json()}")
            return False
        time.sleep(5)
    raise TimeoutError("Timed out waiting for video processing.")


def upload_to_instagram(video_path, caption="Uploaded via API"):
    logging.info("[Instagram] Starting Instagram Reels upload...")
    google_creds = authenticate_google()
    logging.info(
        "[Instagram] Authenticated to Cloud Storage with Google for temporary video hosting."
    )
    video_url = upload_video(video_path, google_creds)
    logging.info(f"[Instagram] Uploaded video to temporary host: {video_url}")

    page_token = get_page_access_token()
    logging.info("[Instagram] Fetched Instagram page access token.")
    ig_user_id = get_ig_user_id(page_token)
    logging.info(f"[Instagram] Fetched Instagram user ID: {ig_user_id}")
    creation_id = create_reel_container(ig_user_id, video_url, caption,
                                        page_token)
    logging.info(
        f"[Instagram] Created Instagram Reel container with ID: {creation_id}")

    try:
        logging.info("[Instagram] Processing video...")
        if wait_for_processing(creation_id, page_token):
            logging.info(
                "[Instagram] Video processing finished. Publishing Reel...")
            media_id = publish_media(ig_user_id, creation_id, page_token)
            logging.info(
                f"[Instagram] Published Reel with media ID: {media_id}")
        else:
            logging.error(
                "[Instagram] Video processing failed or returned error status."
            )
    except TimeoutError as e:
        logging.error(
            f"[Instagram] Timeout while waiting for video processing: {e}")
    except Exception as e:
        logging.error(
            f"[Instagram] Unexpected error during Instagram upload: {e}")
    finally:
        delete_video(video_path, google_creds)
        logging.info("[Instagram] Cleaned up temporary hosted video.")
