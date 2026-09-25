"""OAuth 2.0 user authentication for X."""

from __future__ import annotations

import base64
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import requests
from requests.auth import HTTPBasicAuth

from clipmorph.auth import active_auth_file_path, load_auth_config, persist_auth_credentials


TWITTER_REDIRECT_URI = "http://localhost:8765/callback"
TWITTER_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TWITTER_TOKEN_URL = "https://api.x.com/2/oauth2/token"
TWITTER_SCOPES = "tweet.read tweet.write users.read media.write offline.access"
CALLBACK_TIMEOUT_SECONDS = 60


class _RefreshLock:
    def __init__(self, path: Path, timeout: float = 30):
        self.path = path
        self.timeout = timeout
        self.acquired = False

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                handle = self.path.open("x", encoding="utf-8")
                handle.close()
                self.acquired = True
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for the Twitter token lock")
                time.sleep(0.1)

    def __exit__(self, *_):
        if self.acquired:
            self.path.unlink(missing_ok=True)


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        self.server.callback = parse_qs(parsed.query)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ClipMorph authorization received. You can close this window.")

    def log_message(self, *_):
        return


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _token_values(response: requests.Response) -> dict[str, str]:
    if not response.ok:
        detail = response.text.strip()
        response.reason = (
            f"{response.reason}: {detail[:500]}" if detail else response.reason)
        response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise ValueError("X token response did not contain an access token")
    values = {
        "oauth2_access_token": access_token,
        "oauth2_expires_at": str(int(time.time()) + int(payload.get("expires_in", 7200))),
    }
    if payload.get("refresh_token"):
        values["oauth2_refresh_token"] = payload["refresh_token"]
    return values


def authorize_twitter(data_dir: str | Path | None = None) -> Path:
    config = load_auth_config(data_dir)
    twitter = config.get("twitter", {})
    client_id = twitter.get("client_id")
    client_secret = twitter.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError("Twitter OAuth2 client_id and client_secret are required")

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    authorization_url = TWITTER_AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": TWITTER_REDIRECT_URI,
        "scope": TWITTER_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    server = HTTPServer(("localhost", 8765), _CallbackHandler)
    server.timeout = CALLBACK_TIMEOUT_SECONDS
    print(f"Open this URL to authorize ClipMorph:\n{authorization_url}")
    webbrowser.open(authorization_url)
    server.handle_request()
    callback = getattr(server, "callback", None)
    server.server_close()
    if not callback:
        raise TimeoutError(
            "Timed out waiting for the X authorization callback. Confirm that "
            "OAuth2 is enabled and that the registered callback is exactly "
            f"{TWITTER_REDIRECT_URI}, then run the command again.")
    if callback.get("state", [None])[0] != state:
        raise ValueError("Twitter authorization state did not match")
    if callback.get("error"):
        raise ValueError(callback["error_description"][0] if callback.get("error_description") else callback["error"][0])
    code = callback.get("code", [None])[0]
    if not code:
        raise ValueError("Twitter authorization callback did not contain a code")

    response = requests.post(
        TWITTER_TOKEN_URL,
        auth=HTTPBasicAuth(client_id, client_secret),
        data={
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": TWITTER_REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=30)
    values = _token_values(response)
    return persist_auth_credentials("twitter", values, data_dir)


def refresh_twitter_access_token(data_dir: str | Path | None = None) -> dict[str, str]:
    config = load_auth_config(data_dir)
    twitter = config.get("twitter", {})
    client_id = twitter.get("client_id")
    client_secret = twitter.get("client_secret")
    if not all([client_id, client_secret, twitter.get("oauth2_refresh_token")]):
        raise ValueError("Twitter OAuth2 client credentials and refresh token are required")

    lock_path = active_auth_file_path().with_name("twitter-oauth2.refresh.lock")
    with _RefreshLock(lock_path):
        config = load_auth_config(data_dir)
        twitter = config.get("twitter", {})
        response = requests.post(
            TWITTER_TOKEN_URL,
            auth=HTTPBasicAuth(client_id, client_secret),
            data={
                "refresh_token": twitter["oauth2_refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=30)
        values = _token_values(response)
        if "oauth2_refresh_token" not in values:
            values["oauth2_refresh_token"] = twitter["oauth2_refresh_token"]
        persist_auth_credentials("twitter", values, data_dir)
        return values
