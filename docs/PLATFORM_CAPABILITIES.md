# Platform Capability Matrix

This is the source-linked policy reference for the upload capability layer. The
runtime policy version is the publication date of the matrix.

## Static artifact rules

| Platform | API/product source | Static rules enforced |
| --- | --- | --- |
| YouTube | [encoding settings](https://support.google.com/youtube/answer/1722171) | MP4/H.264 and supported audio guidance; title/metadata limits remain adapter policy where applicable |
| Instagram Reels | [Graph API v25.0 media](https://developers.facebook.com/docs/instagram-api/reference/ig-user/media) | 3-900 seconds, max 1920 horizontal pixels, max 300 MB, H.264/HEVC, 23-60 FPS, AAC audio |
| TikTok | [media transfer guide](https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide) | MP4/MOV/WebM, H.264/H.265/VP8/VP9, 23-60 FPS, 360-4096 pixel dimensions, max 4 GB, minimum 3 seconds |
| X | [API v2.168 upload](https://docs.x.com/x-api/media/upload-media) and [create posts](https://docs.x.com/x-api/posts/create-post) | one video per post, default 20 minutes/8 GB; account tier may allow 125 minutes/16 GB |

## Dynamic account rules

- TikTok `creator_info/query` supplies the account's `max_video_post_duration_sec`
and privacy options. The runtime accepts these values through
`account_capabilities` and uses them in validation.
- X duration and size limits depend on the posting account tier and media
category. Unknown tier information produces a warning rather than disabling X.
- Instagram containers are asynchronous, expire after 24 hours, and are subject
to account/API publishing limits. Upload adapters retain platform status for
these asynchronous outcomes.
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

Last reviewed: 2026-09-23.
