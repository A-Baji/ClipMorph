"""Read-only, opt-in credential health probes for each platform.

Closes the gap between "credential present" (``clipmorph auth status``) and
"credential works": every probe makes only cheap, authenticated, read-only
calls so a dead refresh token or page access token surfaces before a real
upload starts. Probing is never automatic -- it runs only when a surface
explicitly asks for it.

Secrets are never printed, logged, or returned. Failure details go through
``clipmorph.job.safe_error_message`` so credential-looking values are
redacted with the same discipline job manifests use. Platform adapters are
imported lazily inside each probe so the heavy SDKs stay out of the
``--help`` path.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from clipmorph.auth import credential_status
from clipmorph.job import safe_error_message
from clipmorph.twitter_auth import refresh_twitter_access_token

# One attempt, no retry: this is a health check, not an upload. Instagram's
# Graph GET is held to a tighter 10s bound per its own probe spec.
_PROBE_TIMEOUT = 15


def probe_credentials(platforms: list[str]) -> dict[str, dict[str, Any]]:
    """Probe each named platform's credentials with one read-only call.

    Returns ``{platform: {"configured": bool, "probe": "ok|failed|unavailable",
    "detail": str}}``. ``unavailable`` rows (not configured, incomplete
    credentials, no probe implemented, or interactive authorization required)
    neither fail nor block; only ``failed`` rows fail the run.
    """
    status = credential_status()
    result: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        configured = bool(status.get(platform, False))
        if platform == "hugging_face":
            result[platform] = _record(configured, "unavailable",
                                        "no read-only probe implemented")
            continue
        if not configured:
            result[platform] = _record(False, "unavailable", "not configured")
            continue
        probe = _PROBES.get(platform)
        if probe is None:
            result[platform] = _record(configured, "unavailable",
                                        "no read-only probe implemented")
            continue
        verdict, detail = probe()
        result[platform] = _record(configured, verdict, detail)
    return result


def _record(configured: bool, probe: str, detail: str) -> dict[str, Any]:
    return {"configured": configured, "probe": probe, "detail": detail}


def _probe_youtube() -> tuple[str, str]:
    """Prove the Google refresh token is live by refreshing it once.

    No Data API call is made: a successful refresh is the zero-quota-cost
    health check, and ``mine=True`` reads need a readonly-family scope the
    upload token does not carry.
    """
    from clipmorph.upload_pipeline.platforms.youtube import YouTubeUploadPipeline

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        return "unavailable", "incomplete credentials"
    try:
        credentials = Credentials(
            None,
            refresh_token=refresh_token,
            token_uri=YouTubeUploadPipeline.GOOGLE_TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[YouTubeUploadPipeline.YOUTUBE_UPLOAD_SCOPE],
        )
        credentials.refresh(Request())
    except Exception as error:
        return "failed", safe_error_message(str(error))
    return "ok", "refresh token accepted"


def _probe_instagram() -> tuple[str, str]:
    """Check the Facebook token's Graph access and the GCS bucket.

    The two sub-checks merge into one detail string so a partial failure
    still reports the half that worked. The graph read uses the stored
    token directly, mirroring the Instagram adapter's publish-time
    identity read; the Page-token exchange is Facebook's probe's job.
    """
    from clipmorph.upload_pipeline.platforms.instagram import InstagramUploadPipeline

    try:
        pipeline = InstagramUploadPipeline()
    except Exception:
        return "unavailable", "incomplete credentials"
    graph_ok, graph_detail = _instagram_graph_check(pipeline)
    gcs_ok, gcs_detail = _instagram_gcs_check(pipeline)
    detail = f"{graph_detail}; {gcs_detail}"
    return ("ok" if graph_ok and gcs_ok else "failed"), detail


def _instagram_graph_check(pipeline: Any) -> tuple[bool, str]:
    url = (f"{pipeline.FACEBOOK_GRAPH_BASE_URL}/{pipeline.api_version}/"
           f"{pipeline.page_id}?fields=id&access_token={pipeline.access_token}")
    try:
        response = requests.get(url, timeout=10)
        payload = response.json()
    except Exception as error:
        return False, f"graph api failed: {safe_error_message(str(error))}"
    if response.status_code != 200:
        return False, ("graph api failed: "
                       f"{safe_error_message(f'status {response.status_code} {response.text}')}")
    if payload.get("id") != pipeline.page_id:
        return False, "graph api failed: page id mismatch"
    return True, "graph api ok"


def _instagram_gcs_check(pipeline: Any) -> tuple[bool, str]:
    try:
        pipeline._authenticate_google()
        from google.cloud import storage
        storage_client = storage.Client(credentials=pipeline.google_creds)
        exists = storage_client.bucket(pipeline.gcs_bucket_name).exists()
    except Exception as error:
        return False, f"gcs bucket failed: {safe_error_message(str(error))}"
    if not exists:
        return False, "gcs bucket not found"
    return True, "gcs bucket ok"


def _probe_facebook() -> tuple[str, str]:
    """Prove the stored Meta user token can read the Page and be exchanged.

    Facebook reuses Instagram's Meta app and user token, so this runs the
    identity/capability read plus the `fields=access_token` Page-token
    exchange the adapter performs at publish time: the Page ``tasks`` list
    suggests publish capability (reels need ``CREATE_CONTENT``) and a
    derived Page token proves it. No video is uploaded and no value is
    printed.
    """
    from clipmorph.upload_pipeline.platforms.facebook import FacebookUploadPipeline

    try:
        pipeline = FacebookUploadPipeline()
    except Exception:
        return "unavailable", "incomplete credentials"
    return _facebook_graph_check(pipeline)


def _facebook_graph_check(pipeline: Any) -> tuple[str, str]:
    """Read the Page with one GET per attempt, then attempt the exchange.

    The first read asks `id,tasks` (the token-holder's Page role list
    suggests publish capability); Graph does not answer `tasks` for every
    token kind (a Page access token cannot read its own role list), so a
    `nonexisting field (tasks)` error degrades to the `id,name` identity
    read instead of failing a working credential.

    A user token can read `tasks` while still being unable to publish, so
    the same `fields=access_token` Page-token exchange the Facebook
    adapter performs at publish time runs too: only a derived Page token
    can publish, so a derivation failure fails the probe even when
    `tasks` looks right. A Page token stored outright answers the
    exchange with itself, so both token kinds are validated uniformly.
    No video is uploaded and no value is printed.
    """
    response = _facebook_graph_read("fields=id,tasks", pipeline)
    if response["status"] == 400 and \
            "nonexisting field (tasks)" in response["text"]:
        response = _facebook_graph_read("fields=id,name", pipeline)
    if response["status"] == 0:
        return "failed", f"graph api failed: {response['text']}"
    if response["status"] != 200:
        status = response["status"]
        text = safe_error_message(response["text"])
        return "failed", f"graph api failed: status {status} {text}"
    payload = response["payload"]
    if payload.get("id") != pipeline.page_id:
        return "failed", "graph api failed: page id mismatch"
    tasks = payload.get("tasks") or []
    if isinstance(tasks, list) and "CREATE_CONTENT" in tasks:
        capability = "reels capability granted"
    else:
        capability = "reels capability not confirmed"
    derivable, derivation = _facebook_page_token_exchange(pipeline)
    if not derivable:
        return "failed", f"graph api ok; {derivation}"
    return "ok", f"graph api ok; {capability}; {derivation}"


def _facebook_page_token_exchange(pipeline: Any) -> tuple[bool, str]:
    """Attempt the `fields=access_token` Page-token derivation once.

    Mirrors the publish-time exchange in the Facebook adapter: a user
    token scoped to the Page returns the Page token, and a stored Page
    token returns itself. Any other outcome — a 4xx, an empty body —
    reads as "cannot derive a Page token" and never reports ok. The
    returned token value is never included in the detail; only this
    boolean plus redactable error text come back.
    """
    response = _facebook_graph_read("fields=access_token", pipeline)
    if response["status"] == 0:
        return False, (f"cannot derive a Page token: "
                       f"{response['text']}")
    if response["status"] != 200:
        text = safe_error_message(response["text"])
        return False, ("cannot derive a Page token: "
                       f"status {response['status']} {text}")
    if response["payload"].get("access_token"):
        return True, "can derive a Page token"
    return False, (f"cannot derive a Page token: "
                   f"no access token in the response "
                   f"({safe_error_message(response['text'])})")


def _facebook_graph_read(path_fields: str, pipeline: Any) -> dict[str, Any]:
    """One read-only page query, structured; request failures read status 0."""
    url = (f"{pipeline.FACEBOOK_GRAPH_BASE_URL}/{pipeline.api_version}/"
           f"{pipeline.page_id}?{path_fields}&access_token={pipeline.access_token}")
    try:
        response = requests.get(url, timeout=10)
        return {"status": response.status_code, "text": response.text,
                "payload": response.json()}
    except Exception as error:
        return {"status": 0, "text": safe_error_message(str(error)),
                "payload": {}}


def _probe_tiktok() -> tuple[str, str]:
    """Prove the TikTok refresh token yields a working access token.

    The pipeline is instantiated the same way ``run`` is; the refresh falls
    back to the interactive browser flow only when there is no refresh token,
    so that case is reported as ``unavailable`` instead of opening a browser.
    """
    from clipmorph.upload_pipeline.platforms.tiktok import TikTokUploadPipeline

    try:
        pipeline = TikTokUploadPipeline()
    except Exception:
        return "unavailable", "incomplete credentials"
    if not pipeline.refresh_token:
        return ("unavailable",
                "interactive authorization required; run clipmorph auth set tiktok")
    try:
        access_token = pipeline._refresh_access_token()
        response = requests.get(
            "https://open.tiktokapis.com/v2/user/info/",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_PROBE_TIMEOUT,
        )
        if response.status_code == 401:
            access_token = pipeline._refresh_access_token()
            response = requests.get(
                "https://open.tiktokapis.com/v2/user/info/",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=_PROBE_TIMEOUT,
            )
    except Exception as error:
        return "failed", safe_error_message(str(error))
    if response.status_code == 200:
        return "ok", "user info returned"
    return ("failed",
            safe_error_message(f"status {response.status_code} {response.text}"))


def _probe_twitter() -> tuple[str, str]:
    """Prove the X access token can read the authenticated user.

    ``refresh_twitter_access_token`` is the reusable refresh logic;
    ``authorize_twitter`` (the interactive consent flow) is never invoked, so
    the probe never opens a browser window.
    """
    access_token = os.getenv("TWITTER_OAUTH2_ACCESS_TOKEN")
    if not access_token:
        return "unavailable", "incomplete credentials"
    try:
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {access_token}"})
        response = session.get("https://api.x.com/2/users/me",
                               timeout=_PROBE_TIMEOUT)
        if response.status_code == 401:
            try:
                values = refresh_twitter_access_token()
            except Exception:
                return "failed", "token expired; rerun clipmorph auth twitter"
            session.headers.update(
                {"Authorization": f"Bearer {values['oauth2_access_token']}"})
            response = session.get("https://api.x.com/2/users/me",
                                   timeout=_PROBE_TIMEOUT)
    except Exception as error:
        return "failed", safe_error_message(str(error))
    if response.status_code == 200:
        return "ok", "user info returned"
    return ("failed",
            safe_error_message(f"status {response.status_code} {response.text}"))


_PROBES: dict[str, Callable[[], tuple[str, str]]] = {
    "youtube": _probe_youtube,
    "instagram": _probe_instagram,
    "tiktok": _probe_tiktok,
    "twitter": _probe_twitter,
    "facebook": _probe_facebook,
}
