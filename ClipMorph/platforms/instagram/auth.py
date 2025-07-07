import os
import requests
import webbrowser

# Constants for your app
APP_ID = os.getenv("FACEBOOK_APP_ID")
APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
REDIRECT_URI = 'https://localhost/'  # Set this in your Meta app settings
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


def get_page_access_token(user_access_token):
    """
    Exchanges a user access token for a page access token.
    """
    url = f"https://graph.facebook.com/v23.0/{FACEBOOK_PAGE_ID}?fields=access_token&access_token={user_access_token}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()['access_token']


def get_ig_user_id(page_access_token):
    """
    Gets the Instagram user ID connected to a Facebook Page.
    """
    url = f"https://graph.facebook.com/v23.0/{FACEBOOK_PAGE_ID}?fields=instagram_business_account&access_token={page_access_token}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()['instagram_business_account']['id']
