# Authentication setup

Step-by-step generation of every credential section in `auth.yaml`
(tracks [A-Baji/ClipMorph#167](https://github.com/A-Baji/ClipMorph/issues/167)).

Running `clipmorph init` creates both `app.yml` and an adjacent `auth.yaml`
template with the sections below. Secrets in environment variables take
precedence over `auth.yaml` values; refresh tokens are the exception — a
freshly issued refresh token in `auth.yaml` always wins over a stale
environment value so granted tokens are never lost.

This guide documents exactly the fields in the credential schema. Nothing is
documented that the code does not read: `tests/test_auth.py` walks each
platform adapter and fails if a schema field is unread or a verified-unused
field reappears.

## Contents

- [Where credentials live](#where-credentials-live)
- [YouTube](#youtube-google_)
- [Meta (shared `FACEBOOK_*`)](#meta-meta--the-shared-facebook_-app-and-user-token)
  - [Instagram media hosting](#instagram-media-hosting)
- [TikTok](#tiktok-tiktok_)
- [Twitter / X](#twitter--x-twitter_)
- [Hugging Face](#hugging-face-hugging_face_)
- [Troubleshooting](#troubleshooting)
- [Verification checklist](#verification-checklist)
- [Verify credentials](#verify-credentials)
- [Official documentation](#official-documentation)

## Where credentials live

`auth.yaml` sits next to `app.yml` in the data directory selected by
`--data-dir` (or `--app-config` for a custom location). Each platform is a
mapping of field names to string values; a field ClipMorph needs but you leave
empty is simply not configured.

Check what is configured at any time — this prints one boolean per platform
(`true` when at least one of that platform's fields is set) and never a value:

```bash
clipmorph auth status
```

Add values non-interactively through environment variables, or interactively
with:

```bash
clipmorph auth set youtube
clipmorph auth set instagram
clipmorph auth set tiktok
clipmorph auth set twitter
clipmorph auth set facebook   # the four shared Meta fields, stored under meta:
clipmorph auth set hugging_face
```

Each prompts for that provider's fields (exact names below) and writes them to
`auth.yaml`, keeping a rotated backup of the previous file. Keep both files
private; never commit them. The per-field environment variable name is listed
with every section below.

## YouTube (`GOOGLE_*`)

Fields: `client_id`, `client_secret`, `refresh_token`
(env: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`).

These authorize `clipmorph/upload_pipeline/platforms/youtube.py` to insert
videos into a channel you own. The only scope requested anywhere is
`https://www.googleapis.com/auth/youtube.upload`
([YouTube API scopes](https://developers.google.com/identity/protocols/oauth2/scopes#youtube)).

### Step-by-step console navigation

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and pick
   an existing project from the project picker, or create one
   ([projects](https://cloud.google.com/resource-manager/docs/creating-managing-projects)).
2. Open **APIs & Services → Library**, search for **YouTube Data API v3**, and
   click **Enable**
   ([API library](https://console.cloud.google.com/apis/library)).
3. Open **APIs & Services → OAuth consent screen** and choose **External** (or
   **Internal** for a Workspace organization), then set the app name, support
   email, and developer contact
   ([authentication overview](https://cloud.google.com/docs/authentication)).
4. Under **Data Access**, add the scope
   `https://www.googleapis.com/auth/youtube.upload`. Requesting only this scope
   keeps the consent screen in the non-sensitive tier
   ([scopes](https://developers.google.com/identity/protocols/oauth2/scopes#youtube)).
5. Open **APIs & Services → Credentials → Create credentials → OAuth client
   ID**, choose application type **Desktop app**, and create it
   ([OAuth clients](https://developers.google.com/identity/protocols/oauth2/production)).
6. Open **APIs & Services → Credentials** and copy the **Client ID** and
   **Client secret** of that client. Download the client secret JSON if you
   also want an offline copy.

### Credential generation and verification

- `client_id` — the "Client ID" of the OAuth client. Desktop clients end in
  `.apps.googleusercontent.com`; a bare numeric value is usually the project
  number you copied from the wrong place. Verify on **Credentials → your
  client**.
- `client_secret` — the "Client secret" of the same client. It is shown only in
  the creation dialog, so download the JSON if you did not copy it. Confirm the
  row exists in the console and the value starts with `GOCSPX-`.
- `refresh_token` — never copied from the console; it comes out of the
  authorization-code exchange below.

### OAuth setup walk-through

The adapter uses Google's *installed app* (desktop) flow
([installed-app flow](https://developers.google.com/identity/protocols/oauth2/native-app)):
it starts a short-lived loopback listener on an ephemeral port, opens the
consent page, receives the code on `http://localhost:<port>`, and exchanges it
for tokens. A Desktop client needs no registered redirect URI, so step 5 above
is all the console setup required.

Two ways to obtain the refresh token:

1. **ClipMorph does it for you.** Store only `client_id` and `client_secret`,
   then trigger any YouTube upload. With no valid refresh token configured the
   adapter starts the flow, prints that a refresh token was generated, and
   persists it to `auth.yaml` and `GOOGLE_REFRESH_TOKEN` without ever printing
   it. When a stored refresh token later fails, the same flow re-runs
   automatically.
2. **Manually, via the [OAuth 2.0 Playground](https://developers.google.com/oauthplayground).**
   Set the client id and secret in the gear menu, add the
   `youtube.upload` scope in the step-2 scope selector, **Authorize exchange
   code**, then **Exchange authorization code for tokens** and read
   `refresh_token` from the step-4 response. Offline access — and therefore a
   refresh token at all — requires `access_type=offline`
   ([offline access](https://developers.google.com/identity/protocols/oauth2/web-server#offline)).

Confirm the result without exposing it: **APIs & Services → OAuth consent
screen → Data Access** shows the scopes that were granted, and
`clipmorph auth status` shows `youtube: true`.

### Gotchas

- A refresh token minted while the consent screen is in **Testing** publishing
  status expires after 7 days; publish the consent screen for a long-lived
  token
  ([testing and expiration](https://developers.google.com/identity/protocols/oauth2#expiration)).
- Omitting `access_type=offline` returns a token response with **no** refresh
  token
  ([token response](https://developers.google.com/identity/protocols/oauth2/web-server#call-offline)).
- A refresh token issued for another scope, or belonging to a client you have
  since deleted, fails with `invalid_grant`; re-run the exchange from step 1.
- The token is bound to the Google account that approved it, so switching
  accounts in the consent page changes which channel receives the upload.

## Meta (`meta:` — the shared `FACEBOOK_*` app and user token)

Fields, stored once:

```yaml
meta:
    app_id: ""        # env: FACEBOOK_APP_ID
    app_secret: ""    # env: FACEBOOK_APP_SECRET
    page_id: ""       # env: FACEBOOK_PAGE_ID
    access_token: ""  # env: FACEBOOK_ACCESS_TOKEN
    config_id: ""     # env: FACEBOOK_CONFIG_ID (optional, see below)
```

The Meta app and access token are stored ONCE under `meta:` because the same
Meta app and token authorize both adapters:

- `clipmorph/upload_pipeline/platforms/instagram.py` publishes reels to one
  Instagram professional account.
- `clipmorph/upload_pipeline/platforms/facebook.py` publishes Page Reels and
  Page videos.

`access_token` holds a long-lived **user** access token, not a Page token.
Meta requires a Page access token on Page endpoints, so each adapter derives
the Page token from the user token at publish time with
`GET /v23.0/{page_id}?fields=access_token` — the call Meta's
[Reels publishing guide](https://developers.facebook.com/docs/video-api/guides/reels-publishing/)
prerequisite names, already proven by the Instagram adapter's upload flow.
You never maintain a Page token: the derived one is used for the upload and
not stored. The user token itself is finite-lived (roughly 60 days), so a
revoked or expired token is fixed by rerunning the OAuth walk-through, not
by hand-deriving a Page token.

`clipmorph auth set facebook` prompts for the Meta fields (an empty prompt is
skipped, so non-FL4B apps simply leave `config_id` unset), and
`clipmorph auth set instagram` prompts for the same shared Meta fields; both
write the shared `meta:` section
(schema version 2). A root `facebook:` or `instagram:` section
is refused with an actionable error instead of migrated — move the values
into `meta:`.

Instagram publishes through Meta's resumable upload: the adapter creates a
container with `upload_type=resumable` and streams the render bytes straight
to Meta's upload host, so no Google Cloud Storage bucket, service account, or
public URL is required.

Permissions are attributed per adapter, not as one combined list. The
Instagram adapter publishes through the **Instagram API with Facebook Login**
integration, whose permission set is `instagram_basic`,
`instagram_content_publish`, and `pages_read_engagement`
([content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing)).
The Facebook adapter's Reels and Page-video endpoints require
`pages_manage_posts` on the derived Page token. The Instagram adapter's
built-in login-dialog scope list is the combined set `instagram_basic`,
`pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, and
`instagram_content_publish`, because one shared Meta app and login serve both
adapters; `pages_show_list` supports the Page-listing flow. Do not read that
list as Instagram's own requirement. Meta's permissions reference warns that
requesting permissions an app does not exercise is a common App Review
rejection cause, so request each permission for the adapter that needs it
([permissions](https://developers.facebook.com/docs/permissions/)).

If the app user's role on the Page connected to the Instagram professional
account was granted through Business Manager, Instagram publishing additionally
requires `ads_management` and `ads_read`; a Page role granted directly does not
([content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing)).

For an app using Facebook Login for Business, the permissions instead come
from a **Configuration**: in the Meta App Dashboard, create a Configuration
whose assets include the Page and whose permissions include the scopes
above, then store the shown Configuration ID in `config_id`. When
`config_id` is set, ClipMorph invokes the login dialog with `config_id` and
sends no `scope` parameter, because `config_id` has replaced `scope` and
Meta grants no permissions when the requested set is not the configured one
([Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/)).
The Configuration also selects the token type and the designated assets, so
FL4B access covers exactly what the login delegates; a non-FL4B app leaves
`config_id` empty and keeps the scope flow.

To pull engagement metrics (`clipmorph job update ID --metrics-pull`), the token also
needs `instagram_manage_insights`. This is a re-consent step: add the scope in
the Meta App Dashboard under **Instagram API with Instagram Login →
Permissions and features**, then rerun the OAuth walk-through to mint a new
user token — the Page token derives from it at publish time. Without it the
metrics adapter returns an `unavailable` snapshot with reason
`missing_scopes:instagram_manage_insights`.

### Step-by-step console navigation

1. Create an app in the [Meta App Dashboard](https://developers.facebook.com/apps/),
   linking it to a Business portfolio when prompted
   ([Graph API](https://developers.facebook.com/documentation/facebook-api)).
2. Open **App settings → Basic**. This page holds the numeric **App ID** and the
   **App secret** (behind a **Show** button).
3. Add the **Instagram** product and connect the Instagram professional account
   you intend to publish to. ClipMorph uses the **Instagram API with Facebook
   Login** integration, so the Page-backed setup applies; professional accounts
   are required for reel publishing
   ([Instagram API with Facebook Login setup](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/get-started)).
4. Open that product's **Permissions and features** and request the Instagram
   publishing set — `instagram_basic`, `instagram_content_publish`, and
   `pages_read_engagement` — plus `pages_manage_posts` for the Facebook
   adapter's Page endpoints
   ([permissions](https://developers.facebook.com/docs/permissions/)).
5. Find the Facebook Page that owns the professional account (under
   **Page settings → Connected accounts**, or Business Suite). That Page's
   numeric id is `page_id`.
6. Generate the long-lived user access token (next section) and store it in
   `access_token`. No remote staging is required: Meta's resumable upload
   takes the render bytes directly.

### Credential generation and verification

- `app_id` — the numeric **App ID** on **App settings → Basic**. It is not
  secret; verify it on that page.
- `app_secret` — **App secret → Show** on the same page. Meta does not display
  it again without an explicit reveal, so confirm the pasted value is non-empty
  rather than re-reading it later.
- `page_id` — the numeric Page id. Verify with
  `GET /v23.0/{page_id}?fields=id,name` in the
  [Graph API Explorer](https://developers.facebook.com/tools/explorer/): a
  returned `id`/`name` pair proves both the id and the token's access to it.
- `access_token` — see the OAuth walk-through. Verify it with
  `GET /v23.0/{page_id}?fields=access_token&access_token={token}` in the
  explorer: a returned `access_token` proves the token can derive the Page
  token, which is the same call the adapters make at publish time.
  (`GET /me/accounts` is not a reliable check — under Facebook Login for
  Business it can return `{"data": []}` even when the token is scoped to
  the Page.) The opt-in `clipmorph auth status --probe facebook` runs the
  same two checks for you.
- `config_id` — optional; only for apps using Facebook Login for Business.
  The Configuration ID shown in the Meta App Dashboard under **Facebook Login
  for Business → Configurations**. Verify it against that page.

### OAuth setup walk-through

ClipMorph's Meta flow is a paste-back code exchange rather than a loopback
listener, and it registers `https://localhost/` as the redirect URI:

1. Add `https://localhost/` to **Facebook Login → Settings → Valid OAuth
   Redirect URIs**
   ([manual flow](https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/)).
2. Trigger the flow from an upload with no stored token. The dialog depends
   on the app kind: a non-FL4B app requests the scopes above; a Facebook
   Login for Business app is invoked with the stored `config_id` and no
   `scope` parameter (the Configuration carries the token type, assets, and
   permissions, and both Configuration token types work with the same
   authorization-code exchange below). Redirecting to `https://localhost/`,
   paste the returned `code` back into the CLI when prompted.
3. Exchange the code with `app_id`, `app_secret`, and the **identical**
   `redirect_uri` for a short-lived user access token.
4. Exchange the short-lived user token for a long-lived one
   (`/oauth/access_token?grant_type=fb_exchange_token&client_id=…&client_secret=…&fb_exchange_token=…`).
   That **user** token — finite-lived, roughly 60 days — is the value stored
   in `access_token`. The Page token is never stored or hand-derived:
   ClipMorph derives it at publish time with
   `GET /v23.0/{page_id}?fields=access_token`
   ([access tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/)).
5. Re-verify with the explorer as described above.

### Gotchas

- A short-lived token pasted straight into `access_token` works once and then
  fails with a "Session has expired" Graph error
  ([token types](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/)).
- A Page token cannot request new permissions: a token minted before
  `instagram_content_publish` was approved authenticates but fails at publish
  time, and only a token minted after approval fixes it — rerun the
  walk-through; the fresh user token derives a Page token carrying the new
  scopes
  ([app review](https://developers.facebook.com/docs/instagram-platform/app-review/)).
- An app in development mode only works for roles that have app access; add
  yourself as an administrator or switch the app to Live
  ([app modes](https://developers.facebook.com/docs/development/release/)).
- The stored user token expires after roughly 60 days even though the
  exchange above called it "long-lived"; uploads fail with an expiry error
  at the token exchange until the walk-through is rerun.
- With Facebook Login for Business the dialog grants only the
  Configuration's permissions and designated assets: a Configuration that
  omits one of the scopes above, or the Page asset, yields a token that
  authenticates but cannot publish
  ([Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/)).
- **Page Publishing Authorization (PPA)**: an Instagram professional account
  connected to a Page that requires PPA cannot be published to until PPA is
  completed, and Meta exposes no API to detect PPA. There is no local preflight
  check for it, so complete PPA preemptively in the Page's settings for any
  account that might be affected
  ([Page Publishing Authorization](https://www.facebook.com/business/m/one-sheeters/page-publishing-authorization)),
  then rerun the upload.

## Instagram media hosting

Instagram reels are published through Meta's resumable upload protocol, so
ClipMorph streams the render bytes directly to Meta's upload host. No Google
Cloud Storage bucket, service account, or signed URL is involved, and there is
no remote staging to configure.

## TikTok (`TIKTOK_*`)

Fields: `client_key`, `client_secret`, `refresh_token`
(env: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`).

These authorize `clipmorph/upload_pipeline/platforms/tiktok.py` to publish
videos to the authorized TikTok account, requesting the scopes
`user.info.basic,video.upload,video.publish`
([content posting](https://developers.tiktok.com/doc/content-posting-api-get-started)).

To pull engagement metrics (`clipmorph job update ID --metrics-pull`), the app also
needs the `video.list` scope. Add it in the TikTok Developer Portal under
**Products → Video Upload → Scopes**, then re-authorize. Without it the
metrics adapter returns an `unavailable` snapshot with reason
`missing_scopes:video.list`.

There is deliberately no access-token or open-id field: the adapter derives a
short-lived access token from `refresh_token` on every upload and persists a
rotated refresh token whenever TikTok issues one
([token management](https://developers.tiktok.com/doc/oauth-user-access-token-management)).

### Step-by-step console navigation

1. Register an app in the [TikTok for Developers](https://developers.tiktok.com/)
   portal and open it
   ([create an app](https://developers.tiktok.com/doc/getting-started-create-an-app)).
2. Under **Products**, request **Video Upload** and **Video Publish**
   ([content posting](https://developers.tiktok.com/doc/content-posting-api-get-started)).
3. Under the app's **Credentials** section, copy **Client key** and **Client
   secret**.
4. Under **Login Kit** settings, add the redirect URI the authorization URL
   uses. The adapter sends `http://127.0.0.1:80/callback/`, and desktop
   redirect URIs must be a loopback host (`localhost` or `127.0.0.1`) with a
   port, where plain `http` is allowed
   ([Login Kit](https://developers.tiktok.com/doc/login-kit-web/)).
5. Stay in **Sandbox** while testing, then switch the app to **Production** and
   submit it for audit before posting to real accounts
   ([content posting](https://developers.tiktok.com/doc/content-posting-api-get-started)).

### Credential generation and verification

- `client_key` and `client_secret` — from the app's **Credentials** section.
  These are app credentials, not user credentials; verify them against the
  console page rather than by calling the API.
- `refresh_token` — produced by the authorization-code + PKCE exchange the
  adapter performs when no valid refresh token is stored. Run one upload and
  let the interactive authorization complete; the refresh token is written to
  `auth.yaml` and to `TIKTOK_REFRESH_TOKEN`.

Verify without exposing it: the portal's **Content posting analytics** shows an
active user, and `clipmorph auth status` shows `tiktok: true`.

### OAuth setup walk-through

1. Open the authorization URL with `client_key`, the scopes above, and
   `redirect_uri=http://127.0.0.1:80/callback/`
   ([authorization](https://developers.tiktok.com/doc/login-kit-web/)).
2. Approve on the consent page; TikTok returns the authorization code to the
   redirect URI, and the adapter reads it from its callback listener.
3. The adapter exchanges the code together with its PKCE verifier at the token
   endpoint, receiving `access_token` (24 hours) and `refresh_token`
   (365 days)
   ([token management](https://developers.tiktok.com/doc/oauth-user-access-token-management)).
4. The refresh token is persisted; a `refresh_token` returned by a later refresh
   **replaces** the stored one, which is why the adapter writes rotated values
   back to `auth.yaml`.

Once stored, uploads exchange the refresh token for a short-lived access token
automatically and fall back to the interactive flow when TikTok invalidates the
refresh token.

### Gotchas

- An unapproved app only works for accounts the developer authorized; production
  posting fails until the app is submitted and approved.
- A refresh token is bound to the app it was issued for; rotating the client
  secret or recreating the app invalidates it
  ([refresh tokens](https://developers.tiktok.com/doc/oauth-user-access-token-management)).
- A registered redirect domain that does not match the adapter's loopback URI
  is rejected before any token is issued
  ([Login Kit](https://developers.tiktok.com/doc/login-kit-web/)).

## Twitter / X (`TWITTER_*`)

Fields: `client_id`, `client_secret`, `oauth2_access_token`,
`oauth2_refresh_token`, `oauth2_expires_at`
(env: `TWITTER_CLIENT_ID`, `TWITTER_CLIENT_SECRET`,
`TWITTER_OAUTH2_ACCESS_TOKEN`, `TWITTER_OAUTH2_REFRESH_TOKEN`,
`TWITTER_OAUTH2_EXPIRES_AT`).

These are **OAuth 2.0** credentials only, consumed by
`clipmorph/twitter_auth.py` and
`clipmorph/upload_pipeline/platforms/twitter.py`. X API v1.1
key/secret/bearer fields are not part of the auth.yaml schema and are not
read anywhere.

Requested scopes: `tweet.read`, `tweet.write`, `users.read`, `media.write`,
`offline.access`
([authorization code with PKCE](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)).

### Step-by-step console navigation

1. Sign in to the [X Developer Portal](https://developer.x.com/), create a
   project, then an app inside it
   ([developer apps](https://docs.x.com/fundamentals/developer-apps)).
2. Open the app's **Settings → User authentication settings**, enable **OAuth
   2.0**, and choose the **Web App** type so a client secret is issued.
3. Under **Keys and tokens**, copy **Client ID** and **Client Secret** and click
   **Generate and save** if they are not shown
   ([authentication overview](https://docs.x.com/fundamentals/authentication/overview)).
4. Under **User authentication settings → Callback URIs**, add exactly
   `http://localhost:8765/callback`. Callback URLs must match exactly,
   including the port and any trailing slash
   ([developer apps](https://docs.x.com/fundamentals/developer-apps)).
5. Set the app's **User authentication settings** permission to **Read and
   write**, which is what enables the media-upload and post endpoints.
6. Run the interactive flow (next section), which writes the remaining three
   fields.

### Credential generation and verification

- `client_id` / `client_secret` — from the app's **Keys and tokens** page.
  Verify both against that page.
- `oauth2_access_token`, `oauth2_refresh_token`, `oauth2_expires_at` — written
  by the interactive flow. `oauth2_expires_at` is the UTC ISO-8601 expiry derived
  from the response's `expires_in`.

Verify without exposing it: the portal's **Keys and tokens** page shows the app
key, and `clipmorph auth status` shows `twitter: true`.

### OAuth setup walk-through

1. Store `client_id` and `client_secret` (or set `TWITTER_CLIENT_ID` and
   `TWITTER_CLIENT_SECRET`), then run:

   ```bash
   clipmorph auth twitter
   ```

2. ClipMorph opens the consent page at `https://x.com/i/oauth2/authorize` with
   `redirect_uri=http://localhost:8765/callback`, the scopes above, a random
   `state`, and a PKCE `S256` challenge
   ([authorization code with PKCE](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)).
3. The command listens on `http://localhost:8765/callback` for up to 60
   seconds, validates the returned `state` against the value it generated, then
   exchanges the code with the PKCE verifier against
   `https://api.x.com/2/oauth2/token`.
4. The response's `access_token`, `refresh_token`, and `expires_in` are
   persisted as `oauth2_access_token`, `oauth2_refresh_token`, and
   `oauth2_expires_at`.

Expired access tokens are refreshed automatically from `oauth2_refresh_token`;
if the refresh token is rejected, the CLI reruns the interactive
authorization.

### Gotchas

- A callback URI registered with a trailing slash, a different port, or an
  `https` scheme does not match, and the token exchange reports
  `redirect_uri_mismatch`
  ([developer apps](https://docs.x.com/fundamentals/developer-apps)).
- Without `offline.access` no refresh token is issued, so the whole flow has to
  be repeated whenever the roughly two-hour access token expires
  ([scopes](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)).
- App permissions must be read/write before the media and post endpoints
  respond; a read-only app fails at upload with a `403`.
- Tokens already issued do not gain new scopes or new app permissions — re-run
  `clipmorph auth twitter` after changing either.

## Hugging Face (`HUGGING_FACE_ACCESS_TOKEN`)

Field: `access_token` (env: `HUGGING_FACE_ACCESS_TOKEN`).

Required for optional speaker diarization models; transcription works without it
when diarization is not used.

### Step-by-step and verification

1. Open **Settings → Access Tokens → Create new token**
   ([access tokens](https://huggingface.co/docs/hub/security-tokens)).
2. Choose the **Read** role — ClipMorph only downloads gated diarization models
   with it, so a **Write** token is unnecessary and over-privileged.
3. Paste it under `hugging_face.access_token`.

Verify without exposing it: the token list on that page shows the token's name
and role, never the value, and `clipmorph auth status` shows
`hugging_face: true`. A `401` when loading the diarization model usually means
the gated model's terms were not accepted for your account
([gated repositories](https://huggingface.co/docs/hub/repositories-licenses)).

## Troubleshooting

Every diagnosis below is something you can inspect in a console, never a secret
you have to echo. Replace placeholders with your own values.

| Symptom | Diagnosis | Fix |
| --- | --- | --- |
| Redirect URI mismatch (Meta) | The registered URI differs from `https://localhost/`. | Register `https://localhost/` on the app and send the identical value in the exchange. |
| Redirect URI mismatch (X) | The registered callback differs from the adapter's URI in port, scheme, or trailing slash. | Register exactly `http://localhost:8765/callback`. |
| `invalid_grant` on a YouTube refresh | Token issued for another scope, or a deleted/rotated client. | Re-run the installed-app flow with `youtube.upload`. |
| "Session has expired" (Instagram) | A short-lived user token was stored. | Rerun the OAuth walk-through to store a fresh long-lived user token; the Page token derives from it at publish time. |
| `403 (#200)` on a Facebook Reels publish | A user token reached `video_reels` directly, or the stored token lacks `pages_manage_posts` scoped to the Page. | Confirm `GET /v23.0/{page_id}?fields=access_token` returns a token; if it does, publishing uses the derived Page token — rerun the OAuth walk-through if the scopes are missing. |
| Empty `{"data": []}` from `GET /me/accounts` (Meta) | Facebook Login for Business delegates asset access via the Configuration instead of Page roles, so `/me/accounts` can be empty even with valid grants. | Do not gate on `/me/accounts`; verify with `GET /v23.0/{page_id}?fields=access_token` or `clipmorph auth status --probe facebook`. |
| `403` on Instagram publish | The user token predates an approved permission. | Re-approve `instagram_content_publish`, then rerun the OAuth walk-through; the fresh user token derives a Page token with the new scopes. |
| Instagram publish blocked with no credential error | The Instagram professional account's connected Page requires Page Publishing Authorization (PPA), which cannot be detected through the API. | Complete PPA for the Page in Meta Business Suite, then retry ([Page Publishing Authorization](https://www.facebook.com/business/m/one-sheeters/page-publishing-authorization)). |
| TikTok refresh rejected | Token bound to a previous client key, or the app is not in production. | Recreate the app authorization and confirm audit approval. |
| X access token expired with no refresh | `offline.access` was not granted. | Re-run `clipmorph auth twitter` after adding the scope. |
| X `403` on media upload | App permissions are read-only. | Set **User authentication settings** to **Read and write**, then re-authorize. |
| `auth.yaml` fails to load | A value contains an unescaped `:`, `#`, or a tab. | Quote the value, or set the matching environment variable instead. |
| `429` or provider-side throttling | The provider is rate limiting the app. | Wait for the window to reset; a retry reuses the frozen snapshot. |
| A platform is reported unconfigured | `clipmorph auth status` shows `false` for it. | Run `clipmorph auth set PLATFORM`, or export the documented environment variable. |
| A job is stuck `running` after a crash | The process died mid-step. | Reconciliation marks it `interrupted_by_restart` on the next service start; retry the checkpoint. |

## Verification checklist

Run these after filling in the file. None of them print a credential value.

1. `clipmorph auth status` — one boolean per platform, computed from the local
   `auth.yaml` and the environment only. No network calls.
2. `clipmorph auth set PLATFORM` when a value is wrong; it rewrites the field
   through the same loader the upload path uses and keeps a rotated backup of
   the previous file.
3. A first-upload dry run: `clipmorph job create sources/video.mp4 --dry-run`
   validates and resolves configuration without publishing, confirming the
   source and layout side of the setup. The first real upload for a platform is
   the step that proves the credential works against the provider end to end —
   and it is the step that publishes something, so post to a test or private
   account first.
4. Read the provider's own console afterwards to confirm the request arrived
   (YouTube **Video Manager**, Meta **Content**, X **Posts**, TikTok **Content
   posting analytics**, Hugging Face **last-login/activity**). That verifies the
   credential without you ever re-reading the secret.

## Verify credentials

`clipmorph auth status` only reports whether a credential is *present*. To
prove it *works* against the provider, run the opt-in probe. It makes only
read-only calls, never prints a value, and exits `1` when any probe
fails. Two surfaces expose it:

- **CLI:** `clipmorph auth status --probe [PLATFORM ...]` — probe the named
  platforms, or omit the names to probe every known provider. The verdict is
  printed as JSON. This is a network call, unlike the local-only
  `clipmorph auth status`.
- **Dashboard:** the Settings view's credential-status section has a **Probe**
  button per platform, backed by `POST /api/v1/credentials/{platform}/probe`,
  which returns the same masked verdict.

Probing is never automatic — it never runs from preflight, startup, or the
bare `auth status` command. Hugging Face has no read-only probe, so it always
reports `unavailable` there.

## Official documentation

- Google Cloud: [projects](https://cloud.google.com/resource-manager/docs/creating-managing-projects),
  [API library](https://console.cloud.google.com/apis/library),
  [authentication overview](https://cloud.google.com/docs/authentication)
- Google OAuth: [OAuth 2.0](https://developers.google.com/identity/protocols/oauth2),
  [installed (desktop) apps](https://developers.google.com/identity/protocols/oauth2/native-app),
  [scopes](https://developers.google.com/identity/protocols/oauth2/scopes#youtube),
  [offline access](https://developers.google.com/identity/protocols/oauth2/web-server#offline),
  [testing and token expiration](https://developers.google.com/identity/protocols/oauth2#expiration),
  [OAuth 2.0 Playground](https://developers.google.com/oauthplayground)
- Meta: [App Dashboard](https://developers.facebook.com/apps/),
  [Graph API](https://developers.facebook.com/documentation/facebook-api),
  [Graph API Explorer](https://developers.facebook.com/tools/explorer/),
  [manual OAuth flow](https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/),
  [Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/),
  [access tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/),
  [permissions](https://developers.facebook.com/docs/permissions/),
  [Instagram platform overview](https://developers.facebook.com/docs/instagram-platform/overview),
  [Instagram content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing),
  [Instagram app review](https://developers.facebook.com/docs/instagram-platform/app-review/),
  [Page Reels publishing](https://developers.facebook.com/docs/video-api/guides/reels-publishing/),
  [app modes](https://developers.facebook.com/docs/development/release/)
- TikTok: [developer portal](https://developers.tiktok.com/),
  [create an app](https://developers.tiktok.com/doc/getting-started-create-an-app),
  [Login Kit and redirect URIs](https://developers.tiktok.com/doc/login-kit-web/),
  [user access token management](https://developers.tiktok.com/doc/oauth-user-access-token-management),
  [content posting](https://developers.tiktok.com/doc/content-posting-api-get-started)
- X: [developer portal](https://developer.x.com/),
  [developer apps and callback URLs](https://docs.x.com/fundamentals/developer-apps),
  [authentication overview](https://docs.x.com/fundamentals/authentication/overview),
  [OAuth 2.0 authorization code with PKCE](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)
- Hugging Face: [access tokens](https://huggingface.co/docs/hub/security-tokens),
  [gated repositories](https://huggingface.co/docs/hub/repositories-licenses)

## Precedence and storage

- `auth.yaml` lives next to `app.yml` in the selected data directory
  (`--data-dir` / `--app-config` when using a custom location).
- Environment variables override file values, except refresh tokens where the
  newest persisted grant wins.
- `clipmorph auth set` and the OAuth flows write only to `auth.yaml`; the CLI
  never prints full secrets, and manifest errors redact credential-looking
  values.
- `auth.yaml` backups are rotated to `auth.yaml.backup`, `auth.yaml.backup1`,
  and so on. The number kept is `app.yml:retention.backups.keep_n`, defaulting
  to 5; see [CONFIG_LAYERS.md](CONFIG_LAYERS.md).
