import requests


def upload_to_0x0(video_path: str) -> tuple[str, str]:
    """
    Uploads to 0x0.st with a 'secret' field to force token issuance.
    Returns (public_url, management_token).
    """
    url = "https://0x0.st"
    headers = {"User-Agent": "curl/7.85.0"}  # mimic curl to avoid blocking

    with open(video_path, "rb") as f:
        files = {
            # The 'file' part must name the filefield and file content
            "file": (video_path, f),
            # The 'secret' part forces a new upload and token generation
            "secret": (None, "")
        }
        resp = requests.post(url, files=files, headers=headers)

    resp.raise_for_status()
    public_url = resp.text.strip()
    print(resp.headers)
    token = resp.headers.get("X-Token")
    if not token:
        raise RuntimeError("X-Token not returned")

    return public_url, token


def delete_from_0x0(file_url: str, token: str) -> None:
    """
    Deletes the file at file_url using the management token.
    """
    # Note: file_url ends in e.g. "/AbCd.mp4"
    resp = requests.post(file_url,
                         files={
                             "token": (None, token),
                             "delete": (None, "")
                         },
                         headers={"User-Agent": "curl/7.85.0"})
    resp.raise_for_status()
