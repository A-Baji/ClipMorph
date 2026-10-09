# Platform Capability Matrix

This is the source-linked policy reference for the upload capability layer. The
runtime policy version is the publication date of the matrix.

Adding a platform or a rule? [PLATFORM_EXTENSION_GUIDE.md](PLATFORM_EXTENSION_GUIDE.md)
is the step-by-step checklist, and the drift suite in `tests/test_platforms.py`
fails when a platform is missing from any touchpoint this document names.

## Static artifact rules

| Platform | API/product source | Static rules enforced |
| --- | --- | --- |
| YouTube | [encoding settings](https://support.google.com/youtube/answer/1722171) | MP4/H.264 and supported audio guidance; title/description/keyword limits follow the upload metadata rules below |
| Instagram Reels | [Graph API v25.0 media](https://developers.facebook.com/docs/instagram-api/reference/ig-user/media) | 3-900 seconds, max 1920 horizontal pixels, max 300 MB, H.264/HEVC, 23-60 FPS, AAC audio |
| TikTok | [media transfer guide](https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide) | MP4/MOV/WebM, H.264/H.265/VP8/VP9, 23-60 FPS, 360-4096 pixel dimensions, max 4 GB, minimum 3 seconds |
| X | [API v2.168 upload](https://docs.x.com/x-api/media/upload-media) and [create posts](https://docs.x.com/x-api/posts/create-post) | one video per post, default 20 minutes/8 GB; account tier may allow 125 minutes/16 GB |
| Facebook | [Page videos](https://developers.facebook.com/docs/graph-api/reference/page/videos/) and [Page Reels](https://developers.facebook.com/docs/graph-api/reference/page/video_reels/) | 3-2700 seconds, max 1.75 GB, H.264/HEVC, MP4/MOV/MKV/AVI/WMV; Reels additionally require a 9:16 ratio and 3-90 seconds |

## Upload metadata rules

`clipmorph/policy.py` turns `upload.content` (`title`, `description`, `tags`)
into the fields an adapter sends; the adapters only transport the shaped values.
The table mirrors `CAPABILITY_MATRIX`, and `tests/test_policy_metadata.py` fails
if the two drift apart.

| Platform | content_mode | output_keys | caption_limit |
| --- | --- | --- | --- |
| youtube | separate | title, description, keywords | 5000 |
| instagram | caption | caption | 2200 |
| tiktok | combined | title | 4000 |
| twitter | combined | tweet_text | 280 |
| facebook | combined | description | 63206 |

`separate` keeps the three content fields apart: YouTube trims its title to 100
characters, its keyword string to 500 characters, and its description to
`caption_limit` (substituting a placeholder description when none is set).
`combined` and `caption` compose title, hashtags, and description into one
field, prioritized title > hashtags > description, truncated to `caption_limit`.
Per-platform upload defaults (category, privacy status, share-to-feed,
thumbnail offset, AI-content disclosure) are plain values owned by
`clipmorph/platforms.py`, not content rules.

## Dynamic account rules

- TikTok `creator_info/query` supplies the account's `max_video_post_duration_sec`
and privacy options. The runtime accepts these values through
`account_capabilities` and uses them in validation.
- X duration and size limits depend on the posting account tier and media
category. Unknown tier information produces a warning rather than disabling X.
- Instagram containers are asynchronous, expire after 24 hours, and are subject
to account/API publishing limits. Upload adapters retain platform status for
these asynchronous outcomes.
- Facebook shares Instagram's Meta app and user token; the Page token Meta
  requires on publish endpoints is derived at upload time, and
  `clipmorph auth status --probe` verifies that derivation (the Page `tasks`
  read alone cannot confirm publish capability, since a user token can read
  it while being unable to publish). Reels require a 9:16 ratio and 3-90
  seconds, which the platform enforces at publish time rather than the
  static rule blocking a Page video.
- YouTube Shorts eligibility and account-specific upload limits are not inferred
from generic encoding recommendations; unknown limits warn and do not block.

## Decision semantics

- Static artifact properties are checked before transport.
- Known incompatibilities block only the affected platform unless a compatible
derived artifact is supplied.
- Safe metadata transformations are recorded in the upload result.
- Unknown rules warn and continue; they never silently disable a platform.
- Policy version, warnings, transformations, blockers, and artifact references
belong in job/platform state.

## Existing-post detection

Platform-side existing-post detection is opt-in per platform, coded via the
adapter's `supports_existing_detection` capability flag and the
`find_existing_post(artifact_sha)` hook on `BaseUploadPipeline`. The hook runs
at submission time (outside the service lock) and returns the id of an
existing post carrying the artifact's `clip:{sha256}` marker, or `None` when
no match exists. A detection failure (for example a token lacking the read
scope) surfaces as an `unavailable` note, never a blocker.

| Platform | Detection | Mechanism |
| --- | --- | --- |
| YouTube | Supported (opt-in) | `channels.list(mine=true)` → uploads playlist → one `playlistItems.list` page; matches `clip:{artifact_sha}` marker in description |
| Instagram | Not supported | Submission-side dedup guard only |
| TikTok | Not supported | Submission-side dedup guard only |
| Twitter/X | Not supported | Submission-side dedup guard only |
| Facebook | Not supported | Submission-side dedup guard only |

YouTube's detection requires the `youtube.readonly` scope. The consent
request asks for both `youtube.upload` and `youtube.readonly`; existing
upload-only refresh tokens stay valid for uploads, but detection remains
unavailable until the user re-runs `clipmorph auth youtube` to grant the read
scope. The marker is embedded in the video description at publish time and is
truncated to stay within the platform's description limit.

## Native publish scheduling

`upload.schedule.mode: platform` hands the future publication to the platform
itself instead of holding a ClipMorph timer, so it may only name a platform
whose registry entry in `clipmorph/platforms.py::SUPPORTED_NATIVE_SCHEDULING`
is `True`. An entry is flipped only after the maintainer has run
`quality/research/scheduling_probe.py` against the live API with sandbox
credentials and observed a complete schedule -> inspect -> cancel cycle; the
registry dict and this row change in the same commit, with the probe date
recorded in the cell. Every entry ships `False`, so a submission naming a
platform before its probe is refused with
`upload.schedule.mode platform is not enabled for: <platforms>` and no attempt
is created. Instagram, TikTok, and X are permanently `Not available`: their
current APIs expose no scheduled-publication parameter (verified 2026-09-27
against the container/`media_publish` flow, direct-post `post_info`, and
`POST /2/tweets`), so the local timer stays their only mode. Facebook also
ships `Not available` pending its own probe, but its Reels finish phase
carries a `scheduled_publish_time` field, so it is a probe candidate rather
than a permanent no.

| Platform | Native publish scheduling | Adapter surface | Detection role |
| --- | --- | --- | --- |
| youtube | Not enabled (probe not run) | `scheduled_publish_at` -> `status.publishAt` with `privacyStatus=private`; `notifySubscribers` on a scheduled insert; `cancel_scheduled_post` -> `videos.delete` (50 quota units) | Required to re-attach a scheduled post stranded by a restart |
| instagram | Not available | none | n/a |
| tiktok | Not available | none | n/a |
| twitter | Not available | none | n/a |
| facebook | Not available | none | n/a |

YouTube accepts a scheduled publication only on a private video, so a
scheduled insert forces `privacyStatus=private` regardless of the configured
`platforms.youtube.privacy_status`; an unscheduled insert is unchanged.
A successful platform-scheduled attempt is recorded as `scheduled`, not
`published`: the platform still holds the publication, and only the platform
knows when it became visible, so the terminal flip belongs to the metrics pull
rather than to a local guess. Because the platform holds the post, cancelling
it is a remote action — `job update ID --cancel --attempt-id A` (web
`DELETE /api/v1/jobs/{id}/scheduled/{attempt_id}`) calls the adapter hook
instead of a local timer, and a rerender that supersedes an armed schedule
deletes the held post on a best-effort basis.

Last reviewed: 2026-10-02.
