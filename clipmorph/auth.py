"""Load local platform credentials without exposing their secret values."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any

import yaml

from clipmorph.job import default_data_dir


AUTH_FILE_NAME = "auth.yaml"

AUTH_ENVIRONMENT_KEYS = {
    "youtube": {
        "client_id": "GOOGLE_CLIENT_ID",
        "client_secret": "GOOGLE_CLIENT_SECRET",
        "refresh_token": "GOOGLE_REFRESH_TOKEN",
    },
    "instagram": {
        "app_id": "FACEBOOK_APP_ID",
        "app_secret": "FACEBOOK_APP_SECRET",
        "page_id": "FACEBOOK_PAGE_ID",
        "access_token": "FACEBOOK_ACCESS_TOKEN",
        "gcs_bucket_name": "GCS_BUCKET_NAME",
        "gcp_private_key_id": "GCP_PRIVATE_KEY_ID",
        "gcp_private_key": "GCP_PRIVATE_KEY",
        "gcp_client_email": "GCP_CLIENT_EMAIL",
        "gcp_client_id": "GCP_CLIENT_ID",
        "gcp_project_id": "GCP_PROJECT_ID",
    },
    "tiktok": {
        "client_key": "TIKTOK_CLIENT_KEY",
        "client_secret": "TIKTOK_CLIENT_SECRET",
        "access_token": "TIKTOK_ACCESS_TOKEN",
        "refresh_token": "TIKTOK_REFRESH_TOKEN",
        "open_id": "TIKTOK_OPEN_ID",
    },
    "twitter": {
        "client_id": "TWITTER_CLIENT_ID",
        "client_secret": "TWITTER_CLIENT_SECRET",
        "api_key": "TWITTER_API_KEY",
        "api_key_secret": "TWITTER_API_KEY_SECRET",
        "access_token": "TWITTER_ACCESS_TOKEN",
        "access_token_secret": "TWITTER_ACCESS_TOKEN_SECRET",
        "bearer_token": "TWITTER_BEARER_TOKEN",
    },
    "hugging_face": {
        "access_token": "HUGGING_FACE_ACCESS_TOKEN",
    },
}

AUTH_TEMPLATE = """# ClipMorph platform credentials
# Keep this file private. Values in the environment take precedence.
youtube:
    client_id: ""
    client_secret: ""
    refresh_token: ""
instagram:
    app_id: ""
    app_secret: ""
    page_id: ""
    access_token: ""
    gcs_bucket_name: ""
    gcp_private_key_id: ""
    gcp_private_key: ""
    gcp_client_email: ""
    gcp_client_id: ""
    gcp_project_id: ""
tiktok:
    client_key: ""
    client_secret: ""
    access_token: ""
    refresh_token: ""
    open_id: ""
twitter:
    client_id: ""
    client_secret: ""
    api_key: ""
    api_key_secret: ""
    access_token: ""
    access_token_secret: ""
    bearer_token: ""
hugging_face:
    access_token: ""
"""


def auth_file_path(data_dir: str | Path | None = None) -> Path:
    """Return the local auth file path for the selected data directory."""
    directory = Path(data_dir) if data_dir else default_data_dir()
    return directory / AUTH_FILE_NAME


def create_auth_template(data_dir: str | Path | None = None) -> Path:
    """Create a blank auth template, backing up an existing auth file first."""
    path = auth_file_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup_path = path.with_suffix(path.suffix + ".backup")
        shutil.copy2(path, backup_path)
        print(f"Existing auth file backed up to: {backup_path}")
    path.write_text(AUTH_TEMPLATE, encoding="utf-8")
    print(f"Created auth template at: {path}")
    return path


def load_auth_config(data_dir: str | Path | None = None) -> dict[str, Any]:
    """Load ``auth.yaml`` and fill missing platform environment variables."""
    path = auth_file_path(data_dir)
    if not path.exists():
        return {}

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Unable to read auth file {path}: {error}") from error

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("Auth file root must be an object")

    for platform, fields in loaded.items():
        if platform not in AUTH_ENVIRONMENT_KEYS:
            continue
        if not isinstance(fields, dict):
            raise ValueError(f"Auth configuration for {platform} must be an object")
        for field, environment_key in AUTH_ENVIRONMENT_KEYS[platform].items():
            value = fields.get(field)
            if value is not None and value != "":
                os.environ.setdefault(environment_key, str(value))
    return loaded


def credential_status() -> dict[str, bool]:
    """Return whether each platform has at least one configured credential."""
    return {
        platform: any(os.getenv(environment_key)
                      for environment_key in fields.values())
        for platform, fields in AUTH_ENVIRONMENT_KEYS.items()
    }