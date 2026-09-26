import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.__main__ import main
from clipmorph.cli import run_cli
from clipmorph.job import JobManifest
from clipmorph.service import JobService


class CliInitializationTests(unittest.TestCase):
    def test_init_writes_app_yaml_and_auth_in_selected_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            with patch.object(sys, "argv", [
                    "clipmorph", "--data-dir", str(data_dir), "init"]):
                main()

            self.assertTrue((data_dir / "app.yml").exists())
            self.assertTrue((data_dir / "auth.yaml").exists())

    def test_init_config_path_writes_adjacent_auth_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yml"
            with patch.object(sys, "argv", [
                    "clipmorph", "init", "--config-path", str(config_path)
            ]):
                main()

            self.assertTrue(config_path.exists())
            self.assertTrue((Path(temp_dir) / "auth.yaml").exists())

    def test_init_does_not_replace_existing_app_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yml"
            config_path.write_text("existing: true\n", encoding="utf-8")
            with patch.object(sys, "argv", [
                    "clipmorph", "init", "--config-path", str(config_path)
            ]):
                main()

            self.assertEqual(config_path.read_text(encoding="utf-8"), "existing: true\n")


class JobCommandPersistenceTests(unittest.TestCase):
    def test_cli_data_dir_persists_updated_manifest_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "custom-data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "input.mp4"
            source.write_bytes(b"video")

            with patch.object(sys, "argv", [
                    "clipmorph", "--data-dir", str(data_dir),
                "job", "create", str(source)
            ]), patch("clipmorph.workflow.execute_job"):
                main()

            manifests = list((data_dir / "jobs").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            loaded = JobManifest.load(manifests[0].parent.name, str(data_dir / "jobs"))
            self.assertEqual(loaded.status, "queued")
            self.assertEqual(loaded.configuration["general"]["source"], "input.mp4")


class JobCommandTests(unittest.TestCase):
    def test_init_writes_app_yaml_and_auth_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            result = run_cli(["--data-dir", str(data_dir), "init"])

            self.assertEqual(result, 0)
            self.assertTrue((data_dir / "app.yml").exists())
            self.assertTrue((data_dir / "auth.yaml").exists())
            self.assertFalse((data_dir / "clipmorph.yaml").exists())

    def test_job_create_dry_run_uses_service_and_writes_no_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "A clip.mp4").write_bytes(b"video")

            result = run_cli([
                "--data-dir", str(data_dir), "job", "create", str(source_dir),
                "--dry-run",
            ])

            self.assertEqual(result, 0)
            self.assertFalse((data_dir / "jobs").exists())

    def test_upload_review_edits_update_the_pending_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "sources").mkdir()
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"video")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {})
            checkpoint = manifest.checkpoints["upload"]
            manifest.transition_checkpoint(
                "upload", "awaiting_review", checkpoint["revision"], service.jobs_dir)
            service.close()
            edit_path = Path(temp_dir) / "upload.yml"
            edit_path.write_text(
                "content:\n  title: Reviewed title\n", encoding="utf-8")

            result = run_cli([
                "--data-dir", str(data_dir), "job", "review", manifest.job_id,
                "upload", "--edits", str(edit_path),
            ])

            self.assertEqual(result, 0)
            saved = JobManifest.load(manifest.job_id, data_dir / "jobs")
            self.assertEqual(
                saved.configuration["upload"]["content"]["title"],
                "Reviewed title")


if __name__ == "__main__":
    unittest.main()
