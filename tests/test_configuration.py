import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from clipmorph.configuration import load_app_configuration
from clipmorph.configuration import load_job_records
from clipmorph.configuration import merge_source_configurations
from clipmorph.configuration import merge_configuration
from clipmorph.configuration import resolve_job_configuration
from clipmorph.configuration import save_app_configuration
from clipmorph.configuration import discover_source_names
from clipmorph.job import JobManifest
from clipmorph.service import JobService
from clipmorph.service import CancellationToken
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
        ]
        for configuration in invalid:
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(ValueError, "Unknown|unsupported"):
                    resolve_job_configuration({}, configuration)

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

    def test_app_configuration_rejects_unknown_top_level_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.yml"
            path.write_text("legacy_config: true\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unknown app configuration"):
                load_app_configuration(path)

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
            self.assertEqual(manifest.schema_version, 2)
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
                    "upload": {"platforms": {"include": ["youtube"]}},
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
                    "upload": {"platforms": {"include": ["youtube", "tiktok"]}},
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
                    "upload": {"platforms": {"include": ["youtube"]}},
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


if __name__ == "__main__":
    unittest.main()