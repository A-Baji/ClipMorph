import logging
import os
import requests

from clipmorph.platforms.instagram.auth import authenticate_instagram, GRAPH_BASE
from clipmorph.platforms.instagram.temp_host import upload_to_0x0

logging.basicConfig(level=logging.INFO)

logging.basicConfig(level=logging.INFO)


def upload_to_instagram(video_path: str, caption: str = "") -> dict:
    # 1. Authenticate
    access_token, user_id = authenticate_instagram()

    # 2. Upload to 0x0.st
    # result = upload_to_0x0(video_path)
    video_url = "https://0x0.st/80Jg.mp4"
    logging.info(f"[0x0.st] Hosted URL: {video_url}")

    # 3. Create Reels container
    create_endpoint = f"{GRAPH_BASE}/{user_id}/media"
    params_create = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": access_token
    }
    logging.info("[Instagram] Creating Reels media container…")
    resp_create = requests.post(create_endpoint, params=params_create)
    resp_create.raise_for_status()
    creation_id = resp_create.json().get("id")
    if not creation_id:
        logging.error(
            f"[Instagram] Container creation failed: {resp_create.text}")
        raise RuntimeError("Failed to create media container")

    # 4. Publish the Reel
    publish_endpoint = f"{GRAPH_BASE.replace("instagram", "facebook")}/{user_id}/media_publish"
    params_publish = {"creation_id": creation_id, "access_token": access_token}
    logging.info("[Instagram] Publishing Reels…")
    resp_publish = requests.post(publish_endpoint, params=params_publish)
    resp_publish.raise_for_status()

    publish_response = resp_publish.json()
    logging.info(f"[Instagram] Publish response: {publish_response}")
    return publish_response
