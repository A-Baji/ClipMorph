#!/usr/bin/env python3
"""Maintainer-only probe for the Hugging Face suggestion provider.

Run me with real tokens to validate the HF provider's JSON reliability
before enabling it. This script is never run by CI or the test suite;
it performs a live call to the Hugging Face Inference Providers router.

Usage:

    python quality/research/ai_suggest_probe.py
    python quality/research/ai_suggest_probe.py --model meta-llama/Llama-3.3-70B-Instruct

The probe calls the same ``suggest_metadata`` function the service uses,
so what passes here is exactly what a user's Generate action does.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:  # allow running from a source checkout
    sys.path.insert(0, str(REPO_ROOT))

from clipmorph.suggest import suggest_metadata  # noqa: E402

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe the Hugging Face suggestion provider end to end.")
    parser.add_argument(
        "--model", default=None,
        help="Model id override (defaults to the provider's built-in default).")
    parser.add_argument(
        "--provider", default="hugging_face",
        help="Provider to probe (default: hugging_face).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    print("ClipMorph AI suggestion provider probe")
    print(f"provider: {args.provider}")
    if args.model:
        print(f"model: {args.model}")

    content_baseline = {
        "source_title": "boss_fight_clip",
        "video_title": "Epic boss fight clutch",
        "duration_seconds": 45,
        "game_name": "TestGame",
        "tags": ["gaming", "bossfight", "clutch"],
    }
    limits = {"caption_limit": 2200}
    transcript_excerpt = (
        "And he's down to one health potion. Can he pull this off? "
        "The crowd is on their feet. Here comes the final phase."
    )

    print("\nCalling suggest_metadata...")
    try:
        result = suggest_metadata(
            "instagram", transcript_excerpt, content_baseline, limits,
            args.provider, args.model,
        )
    except Exception as error:
        print(f"{VERDICT_FAIL} the call raised: {error}")
        return 1

    print(f"\nprovider: {result.get('provider')}")
    print(f"model: {result.get('model')}")
    print(f"title: {result.get('title')}")
    print(f"description: {result.get('description')}")
    print(f"hashtags: {result.get('hashtags')}")
    if result.get("note"):
        print(f"note: {result.get('note')}")

    # Validate the output shape
    required = {"title", "description", "hashtags", "notes"}
    missing = required - set(result)
    if missing:
        print(f"{VERDICT_FAIL} missing keys: {', '.join(sorted(missing))}")
        return 1

    # Validate the provider actually ran (not a silent template fallback)
    if result.get("provider") != args.provider:
        print(f"{VERDICT_FAIL} expected provider {args.provider!r}, "
              f"got {result.get('provider')!r}")
        return 1

    # Validate the title respects the caption limit
    title = result.get("title", "")
    if len(title) > limits["caption_limit"]:
        print(f"{VERDICT_FAIL} title exceeds caption limit "
              f"({len(title)} > {limits['caption_limit']})")
        return 1

    print(f"\n{VERDICT_PASS} the {args.provider} provider returned valid metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
