#!/usr/bin/env python3
"""Maintainer-only probe for a platform's native publish scheduling.

``upload.schedule.mode: platform`` is gated by one registry entry per
platform in ``clipmorph/platforms.py``, and an entry is only ``True`` after
this probe has observed a complete schedule -> inspect -> cancel cycle against
the real platform API with sandbox credentials. Every entry ships ``False``,
so the gate is deliberately inconvenient: a live upload is the only honest
evidence that the API accepts the request ClipMorph builds, holds the
publication, and can be undone.

This script is never run by CI or the test suite; it performs a real upload
and a real deletion. Use a sandbox channel whose quota you can afford to
spend (a YouTube ``videos.delete`` costs 50 quota units).

Usage:

    python quality/research/scheduling_probe.py --video input/clip.mp4
    python quality/research/scheduling_probe.py --video input/clip.mp4 \\
        --platform youtube --in-minutes 120 --keep

The submission goes through the production mapping (a
``upload.platforms.<platform>`` override becomes the adapter keyword), so what
passes here is exactly what a user submission does.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:  # allow running from a source checkout
    sys.path.insert(0, str(REPO_ROOT))

from clipmorph.platforms import native_scheduling_support  # noqa: E402
from clipmorph.upload_attempts import content_options  # noqa: E402
from clipmorph.upload_pipeline import UploadPipeline  # noqa: E402

MARKER_PREFIX = "clip:"
VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe a platform's native publish scheduling end to end.")
    parser.add_argument(
        "--video", required=True,
        help="Local video file to schedule; it is uploaded and then deleted.")
    parser.add_argument(
        "--platform", default="youtube", choices=["youtube"],
        help="Platform to probe. Only platforms with a native scheduled-"
             "publication parameter can be probed.")
    parser.add_argument(
        "--in-minutes", type=int, default=60,
        help="How far in the future to schedule the publication.")
    parser.add_argument(
        "--notify-subscribers", action="store_true",
        help="Send notifySubscribers with the scheduled insert.")
    parser.add_argument(
        "--keep", action="store_true",
        help="Skip the cancel step so the scheduled post can be inspected by "
             "hand. A kept post stays live until you delete it.")
    return parser.parse_args(argv)


def _step(number: int, title: str) -> None:
    print(f"\n[{number}/3] {title}")


def _adapter(platform: str) -> Any:
    """Return the platform's upload adapter, failing loudly when it cannot load."""
    pipeline = UploadPipeline(**{platform: True})
    if pipeline.initialization_errors:
        messages = "; ".join(pipeline.initialization_errors.values())
        raise SystemExit(f"Could not initialize the {platform} adapter: {messages}")
    from clipmorph.platforms import PLATFORM_TITLE

    adapter = pipeline.enabled_platforms.get(PLATFORM_TITLE.get(platform, platform))
    if adapter is None:
        raise SystemExit(f"No {platform} adapter is registered")
    return adapter


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"video was not found: {video}")
    if args.in_minutes < 1:
        raise SystemExit("--in-minutes must be at least 1")
    platform = args.platform
    publish_at = (datetime.now(timezone.utc)
                  + timedelta(minutes=args.in_minutes))
    artifact_sha = hashlib.sha256(video.read_bytes()).hexdigest()

    print(f"ClipMorph native-scheduling probe: {platform}")
    print(f"video: {video}")
    print(f"scheduled publication: {publish_at.isoformat()}")
    print(f"registry currently says native scheduling: "
          f"{native_scheduling_support(platform)}")

    adapter = _adapter(platform)
    if getattr(adapter, "supports_existing_detection", False) is not True:
        raise SystemExit(
            f"{platform} has no existing-post detection, so the probe cannot "
            "confirm or clean up what it submitted")

    _step(1, "Schedule the publication through the production mapping")
    overrides: dict[str, Any] = {
        "scheduled_publish_at": publish_at.isoformat(),
    }
    if args.notify_subscribers:
        overrides["notify_subscribers"] = True
    upload_config = {
        "content": {"title": f"ClipMorph scheduling probe {publish_at:%Y-%m-%d}",
                    "description": "sandbox probe", "tags": ["clipmorph-probe"]},
        "platforms": {platform: overrides},
    }
    pipeline = UploadPipeline(**{platform: True})
    try:
        results = pipeline.run(
            str(video), upload_config["content"]["title"],
            **content_options(upload_config, [platform]))
    except Exception as error:
        print(f"{VERDICT_FAIL} the insert raised: {error}")
        return 1
    result = results.get(platform) or next(iter(results.values()), {})
    if not result.get("success"):
        print(f"{VERDICT_FAIL} the insert failed: {result.get('error')}")
        return 1
    post_id = result.get("result")
    print(f"platform accepted the upload as {post_id}")
    if not isinstance(post_id, str) or not post_id:
        print(f"{VERDICT_FAIL} the insert returned no post id")
        return 1

    _step(2, "Confirm the platform is holding the future publication")
    try:
        found = adapter.find_existing_post(artifact_sha)
    except Exception as error:
        print(f"{VERDICT_FAIL} the post lookup failed: {error}")
        return 1
    if found != post_id:
        print(f"{VERDICT_FAIL} the platform does not list the scheduled post "
              f"(looked for {post_id}, found {found})")
        print("The post may already be public. Delete it by hand before "
              "flipping anything.")
        return 1
    print(f"the platform holds {found} and has not published it")

    _step(3, "Cancel the publication")
    if args.keep:
        print(f"skipped (--keep): {post_id} stays scheduled. Delete it by hand "
              "or re-run the probe without --keep.")
        return 0
    try:
        adapter.cancel_scheduled_post(post_id)
    except Exception as error:
        print(f"{VERDICT_FAIL} the cancel raised: {error}")
        print(f"the post {post_id} may still be scheduled; delete it by hand")
        return 1
    try:
        remaining = adapter.find_existing_post(artifact_sha)
    except Exception as error:
        print(f"WARN the post-delete lookup failed: {error}")
        return 0
    if remaining is not None:
        print(f"{VERDICT_FAIL} the post {remaining} survived the cancel")
        return 1
    print(f"the platform no longer holds {post_id}")

    date = datetime.now(timezone.utc).date().isoformat()
    print(f"\n{VERDICT_PASS} {platform} completed schedule -> inspect -> cancel "
          f"on {date}")
    print("A maintainer may now, in one commit:")
    print(f"  1. set SUPPORTED_NATIVE_SCHEDULING[{platform!r}] = True in "
          "clipmorph/platforms.py")
    print(f"  2. set the {platform} 'Native publish scheduling' cell in "
          f"docs/PLATFORM_CAPABILITIES.md to 'Enabled (probe {date})'")
    print("  3. re-run the test suite, then merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
