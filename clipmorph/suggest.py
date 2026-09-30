"""AI-assisted platform metadata and caption suggestions.

This module owns the provider abstraction for generating platform-aware
title, description, and hashtag drafts from a clip's transcript. The
template provider is deterministic and always works; the Hugging Face
provider is opt-in via configuration.

Suggestions are draft-level only: they live in the upload draft
configuration and never auto-publish. Accepting a suggestion copies it
into ``upload.content`` through the existing review gate.
"""

from __future__ import annotations

import json
import os
from typing import Any

from clipmorph.job import safe_error_message
from clipmorph.policy import CAPABILITY_MATRIX, SEPARATE_TITLE_LIMIT
from clipmorph.policy import build_platform_metadata

SUGGESTION_SCHEMA_VERSION = 1

# Hugging Face Inference Providers router (OpenAI-compatible chat completions).
HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
HF_DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
HF_TIMEOUT_SECONDS = 30
HF_MAX_TRANSCRIPT_CHARS = 2000
# Top-K distinct hashtags the deterministic helper selects (and the prompt
# advertises). The platform registry declares no hashtag-count rule, so this is
# the one bounded constant both providers share.
DEFAULT_HASHTAG_LIMIT = 5

# Provider names.
PROVIDER_TEMPLATE = "template"
PROVIDER_HUGGING_FACE = "hugging_face"

# Output JSON shape per #206's spec.
SUGGESTION_OUTPUT_KEYS = ("title", "description", "hashtags", "notes")

# Prompt template for the HF provider. The caption limit and hashtag count are
# interpolated from the policy limits argument, never hardcoded.
PROMPT_TEMPLATE = """You are a social media content assistant. Generate platform-aware metadata for a {platform} post.

Platform limits:
- Caption limit: {caption_limit} characters

Transcript excerpt:
{transcript_excerpt}

Content baseline:
- Source title: {source_title}
- Video title: {video_title}
- Duration: {duration_seconds} seconds
- Game: {game_name}

Hashtag discipline: Use up to {hashtag_limit} distinct hashtags derived from the content tags or title tokens.

Output JSON shape:
{{"title": str, "description": str, "hashtags": [str], "notes": str}}

The title must respect the platform's caption limit. The description provides context about the source/video. The hashtags are up to {hashtag_limit} distinct tags. Respond with only the JSON object.
"""


def _truncate_transcript(transcript: str,
                         max_chars: int = HF_MAX_TRANSCRIPT_CHARS) -> str:
    """Truncate the transcript to ``max_chars``, taking the head and tail."""
    if len(transcript) <= max_chars:
        return transcript
    half = max_chars // 2
    return transcript[:half] + "\n...\n" + transcript[-half:]


def _select_hashtags(title: str, tags: Any,
                     k: int = DEFAULT_HASHTAG_LIMIT) -> list[str]:
    """Return top-K distinct hashtags from ``tags``, or title tokens when none."""
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        value = str(tag).strip("#").replace(" ", "")
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
        if len(normalized) >= k:
            return normalized
    if normalized:
        return normalized
    for token in str(title).split():
        value = token.strip("#").replace(" ", "")
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
        if len(normalized) >= k:
            break
    return normalized


def _bounded_text(text: str, limit: int | None) -> str:
    """Truncate ``text`` to ``limit`` with the policy's ``rstrip`` discipline."""
    if limit is None:
        return text
    return text[:limit].rstrip()


def _trim_hashtags(title: str, hashtags: list[str], limit: int | None) -> list[str]:
    """Drop trailing hashtags until title + hashtags fit within ``limit``."""
    if limit is None:
        return hashtags
    remaining = list(hashtags)
    while remaining:
        composed = title + "\n\n" + " ".join(
            f"#{tag}" for tag in remaining)
        if len(composed) <= limit:
            break
        remaining.pop()
    return remaining


def _bound_result(platform: str, result: dict[str, Any],
                  limits: dict[str, Any]) -> dict[str, Any]:
    """Length-truncate a provider's output to the platform's policy limit.

    Mirrors ``policy.validate_artifact``: a value longer than the platform's
    ``caption_limit`` is sliced and right-stripped. Separate-mode platforms
    bound the title to the platform's own title limit instead, and keep their
    hashtags because those compose into the keyword string, not the caption.
    """
    limit = limits.get("caption_limit")
    if limit is None:
        return result
    rule = CAPABILITY_MATRIX.get(platform)
    separate = rule is not None and rule.content_mode == "separate"
    title_limit = min(limit, SEPARATE_TITLE_LIMIT) if separate else limit
    result["title"] = _bounded_text(str(result.get("title", "")), title_limit)
    result["description"] = _bounded_text(
        str(result.get("description", "")), limit)
    hashtags = [str(tag).strip("#").replace(" ", "")
                for tag in (result.get("hashtags") or [])]
    result["hashtags"] = [tag for tag in hashtags if tag]
    if not separate:
        result["hashtags"] = _trim_hashtags(
            result["title"], result["hashtags"], limit)
    return result


