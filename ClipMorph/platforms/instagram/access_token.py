import logging
import os
import webbrowser
import requests

APP_ID = os.getenv("FACEBOOK_APP_ID")
APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
REDIRECT_URI = 'https://localhost/'
SCOPES = [
    'instagram_basic', 'pages_show_list', 'pages_read_engagement',
    'pages_manage_posts', 'instagram_content_publish'
]


def get_user_access_token():
    """
    Guides user through browser-based OAuth to obtain a user access token.
    """
    oauth_url = (f"https://www.facebook.com/v23.0/dialog/oauth"
                 f"?client_id={APP_ID}"
                 f"&redirect_uri={REDIRECT_URI}"
                 f"&scope={','.join(SCOPES)}"
                 f"&response_type=code")
    print("Open this URL in your browser and authorize the app:")
    print(oauth_url)
    webbrowser.open(oauth_url)
    code = input(
        "Paste the 'code' parameter from the redirect URL here: ").strip()

    # Exchange code for access token
    token_url = (f"https://graph.facebook.com/v23.0/oauth/access_token"
                 f"?client_id={APP_ID}"
                 f"&redirect_uri={REDIRECT_URI}"
                 f"&client_secret={APP_SECRET}"
                 f"&code={code}")
    resp = requests.get(token_url)
    resp.raise_for_status()
    data = resp.json()
    return data['access_token']


def generate_long_lived_access_token():
    response = requests.get(
        "https://graph.facebook.com/v23.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "fb_exchange_token": get_user_access_token()
        })
    logging.info(f"Access token: {response.json()["access_token"]}")
    return response.json()["access_token"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        access_token = generate_long_lived_access_token()
        logging.info(
            f"Set FACEBOOK_ACCESS_TOKEN={access_token} in your .env file")
    except Exception as e:
        logging.error(f"Error generating long-lived access token: {e}")
        raise