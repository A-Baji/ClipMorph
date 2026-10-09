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

# Auth.yaml stores the whole Meta surface under ONE top-level `meta:` group,
# because the facebook and instagram adapters publish through the same Meta
# app and Page (`FACEBOOK_*` environment keys). Version 1 files stored these
# as root `facebook:`/`instagram:` sections; version 2 refuses them with an
# actionable error instead of migrating.
AUTH_SCHEMA_VERSION = 2

# The shared Meta app and access-token fields, mapped to the env keys the Meta
# adapters read (`FACEBOOK_CONFIG_ID` is the optional Facebook Login for
# Business Configuration ID; only the Instagram login URL sends it).
META_ENVIRONMENT_KEYS = {
    "app_id": "FACEBOOK_APP_ID",
    "app_secret": "FACEBOOK_APP_SECRET",
    "page_id": "FACEBOOK_PAGE_ID",
    "access_token": "FACEBOOK_ACCESS_TOKEN",
    "config_id": "FACEBOOK_CONFIG_ID",
}

AUTH_ENVIRONMENT_KEYS = {
    "youtube": {
        "client_id": "GOOGLE_CLIENT_ID",
        "client_secret": "GOOGLE_CLIENT_SECRET",
        "refresh_token": "GOOGLE_REFRESH_TOKEN",
    },
    # Instagram and Facebook both publish through the shared `meta:` block, so
    # their writable and readable credential surface aliases the Meta fields.
    # Instagram needs no hosting credentials: Meta's resumable upload takes
    # the render bytes directly.
    "instagram": dict(META_ENVIRONMENT_KEYS),
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
    # Facebook reads the shared `meta:` fields (the same Meta app and user
    # token Instagram publishes through), so this schema aliases them rather
    # than a second credential block.
    "facebook": dict(META_ENVIRONMENT_KEYS),
    "hugging_face": {
        "access_token": "HUGGING_FACE_ACCESS_TOKEN",
    },
}

AUTH_TEMPLATE = f"""# ClipMorph platform credentials
# Keep this file private. Values in the environment take precedence.
auth_schema_version: {AUTH_SCHEMA_VERSION}
youtube:
    client_id: ""
    client_secret: ""
    refresh_token: ""
meta:
    app_id: ""
    app_secret: ""
    page_id: ""
    access_token: ""
    config_id: ""
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


def credential_fields(platform: str) -> dict[str, str]:
    """Return a platform's known credential fields and their env keys.

    Meta platforms (facebook, instagram) share the Meta app and access-token
    fields, so their credential surface is the shared `meta:` set.
    """
    return AUTH_ENVIRONMENT_KEYS.get(platform, {})


def _set_environments(fields: dict[str, str], values: dict[str, Any],
                      stale_env_replacement: tuple[str, ...] = ()) -> None:
    """Export credential values into the adapter environment keys.

    A non-empty environment value keeps precedence. An EMPTY environment
    entry is not an override, so it never shadows a configured file value —
    and `stale_env_replacement` fields are always file-won (rotated tokens
    persist into the file, so a stale process env must not outlive them).
    """
    for field, environment_key in fields.items():
        value = values.get(field)
        if value is None or value == "":
            continue
        if field in stale_env_replacement or not os.environ.get(environment_key):
            os.environ[environment_key] = str(value)


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
    if loaded.get("auth_schema_version") != AUTH_SCHEMA_VERSION:
        raise ValueError(
            f"Auth file {path} must declare auth_schema_version: "
            f"{AUTH_SCHEMA_VERSION} (the file stores the shared Meta app and "
            "access token once, under `meta:`); create the current template "
            "with `clipmorph init` (the old file is backed up) and re-enter "
            "its credential values with `clipmorph auth set`.")

    meta = loaded.get("meta") or {}
    if not isinstance(meta, dict):
        raise ValueError("The auth `meta` block must be an object")
    _set_environments(META_ENVIRONMENT_KEYS, meta)
    for platform in ("youtube", "tiktok", "twitter", "hugging_face"):
        fields = loaded.get(platform)
        if platform not in loaded or fields is None:
            continue
        if not isinstance(fields, dict):
            raise ValueError(f"Auth configuration for {platform} must be an object")
        _set_environments(AUTH_ENVIRONMENT_KEYS[platform], fields,
                          stale_env_replacement=("refresh_token",))
    # A legacy root `facebook:`/`instagram:` section is schema 1 drift: the
    # actionable error names the new home instead of migrating.
    for legacy in ("facebook", "instagram"):
        if legacy in loaded:
            raise ValueError(
                f"Auth section `{legacy}:` is schema version 1; "
                f"{AUTH_SCHEMA_VERSION} stores the Meta surface under "
                f"`meta:`: {path}")
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
    # Meta platforms (facebook, instagram) share the Meta app and access-token
    # fields, so their known field list already aliases the shared set in
    # AUTH_ENVIRONMENT_KEYS.
    allowed = AUTH_ENVIRONMENT_KEYS[platform]
    unsupported = set(values) - set(allowed)
    if unsupported:
        raise ValueError(f"Unsupported auth credential(s): {', '.join(sorted(unsupported))}")
    if any(not value for value in values.values()):
        raise ValueError("Auth credential values must not be empty")

    # Credential storage follows the schema-2 file shape: shared Meta fields
    # at `meta:` and every other platform's own fields at its own section.
    shared_fields = set(values) & set(META_ENVIRONMENT_KEYS)
    own_fields = set(values) - shared_fields
    routed: dict[str, dict[str, str]] = {}
    if shared_fields:
        routed["meta"] = {field: values[field] for field in shared_fields}
    if own_fields:
        routed[platform] = {field: values[field]
                            for field in own_fields}

    path = Path(data_dir) / AUTH_FILE_NAME if data_dir else (_active_auth_path or auth_file_path())
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ValueError("Auth file root must be an object")
    for section, section_values in routed.items():
        block = loaded.setdefault(section, {})
        if not isinstance(block, dict):
            raise ValueError(f"Auth configuration for {section} must be an object")
        block.update(section_values)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _backup_existing_file(path)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    os.replace(temporary_path, path)
    for section, section_values in routed.items():
        fields = (META_ENVIRONMENT_KEYS if section == "meta"
                  else AUTH_ENVIRONMENT_KEYS[section])
        for field, value in section_values.items():
            os.environ[fields[field]] = value
    return path


def credential_status() -> dict[str, bool]:
    """Return whether each platform has at least one configured credential."""
    return {
        platform: any(os.getenv(environment_key)
                      for environment_key in fields.values())
        for platform, fields in AUTH_ENVIRONMENT_KEYS.items()
    }