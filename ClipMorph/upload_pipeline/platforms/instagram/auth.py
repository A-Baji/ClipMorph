import os
import requests

FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")


def get_page_access_token():
    """
    Exchanges a user access token for a page access token.
    """
    url = f"https://graph.facebook.com/v23.0/{FACEBOOK_PAGE_ID}?fields=access_token&access_token={FACEBOOK_ACCESS_TOKEN}"
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
