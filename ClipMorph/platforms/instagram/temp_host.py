from google.cloud import storage
from google.oauth2 import service_account

import os
import urllib.parse

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")


def authenticate_google():
    """
    Authenticates with Google Cloud using the provided scopes.
    Returns a credentials object.
    """
    credentials_info = {
        "type":
        "service_account",
        "project_id":
        os.environ["GCP_PROJECT_ID"],
        "private_key_id":
        os.environ["GCP_PRIVATE_KEY_ID"],
        "private_key":
        os.environ["GCP_PRIVATE_KEY"].replace('\\n', '\n'),
        "client_email":
        os.environ["GCP_CLIENT_EMAIL"],
        "client_id":
        os.environ["GCP_CLIENT_ID"],
        "auth_uri":
        "https://accounts.google.com/o/oauth2/auth",
        "token_uri":
        "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url":
        "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url":
        f"https://www.googleapis.com/robot/v1/metadata/x509/{urllib.parse.quote(os.environ['GCP_CLIENT_EMAIL'])}",
    }

    creds = service_account.Credentials.from_service_account_info(
        credentials_info)

    return creds


def upload_video(video_path, creds):
    """
    Uploads a video to Google Cloud Storage and makes it public.
    Returns the public URL to the uploaded video.
    """
    destination_blob_name = os.path.basename(video_path)
    storage_client = storage.Client(credentials=creds)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(video_path)

    return blob.public_url


def delete_video(video_path, creds):
    """
    Deletes a video from Google Cloud Storage.
    """
    blob_name = os.path.basename(video_path)
    storage_client = storage.Client(credentials=creds)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.delete()

    return True
