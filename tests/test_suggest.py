"""Tests for AI-assisted platform metadata and caption suggestions."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.configuration import resolve_job_configuration
from clipmorph.job import JobManifest
from clipmorph.service import JobService
from clipmorph.suggest import (
    PROVIDER_HUGGING_FACE,
    PROVIDER_TEMPLATE,
    suggest_metadata,
)


class TemplateProviderTests(unittest.TestCase):
    def test_template_provider_truncates_to_each_platform_caption_limit(self):
        from clipmorph.policy import CAPABILITY_MATRIX

        long_title = "t" * 5000
        content_baseline = {
            "source_title": "clip",
            "video_title": long_title,
            "duration_seconds": 30,
            "game_name": "TestGame",
            "tags": ["gaming", "test"],
        }

        for platform, rule in CAPABILITY_MATRIX.items():
            with self.subTest(platform=platform):
                limits = {"caption_limit": rule.caption_limit}
                result = suggest_metadata(
                    platform, "", content_baseline, limits, PROVIDER_TEMPLATE
                )
                self.assertEqual(result["provider"], PROVIDER_TEMPLATE)
                self.assertIsNone(result["model"])
                self.assertIn("title", result)
                self.assertIn("description", result)
                self.assertIn("hashtags", result)
                self.assertIn("notes", result)
                # The composed title must respect the caption limit
                self.assertLessEqual(len(result["title"]), rule.caption_limit)

    def test_template_provider_hashtags_from_tags(self):
        content_baseline = {
            "source_title": "clip",
            "video_title": "Boss fight",
            "tags": ["gaming", "boss", "fight"],
        }
        limits = {"caption_limit": 2200}
        result = suggest_metadata(
            "instagram", "", content_baseline, limits, PROVIDER_TEMPLATE
        )
        self.assertEqual(result["hashtags"], ["gaming", "boss", "fight"])

    def test_template_provider_no_tags_fallback_to_title_tokens(self):
        content_baseline = {
            "source_title": "clip",
            "video_title": "Boss fight clutch",
            "tags": [],
        }
        limits = {"caption_limit": 2200}
        result = suggest_metadata(
            "instagram", "", content_baseline, limits, PROVIDER_TEMPLATE
        )
        self.assertEqual(result["hashtags"], ["Boss", "fight", "clutch"])

    def test_template_provider_empty_transcript_still_produces_valid_output(self):
        content_baseline = {
            "source_title": "clip",
            "video_title": "Test title",
            "tags": ["gaming"],
        }
        limits = {"caption_limit": 280}
        result = suggest_metadata(
            "twitter", "", content_baseline, limits, PROVIDER_TEMPLATE
        )
        self.assertEqual(result["provider"], PROVIDER_TEMPLATE)
        self.assertTrue(result["title"])
        self.assertIsInstance(result["hashtags"], list)

    def test_template_provider_hashtag_limit_is_five(self):
        content_baseline = {
            "source_title": "clip",
            "video_title": "Title",
            "tags": ["a", "b", "c", "d", "e", "f", "g"],
        }
        limits = {"caption_limit": 2200}
        result = suggest_metadata(
            "instagram", "", content_baseline, limits, PROVIDER_TEMPLATE
        )
        self.assertEqual(len(result["hashtags"]), 5)

    def test_template_provider_deduplicates_hashtags(self):
        content_baseline = {
            "source_title": "clip",
            "video_title": "Title",
            "tags": ["gaming", "gaming", "boss", "boss"],
        }
        limits = {"caption_limit": 2200}
        result = suggest_metadata(
            "instagram", "", content_baseline, limits, PROVIDER_TEMPLATE
        )
        self.assertEqual(result["hashtags"], ["gaming", "boss"])

    def test_template_output_recomposes_without_duplicating_fields(self):
        from clipmorph.policy import CAPABILITY_MATRIX, build_platform_metadata

        content_baseline = {
            "source_title": "clip",
            "video_title": "Boss fight",
            "tags": ["gaming", "speedrun"],
        }
        for platform in ("instagram", "tiktok", "twitter", "facebook"):
            with self.subTest(platform=platform):
                limits = {"caption_limit": CAPABILITY_MATRIX[platform].caption_limit}
                result = suggest_metadata(
                    platform, "", content_baseline, limits, PROVIDER_TEMPLATE)
                # Accepting a row copies title/description/tags into
                # upload.content, which policy composes once more on submit.
                composed = next(iter(build_platform_metadata(platform, {
                    "title": result["title"],
                    "description": result["description"],
                    "tags": result["hashtags"],
                }).values()))
                self.assertEqual(composed.count(result["description"]), 1)
                for tag in result["hashtags"]:
                    self.assertEqual(composed.count(f"#{tag}"), 1)


class HuggingFaceProviderTests(unittest.TestCase):
    def _hf_response(self, content: str) -> dict:
        return {
            "choices": [{
                "message": {"content": content},
            }],
        }

    def test_hf_provider_parses_valid_json_response(self):
        content_baseline = {
            "source_title": "clip",
            "video_title": "Boss fight",
            "tags": ["gaming"],
        }
        limits = {"caption_limit": 2200}
        response_data = self._hf_response(json.dumps({
            "title": "Epic boss fight",
            "description": "Final boss with no healing",
            "hashtags": ["gaming", "bossfight"],
            "notes": "",
        }))

        with patch("clipmorph.suggest._call_hf_router", return_value=response_data):
            with patch.dict("os.environ", {"HUGGING_FACE_ACCESS_TOKEN": "test-token"}):
                result = suggest_metadata(
                    "instagram", "transcript text", content_baseline, limits,
                    PROVIDER_HUGGING_FACE,
                )

        self.assertEqual(result["provider"], PROVIDER_HUGGING_FACE)
        self.assertEqual(result["title"], "Epic boss fight")
        self.assertEqual(result["description"], "Final boss with no healing")
        self.assertEqual(result["hashtags"], ["gaming", "bossfight"])

    def test_hf_provider_truncates_values_to_the_caption_limit(self):
        content_baseline = {"source_title": "clip", "video_title": "Title"}
        limits = {"caption_limit": 280}
        response_data = self._hf_response(json.dumps({
            "title": "t" * 400,
            "description": "d" * 400,
            "hashtags": ["gaming"],
            "notes": "",
        }))

        with patch("clipmorph.suggest._call_hf_router", return_value=response_data):
            with patch.dict("os.environ", {"HUGGING_FACE_ACCESS_TOKEN": "test-token"}):
                result = suggest_metadata(
                    "twitter", "transcript", content_baseline, limits,
                    PROVIDER_HUGGING_FACE,
                )

        self.assertLessEqual(len(result["title"]), 280)
        self.assertLessEqual(len(result["description"]), 280)

    def test_hf_provider_model_override_reaches_the_router(self):
        content_baseline = {"source_title": "clip", "video_title": "Title"}
        limits = {"caption_limit": 2200}
        response_data = self._hf_response(json.dumps({
            "title": "Title",
            "description": "Description",
            "hashtags": ["gaming"],
            "notes": "",
        }))

        with patch("clipmorph.suggest._call_hf_router",
                   return_value=response_data) as router:
            with patch.dict("os.environ", {"HUGGING_FACE_ACCESS_TOKEN": "test-token"}):
                result = suggest_metadata(
                    "instagram", "transcript", content_baseline, limits,
                    PROVIDER_HUGGING_FACE, "custom/model",
                )

        self.assertEqual(result["model"], "custom/model")
        self.assertEqual(router.call_args.args[1], "custom/model")

    def test_hf_provider_non_json_then_repair_retry(self):
        content_baseline = {"source_title": "clip", "video_title": "Title"}
        limits = {"caption_limit": 2200}

        # First call returns non-JSON, second call returns valid JSON
        call_count = 0
        def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._hf_response("not valid json")
            return self._hf_response(json.dumps({
                "title": "Repaired title",
                "description": "Repaired description",
                "hashtags": ["fixed"],
                "notes": "",
            }))

        with patch("clipmorph.suggest._call_hf_router", side_effect=mock_call):
            with patch.dict("os.environ", {"HUGGING_FACE_ACCESS_TOKEN": "test-token"}):
                result = suggest_metadata(
                    "instagram", "transcript", content_baseline, limits,
                    PROVIDER_HUGGING_FACE,
                )

        self.assertEqual(call_count, 2)
        self.assertEqual(result["title"], "Repaired title")
        self.assertEqual(result["provider"], PROVIDER_HUGGING_FACE)

    def test_hf_provider_non_json_both_attempts_falls_back_to_template(self):
        content_baseline = {"source_title": "clip", "video_title": "Title"}
        limits = {"caption_limit": 2200}

        with patch("clipmorph.suggest._call_hf_router",
                    return_value=self._hf_response("not json")):
            with patch.dict("os.environ", {"HUGGING_FACE_ACCESS_TOKEN": "test-token"}):
                result = suggest_metadata(
                    "instagram", "transcript", content_baseline, limits,
                    PROVIDER_HUGGING_FACE,
                )

        self.assertEqual(result["provider"], PROVIDER_TEMPLATE)
        self.assertIn("note", result)
        self.assertIn("failed", result["note"].lower())

    def test_hf_provider_http_error_falls_back_to_template(self):
        from clipmorph.suggest import _HFHTTPError

        content_baseline = {"source_title": "clip", "video_title": "Title"}
        limits = {"caption_limit": 2200}

        with patch("clipmorph.suggest._call_hf_router",
                    side_effect=_HFHTTPError("401 Unauthorized")):
            with patch.dict("os.environ", {"HUGGING_FACE_ACCESS_TOKEN": "test-token"}):
                result = suggest_metadata(
                    "instagram", "transcript", content_baseline, limits,
                    PROVIDER_HUGGING_FACE,
                )

        self.assertEqual(result["provider"], PROVIDER_TEMPLATE)
        self.assertIn("note", result)
        self.assertIn("401", result["note"])

    def test_hf_provider_token_never_in_error_text(self):
        from clipmorph.suggest import _HFHTTPError

        content_baseline = {"source_title": "clip", "video_title": "Title"}
        limits = {"caption_limit": 2200}

        with patch("clipmorph.suggest._call_hf_router",
                    side_effect=_HFHTTPError("401 Unauthorized")):
            with patch.dict("os.environ", {"HUGGING_FACE_ACCESS_TOKEN": "secret-token-123"}):
                result = suggest_metadata(
                    "instagram", "transcript", content_baseline, limits,
                    PROVIDER_HUGGING_FACE,
                )

        self.assertNotIn("secret-token-123", result.get("note", ""))

    def test_hf_provider_no_token_falls_back_to_template(self):
        content_baseline = {"source_title": "clip", "video_title": "Title"}
        limits = {"caption_limit": 2200}

        with patch.dict("os.environ", {}, clear=True):
            result = suggest_metadata(
                "instagram", "transcript", content_baseline, limits,
                PROVIDER_HUGGING_FACE,
            )

        self.assertEqual(result["provider"], PROVIDER_TEMPLATE)
        self.assertIn("note", result)
        self.assertIn("HUGGING_FACE_ACCESS_TOKEN", result["note"])


class UnknownProviderTests(unittest.TestCase):
    def test_unknown_provider_degrades_to_template_with_note(self):
        content_baseline = {"source_title": "clip", "video_title": "Title"}
        limits = {"caption_limit": 2200}
        result = suggest_metadata(
            "instagram", "", content_baseline, limits, "unknown_provider"
        )
        self.assertEqual(result["provider"], PROVIDER_TEMPLATE)
        self.assertIn("note", result)
        self.assertIn("unknown provider", result["note"])


class ServiceSuggestTests(unittest.TestCase):
    def _reviewed_job(self, data_dir: Path) -> tuple[JobService, JobManifest]:
        source_dir = data_dir / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        source = source_dir / "clip.mp4"
        source.write_bytes(b"video")
        service = JobService(data_dir)
        # Mirror ``create_job``: the effective configuration is resolved before
        # it reaches the manifest, so ``upload.content.title`` is already
        # derived when the first generation computes its dedup hash.
        manifest = JobManifest.create(
            str(source),
            {"general": {"source": source.name},
             "upload": {"content": {"title": source.stem}},
             "conversion": {"skip": True, "subtitles": {"skip": True}}},
            service.jobs_dir,
        )
        manifest.record_artifact("source", source, service.jobs_dir)
        manifest.transition_checkpoint(
            "upload", "awaiting_review",
            manifest.checkpoints["upload"]["revision"], service.jobs_dir,
        )
        return service, manifest

    def test_suggest_writes_block_and_bumps_revision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_job(data_dir)
            self.addCleanup(service.close)

            result = service.suggest_upload_metadata(manifest.job_id)

            self.assertIn("upload", result)
            self.assertIn("suggestions", result["upload"])
            self.assertIn("youtube", result["upload"]["suggestions"])
            suggestion = result["upload"]["suggestions"]["youtube"]
            self.assertEqual(suggestion["provider"], "template")
            self.assertIn("generated_at", suggestion)
            self.assertIn("configuration_hash", suggestion)
            self.assertIn("title", suggestion)
            self.assertIn("description", suggestion)
            self.assertIn("hashtags", suggestion)

            # Revision was bumped
            saved = service.get_job(manifest.job_id)
            self.assertGreater(
                saved.checkpoints["upload"]["revision"],
                manifest.checkpoints["upload"]["revision"],
            )

    def test_suggest_dedup_noop_on_unchanged_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_job(data_dir)
            self.addCleanup(service.close)

            first = service.suggest_upload_metadata(manifest.job_id)
            first_suggestion = first["upload"]["suggestions"]["youtube"]
            first_revision = first["checkpoint"]["revision"]

            # Second call without force should be a no-op
            second = service.suggest_upload_metadata(manifest.job_id)
            second_suggestion = second["upload"]["suggestions"]["youtube"]

            self.assertEqual(
                first_suggestion["generated_at"],
                second_suggestion["generated_at"],
            )
            self.assertEqual(first_revision, second["checkpoint"]["revision"])

    def test_suggest_force_regenerates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_job(data_dir)
            self.addCleanup(service.close)

            first = service.suggest_upload_metadata(manifest.job_id)
            first_suggestion = first["upload"]["suggestions"]["youtube"]

            second = service.suggest_upload_metadata(manifest.job_id, force=True)
            second_suggestion = second["upload"]["suggestions"]["youtube"]

            self.assertNotEqual(
                first_suggestion["generated_at"],
                second_suggestion["generated_at"],
            )

    def test_suggest_rejected_before_awaiting_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            self.addCleanup(service.close)
            manifest = JobManifest.create(
                str(source),
                {"general": {"source": source.name},
                 "conversion": {"skip": True, "subtitles": {"skip": True}}},
                service.jobs_dir,
            )

            with self.assertRaisesRegex(ValueError, "awaiting review"):
                service.suggest_upload_metadata(manifest.job_id)

    def test_accept_copies_into_content_and_clears_block(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_job(data_dir)
            self.addCleanup(service.close)

            generated = service.suggest_upload_metadata(manifest.job_id)
            suggestion_title = generated["upload"]["suggestions"]["youtube"]["title"]
            result = service.accept_suggestions(manifest.job_id, ["youtube"])

            upload = result["upload"]
            self.assertEqual(upload["content"]["title"], suggestion_title)
            # The accepted suggestion row is cleared
            self.assertNotIn("youtube", upload["suggestions"])

    def test_accept_rejects_unknown_platform(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_job(data_dir)
            self.addCleanup(service.close)

            service.suggest_upload_metadata(manifest.job_id, ["youtube"])

            with self.assertRaisesRegex(ValueError, "no suggestion"):
                service.accept_suggestions(manifest.job_id, ["tiktok"])


class ConfigurationValidatorTests(unittest.TestCase):
    def test_suggestions_key_is_allowed_in_upload_configuration(self):
        configuration = resolve_job_configuration({}, {
            "general": {"source": "clip.mp4"},
            "upload": {"suggestions": {"provider": "hugging_face", "model": "test-model"}},
        })
        self.assertEqual(
            configuration["upload"]["suggestions"]["provider"], "hugging_face")
        self.assertEqual(
            configuration["upload"]["suggestions"]["model"], "test-model")

    def test_suggestions_provider_must_be_non_empty_string(self):
        with self.assertRaisesRegex(ValueError, "provider"):
            resolve_job_configuration({}, {
                "general": {"source": "clip.mp4"},
                "upload": {"suggestions": {"provider": ""}},
            })

    def test_suggestions_model_must_be_string_or_null(self):
        with self.assertRaisesRegex(ValueError, "model"):
            resolve_job_configuration({}, {
                "general": {"source": "clip.mp4"},
                "upload": {"suggestions": {"model": 123}},
            })

    def test_suggestions_unknown_key_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            resolve_job_configuration({}, {
                "general": {"source": "clip.mp4"},
                "upload": {"suggestions": {"unknown_key": "value"}},
            })


if __name__ == "__main__":
    unittest.main()
