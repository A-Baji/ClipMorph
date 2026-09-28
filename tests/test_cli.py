"""CLI behavior: exit codes, human rendering, and the ``--json`` escape hatch.

Every case calls ``run_cli([...])`` with an explicit argument list so the
tests exercise the same public entry point as the console script without
patching ``sys.argv``.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.cli import run_cli
from clipmorph.configuration import save_app_configuration
from clipmorph.job import JobManifest
from clipmorph.service import JobService

# rich reads COLUMNS when stdout is not a terminal, so table assertions can
# pin a wide-enough layout instead of depending on the 80-column default.
WIDE_TERMINAL = {"COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1"}


def invoke(argv):
    """Run one command, returning ``(exit code, stdout)``."""
    output = io.StringIO()
    with patch.dict(os.environ, WIDE_TERMINAL), contextlib.redirect_stdout(output):
        code = run_cli(list(argv))
    return code, output.getvalue()


def invoke_json(argv):
    """Run one command and parse its ``--json`` payload."""
    code, output = invoke([*argv, "--json"])
    return code, json.loads(output)


def seed_job(data_dir, source_name="clip.mp4", configuration=None):
    """Create one job directly through the service, without the workflow."""
    source_dir = data_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    (source_dir / source_name).write_bytes(b"video")
    service = JobService(data_dir)
    try:
        return service.create_job(source_name, configuration or {})
    finally:
        service.close()



def save_manifest_fields(data_dir, job_id, **fields):
    """Persist extra manifest fields created outside the normal lifecycle."""
    path = data_dir / "jobs" / job_id / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(fields)
    path.write_text(json.dumps(value), encoding="utf-8")


class CliInitializationTests(unittest.TestCase):
    def test_init_writes_app_yaml_and_auth_in_selected_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            result, _ = invoke(["--data-dir", str(data_dir), "init"])

            self.assertEqual(result, 0)
            self.assertTrue((data_dir / "app.yml").exists())
            self.assertTrue((data_dir / "auth.yaml").exists())
            self.assertFalse((data_dir / "clipmorph.yaml").exists())

    def test_init_config_path_writes_adjacent_auth_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yml"

            result, _ = invoke(["init", "--config-path", str(config_path)])

            self.assertEqual(result, 0)
            self.assertTrue(config_path.exists())
            self.assertTrue((Path(temp_dir) / "auth.yaml").exists())

    def test_init_does_not_replace_existing_app_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yml"
            config_path.write_text("existing: true\n", encoding="utf-8")

            result, _ = invoke(["init", "--config-path", str(config_path)])

            self.assertEqual(result, 0)
            self.assertEqual(config_path.read_text(encoding="utf-8"), "existing: true\n")


class CliDataDirectoryTests(unittest.TestCase):
    def test_data_dir_is_accepted_before_and_after_the_subcommand(self):
        for argv in (["--data-dir", "{data}", "job", "list"],
                     ["job", "list", "--data-dir", "{data}"]):
            with self.subTest(argv=argv):
                with tempfile.TemporaryDirectory() as temp_dir:
                    data_dir = Path(temp_dir) / "data"
                    (data_dir / "sources").mkdir(parents=True)
                    seed_job(data_dir)

                    code, records = invoke_json(
                        [part.format(data=str(data_dir)) for part in argv])

                    self.assertEqual(code, 0)
                    self.assertEqual(len(records), 1)
                    self.assertTrue((data_dir / "jobs").is_dir())

    def test_data_dir_on_the_command_wins_over_the_global_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            global_dir = Path(temp_dir) / "global"
            command_dir = Path(temp_dir) / "command"
            for data_dir in (global_dir, command_dir):
                (data_dir / "sources").mkdir(parents=True)
                seed_job(data_dir)
            command_job = JobManifest.load(
                next((command_dir / "jobs").glob("*/manifest.json")).parent.name,
                str(command_dir / "jobs"))
            global_job = JobManifest.load(
                next((global_dir / "jobs").glob("*/manifest.json")).parent.name,
                str(global_dir / "jobs"))

            code, records = invoke_json(["--data-dir", str(global_dir), "job",
                                         "list", "--data-dir", str(command_dir)])

            self.assertEqual(code, 0)
            self.assertEqual([record["job_id"] for record in records],
                             [command_job.job_id])
            self.assertNotIn(global_job.job_id, [record["job_id"] for record in records])


class CliExitCodeTests(unittest.TestCase):
    def test_missing_command_is_a_usage_error(self):
        self.assertEqual(invoke([])[0], 2)
        self.assertEqual(invoke(["job"])[0], 2)

    def test_unknown_option_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)

            result, _ = invoke(["--data-dir", str(data_dir), "job", "list", "--nope"])

            self.assertEqual(result, 2)

    def test_invalid_checkpoint_choice_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)

            result, _ = invoke(["--data-dir", str(data_dir), "job", "review",
                                manifest.job_id, "nope"])

            self.assertEqual(result, 2)

    def test_missing_configuration_input_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)

            result, _ = invoke(["--data-dir", str(data_dir), "job", "update",
                                manifest.job_id])

            self.assertEqual(result, 2)

    def test_missing_job_is_a_runtime_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir(parents=True)

            result, _ = invoke(["--data-dir", str(data_dir), "job", "get", "absent"])

            self.assertEqual(result, 1)

    def test_confirmation_gated_command_without_yes_is_a_configuration_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)

            result, _ = invoke(["--data-dir", str(data_dir), "job", "delete",
                                manifest.job_id])

            self.assertEqual(result, 2)
            self.assertTrue(JobManifest.load(manifest.job_id, data_dir / "jobs"))

    def test_upload_without_a_job_id_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir(parents=True)

            result, _ = invoke(["--data-dir", str(data_dir), "job", "upload"])

            self.assertEqual(result, 2)


class CliHumanOutputTests(unittest.TestCase):
    def test_job_list_renders_one_row_per_job_with_a_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)

            code, output = invoke(["--data-dir", str(data_dir), "job", "list"])

            self.assertEqual(code, 0)
            self.assertIn("Jobs", output)
            self.assertIn(manifest.job_id, output)
            self.assertIn("clip.mp4", output)
            self.assertIn("created", output)
            self.assertIn("transcript", output)
            self.assertIn("Status", output)

    def test_job_list_filters_by_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)

            code, output = invoke(["--data-dir", str(data_dir), "job", "list",
                                   "--status", "created"])
            self.assertEqual(code, 0)
            self.assertIn(manifest.job_id, output)

            code, output = invoke(["--data-dir", str(data_dir), "job", "list",
                                   "--status", "failed"])
            self.assertEqual(code, 0)
            self.assertNotIn(manifest.job_id, output)

    def test_empty_job_list_renders_a_table_with_no_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir(parents=True)

            code, output = invoke(["--data-dir", str(data_dir), "job", "list"])

            self.assertEqual(code, 0)
            self.assertIn("Jobs", output)
            self.assertIn("(no entries)", output)

    def test_job_get_renders_record_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)

            code, output = invoke(["--data-dir", str(data_dir), "job", "get",
                                   manifest.job_id])

            self.assertEqual(code, 0)
            self.assertIn(manifest.job_id, output)
            self.assertIn("Checkpoint", output)
            self.assertIn("Platforms", output)

    def test_artifacts_prune_renders_a_summary_without_json_flag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            (source_dir / "clip.mp4").write_bytes(b"video")
            service = JobService(data_dir)
            manifest = service.create_job("clip.mp4", {
                "conversion": {"skip": True, "subtitles": {"skip": True}}})
            jobs_dir = service.jobs_dir
            artifact_dir = data_dir / "output" / manifest.job_id
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "obsolete.mp4").write_bytes(b"0" * 12)
            manifest.record_artifact("primary", artifact_dir / "obsolete.mp4", jobs_dir)
            (artifact_dir / "kept.mp4").write_bytes(b"0" * 5)
            manifest.record_artifact("primary", artifact_dir / "kept.mp4", jobs_dir)
            obsolete_id = next(
                artifact_id for artifact_id, artifact in manifest.artifacts.items()
                if artifact["state"] == "superseded")
            manifest.artifacts[obsolete_id]["superseded_at"] = "2000-01-01T00:00:00+00:00"
            manifest.save(jobs_dir)
            service.close()
            save_app_configuration(
                data_dir / "app.yml", {"retention": {"artifacts": {"max_age_days": 1}}})

            code, output = invoke(["--data-dir", str(data_dir), "job", "artifacts",
                                   "prune", manifest.job_id])

            self.assertEqual(code, 0)
            self.assertIn(obsolete_id, output)
            self.assertIn("12", output)
            self.assertFalse((artifact_dir / "obsolete.mp4").exists())
            saved = JobManifest.load(manifest.job_id, data_dir / "jobs")
            self.assertEqual(saved.artifacts[obsolete_id]["state"], "deleted")
            self.assertTrue(saved.artifact_path.endswith("kept.mp4"))

    def test_layout_list_renders_registry_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            invoke(["--data-dir", str(data_dir), "init"])
            layout_file = Path(temp_dir) / "layout.yml"
            layout_file.write_text(
                "name: Vertical\n"
                "layout:\n"
                "  crop:\n"
                "    enabled: true\n"
                "    source: {x: 0, y: 0, width: 320, height: 240}\n"
                "    sizing: {mode: fit, dimensions: {width: 320, height: 240}}\n"
                "    composition: {mode: overlay, placement: top}\n"
                "  captions:\n"
                "    overlay:\n"
                "      items:\n"
                "        - {text: Hi, placement: bottom, range: [0, 2]}\n",
                encoding="utf-8")

            code, record = invoke_json(["--data-dir", str(data_dir), "layout",
                                        "create", str(layout_file)])
            self.assertEqual(code, 0)
            self.assertEqual(record["name"], "Vertical")

            code, output = invoke(["--data-dir", str(data_dir), "layout", "list"])

            self.assertEqual(code, 0)
            self.assertIn("Layouts", output)
            self.assertIn("Vertical", output)
            self.assertIn("enabled", output)
            self.assertIn("overlay=1 items", output)

            code, output = invoke(["--data-dir", str(data_dir), "layout", "get",
                                   record["id"]])
            self.assertEqual(code, 0)
            self.assertIn(record["id"], output)

    def test_auth_status_renders_configured_platforms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            code, output = invoke(["--data-dir", str(data_dir), "auth", "status"])

            self.assertEqual(code, 0)
            self.assertIn("Credentials", output)
            self.assertIn("youtube", output)

    def test_table_title_keeps_markup_looking_names_literal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            invoke(["--data-dir", str(data_dir), "init"])
            layout_file = Path(temp_dir) / "layout.yml"
            layout_file.write_text(
                "name: '[red]evil[/]'\n"
                "layout:\n"
                "  crop:\n"
                "    enabled: true\n"
                "    source: {x: 0, y: 0, width: 320, height: 240}\n"
                "    sizing: {mode: fit, dimensions: {width: 320, height: 240}}\n"
                "    composition: {mode: overlay, placement: top}\n",
                encoding="utf-8")

            code, record = invoke_json(["--data-dir", str(data_dir), "layout",
                                        "create", str(layout_file)])
            self.assertEqual(code, 0)

            code, output = invoke(["--data-dir", str(data_dir), "layout", "get",
                                   record["id"]])

            self.assertEqual(code, 0)
            # The registry name is user data: its brackets must survive verbatim
            # instead of being read as rich markup.
            self.assertIn("[red]evil[/]", output)

    def test_job_fields_keep_markup_looking_warnings_literal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)
            save_manifest_fields(
                data_dir, manifest.job_id,
                warnings=["[red]watch out[/]"],
                errors=[{"code": "upload_failed", "message": "boom [bold]now[/]"}])

            code, output = invoke(["--data-dir", str(data_dir), "job", "get",
                                   manifest.job_id])

            self.assertEqual(code, 0)
            self.assertIn("[red]watch out[/]", output)
            self.assertIn("boom [bold]now[/]", output)

    def test_human_output_survives_a_locale_that_cannot_encode_the_data(self):
        """Non-encodable titles become escapes instead of a codec crash.

        A cp1252 stdout is the redirected default on Western-locale Windows:
        the old JSON output was ASCII-escaped there, so the human tables have
        to stay equally survivable.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir, source_name="\u65e5\u672c clip.mp4")
            service = JobService(data_dir)
            try:
                fetched = service.get_job(manifest.job_id)
                content = fetched.configuration.setdefault(
                    "upload", {}).setdefault("content", {})
                content["title"] = "\u26a1 kwik \u00fcber \u65e5\u672c"
                fetched.save(service.jobs_dir)
            finally:
                service.close()

            # Feed the CLI a cp1252, strict-encoding stdout through the same
            # redirect mechanism rich honours in production.
            buffer = io.BytesIO()
            stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict",
                                      write_through=True)
            with patch.dict(os.environ, WIDE_TERMINAL), patch("sys.stdout", stream):
                code = run_cli(["--data-dir", str(data_dir), "job", "list"])
            rendered = buffer.getvalue().decode("cp1252")

            self.assertEqual(code, 0)
            self.assertIn(manifest.job_id, rendered)
            # Characters outside cp1252 render as their escapes, not a crash.
            self.assertIn("\\u26a1", rendered)
            self.assertIn("\\u65e5", rendered)