def _template_provider(
    platform: str,
    transcript_excerpt: str,
    content_baseline: dict[str, Any],
    limits: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    """Deterministic, zero-dep provider that uses policy composition rules."""
    title = (
        content_baseline.get("video_title")
        or content_baseline.get("source_title")
        or ""
    )
    description = content_baseline.get("source_title") or ""
    tags = content_baseline.get("tags", [])

    content = {"title": title, "description": description, "tags": tags}
    metadata = build_platform_metadata(platform, content)
    # The row keeps a bare title for every content mode so accepting it copies
    # separate title/description/hashtags fields; ``build_platform_metadata``
    # is the authority only for the separate-mode title bound, and
    # ``_bound_result`` applies the caption/title limits afterwards.
    rule = CAPABILITY_MATRIX.get(platform)
    if rule is not None and rule.content_mode == "separate":
        bounded_title = metadata.get("title", "")
    else:
        bounded_title = title

    return {
        "title": bounded_title,
        "description": description,
        "hashtags": _select_hashtags(title, tags),
        "notes": "",
        "provider": PROVIDER_TEMPLATE,
        "model": None,
    }


class _HFError(Exception):
    """Base class for Hugging Face provider errors."""


class _HFHTTPError(_HFError):
    """HTTP-level failure from the HF router."""


class _HFParseError(_HFError):
    """Parse-level failure from the HF router response."""


def _call_hf_router(
    token: str,
    model: str,
    prompt: str,
    repair: bool = False,
) -> dict[str, Any]:
    """Call the HF router and return the parsed JSON response."""
    import requests

    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    if repair:
        messages.append({
            "role": "user",
            "content": (
                "Your previous response was not valid JSON. "
                "Respond with only the JSON object."
            ),
        })

    try:
        response = requests.post(
            HF_ROUTER_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=HF_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except Exception as error:
        # ``safe_error_message`` strips any credential-shaped assignment; the
        # bearer token is never included in the raised text.
        raise _HFHTTPError(safe_error_message(error)) from error


def _parse_hf_response(data: dict[str, Any]) -> dict[str, Any]:
    """Parse the HF router response and validate the output shape."""
    try:
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise _HFParseError(f"invalid response shape: {error}") from error

    if not isinstance(result, dict):
        raise _HFParseError("response is not a JSON object")

    missing = [key for key in SUGGESTION_OUTPUT_KEYS if key not in result]
    if missing:
        raise _HFParseError(f"missing keys: {', '.join(missing)}")

    hashtags = result.get("hashtags", [])
    if not isinstance(hashtags, list):
        hashtags = [str(hashtags)]
    return {
        "title": str(result.get("title", "")),
        "description": str(result.get("description", "")),
        "hashtags": [str(tag) for tag in hashtags],
        "notes": str(result.get("notes", "")),
    }


def _hugging_face_provider(
    platform: str,
    transcript_excerpt: str,
    content_baseline: dict[str, Any],
    limits: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    """Hugging Face provider using the Inference Providers router."""
    token = os.environ.get("HUGGING_FACE_ACCESS_TOKEN")
    if not token:
        result = _template_provider(
            platform, transcript_excerpt, content_baseline, limits)
        result["note"] = "HUGGING_FACE_ACCESS_TOKEN not set; used template"
        return result

    resolved_model = (model or os.environ.get("HUGGING_FACE_MODEL")
                      or HF_DEFAULT_MODEL)
    prompt = PROMPT_TEMPLATE.format(
        platform=platform,
        caption_limit=limits.get("caption_limit", "unlimited"),
        transcript_excerpt=_truncate_transcript(transcript_excerpt),
        source_title=content_baseline.get("source_title", ""),
        video_title=content_baseline.get("video_title", ""),
        duration_seconds=content_baseline.get("duration_seconds") or "unknown",
        game_name=content_baseline.get("game_name") or "unknown",
        hashtag_limit=DEFAULT_HASHTAG_LIMIT,
    )

    def _success(parsed: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": parsed["title"],
            "description": parsed["description"],
            "hashtags": parsed["hashtags"],
            "notes": parsed["notes"],
            "provider": PROVIDER_HUGGING_FACE,
            "model": resolved_model,
        }

    try:
        return _success(_parse_hf_response(_call_hf_router(token, resolved_model, prompt)))
    except _HFHTTPError as error:
        # HTTP error -> immediate template fallback.
        result = _template_provider(
            platform, transcript_excerpt, content_baseline, limits)
        result["note"] = f"Hugging Face provider failed: {error}; used template"
        return result
    except _HFParseError:
        # Parse error -> retry once with a repair instruction.
        try:
            return _success(_parse_hf_response(
                _call_hf_router(token, resolved_model, prompt, repair=True)))
        except _HFError as retry_error:
            result = _template_provider(
                platform, transcript_excerpt, content_baseline, limits)
            result["note"] = (
                f"Hugging Face provider failed: {retry_error}; used template")
            return result


# Provider registry - same pattern as clipmorph/platforms.py registration.
_PROVIDER_REGISTRY: dict[str, Any] = {
    PROVIDER_TEMPLATE: _template_provider,
    PROVIDER_HUGGING_FACE: _hugging_face_provider,
}


def suggest_metadata(
    platform: str,
    transcript_excerpt: str,
    content_baseline: dict[str, Any],
    limits: dict[str, Any],
    provider: str = "template",
    model: str | None = None,
) -> dict[str, Any]:
    """Generate platform-aware metadata suggestions for one platform.

    ``content_baseline`` carries ``{source_title, video_title,
    duration_seconds, game_name}`` plus the current ``tags`` (all optional).
    ``limits`` carries ``{caption_limit: int | None}`` from the policy.
    ``model`` optionally overrides the provider's model. Unknown providers
    degrade to the template provider with a note, and every result is
    length-truncated to the platform's policy limit post-hoc.
    """
    provider_fn = _PROVIDER_REGISTRY.get(provider)
    if provider_fn is None:
        result = _template_provider(
            platform, transcript_excerpt, content_baseline, limits)
        result["note"] = f"unknown provider {provider!r}; used template"
        return _bound_result(platform, result, limits)
    return _bound_result(
        platform, provider_fn(
            platform, transcript_excerpt, content_baseline, limits, model),
        limits)
