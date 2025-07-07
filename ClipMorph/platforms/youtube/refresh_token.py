import os
import logging
from google_auth_oauthlib.flow import InstalledAppFlow


def generate_refresh_token():
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "redirect_uris":
                ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        }, scopes)
    creds = flow.run_local_server(port=0, prompt='select_account')
    logging.info(f"Refresh token: {creds.refresh_token}")
    return creds.refresh_token


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        refresh_token = generate_refresh_token()
        logging.info(
            f"Set GOOGLE_REFRESH_TOKEN={refresh_token} in your .env file")
    except Exception as e:
        logging.error(f"Error generating refresh token: {e}")
        raise
