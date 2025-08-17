import time
import logging
from requests_oauthlib import OAuth1Session

from clipmorph.platforms.twitter.auth import authenticate_twitter

logger = logging.getLogger(__name__)


def upload_to_twitter(video_path, tweet_text="Twitter/X Upload"):
    api, client = authenticate_twitter()

    try:
        logger.info(f"[Twitter/X] Uploading {video_path}...")
        media = api.media_upload(video_path, media_category="tweet_video")
        media_id = media.media_id_string
        logger.info(
            f"[Twitter/X] Video upload initiated. Media ID: {media_id}")

        processing_state = None
        max_retries = 30
        retry_count = 0
        poll_interval = 5

        oauth = OAuth1Session(
            api.auth.consumer_key,
            client_secret=api.auth.consumer_secret,
            resource_owner_key=api.auth.access_token,
            resource_owner_secret=api.auth.access_token_secret)

        while processing_state != "succeeded" and retry_count < max_retries:
            logger.info("[Twitter/X] Checking video processing status...")
            status_url = f"https://upload.twitter.com/1.1/media/upload.json?command=STATUS&media_id={media_id}"
            response = oauth.get(status_url)
            response.raise_for_status()
            media_status = response.json()
            processing_info = media_status.get("processing_info")

            if processing_info and processing_info.get("state"):
                processing_state = processing_info["state"]
                logger.info(
                    f"[Twitter/X] Current processing state: {processing_state}"
                )

                if processing_state == "succeeded":
                    logger.info(
                        "[Twitter/X] Video successfully processed and ready to be attached to a Tweet!"
                    )
                    break
                elif processing_state == "failed":
                    error = processing_info.get("error")
                    raise Exception(
                        f"Video processing failed: {error.get('message', 'Unknown error')}"
                    )
                else:
                    check_after_secs = processing_info.get(
                        "check_after_secs", poll_interval)
                    logger.info(
                        f"[Twitter/X] Waiting {check_after_secs} seconds before checking again..."
                    )
                    time.sleep(check_after_secs)
                    retry_count += 1
            else:
                logger.info(
                    "[Twitter/X] Processing info not immediately available. Waiting a bit longer."
                )
                time.sleep(poll_interval)
                retry_count += 1

        if processing_state != "succeeded":
            raise Exception(
                "Video did not finish processing within the allowed time or failed."
            )

        logger.info("[Twitter/X] Creating tweet with the uploaded video...")
        media_ids_list = [media_id]
        response = client.create_tweet(text=tweet_text,
                                       media_ids=media_ids_list)
        logger.info("[Twitter/X] Tweet posted successfully!")
        logger.info(f"[Twitter/X] Tweet ID: {response.data['id']}")
        logger.info(f"[Twitter/X] Tweet Text: {response.data['text']}")

    except Exception as e:
        logger.error(f"[Twitter/X] An error occurred: {e}")