class CliJsonOutputTests(unittest.TestCase):
    def test_job_list_json_is_a_list_of_manifest_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)

            code, records = invoke_json(["--data-dir", str(data_dir), "job", "list"])

            self.assertEqual(code, 0)
            self.assertIsInstance(records, list)
            self.assertEqual(records[0]["job_id"], manifest.job_id)
            self.assertEqual(records[0]["status"], "created")
            self.assertIn("checkpoints", records[0])
            self.assertIn("artifacts", records[0])
            self.assertIn("platforms", records[0])

    def test_job_get_json_is_one_manifest_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)

            code, record = invoke_json(["--data-dir", str(data_dir), "job", "get",
                                        manifest.job_id])

            self.assertEqual(code, 0)
            self.assertIsInstance(record, dict)
            self.assertEqual(record["job_id"], manifest.job_id)

    def test_artifacts_list_json_omits_local_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            (source_dir / "clip.mp4").write_bytes(b"video")
            service = JobService(data_dir)
            manifest = service.create_job("clip.mp4", {
                "conversion": {"skip": True, "subtitles": {"skip": True}}})
            jobs_dir = service.jobs_dir
            artifact_dir = data_dir / "output" / manifest.job_id
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "clip.mp4").write_bytes(b"0" * 4)
            manifest.record_artifact("primary", artifact_dir / "clip.mp4", jobs_dir)
            manifest.save(jobs_dir)
            service.close()

            code, records = invoke_json(["--data-dir", str(data_dir), "job",
                                         "artifacts", "list", manifest.job_id])

            self.assertEqual(code, 0)
            self.assertEqual(len(records), 1)
            self.assertNotIn("path", records[0])
            self.assertIn("id", records[0])
            self.assertIn("state", records[0])

    def test_auth_status_json_is_the_credential_status_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            code, status = invoke_json(["--data-dir", str(data_dir), "auth",
                                        "status"])

            self.assertEqual(code, 0)
            self.assertIsInstance(status, dict)
            self.assertIn("youtube", status)
            self.assertIsInstance(status["youtube"], bool)

    def test_layout_list_json_is_the_registry_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            invoke(["--data-dir", str(data_dir), "init"])

            code, layouts = invoke_json(["--data-dir", str(data_dir), "layout",
                                         "list"])

            self.assertEqual(code, 0)
            self.assertIsInstance(layouts, list)


