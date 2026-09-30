"""Load local platform credentials without exposing their secret values."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from clipmorph.configuration import resolve_backup_keep_n, rotate_backup
from clipmorph.job import default_data_dir


AUTH_FILE_NAME = "auth.yaml"
_active_auth_path: Path | None = None

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
        "refresh_token": "TIKTOK_REFRESH_TOKEN",
    },
    "twitter": {
        "client_id": "TWITTER_CLIENT_ID",
        "client_secret": "TWITTER_CLIENT_SECRET",
        "oauth2_access_token": "TWITTER_OAUTH2_ACCESS_TOKEN",
        "oauth2_refresh_token": "TWITTER_OAUTH2_REFRESH_TOKEN",
        "oauth2_expires_at": "TWITTER_OAUTH2_EXPIRES_AT",
    },
    # Facebook publishes through the same Meta app and Page token as Instagram,
    # so this schema aliases the shared FACEBOOK_* environment keys rather than
    # introducing a second credential block. A user configures the Instagram
    # section once and both adapters read it (see docs/AUTHENTICATION.md).
    "facebook": {
        "app_id": "FACEBOOK_APP_ID",
        "app_secret": "FACEBOOK_APP_SECRET",
        "page_id": "FACEBOOK_PAGE_ID",
        "access_token": "FACEBOOK_ACCESS_TOKEN",
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
    refresh_token: ""
twitter:
    client_id: ""
    client_secret: ""
    oauth2_access_token: ""
    oauth2_refresh_token: ""
    oauth2_expires_at: ""
hugging_face:
    access_token: ""
"""


def auth_file_path(data_dir: str | Path | None = None) -> Path:
    """Return the local auth file path for the selected data directory."""
    directory = Path(data_dir) if data_dir else default_data_dir()
    return directory / AUTH_FILE_NAME


def active_auth_file_path() -> Path:
    """Return the auth path selected by the current process."""
    return _active_auth_path or auth_file_path()


def _backup_existing_file(path: Path) -> Path:
    """Copy path into the newest backup slot, honouring app.yml keep_n."""
    return rotate_backup(path, resolve_backup_keep_n(path.parent / "app.yml"))


def create_auth_template(data_dir: str | Path | None = None) -> Path:
    """Create a blank auth template, backing up an existing auth file first."""
    path = auth_file_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup_path = _backup_existing_file(path)
        print(f"Existing auth file backed up to: {backup_path}")
    path.write_text(AUTH_TEMPLATE, encoding="utf-8")
    print(f"Created auth template at: {path}")
    return path


def load_auth_config(data_dir: str | Path | None = None) -> dict[str, Any]:
    """Load auth values, preferring persisted rotating tokens over stale env values."""
    global _active_auth_path
    path = auth_file_path(data_dir)
    _active_auth_path = path
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
                if field == "refresh_token":
                    os.environ[environment_key] = str(value)
                else:
                    os.environ.setdefault(environment_key, str(value))
    return loaded


def persist_auth_credential(platform: str, field: str, value: str,
                            data_dir: str | Path | None = None) -> Path:
    """Persist a newly issued platform credential and update this process."""
    return persist_auth_credentials(platform, {field: value}, data_dir)


def persist_auth_credentials(platform: str, values: dict[str, str],
                             data_dir: str | Path | None = None) -> Path:
    """Persist related credentials together and update this process."""
    if platform not in AUTH_ENVIRONMENT_KEYS:
        raise ValueError(f"Unsupported auth platform: {platform}")
    if not values:
        raise ValueError("At least one auth credential is required")
    unsupported = set(values) - set(AUTH_ENVIRONMENT_KEYS[platform])
    if unsupported:
        raise ValueError(f"Unsupported auth credential(s): {', '.join(sorted(unsupported))}")
    if any(not value for value in values.values()):
        raise ValueError("Auth credential values must not be empty")

    path = Path(data_dir) / AUTH_FILE_NAME if data_dir else (_active_auth_path or auth_file_path())
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ValueError("Auth file root must be an object")
    section = loaded.setdefault(platform, {})
    if not isinstance(section, dict):
        raise ValueError(f"Auth configuration for {platform} must be an object")
    section.update(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _backup_existing_file(path)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    os.replace(temporary_path, path)
    for field, value in values.items():
        os.environ[AUTH_ENVIRONMENT_KEYS[platform][field]] = value
    return path


def credential_status() -> dict[str, bool]:
    """Return whether each platform has at least one configured credential."""
    return {
        platform: any(os.getenv(environment_key)
                      for environment_key in fields.values())
        for platform, fields in AUTH_ENVIRONMENT_KEYS.items()
    }