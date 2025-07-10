import os
import secrets
import hashlib
import urllib.parse
import requests

# --- Configuration ---
CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
REDIRECT_URI = "http://127.0.0.1:80/callback/"  # Must match your TikTok app dashboard
SCOPE = "user.info.basic,video.upload,video.publish"


# --- PKCE Functions ---
def generate_code_verifier(length=64):
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
    return ''.join(secrets.choice(chars) for _ in range(length))


def generate_code_challenge(code_verifier):
    sha256 = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    # Base64 URL-safe encoding, strip trailing '='
    return sha256.hex()


# --- Step 1: Generate TikTok OAuth Authorization URL ---
def generate_auth_url(code_challenge):
    params = {
        "client_key": CLIENT_KEY,
        "response_type": "code",
        "scope": SCOPE,
        "redirect_uri": REDIRECT_URI,
        "state": "random_state_string",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(
        params)
    return url


# --- Step 2: Exchange Authorization Code for Access Token & Open ID ---
def exchange_code_for_token(auth_code, code_verifier):
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "code": auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(token_url, data=data, headers=headers)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    # Generate PKCE values
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    # Step 1: Direct user to TikTok authorization URL
    print("Step 1: Go to the following URL and authorize the app:")
    print(generate_auth_url(code_challenge))

    # Step 2: User pastes redirect URL after authorization
    redirected_url = input(
        "\nStep 2: After authorizing, paste the full redirect URL here:\n")
    parsed = urllib.parse.urlparse(redirected_url)
    query = urllib.parse.parse_qs(parsed.query)
    auth_code = query.get("code", [None])[0]
    if not auth_code:
        print("Authorization code not found in the URL.")
        exit(1)

    # Step 3: Exchange code for access token and open ID
    print(
        "\nStep 3: Exchanging code for access token, refresh_token, and open ID..."
    )
    token_response = exchange_code_for_token(auth_code, code_verifier)
    print("Access Token:", token_response.get("access_token"))
    print("Refresh Token:", token_response.get("refresh_token"))
    print("Open ID:", token_response.get("open_id"))
