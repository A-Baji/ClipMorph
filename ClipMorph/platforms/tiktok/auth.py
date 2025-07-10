import os
import requests

TOKEN_URL = 'https://open.tiktokapis.com/v2/oauth/token/'

TIKTOK_CLIENT_KEY = os.getenv('TIKTOK_CLIENT_KEY')
TIKTOK_CLIENT_SECRET = os.getenv('TIKTOK_CLIENT_SECRET')
TIKTOK_REFRESH_TOKEN = os.getenv('TIKTOK_REFRESH_TOKEN')


def refresh_access_token():
    data = {
        'client_key': TIKTOK_CLIENT_KEY,
        'client_secret': TIKTOK_CLIENT_SECRET,
        'grant_type': 'refresh_token',
        'refresh_token': TIKTOK_REFRESH_TOKEN
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    response = requests.post(TOKEN_URL, data=data, headers=headers)
    response.raise_for_status()
    resp_json = response.json()

    return resp_json.get('access_token')
