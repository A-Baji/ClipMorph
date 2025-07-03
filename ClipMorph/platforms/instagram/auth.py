# auth.py
import os
import logging
from dotenv import load_dotenv

load_dotenv()
GRAPH_BASE = "https://graph.instagram.com/v23.0"


def authenticate_instagram():
    """
    Validates presence of credentials and returns access token & user ID.
    """
    app_id = os.getenv("INSTAGRAM_APP_ID")
    app_secret = os.getenv("INSTAGRAM_APP_SECRET")
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    user_id = os.getenv("INSTAGRAM_USER_ID")

    logging.info("[Instagram] Authenticating with provided credentials...")
    missing = [
        k for k, v in {
            "APP_ID": app_id,
            "APP_SECRET": app_secret,
            "ACCESS_TOKEN": access_token,
            "USER_ID": user_id
        }.items() if not v
    ]
    if missing:
        logging.error(f"[Instagram] Missing credentials: {missing}")
        raise EnvironmentError("Instagram credentials not set")
    logging.info("[Instagram] Credentials loaded successfully")
    return access_token, user_id