class JobCommandPersistenceTests(unittest.TestCase):
    def test_cli_data_dir_persists_updated_manifest_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "custom-data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "input.mp4"
            source.write_bytes(b"video")

            with patch("clipmorph.workflow.execute_job"):
                result, _ = invoke(["--data-dir", str(data_dir), "job", "create",
                                    str(source)])

            self.assertEqual(result, 0)
            manifests = list((data_dir / "jobs").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            loaded = JobManifest.load(manifests[0].parent.name, str(data_dir / "jobs"))
            self.assertEqual(loaded.status, "queued")
            self.assertEqual(loaded.configuration["general"]["source"], "input.mp4")


class JobCommandTests(unittest.TestCase):
    def test_job_create_dry_run_uses_service_and_writes_no_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "A clip.mp4").write_bytes(b"video")

            code, output = invoke(["--data-dir", str(data_dir), "job", "create",
                                   str(source_dir), "--dry-run"])

            self.assertEqual(code, 0)
            self.assertFalse((data_dir / "jobs").exists())
            self.assertIn("Sources", output)
            self.assertIn("total: 1", output)
            self.assertIn("failed: 0", output)

    def test_job_create_renders_one_outcome_row_per_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "clip.mp4").write_bytes(b"video")
            (source_dir / "notes.txt").write_bytes(b"text")

            code, result = invoke_json(["--data-dir", str(data_dir), "job",
                                        "create", str(source_dir)])

            self.assertEqual(code, 0)
            self.assertEqual(result["summary"]["created"], 1)
            self.assertEqual(result["summary"]["skipped"], 1)
            self.assertEqual(result["skipped"][0]["code"], "unsupported_extension")

    def test_job_create_fails_with_status_one_when_a_record_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "clip.mp4").write_bytes(b"video")
            records = Path(temp_dir) / "jobs.jsonl"
            records.write_text('{"general": {}}\n', encoding="utf-8")

            code, result = invoke_json(["--data-dir", str(data_dir), "job",
                                        "create", str(source_dir),
                                        "--job-configs", str(records)])

            self.assertEqual(code, 1)
            self.assertEqual(result["summary"]["created"], 1)
            self.assertEqual(result["failed"][0]["code"], "invalid_record")

            code, output = invoke(["--data-dir", str(data_dir), "job", "create",
                                   str(source_dir), "--job-configs", str(records)])
            self.assertEqual(code, 1)
            self.assertIn("invalid_record", output)
            self.assertIn("failed: 1", output)

    def test_upload_review_edits_update_the_pending_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            manifest = seed_job(data_dir)
            service = JobService(data_dir)
            try:
                revision = manifest.checkpoints["upload"]["revision"]
                manifest.transition_checkpoint("upload", "awaiting_review",
                                               revision, service.jobs_dir)
            finally:
                service.close()
            edit_path = Path(temp_dir) / "upload.yml"
            edit_path.write_text(
                "content:\n  title: Reviewed title\n", encoding="utf-8")

            result, _ = invoke(["--data-dir", str(data_dir), "job", "review",
                                manifest.job_id, "upload", "--edits", str(edit_path)])

            self.assertEqual(result, 0)
            saved = JobManifest.load(manifest.job_id, data_dir / "jobs")
            self.assertEqual(
                saved.configuration["upload"]["content"]["title"],
                "Reviewed title")

    def test_job_artifacts_prune_reports_the_retention_policy_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_dir = data_dir / "sources"
            source_dir.mkdir()
            (source_dir / "clip.mp4").write_bytes(b"video")
            service = JobService(data_dir)
            manifest = service.create_job("clip.mp4", {
                "conversion": {"skip": True, "subtitles": {"skip": True}}})
            jobs_dir = service.jobs_dir
            artifact_dir = data_dir / "output" / manifest.job_id
            artifact_dir.mkdir(parents=True)
            obsolete_path = artifact_dir / "obsolete.mp4"
            obsolete_path.write_bytes(b"0" * 12)
            manifest.record_artifact("primary", obsolete_path, jobs_dir)
            kept_path = artifact_dir / "kept.mp4"
            kept_path.write_bytes(b"0" * 5)
            manifest.record_artifact("primary", kept_path, jobs_dir)
            obsolete_id = next(
                artifact_id for artifact_id, artifact in manifest.artifacts.items()
                if artifact["state"] == "superseded")
            manifest.artifacts[obsolete_id]["superseded_at"] = "2000-01-01T00:00:00+00:00"
            manifest.save(jobs_dir)
            service.close()
            save_app_configuration(
                data_dir / "app.yml", {"retention": {"artifacts": {"max_age_days": 1}}})

            code, result = invoke_json(["--data-dir", str(data_dir), "job",
                                        "artifacts", "prune", manifest.job_id])

            self.assertEqual(code, 0)
            self.assertEqual(result, {"pruned": [obsolete_id], "bytes_freed": 12})
            self.assertFalse(obsolete_path.exists())


if __name__ == "__main__":
    unittest.main()
