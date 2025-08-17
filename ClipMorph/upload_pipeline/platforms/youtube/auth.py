import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


def authenticate_youtube():
    """
    Returns a valid Credentials object for YouTube Data API v3 using environment variables.
    Expects GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "Missing one or more required YouTube OAuth2 environment variables."
        )

    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds
