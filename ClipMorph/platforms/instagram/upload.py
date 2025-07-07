import logging
import requests
import time

from clipmorph.platforms.instagram.auth import get_page_access_token, get_ig_user_id
from clipmorph.platforms.instagram.temp_host import upload_to_0x0, delete_from_0x0


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
    video_url, token = upload_to_0x0(video_path)

    page_token = get_page_access_token()
    ig_user_id = get_ig_user_id(page_token)
    creation_id = create_reel_container(ig_user_id, video_url, caption,
                                        page_token)

    if wait_for_processing(creation_id, page_token):
        media_id = publish_media(ig_user_id, creation_id, page_token)
        logging.info(f"Published Reel with media ID: {media_id}")

    if token:
        delete_from_0x0(video_url, token)
