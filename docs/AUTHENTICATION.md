# Authentication setup

Step-by-step generation of every credential section in `auth.yaml`
(tracks [A-Baji/ClipMorph#167](https://github.com/A-Baji/ClipMorph/issues/167)).

Running `clipmorph init` creates both `app.yml` and an adjacent `auth.yaml`
template with the sections below. Secrets in environment variables take
precedence over `auth.yaml` values; refresh tokens are the exception — a
freshly issued refresh token in `auth.yaml` always wins over a stale
environment value so granted tokens are never lost.

Status overview at any time: `clipmorph auth status` prints configured
booleans per field without revealing values. Add values non-interactively
through environment variables, or interactively with:

```bash
clipmorph auth set youtube
clipmorph auth set instagram
clipmorph auth set tiktok
clipmorph auth set twitter
clipmorph auth set hugging_face
```

Each prompts for that provider's fields (exact names below) and writes them to
`auth.yaml`. Keep both files private; never commit them.

## YouTube (`GOOGLE_*`)

Fields: `client_id`, `client_secret`, `refresh_token`
(env: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`).

1. In [Google Cloud Console](https://console.cloud.google.com/) create a
   project (or reuse one) and enable the **YouTube Data API v3**.
2. Configure the OAuth consent screen for **External** (or Internal for a
   Workspace org). Add the scope
   `https://www.googleapis.com/auth/youtube.upload` to the consent
   configuration.
3. Create OAuth client credentials of type **Desktop app**. Desktop clients
   use loopback redirects, matching how ClipMorph treats the stored refresh
   token as an installed-app credential.
4. Copy the client ID and secret into the `youtube` section.
5. Generate a refresh token with the `youtube.upload` scope (for example via
   [OAuth 2.0 Playground](https://developers.google.com/oauthplayground):
   add the scope in settings, authorize, exchange the code, copy the refresh
   token). Store it under `refresh_token`.

Uploads refresh the access token automatically from this refresh token; when
the refresh token itself is rejected, the CLI falls back to an interactive
browser authorization and persists the new token into `auth.yaml`.

## Instagram (`FACEBOOK_*`, `GCS_*`, `GCP_*`)

Fields: `app_id`, `app_secret`, `page_id`, `access_token`,
`gcs_bucket_name`, `gcp_private_key_id`, `gcp_private_key`,
`gcp_client_email`, `gcp_client_id`, `gcp_project_id`.

1. Create a **Facebook App** (business type) in the
   [Meta App Dashboard](https://developers.facebook.com/) and note the App ID
   (`app_id`) and App Secret (`app_secret`).
2. Link or create a Facebook Page; its numeric ID goes to `page_id`. Reels
   publish to that page.
3. Generate a long-lived page access token with
   `instagram_content_publish` (and `pages_manage_metadata`) permissions —
   for example via the Graph API Explorer → exchange for a long-lived token →
   then derive the page token. Put it in `access_token`.
4. Instagram upload relies on temporary media hosting in Google Cloud
   Storage. Create or select a bucket and a service account with
   `roles/storage.objectAdmin` (or object create/delete) on that bucket,
   export a JSON key, and fill the `gcs_bucket_name` plus the five
   `GCP_*` values from that key (`private_key_id`, `private_key`,
   `client_email`, `client_id`, `project_id`).

ClipMorph uploads each video under a job-scoped unique object key, grants a
signed URL to Meta, and deletes the object it created after the upload.

## TikTok (`TIKTOK_*`)

Fields: `client_key`, `client_secret`, `access_token`, `refresh_token`,
`open_id` (env: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`,
`TIKTOK_ACCESS_TOKEN`, `TIKTOK_REFRESH_TOKEN`, `TIKTOK_OPEN_ID`).

1. Register an app on the
   [TikTok for Developers](https://developers.tiktok.com/) portal, request the
   **Video Upload** and **Video Publish** products, and note the client key
   and secret.
2. Add an OAuth redirect domain that you control; the PKCE authorization flow
   opens the consent page in your browser.
3. Store `client_key` and `client_secret`, then run a refresh-token
   authorization (the pipeline opens the consent page, handles the code
   exchange, and returns the refresh token) and fill in
   `refresh_token` (plus `access_token` and `open_id` from the same
   response). Scope requested:
   `user.info.basic,video.upload,video.publish`.
4. With a persisted `refresh_token`, uploads refresh the access token
   automatically and fall back to the interactive flow when it expires.

## Twitter/X (`TWITTER_*`)

Fields: `client_id`, `client_secret`, `oauth2_access_token`,
`oauth2_refresh_token`, `oauth2_expires_at`.

1. Create a project and app in the
   [X Developer Portal](https://developer.x.com/); enable **OAuth 2.0** with
   the **Web App** type and add the redirect callback
   `http://localhost:8765/callback`.
2. Store the client ID and secret, then run:

   ```bash
   clipmorph auth twitter
   ```

   ClipMorph opens the X consent page, validates the returned state,
   exchanges the code with PKCE (S256), and stores the user access token,
   refresh token, and expiry in `auth.yaml`. Requested scopes:
   `tweet.read`, `tweet.write`, `users.read`, `media.write`,
   `offline.access`.
3. Expired access tokens are refreshed automatically from
   `oauth2_refresh_token`; if the refresh token is rejected the CLI reruns
   the interactive authorization.

## Hugging Face (`HUGGING_FACE_ACCESS_TOKEN`)

Field: `access_token` (env: `HUGGING_FACE_ACCESS_TOKEN`).

Required for optional speaker diarization models. Create a read token in your
[Hugging Face settings](https://huggingface.co/settings/tokens) and paste it
under `hugging_face.access_token`. Transcription works without it when
diarization is not used.

## Precedence and storage

- `auth.yaml` lives next to `app.yml` in the selected data directory
  (`--data-dir` / `--app-config` when using a custom location).
- Environment variables override file values, except refresh tokens where the
  newest persisted grant wins.
- `clipmorph auth set` and the OAuth flows write only to `auth.yaml`; the CLI
  never prints full secrets, and manifest errors redact credential-looking
  values.
