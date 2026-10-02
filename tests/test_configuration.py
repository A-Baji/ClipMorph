import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import yaml

from clipmorph.configuration import APP_CONFIG_VERSION
from clipmorph.configuration import DEFAULT_APP_CONFIGURATION
from clipmorph.configuration import load_app_configuration
from clipmorph.configuration import load_job_records
from clipmorph.configuration import merge_source_configurations
from clipmorph.configuration import merge_configuration
from clipmorph.configuration import resolve_job_configuration
from clipmorph.configuration import resolve_platform_configuration
from clipmorph.configuration import save_app_configuration
from clipmorph.configuration import discover_source_names
from clipmorph.platforms import build_platform_default_config
from clipmorph.job import JobManifest
from clipmorph.job import MANIFEST_SCHEMA_VERSION
from clipmorph.service import JobService
from clipmorph.service import CancellationToken
from clipmorph.service import conversion_groups
from clipmorph.transcript import create_edit_session
from clipmorph.workflow import _effective_no_confirm, execute_job


class FilenameTitleTests(unittest.TestCase):
    def test_step_confirmation_uses_the_matching_section_setting(self):
        configuration = {
            "general": {"no_confirm": False},
            "conversion": {"no_confirm": True,
                           "subtitles": {"no_confirm": None}},
            "upload": {"no_confirm": False},
        }
        self.assertTrue(_effective_no_confirm(configuration, "conversion"))
        self.assertFalse(_effective_no_confirm(configuration, "upload"))
        self.assertTrue(_effective_no_confirm(configuration, "transcript"))

    def test_derives_titles_from_valid_source_filenames(self):
        cases = {
            "clip.mp4": "clip",
            "round.one.final.mp4": "round.one.final",
            "My clip 01.MP4": "My clip 01",
            "...mp4": "..",
            "_-.mp4": "_-",
            ".mp4": "",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                configuration = resolve_job_configuration(
                    {}, {"general": {"source": source}})
                self.assertEqual(configuration["upload"]["content"]["title"],
                                 expected)

    def test_empty_title_is_derived_and_explicit_title_wins(self):
        for title in (None, ""):
            with self.subTest(title=title):
                configuration = resolve_job_configuration(
                    {}, {
                        "general": {"source": "My Clip.mp4"},
                        "upload": {"content": {"title": title}},
                    })
                self.assertEqual(configuration["upload"]["content"]["title"],
                                 "My Clip")

        explicit = resolve_job_configuration(
            {}, {
                "general": {"source": "My Clip.mp4"},
                "upload": {"content": {"title": "Chosen title"}},
            })
        self.assertEqual(explicit["upload"]["content"]["title"], "Chosen title")


class JobConfigurationTests(unittest.TestCase):
    def test_merge_replaces_lists_and_does_not_mutate_inputs(self):
        defaults = {
            "general": {"source": None, "clean": False},
            "upload": {"content": {"tags": ["default"], "title": ""}},
        }
        overrides = {
            "general": {"source": "clip.mp4"},
            "upload": {"content": {"tags": ["job"]}},
        }

        effective = merge_configuration(defaults, overrides)

        self.assertEqual(effective["upload"]["content"],
                         {"tags": ["job"], "title": ""})
        self.assertIsNone(defaults["general"]["source"])
        self.assertEqual(overrides["upload"]["content"]["tags"], ["job"])

    def test_layout_preset_is_materialized_then_inline_layout_overrides_it(self):
        configuration = resolve_job_configuration(
            {"conversion": {"layout_id": "vertical"}},
            {"general": {"source": "clip.mp4"},
             "conversion": {"layout": {"crop": {"enabled": False}}}},
            [{"id": "vertical", "name": "Vertical", "layout": {
                "crop": {
                    "enabled": True,
                    "source": {"x": 0, "y": 0, "width": 100, "height": 100},
                    "sizing": {"mode": "native"},
                    "composition": {"mode": "overlay", "placement": "center"},
                },
                "captions": {"overlay": {"items": []}}
            }}],
        )

        self.assertEqual(configuration["conversion"]["layout_id"], "vertical")
        self.assertEqual(configuration["conversion"]["layout"], {
            "crop": {
                "enabled": False,
                "source": {"x": 0, "y": 0, "width": 100, "height": 100},
                "sizing": {"mode": "native"},
                "composition": {"mode": "overlay", "placement": "center"},
            },
            "captions": {"overlay": {"items": []}}
        })

    def test_source_must_be_a_root_level_filename(self):
        for source in ("../clip.mp4", "folder/clip.mp4", r"folder\clip.mp4"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "root-level|separators"):
                    resolve_job_configuration({}, {"general": {"source": source}})

    def test_resolver_rejects_legacy_and_unknown_job_configuration_fields(self):
        invalid = [
            {"general": {"no_conversion": True}},
            {"conversion": {"camera": {"x": 1}}},
            {"content": {"title": "Flat title"}},
            {"upload": {"platforms": {"unknown": {}}}},
            {"platforms": {"unknown": {}}},
        ]
        for configuration in invalid:
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(ValueError, "Unknown|unsupported"):
                    resolve_job_configuration({}, configuration)

    def test_schedule_mode_selects_who_holds_the_publication(self):
        publish_at = "2026-10-01T12:00:00+00:00"

        for mode in (None, "local", "platform"):
            with self.subTest(mode=mode):
                configuration = resolve_job_configuration({}, {
                    "general": {"source": "clip.mp4"},
                    "upload": {"schedule": {"publish_at": publish_at,
                                            "mode": mode}},
                })
                self.assertEqual(
                    configuration["upload"]["schedule"]["mode"], mode)

    def test_schedule_mode_rejects_an_unknown_holder(self):
        with self.assertRaisesRegex(
                ValueError, "upload.schedule.mode must be one of: local, platform"):
            resolve_job_configuration({}, {
                "general": {"source": "clip.mp4"},
                "upload": {"schedule": {"publish_at": "2026-10-01T12:00:00+00:00",
                                        "mode": "youtube"}},
            })

    def test_schedule_mode_alone_schedules_nothing(self):
        # The key is inert without a future publish_at: the service resolves
        # the holder only when a publication is actually deferred.
        configuration = resolve_job_configuration({}, {
            "general": {"source": "clip.mp4"},
            "upload": {"schedule": {"mode": "platform"}},
        })

        self.assertIsNone(configuration["upload"]["schedule"].get("publish_at"))
        self.assertEqual(configuration["upload"]["schedule"]["mode"],
                         "platform")

    def test_suggestions_block_accepts_scalars_and_platform_rows(self):
        configuration = resolve_job_configuration({}, {
            "general": {"source": "clip.mp4"},
            "upload": {"suggestions": {
                "provider": "hugging_face",
                "model": "test-model",
                "youtube": {
                    "title": "A title",
                    "description": "A description",
                    "hashtags": ["gaming"],
                    "generated_at": "2026-09-30T00:00:00+00:00",
                    "provider": "template",
                    "model": None,
                },
            }},
        })

        suggestions = configuration["upload"]["suggestions"]
        self.assertEqual(suggestions["provider"], "hugging_face")
        self.assertEqual(suggestions["model"], "test-model")
        self.assertEqual(suggestions["youtube"]["title"], "A title")

    def test_suggestions_block_rejects_unknown_keys_and_bad_rows(self):
        invalid = [
            {"unknown_key": "value"},
            {"youtube": "not an object"},
        ]
        for suggestions in invalid:
            with self.subTest(suggestions=suggestions):
                with self.assertRaisesRegex(ValueError, "Unknown|object"):
                    resolve_job_configuration({}, {
                        "general": {"source": "clip.mp4"},
                        "upload": {"suggestions": suggestions},
                    })

    def test_suggestions_provider_and_model_types_are_validated(self):
        with self.assertRaisesRegex(ValueError, "provider"):
            resolve_job_configuration({}, {
                "general": {"source": "clip.mp4"},
                "upload": {"suggestions": {"provider": ""}},
            })
        with self.assertRaisesRegex(ValueError, "model"):
            resolve_job_configuration({}, {
                "general": {"source": "clip.mp4"},
                "upload": {"suggestions": {"model": 123}},
            })

    def test_per_platform_resolution_merges_override_sections(self):
        from clipmorph.configuration import resolve_platform_configuration
        manifest_config = {
            "general": {"source": "clip.mp4"},
            "conversion": {"layout_id": None, "skip": False,
                           "subtitles": {"skip": False, "renderer": "overlay",
                                          "transcription_model": "tiny"}},
            "upload": {"skip": False, "content": {"title": "Job title"}},
            "platforms": {
                "youtube": {
                    "category": "22",
                    "conversion": {"skip": True},
                    "upload": {"content": {"title": "Full stream VOD"}},
                },
                "tiktok": {
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "upload": {"skip": True},
                },
            },
        }
        global_defaults = {
            "general": {"source": None},
            "conversion": {"layout_id": None, "skip": False,
                           "subtitles": {"skip": False, "renderer": "overlay",
                                          "transcription_model": "tiny"}},
            "upload": {"skip": False, "content": {"title": ""}},
        }
        youtube = resolve_platform_configuration(
            manifest_config, global_defaults, [], "youtube")
        self.assertTrue(youtube["conversion"]["skip"])
        self.assertEqual(youtube["upload"]["content"]["title"], "Full stream VOD")
        self.assertEqual(youtube["platforms"]["youtube"]["category"], "22")

        tiktok = resolve_platform_configuration(
            manifest_config, global_defaults, [], "tiktok")
        self.assertFalse(tiktok["conversion"]["skip"])
        self.assertTrue(tiktok["platforms"]["tiktok"]["upload"]["skip"])

    def test_per_platform_resolution_rejects_protected_keys(self):
        # Protected-key validation happens during resolve_job_configuration,
        # which resolve_platform_configuration calls internally.
        invalid = [
            {"platforms": {"youtube": {"platforms": {}}}},
            {"platforms": {"youtube": {"general": {"source": "other.mp4"}}}},
        ]
        for configuration in invalid:
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(ValueError, "platforms|source identity"):
                    resolve_job_configuration({}, configuration)

    def test_per_platform_upload_skip_must_be_boolean(self):
        invalid = [
            {"platforms": {"youtube": {"upload": {"skip": "yes"}}}},
            {"platforms": {"youtube": {"upload": {"skip": 1}}}},
        ]
        for configuration in invalid:
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(ValueError, "skip.*boolean"):
                    resolve_job_configuration({}, configuration)

    def test_per_platform_conversion_schema_violations_fail(self):
        invalid = [
            {"platforms": {"youtube": {"conversion": {"skip": "yes"}}}},
            {"platforms": {"youtube": {"conversion": {"subtitles": {"renderer": "bad"}}}}},
            {"platforms": {"youtube": {"conversion": {"layout_id": 123}}}},
        ]
        for configuration in invalid:
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(ValueError, "conversion"):
                    resolve_job_configuration({}, configuration)

    def test_conversion_groups_identical_configs_share_one_group(self):
        from clipmorph.service import conversion_groups
        config = {
            "general": {"source": "clip.mp4"},
            "conversion": {"layout_id": None, "skip": False,
                           "subtitles": {"skip": False}},
            "upload": {"skip": False},
            "platforms": {
                "youtube": {"upload": {"skip": False}},
                "tiktok": {"upload": {"skip": False}},
            },
        }
        groups = conversion_groups(config)
        self.assertEqual(len(groups), 1)
        # All platforms without a conversion override share the job-level
        # conversion config, so they all land in the same group.
        self.assertEqual(
            set(groups[0]["platforms"]),
            {"youtube", "instagram", "tiktok", "twitter", "facebook"})

    def test_conversion_groups_distinct_configs_produce_two_groups(self):
        from clipmorph.service import conversion_groups
        config = {
            "general": {"source": "clip.mp4"},
            "conversion": {"layout_id": None, "skip": False,
                           "subtitles": {"skip": False}},
            "upload": {"skip": False},
            "platforms": {
                "youtube": {"conversion": {"skip": True}},
                "tiktok": {"conversion": {"skip": False}},
            },
        }
        groups = conversion_groups(config)
        self.assertEqual(len(groups), 2)
        skip_group = next(g for g in groups if g["conversion"].get("skip"))
        render_group = next(g for g in groups if not g["conversion"].get("skip"))
        self.assertEqual(skip_group["platforms"], ["youtube"])
        # Platforms without a conversion override inherit the job-level
        # config, so they join the render group.
        self.assertEqual(
            set(render_group["platforms"]),
            {"instagram", "tiktok", "twitter", "facebook"})

    def test_per_platform_layout_id_is_materialized_and_names_the_group(self):
        from clipmorph.service import conversion_groups
        preset = {"crop": {"enabled": True,
                           "source": {"x": 0, "y": 140, "width": 1280,
                                      "height": 440},
                           "sizing": {"mode": "fit",
                                      "dimensions": {"width": 1080,
                                                     "height": 1920}},
                           "composition": {"mode": "overlay",
                                           "placement": "top"}}}
        layouts = [{"id": "vertical", "name": "vertical", "layout": preset}]
        resolved = resolve_job_configuration({}, {
            "general": {"source": "clip.mp4"},
            "conversion": {"subtitles": {"skip": True}},
            "platforms": {"tiktok": {"conversion": {"layout_id": "vertical"}}},
        }, layouts)
        # The manifest stores one already-resolved shape, so the group digest
        # every later derivation takes is stable: a platform that names a
        # layout is hashed on the layout it will actually render.
        platform_conversion = resolved["platforms"]["tiktok"]["conversion"]
        self.assertEqual(platform_conversion["layout"]["crop"],
                         preset["crop"])
        group = next(item for item in conversion_groups(resolved)
                     if "tiktok" in item["platforms"])
        self.assertEqual(group["conversion"]["layout"]["crop"],
                         preset["crop"])
        # Re-resolving the stored configuration is idempotent.
        again = resolve_platform_configuration(resolved, {}, layouts, "tiktok")
        self.assertEqual(
            again["platforms"]["tiktok"]["conversion"]["layout"]["crop"],
            preset["crop"])

    def test_per_platform_unknown_layout_id_is_rejected(self):
        with self.assertRaisesRegex(
                ValueError,
                r"Unknown platforms\.tiktok\.conversion\.layout_id: nope"):
            resolve_job_configuration({}, {
                "general": {"source": "clip.mp4"},
                "platforms": {"tiktok": {"conversion": {"layout_id": "nope"}}},
            }, [])

    def test_per_platform_override_changes_only_the_stage_that_consumes_it(self):
        from clipmorph.job import checkpoint_configuration_hash
        base = {"general": {"source": "clip.mp4"},
                "conversion": {"subtitles": {"skip": True}},
                "upload": {"skip": False},
                "platforms": {"tiktok": {}}}
        conversion_edit = merge_configuration(base, {
            "platforms": {"tiktok": {"conversion": {"strict": True}}}})
        self.assertNotEqual(checkpoint_configuration_hash(base, "conversion"),
                            checkpoint_configuration_hash(conversion_edit,
                                                          "conversion"))
        upload_edit = merge_configuration(base, {
            "platforms": {"tiktok": {"upload": {"content": {"title": "x"}}}}})
        self.assertEqual(checkpoint_configuration_hash(base, "conversion"),
                         checkpoint_configuration_hash(upload_edit, "conversion"))
        self.assertNotEqual(checkpoint_configuration_hash(base, "upload"),
                            checkpoint_configuration_hash(upload_edit, "upload"))

    def test_per_platform_transcription_keys_are_rejected(self):
        # The job produces ONE transcript session, so a per-platform
        # transcription override has nothing to bind to.  It is refused rather
        # than silently ignored.
        for key in ("transcription_language", "transcription_model",
                    "transcription_device", "transcription_compute_type"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                        ValueError, "one transcript session"):
                    resolve_job_configuration({}, {
                        "general": {"source": "clip.mp4"},
                        "platforms": {
                            "youtube": {"conversion": {"subtitles": {key: "x"}}},
                        },
                    })

    def test_conversion_group_ids_match_the_group_section_digest(self):
        from clipmorph.job import configuration_sha256
        from clipmorph.service import conversion_groups
        config = {
            "general": {"source": "clip.mp4"},
            "conversion": {"skip": False, "subtitles": {"skip": False}},
            "upload": {"skip": False},
            "platforms": {
                "youtube": {"conversion": {"strict": True}},
                "tiktok": {"upload": {"content": {"title": "Other"}}},
            },
        }
        groups = conversion_groups(config)
        for group in groups:
            self.assertEqual(
                group["id"], configuration_sha256(group["conversion"])[:12])

    def test_resolver_materializes_minimal_selected_caption_renderer(self):
        configuration = resolve_job_configuration(
            {}, {"general": {"source": "clip.mp4"}})

        self.assertIsNone(configuration["conversion"]["layout_id"])
        self.assertEqual(configuration["conversion"]["layout"]["captions"]["overlay"]["items"], [])
        self.assertEqual(configuration["conversion"]["subtitles"]["renderer"], "overlay")

    def test_resolver_rejects_unknown_caption_renderer(self):
        with self.assertRaisesRegex(ValueError, "renderer"):
            resolve_job_configuration({}, {
                "general": {"source": "clip.mp4"},
                "conversion": {"subtitles": {"renderer": "unknown"}},
            })

    def test_resolver_materializes_named_placements_and_omitted_dimensions(self):
        configuration = resolve_job_configuration({}, {
            "general": {"source": "clip.mp4"},
            "conversion": {"layout": {
                "crop": {
                    "enabled": True,
                    "source": {"x": 0, "y": 0, "width": 320, "height": 240},
                    "sizing": {"mode": "native"},
                    "composition": {"mode": "overlay", "placement": "center"},
                },
                "captions": {
                    "overlay": {"items": [{
                        "text": "Bottom caption", "placement": "bottom",
                    }]},
                    "stacked": {"placement": "top", "items": [{
                        "text": "Panel caption",
                    }]},
                },
            }},
        })
        layout = configuration["conversion"]["layout"]
        crop = layout["crop"]
        self.assertEqual(crop["composition"]["placement"], {"x": 540, "y": 960})
        overlay_item = layout["captions"]["overlay"]["items"][0]
        self.assertIsInstance(overlay_item["dimensions"]["width"], int)
        self.assertEqual(overlay_item["placement"], {
            "x": 540, "y": 1920 - overlay_item["dimensions"]["height"] // 2,
        })
        stacked = layout["captions"]["stacked"]
        self.assertIn("width", stacked["dimensions"])
        self.assertEqual(stacked["placement"]["y"], stacked["dimensions"]["height"] // 2)


class AppConfigurationTests(unittest.TestCase):
    def test_app_configuration_uses_yaml_and_round_trips_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"
            configuration = {
                "source_dir": "sources",
                "output_dir": "output",
                "job_defaults": {"general": {"source": None}},
                "layouts": [],
            }

            save_app_configuration(path, configuration)

            loaded = load_app_configuration(path)
            self.assertEqual(loaded["source_dir"], configuration["source_dir"])
            self.assertEqual(loaded["output_dir"], configuration["output_dir"])
            self.assertIsNone(loaded["job_defaults"]["general"]["source"])
            self.assertEqual(loaded["layouts"], [])
            self.assertTrue(path.exists())
            self.assertFalse(path.with_suffix(".yml.tmp").exists())

    def test_app_template_includes_registry_platform_defaults(self):
        """``clipmorph init`` carries the mandatory per-platform section.

        The template's flat options are generated from the platform
        registry (#225) instead of a hand-maintained copy, so the template
        and the upload adapters cannot drift apart.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"
            save_app_configuration(path, DEFAULT_APP_CONFIGURATION)
            loaded = load_app_configuration(path)

        self.assertEqual(loaded["job_defaults"]["platforms"],
                         build_platform_default_config())
        self.assertIn("youtube", loaded["job_defaults"]["platforms"])

    def test_app_configuration_rejects_unknown_top_level_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"
            path.write_text(
                f"config_version: {APP_CONFIG_VERSION}\nlegacy_config: true\n",
                encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unknown app configuration"):
                load_app_configuration(path)

    def test_app_configuration_requires_the_current_version_stamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"
            path.write_text("source_dir: sources\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, f"config_version must be {APP_CONFIG_VERSION}"):
                load_app_configuration(path)

            path.write_text("config_version: 99\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, f"config_version must be {APP_CONFIG_VERSION}"):
                load_app_configuration(path)

    def test_app_configuration_stamps_the_version_on_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"

            save_app_configuration(path, {"source_dir": "clips"})

            self.assertEqual(load_app_configuration(path)["config_version"],
                             APP_CONFIG_VERSION)
            self.assertEqual(
                yaml.safe_load(path.read_text(encoding="utf-8"))["config_version"],
                APP_CONFIG_VERSION)

    def test_app_configuration_rejects_a_stale_stamp_on_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"

            with self.assertRaisesRegex(ValueError, f"config_version must be {APP_CONFIG_VERSION}"):
                save_app_configuration(path, {"config_version": 99})
            self.assertFalse(path.exists())

    def test_app_configuration_validates_retention_knobs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"

            save_app_configuration(path, {"retention": {
                "artifacts": {"max_age_days": 90, "max_bytes": 5_000_000_000},
                "backups": {"keep_n": 3},
            }})
            retention = load_app_configuration(path)["retention"]
            self.assertEqual(retention["artifacts"]["max_age_days"], 90)
            self.assertEqual(retention["backups"]["keep_n"], 3)

            for invalid in ({"artifacts": {"max_age_days": 0}},
                            {"artifacts": {"max_bytes": "big"}},
                            {"artifacts": {"max_age_days": 1.5}},
                            {"artifacts": {"max_age_days": True}},
                            {"backups": {"keep_n": -1}},
                            {"backups": {"keep_n": None, "keep_all": True}},
                            {"artifacts": "90 days"},
                            {"never_delete": {"max_age_days": 1}}):
                with self.subTest(invalid=invalid):
                    with self.assertRaisesRegex(ValueError, "retention"):
                        save_app_configuration(path, {"retention": invalid})

    def test_app_configuration_validates_layout_registry_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"
            with self.assertRaisesRegex(ValueError, "source"):
                save_app_configuration(path, {"layouts": [{
                    "id": "broken", "name": "Broken",
                    "layout": {"crop": {"enabled": True}},
                }]})


class MultiSourceConfigurationTests(unittest.TestCase):
    def test_jsonl_and_yaml_records_are_job_objects_and_sidecars_merge_by_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "sources"
            explicit_dir = root / "configs"
            source_dir.mkdir()
            explicit_dir.mkdir()
            records_path = root / "jobs.jsonl"
            records_path.write_text(
                '{"general":{"source":"clip.mp4"},'
                '"upload":{"content":{"title":"record"}}}\n',
                encoding="utf-8")
            (source_dir / "source-settings.yml").write_text(
                "general:\n  source: clip.mp4\nupload:\n  content:\n    description: source-sidecar\n",
                encoding="utf-8")
            (source_dir / "another-source.yaml").write_text(
                "general:\n  source: clip.mov\nupload:\n  content:\n    description: mov-sidecar\n",
                encoding="utf-8")
            (explicit_dir / "explicit-settings.yml").write_text(
                "general:\n  source: clip.mp4\nupload:\n  content:\n    title: explicit-sidecar\n",
                encoding="utf-8")

            records = load_job_records(records_path)
            merged = merge_source_configurations(
                "clip.mp4", records, explicit_dir, source_dir)

            self.assertEqual(merged["upload"]["content"], {
                "title": "record", "description": "source-sidecar"})
            merged_mov = merge_source_configurations(
                "clip.mov", [], explicit_dir, source_dir)
            self.assertEqual(
                merged_mov["upload"]["content"]["description"], "mov-sidecar")

            yaml_path = root / "jobs.yaml"
            yaml_path.write_text(
                "- general:\n    source: clip.mp4\n  upload:\n    skip: true\n",
                encoding="utf-8")
            self.assertEqual(load_job_records(yaml_path)[0]["upload"]["skip"], True)

    def test_sidecars_reject_multiple_records_for_the_same_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            for filename in ("first.yml", "second.yaml"):
                (config_dir / filename).write_text(
                    "general:\n  source: clip.mp4\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Multiple job sidecars.*clip.mp4"):
                merge_source_configurations("clip.mp4", [], config_dir, config_dir)

    def test_source_discovery_is_root_only_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "z.MP4").write_bytes(b"z")
            (root / "A.mov").write_bytes(b"a")
            (root / "notes.txt").write_text("ignored", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "hidden.mp4").write_bytes(b"hidden")

            self.assertEqual(discover_source_names(root), ["A.mov", "z.MP4"])

    def test_fanout_reports_unsupported_files_and_duplicate_source_selections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            (source_dir / "clip.mp4").write_bytes(b"clip")
            (source_dir / "notes.txt").write_text("not media", encoding="utf-8")
            service = JobService(data_dir)
            try:
                result = service.create_jobs(dry_run=True)
                self.assertEqual(len(result["created"]), 1)
                self.assertEqual(result["skipped"][0]["code"], "unsupported_extension")

                duplicate = service.create_jobs(
                    source_names=["clip.mp4", "clip.mp4"], dry_run=True)
                self.assertEqual(len(duplicate["created"]), 1)
                self.assertEqual(duplicate["skipped"][0]["code"], "duplicate_source")
            finally:
                service.close()

    def test_duplicate_config_records_are_reported_instead_of_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "sources"
            source_dir.mkdir()
            (source_dir / "clip.mp4").write_bytes(b"clip")
            service = JobService(root)
            try:
                result = service.create_jobs(
                    job_configs=[
                        {"general": {"source": "clip.mp4"},
                         "upload": {"content": {"title": "First"}}},
                        {"general": {"source": "clip.mp4"},
                         "upload": {"content": {"title": "Second"}}},
                    ],
                    dry_run=True)
                self.assertEqual(len(result["created"]), 1)
                self.assertEqual(len(result["skipped"]), 1)
                self.assertEqual(result["skipped"][0]["code"], "duplicate_source")
                self.assertEqual(result["skipped"][0]["record_index"], 2)
                self.assertEqual(
                    result["effective_configurations"][0]["configuration"]
                    ["upload"]["content"]["title"], "First")
            finally:
                service.close()


class ManifestPersistenceTests(unittest.TestCase):
    def test_manifest_persists_final_job_yaml_defaults_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "clip.mp4"
            source.write_bytes(b"video")
            jobs_dir = Path(temp_dir) / "jobs"
            defaults = {"general": {"clean": False}}
            configuration = resolve_job_configuration(
                defaults, {"general": {"source": source.name}})

            manifest = JobManifest.create(
                str(source), configuration, jobs_dir, global_defaults=defaults)

            job_directory = jobs_dir / manifest.job_id
            self.assertEqual(manifest.schema_version, MANIFEST_SCHEMA_VERSION)
            self.assertEqual(
                yaml.safe_load((job_directory / "job.yml").read_text(encoding="utf-8")),
                configuration)
            loaded = JobManifest.load(manifest.job_id, jobs_dir)
            self.assertEqual(loaded.configuration_sources["global_defaults"], defaults)
            self.assertEqual(set(loaded.checkpoints), {"transcript", "conversion", "upload"})
            self.assertIsNotNone(loaded.current_configuration_hash)

    def test_checkpoint_transitions_reject_stale_revisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "clip.mp4"
            source.write_bytes(b"video")
            manifest = JobManifest.create(str(source), {}, temp_dir)

            checkpoint = manifest.transition_checkpoint(
                "transcript", "running", expected_revision=0, jobs_dir=temp_dir)

            self.assertEqual(checkpoint["revision"], 1)
            with self.assertRaisesRegex(ValueError, "stale checkpoint revision"):
                manifest.transition_checkpoint(
                    "transcript", "awaiting_review", expected_revision=0,
                    jobs_dir=temp_dir)

    def test_manifest_load_retries_a_transient_windows_file_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "clip.mp4"
            source.write_bytes(b"video")
            manifest = JobManifest.create(str(source), {}, temp_dir)
            original_open = Path.open
            attempts = 0

            def flaky_open(path, *args, **kwargs):
                nonlocal attempts
                if path.name == "manifest.json" and attempts == 0:
                    attempts += 1
                    raise PermissionError("transient replacement lock")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", flaky_open):
                loaded = JobManifest.load(manifest.job_id, temp_dir)
            self.assertEqual(loaded.job_id, manifest.job_id)
            self.assertEqual(attempts, 1)


class JobServiceConfigurationTests(unittest.TestCase):
    def test_service_resolves_app_defaults_and_persists_only_effective_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            sources_dir = data_dir / "sources"
            sources_dir.mkdir()
            source = sources_dir / "First.clip.mp4"
            source.write_bytes(b"video")
            save_app_configuration(data_dir / "app.yml", {
                "source_dir": "sources",
                "job_defaults": {
                    "general": {"source": None, "clean": True},
                    "upload": {"content": {"title": ""}},
                },
            })
            service = JobService(data_dir)
            try:
                manifest = service.create_job(
                    "First.clip.mp4", {"general": {"source": "First.clip.mp4"}})
                self.assertEqual(
                    manifest.configuration["upload"]["content"]["title"],
                    "First.clip")
                self.assertTrue(manifest.configuration["general"]["clean"])
                self.assertEqual(
                    manifest.configuration_sources["global_defaults"]["general"]["clean"],
                    True)
                self.assertNotIn("overrides", manifest.__dict__)
            finally:
                service.close()

    def test_workflow_stops_at_upload_review_and_never_uploads_automatically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
            })
            fake_runner = type("FakeRunner", (), {
                "get_video_info": lambda _self, _path: {
                    "format": {"duration": "3"},
                    "streams": [{"codec_type": "video", "width": 1920,
                                 "height": 1080}],
                },
            })()
            try:
                with patch("clipmorph.workflow.configure_ffmpeg"), \
                        patch("clipmorph.workflow.FFmpegRunner", return_value=fake_runner), \
                        patch("clipmorph.upload_pipeline.UploadPipeline") as upload:
                    execute_job(manifest, CancellationToken(), service.jobs_dir)

                saved = service.get_job(manifest.job_id)
                self.assertEqual(saved.checkpoints["transcript"]["status"], "skipped")
                self.assertEqual(saved.checkpoints["conversion"]["status"], "skipped")
                self.assertEqual(saved.checkpoints["upload"]["status"], "awaiting_review")
                self.assertEqual(saved.artifacts[saved.current_artifact_id]["kind"], "source")
                upload.assert_not_called()
            finally:
                service.close()

    def test_workflow_uses_the_selected_app_config_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "media"
            source_dir.mkdir()
            source = source_dir / "clip.mp4"
            source.write_bytes(b"video")
            output_root = root / "renders"
            app_path = root / "custom-app.yml"
            save_app_configuration(app_path, {
                "source_dir": str(source_dir),
                "output_dir": str(output_root),
                "job_defaults": {
                    "conversion": {"skip": True, "subtitles": {"skip": True}},
                    "upload": {"skip": True},
                },
            })
            service = JobService(root / "data", app_config_path=app_path)
            fake_runner = type("FakeRunner", (), {
                "get_video_info": lambda _self, _path: {
                    "format": {"duration": "3"},
                    "streams": [{"codec_type": "video", "width": 1920,
                                 "height": 1080}],
                },
            })()
            try:
                manifest = service.create_job(source.name, {})
                with patch("clipmorph.workflow.configure_ffmpeg"), \
                        patch("clipmorph.workflow.FFmpegRunner", return_value=fake_runner), \
                        patch("clipmorph.workflow.PreflightValidator") as preflight:
                    execute_job(manifest, CancellationToken(), service.jobs_dir, app_path)
                self.assertEqual(
                    preflight.return_value.validate.call_args.kwargs["output_dir"],
                    str(output_root / manifest.job_id))
            finally:
                service.close()

    def test_runner_returning_at_review_keeps_job_awaiting_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)

            def pause_for_review(job, _token):
                job.transition_checkpoint("transcript", "running", 0, service.jobs_dir)
                job.transition_checkpoint("transcript", "awaiting_review", 1,
                                           service.jobs_dir)

            try:
                manifest = service.create_job(source.name, {}, pause_for_review)
                service._futures[manifest.job_id].result(timeout=2)
                saved = service.get_job(manifest.job_id)
                self.assertEqual(saved.status, "awaiting_review")
                self.assertEqual(saved.current_checkpoint, "transcript")
            finally:
                service.close()

    def test_runner_observes_checkpoint_changes_persisted_by_nested_service(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)

            def nested_update(job, _token):
                persisted = JobManifest.load(job.job_id, service.jobs_dir)
                persisted.transition_checkpoint(
                    "transcript", "running", 0, service.jobs_dir)
                persisted.transition_checkpoint(
                    "transcript", "awaiting_review", 1, service.jobs_dir)

            try:
                manifest = service.create_job(source.name, {}, nested_update)
                service._futures[manifest.job_id].result(timeout=2)
                saved = service.get_job(manifest.job_id)
                self.assertEqual(saved.checkpoints["transcript"]["status"], "awaiting_review")
                self.assertEqual(saved.status, "awaiting_review")
            finally:
                service.close()

    def test_created_job_without_a_runner_is_resumable(self):
        """A plain creation (no `--yes`) must remain actionable.

        The job stays `created`; `job resume` accepts that status and runs the
        pipeline from the first checkpoint.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)

            def pause_for_review(job, _token):
                job.transition_checkpoint("transcript", "running", 0,
                                          service.jobs_dir)
                job.transition_checkpoint("transcript", "awaiting_review", 1,
                                          service.jobs_dir)

            try:
                created = service.create_job(source.name, {})
                self.assertEqual(created.status, "created")
                resumed = service.resume_job(created.job_id, pause_for_review)
                service._futures[resumed.job_id].result(timeout=2)
                saved = service.get_job(created.job_id)
                self.assertEqual(saved.status, "awaiting_review")
            finally:
                service.close()

    def test_transcript_stage_survives_its_own_session_service(self):
        """A live job must survive the service construction its worker makes.

        ``execute_job`` saves the transcript session through a nested
        ``JobService``; before the nested service skipped the restart-boundary
        scans, that construction reconciled the caller's own running job as
        "interrupted by restart", so the save hit "stale checkpoint revision"
        and the job failed right after a clean transcription.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            fake_runner = type("FakeRunner", (), {
                "extract_audio": lambda _self, _path: "audio.wav",
                "get_video_info": lambda _self, _path: {
                    "format": {"duration": "3"},
                    "streams": [{"codec_type": "video", "width": 1920,
                                 "height": 1080}],
                },
            })()
            # WhisperX emits numpy timestamps; the session save must coerce
            # them before the manifest's YAML dump sees one.
            fake_pipeline = type("FakePipeline", (), {
                "run": lambda self: [{"start": np.float64(0), "end": np.float64(1),
                                      "text": "Hello there"}],
            })()

            try:
                with patch("clipmorph.workflow.configure_ffmpeg"), \
                        patch("clipmorph.workflow.FFmpegRunner",
                              return_value=fake_runner), \
                        patch("clipmorph.conversion_pipeline.transcribe"
                              ".TranscriptionPipeline",
                              return_value=fake_pipeline):
                    manifest = service.create_job(
                        source.name, {},
                        lambda job, token: execute_job(
                            job, token, service.jobs_dir,
                            service.app_config_path))
                    service._futures[manifest.job_id].result(timeout=30)

                saved = service.get_job(manifest.job_id)
                self.assertEqual(saved.status, "awaiting_review")
                self.assertEqual(saved.current_checkpoint, "transcript")
                self.assertEqual(
                    saved.checkpoints["transcript"]["status"], "awaiting_review")
                self.assertIsNone(
                    saved.checkpoints["transcript"]["error"])
                self.assertEqual(saved.active_transcript["revision"], 1)
            finally:
                service.close()

    def test_runner_failures_are_structured_safe_and_checkpointed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(
                    source.name, {},
                    lambda _job, _token: (_ for _ in ()).throw(
                        RuntimeError("client_secret=do-not-persist")))
                service._futures[manifest.job_id].result(timeout=2)
                saved = service.get_job(manifest.job_id)
                self.assertEqual(saved.checkpoints["transcript"]["status"], "failed")
                self.assertEqual(saved.errors[0]["code"], "execution_failed")
                self.assertNotIn("do-not-persist", json.dumps(saved.errors))
            finally:
                service.close()

    def test_cancel_marks_the_current_checkpoint_cancelled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {})
                cancelled = service.cancel_job(manifest.job_id)
                self.assertEqual(cancelled.checkpoints["transcript"]["status"], "cancelled")
                self.assertEqual(cancelled.current_checkpoint, "transcript")
            finally:
                service.close()


class JobServiceRevisionTests(unittest.TestCase):
    def test_resume_rejects_jobs_waiting_for_checkpoint_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            source = source_dir / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = JobManifest.create(str(source), {}, service.jobs_dir)
                checkpoint = manifest.checkpoints["transcript"]
                checkpoint = manifest.transition_checkpoint(
                    "transcript", "running", checkpoint["revision"], service.jobs_dir)
                manifest.transition_checkpoint(
                    "transcript", "awaiting_review", checkpoint["revision"],
                    service.jobs_dir)

                with self.assertRaisesRegex(ValueError, "requires review"):
                    service.resume_job(manifest.job_id, lambda _job, _token: None)
            finally:
                service.close()

    def test_transcript_edits_write_immutable_revisions_and_invalidate_downstream(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {})
                session = create_edit_session(manifest.source_sha256, [{
                    "start": 0, "end": 1, "text": "Original",
                }], 2)
                first = service.save_transcript_session(
                    manifest.job_id, session, expected_revision=0)
                edited = dict(first)
                edited["segments"] = [dict(first["segments"][0], text="Edited")]
                second = service.save_transcript_session(
                    manifest.job_id, edited, expected_revision=1)

                job_directory = data_dir / "jobs" / manifest.job_id
                first_path = job_directory / "transcripts" / "revision-0001.json"
                second_path = job_directory / "transcripts" / "revision-0002.json"
                self.assertEqual(first_path.exists(), True)
                self.assertEqual(second_path.exists(), True)
                self.assertEqual(
                    json.loads(first_path.read_text(encoding="utf-8"))["segments"][0]["text"],
                    "Original")
                self.assertEqual(second["segments"][0]["text"], "Edited")
                saved = service.get_job(manifest.job_id)
                self.assertEqual(saved.active_transcript["revision"], 2)
                self.assertEqual(saved.checkpoints["conversion"]["status"], "stale")
                self.assertEqual(saved.checkpoints["upload"]["status"], "stale")
            finally:
                service.close()

    def test_upload_draft_edit_changes_only_upload_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {})
                updated = service.update_upload_draft(
                    manifest.job_id,
                    {"content": {"title": "Reviewed title"}},
                    expected_revision=0)

                self.assertEqual(
                    updated.configuration["upload"]["content"]["title"],
                    "Reviewed title")
                self.assertEqual(updated.checkpoints["transcript"]["revision"], 0)
                self.assertEqual(updated.checkpoints["conversion"]["revision"], 0)
                self.assertEqual(updated.checkpoints["upload"]["status"], "awaiting_review")
                with self.assertRaisesRegex(ValueError, "stale checkpoint revision"):
                    service.update_upload_draft(
                        manifest.job_id, {}, expected_revision=0)
            finally:
                service.close()

    def test_upload_attempt_freezes_settings_and_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            artifact = data_dir / "render.mp4"
            artifact.write_bytes(b"artifact revision one")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {
                    "conversion": {"skip": True, "subtitles": {"skip": True}},
                    "upload": {"skip": True},
                    "platforms": {"youtube": {"upload": {"skip": False}}},
                })
                service.get_job(manifest.job_id).set_artifact(
                    str(artifact), service.jobs_dir)
                manifest = service.get_job(manifest.job_id)
                manifest = service.update_upload_draft(
                    manifest.job_id, {"content": {"title": "Frozen title"}},
                    manifest.checkpoints["upload"]["revision"])
                with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline_type:
                    pipeline_type.return_value.run.return_value = {
                        "YouTube": {"success": False, "error": "temporary failure"}
                    }
                    result = service.submit_upload(manifest.job_id)
                    service._futures[f"upload:{manifest.job_id}"].result(timeout=2)

                saved = service.get_job(manifest.job_id)
                attempt = saved.upload_attempts[0]
                self.assertEqual(result["attempts"][0]["platform"], "youtube")
                self.assertEqual(attempt["configuration_snapshot"]["content"]["title"],
                                 "Frozen title")
                self.assertEqual(attempt["artifact_id"], saved.current_artifact_id)
                self.assertEqual(attempt["status"], "failed")
                self.assertEqual(saved.checkpoints["upload"]["status"], "failed")
            finally:
                service.close()

    def test_retry_only_retries_failed_platform_with_confirmed_historical_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            source = source_dir / "clip.mp4"
            source.write_bytes(b"source")
            artifacts_dir = data_dir / "output"
            artifacts_dir.mkdir()
            first_artifact = artifacts_dir / "revision-1.mp4"
            first_artifact.write_bytes(b"first revision")
            second_artifact = artifacts_dir / "revision-2.mp4"
            second_artifact.write_bytes(b"second revision")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {
                    "conversion": {"skip": True, "subtitles": {"skip": True}},
                    "upload": {"skip": True},
                    "platforms": {
                        "youtube": {"upload": {"skip": False}},
                        "tiktok": {"upload": {"skip": False}},
                    },
                })
                manifest.set_artifact(str(first_artifact), service.jobs_dir)
                manifest = service.update_upload_draft(
                    manifest.job_id,
                    {"content": {"title": "Frozen title"}},
                    manifest.checkpoints["upload"]["revision"])

                with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline_type:
                    pipeline_type.return_value.run.side_effect = [
                        {
                            "YouTube": {"success": False, "error": "temporary"},
                            "TikTok": {"success": True, "result": "posted"},
                        },
                        {"YouTube": {"success": True, "result": "retried"}},
                    ]
                    service.submit_upload(manifest.job_id)
                    service._futures[f"upload:{manifest.job_id}"].result(timeout=2)
                    first_attempt = service.get_job(manifest.job_id).upload_attempts[0]

                    service.get_job(manifest.job_id).set_artifact(
                        str(second_artifact), service.jobs_dir)
                    with self.assertRaisesRegex(ValueError, "historical artifact"):
                        service.retry_upload(
                            manifest.job_id, "youtube", first_attempt["attempt_id"])

                    retry = service.retry_upload(
                        manifest.job_id, "youtube", first_attempt["attempt_id"],
                        artifact_id=first_attempt["artifact_id"],
                        confirm_historical_artifact=True)
                    service._futures[f"upload:{manifest.job_id}"].result(timeout=2)

                self.assertEqual(len(retry["attempts"]), 1)
                self.assertEqual(retry["attempts"][0]["platform"], "youtube")
                saved = service.get_job(manifest.job_id)
                self.assertEqual(len(saved.upload_attempts), 3)
                self.assertEqual(saved.upload_attempts[0]["platform"], "youtube")
                self.assertEqual(saved.upload_attempts[1]["platform"], "tiktok")
                self.assertEqual(saved.upload_attempts[2]["platform"], "youtube")
                self.assertEqual(saved.upload_attempts[2]["artifact_id"],
                                 first_attempt["artifact_id"])
                self.assertEqual(saved.upload_attempts[2]["artifact_hash"],
                                 first_attempt["artifact_hash"])
                self.assertEqual(
                    saved.upload_attempts[2]["configuration_snapshot"]["content"]["title"],
                    "Frozen title")
                self.assertTrue(saved.platforms["tiktok"]["success"])
            finally:
                service.close()

    def test_upload_rejects_artifact_bytes_that_no_longer_match_manifest_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            artifact = data_dir / "output.mp4"
            artifact.write_bytes(b"original bytes")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {
                    "conversion": {"skip": True, "subtitles": {"skip": True}},
                    "upload": {"skip": True},
                    "platforms": {"youtube": {"upload": {"skip": False}}},
                })
                manifest.set_artifact(str(artifact), service.jobs_dir)
                manifest = service.update_upload_draft(
                    manifest.job_id, {"content": {"title": "Clip"}}, 0)
                artifact.write_bytes(b"modified bytes")
                with patch("clipmorph.upload_pipeline.UploadPipeline") as uploader:
                    with self.assertRaisesRegex(ValueError, "hash"):
                        service.submit_upload(manifest.job_id)
                    uploader.assert_not_called()
            finally:
                service.close()

    def test_configuration_updates_require_current_hash_and_reopen_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {})
                with self.assertRaisesRegex(ValueError, "stale configuration hash"):
                    service.update_job_configuration(
                        manifest.job_id, {"upload": {"content": {"title": "New"}}},
                        expected_configuration_hash="wrong")
                manifest = service.get_job(manifest.job_id)
                manifest.set_status("completed", service.jobs_dir)
                with self.assertRaisesRegex(ValueError, "reopen"):
                    service.update_job_configuration(
                        manifest.job_id, {"upload": {"content": {"title": "New"}}},
                        expected_configuration_hash=manifest.current_configuration_hash)
            finally:
                service.close()

    def test_only_conversion_dependency_changes_stale_current_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            artifact = data_dir / "render.mp4"
            artifact.write_bytes(b"render")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {})
                manifest.set_artifact(str(artifact), service.jobs_dir)
                manifest = service.get_job(manifest.job_id)
                updated = service.update_job_configuration(
                    manifest.job_id, {"upload": {"content": {"title": "New"}}},
                    manifest.current_configuration_hash)
                self.assertEqual(
                    updated.artifacts[updated.current_artifact_id]["state"], "current")
                updated = service.update_job_configuration(
                    manifest.job_id, {"conversion": {"strict": True}},
                    updated.current_configuration_hash)
                self.assertEqual(
                    updated.artifacts[updated.current_artifact_id]["state"], "stale")
                self.assertEqual(updated.checkpoints["conversion"]["status"], "stale")
            finally:
                service.close()

    def test_platform_conversion_edit_re_derives_only_the_changed_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            first = data_dir / "first.mp4"
            first.write_bytes(b"first render")
            second = data_dir / "second.mp4"
            second.write_bytes(b"second render")
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {
                    "conversion": {"skip": False, "subtitles": {"skip": True}},
                    "platforms": {
                        "youtube": {"conversion": {"strict": True}},
                        "tiktok": {"conversion": {"strict": True}},
                    },
                })
                groups = manifest.checkpoints["conversion"]["groups"]
                self.assertEqual(len(groups), 2)
                # Render both groups, the way the workflow does.
                for index, group_id in enumerate(groups):
                    group = groups[group_id]
                    manifest.transition_checkpoint(
                        "conversion", "running", group["revision"],
                        service.jobs_dir, group_id=group_id)
                    manifest.record_artifact(
                        "conversion", first if index == 0 else second,
                        service.jobs_dir, group_id=group_id)
                    manifest = service.get_job(manifest.job_id)
                    group = manifest.checkpoints["conversion"]["groups"][group_id]
                    manifest.transition_checkpoint(
                        "conversion", "completed", group["revision"],
                        service.jobs_dir, group_id=group_id)
                kept = next(group_id for group_id, group in
                            manifest.checkpoints["conversion"]["groups"].items()
                            if "tiktok" in group["platforms"])
                kept_artifact = manifest.checkpoints["conversion"]["groups"][
                    kept]["current_artifact_id"]
                kept_state = manifest.artifacts[kept_artifact]["state"]
                unchanged = next(group_id for group_id, group in
                                 manifest.checkpoints["conversion"]["groups"].items()
                                 if "instagram" in group["platforms"])
                unchanged_artifact = manifest.checkpoints["conversion"]["groups"][
                    unchanged]["current_artifact_id"]
                unchanged_state = manifest.artifacts[unchanged_artifact]["state"]

                updated = service.update_job_configuration(
                    manifest.job_id,
                    {"platforms": {"tiktok": {"conversion": {"strict": False}}}},
                    manifest.current_configuration_hash)

                derived = {group["id"] for group in conversion_groups(
                    updated.configuration)}
                stored = updated.checkpoints["conversion"]["groups"]
                self.assertEqual(set(stored), derived)
                # YouTube keeps the group it already rendered: the override
                # that moved is TikTok's, and its digest is unchanged, so the
                # record, its status and its artifact all survive.
                self.assertEqual(stored[kept]["platforms"], ["youtube"])
                self.assertEqual(stored[kept]["status"], "completed")
                self.assertEqual(stored[kept]["current_artifact_id"],
                                 kept_artifact)
                self.assertEqual(updated.artifacts[kept_artifact]["state"],
                                 kept_state)
                # The group that did not move keeps its artifact's state too:
                # the aggregate invalidation must not stale it.
                self.assertEqual(updated.artifacts[unchanged_artifact]["state"],
                                 unchanged_state)
                # TikTok's new digest is a new group, and the conversion stage
                # is stale so exactly that group re-renders.
                fresh = next(group for group_id, group in stored.items()
                             if group_id != kept)
                # TikTok now resolves to the group the other two platforms
                # already rendered, so that group simply gains a member and
                # keeps its completed render.
                self.assertEqual(fresh["platforms"],
                                 ["instagram", "tiktok", "twitter", "facebook"])
                self.assertEqual(fresh["status"], "completed")
                self.assertIsNotNone(fresh["current_artifact_id"])
                self.assertEqual(updated.checkpoints["conversion"]["status"],
                                 "stale")
                self.assertEqual(updated.checkpoints["upload"]["status"],
                                 "stale")
            finally:
                service.close()

    def test_render_loop_completes_a_stage_no_group_still_needs(self):
        # A configuration edit can re-point platforms onto groups that are
        # already rendered: the stage is invalidated but nothing is left to
        # render, and the aggregate must not stay stuck at ``stale``.
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            rendered = data_dir / "render.mp4"
            rendered.write_bytes(b"render")
            service = JobService(data_dir)
            fake_runner = type("FakeRunner", (), {
                "get_video_info": lambda _self, _path: {
                    "format": {"duration": "3"},
                    "streams": [{"codec_type": "video", "width": 1920,
                                 "height": 1080}],
                },
            })()
            try:
                manifest = service.create_job(source.name, {
                    "conversion": {"skip": False, "subtitles": {"skip": True}},
                    "platforms": {
                        "youtube": {"conversion": {"strict": True}},
                    },
                })
                pipeline = type("FakePipeline", (), {
                    "__init__": lambda self, **kwargs: None,
                    "run": lambda self: str(rendered),
                })()
                with patch("clipmorph.workflow.configure_ffmpeg"), \
                        patch("clipmorph.workflow.FFmpegRunner", return_value=fake_runner), \
                        patch("clipmorph.workflow.PreflightValidator"), \
                        patch("clipmorph.conversion_pipeline.ConversionPipeline",
                              return_value=pipeline):
                    execute_job(manifest, CancellationToken(), service.jobs_dir)
                manifest = service.get_job(manifest.job_id)
                manifest = service.accept_checkpoint(
                    manifest.job_id, "conversion",
                    manifest.checkpoints["conversion"]["revision"])
                self.assertEqual(manifest.checkpoints["conversion"]["status"],
                                 "completed")
                # Move TikTok onto the already-rendered default group: the
                # stage is invalidated but no group is left to render.
                manifest = service.update_job_configuration(
                    manifest.job_id,
                    {"platforms": {"tiktok": {"conversion": {"strict": True}}}},
                    manifest.current_configuration_hash)
                self.assertEqual(manifest.checkpoints["conversion"]["status"],
                                 "stale")
                with patch("clipmorph.workflow.configure_ffmpeg"), \
                        patch("clipmorph.workflow.FFmpegRunner", return_value=fake_runner), \
                        patch("clipmorph.workflow.PreflightValidator"):
                    execute_job(manifest, CancellationToken(), service.jobs_dir)
                saved = service.get_job(manifest.job_id)
                self.assertEqual(saved.checkpoints["conversion"]["status"],
                                 "completed")
                self.assertEqual(saved.errors, [])
            finally:
                service.close()

    def test_workflow_renders_the_render_group_and_binds_the_skip_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            rendered = data_dir / "render.mp4"
            rendered.write_bytes(b"render")
            service = JobService(data_dir)
            fake_runner = type("FakeRunner", (), {
                "get_video_info": lambda _self, _path: {
                    "format": {"duration": "3"},
                    "streams": [{"codec_type": "video", "width": 1920,
                                 "height": 1080}],
                },
            })()
            try:
                manifest = service.create_job(source.name, {
                    "conversion": {"skip": False, "subtitles": {"skip": True}},
                    "platforms": {
                        "youtube": {"conversion": {"skip": True}},
                        "tiktok": {"conversion": {"strict": True}},
                    },
                })
                pipeline = type("FakePipeline", (), {
                    "__init__": lambda self, **kwargs: None,
                    "run": lambda self: str(rendered),
                })()
                with patch("clipmorph.workflow.configure_ffmpeg"), \
                        patch("clipmorph.workflow.FFmpegRunner", return_value=fake_runner), \
                        patch("clipmorph.workflow.PreflightValidator"), \
                        patch("clipmorph.conversion_pipeline.ConversionPipeline",
                              return_value=pipeline):
                    execute_job(manifest, CancellationToken(), service.jobs_dir)

                saved = service.get_job(manifest.job_id)
                groups = saved.checkpoints["conversion"]["groups"]
                # youtube skips, tiktok renders, and the two platforms without a
                # conversion override share the job-level render group.
                self.assertEqual(len(groups), 3)
                skipped = next(group for group in groups.values()
                               if group["platforms"] == ["youtube"])
                rendered_group = next(group for group in groups.values()
                                      if "tiktok" in group["platforms"])
                # The skipping group stays skipped -- ``skipped -> completed``
                # is not a legal transition -- and binds the untouched source.
                self.assertEqual(skipped["status"], "skipped")
                self.assertEqual(
                    saved.artifacts[skipped["current_artifact_id"]]["kind"],
                    "source")
                self.assertEqual(rendered_group["status"], "awaiting_review")
                self.assertEqual(
                    saved.artifacts[rendered_group["current_artifact_id"]]["kind"],
                    "conversion")
                self.assertEqual(saved.checkpoints["conversion"]["status"],
                                 "awaiting_review")
                self.assertEqual(saved.errors, [])
            finally:
                service.close()

    def test_switching_layout_id_discards_previous_materialized_preset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            save_app_configuration(data_dir / "app.yml", {
                "layouts": [
                    {"id": "first", "name": "First", "layout": {
                        "captions": {"overlay": {"items": [{
                            "text": "First preset", "placement": "center",
                        }]}}
                    }},
                    {"id": "second", "name": "Second", "layout": {
                        "captions": {"overlay": {"items": [{
                            "text": "Second preset", "placement": "bottom",
                        }]}}
                    }},
                ],
            })
            service = JobService(data_dir)
            try:
                manifest = service.create_job(source.name, {
                    "conversion": {"layout_id": "first"},
                })
                updated = service.update_job_configuration(
                    manifest.job_id, {"conversion": {"layout_id": "second"}},
                    manifest.current_configuration_hash)
                self.assertEqual(updated.configuration["conversion"]["layout_id"], "second")
                self.assertEqual(
                    updated.configuration["conversion"]["layout"]["captions"][
                        "overlay"]["items"][0]["text"], "Second preset")
            finally:
                service.close()

    def test_multi_source_creation_fans_out_without_group_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            (source_dir / "one.mp4").write_bytes(b"one")
            (source_dir / "two.mp4").write_bytes(b"two")
            service = JobService(data_dir)
            try:
                result = service.create_jobs(
                    job_configs=[{
                        "general": {"source": "one.mp4"},
                        "upload": {"content": {"title": "Configured one"}},
                    }])

                self.assertEqual(result["summary"], {
                    "total": 2, "created": 2, "skipped": 0, "failed": 0})
                manifests = [service.get_job(item["job_id"])
                             for item in result["created"]]
                by_source = {item.configuration["general"]["source"]: item
                             for item in manifests}
                self.assertEqual(
                    by_source["one.mp4"].configuration["upload"]["content"]["title"],
                    "Configured one")
                self.assertEqual(
                    by_source["two.mp4"].configuration["upload"]["content"]["title"],
                    "two")
                self.assertFalse((data_dir / "batches").exists())
            finally:
                service.close()

    def test_multi_source_creation_reports_duplicate_content_and_continues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            (source_dir / "a.mp4").write_bytes(b"same")
            (source_dir / "b.mp4").write_bytes(b"same")
            (source_dir / "c.mp4").write_bytes(b"different")
            service = JobService(data_dir)
            try:
                result = service.create_jobs()
                self.assertEqual(len(result["created"]), 2)
                self.assertEqual(len(result["skipped"]), 1)
                self.assertEqual(result["skipped"][0]["code"], "duplicate_content")
            finally:
                service.close()

    def test_creation_overrides_beat_sidecars_and_job_records(self):
        """`--yes` (`general.no_confirm = true`) is an explicit CLI override.

        It must inject the flag into every created job's effective
        configuration and win over a sidecar and a job record that both set
        `no_confirm: false`.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            (source_dir / "one.mp4").write_bytes(b"one")
            service = JobService(data_dir)
            sidecar = source_dir / "one.yml"
            sidecar.write_text(yaml.safe_dump({
                "general": {"source": "one.mp4", "no_confirm": False},
            }), encoding="utf-8")
            try:
                result = service.create_jobs(
                    job_configs=[{"general": {"source": "one.mp4",
                                              "no_confirm": False}}],
                    confirmed=True)

                manifest = service.get_job(result["created"][0]["job_id"])
                self.assertTrue(manifest.configuration["general"]["no_confirm"])
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()