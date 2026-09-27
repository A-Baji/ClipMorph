"""Opt-in artifact retention and rotated config backup limits."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from clipmorph.configuration import DEFAULT_BACKUP_KEEP_N, rotate_backup
from clipmorph.configuration import resolve_backup_keep_n
from clipmorph.configuration import save_app_configuration
from clipmorph.job import JobManifest
from clipmorph.service import CancellationToken, JobService


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


class ArtifactRetentionTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.data_dir = Path(self._temp.name) / "data"
        self.data_dir.mkdir()
        source_dir = self.data_dir / "sources"
        source_dir.mkdir()
        (source_dir / "clip.mp4").write_bytes(b"video")
        self.service = JobService(self.data_dir)
        self.addCleanup(self.service.close)
        self.manifest = JobManifest.create(
            str(source_dir / "clip.mp4"),
            {"general": {"source": "clip.mp4"},
             "conversion": {"skip": True, "subtitles": {"skip": True}}},
            self.service.jobs_dir)
        self.manifest.record_artifact(
            "source", source_dir / "clip.mp4", self.service.jobs_dir)
        self.manifest.transition_checkpoint(
            "upload", "awaiting_review",
            self.manifest.checkpoints["upload"]["revision"],
            self.service.jobs_dir)

    def _render(self, kind: str, size: int) -> str:
        """Register a real rendered artifact of a known size, returning its id."""
        output_dir = self.data_dir / "output" / self.manifest.job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{kind}-{len(self.manifest.artifacts) + 1}.mp4"
        path.write_bytes(b"0" * size)
        self.manifest.record_artifact(kind, path, self.service.jobs_dir)
        return self.manifest.current_artifact_id

    def _backdate(self, artifact_id: str, **delta) -> None:
        """Age one artifact past a retention threshold."""
        self.manifest.artifacts[artifact_id]["superseded_at"] = _iso(**delta)
        self.manifest.save(self.service.jobs_dir)

    def _policy(self, **retention) -> None:
        save_app_configuration(self.data_dir / "app.yml",
                               {"retention": retention})

    def _saved(self):
        return self.service.get_job(self.manifest.job_id)

    def test_no_policy_is_a_no_op_that_never_touches_the_manifest(self):
        first = self._render("primary", 10)
        second = self._render("primary", 20)
        before = self._saved().updated_at

        result = self.service.enforce_retention(self.manifest.job_id)

        after = self._saved()
        self.assertEqual(result, {"pruned": []})
        self.assertEqual(after.updated_at, before)
        self.assertEqual(after.artifacts[first]["state"], "superseded")
        self.assertEqual(after.artifacts[second]["state"], "current")
        self.assertNotIn("deleted_at", after.artifacts[first])

    def test_age_pruning_tombstones_only_superseded_past_threshold_artifacts(self):
        old = self._render("primary", 10)
        source_copy = self._render("source", 10)
        recent = self._render("primary", 10)
        self._backdate(old, days=-120)
        self._backdate(source_copy, days=-400)
        self._policy(artifacts={"max_age_days": 90})

        result = self.service.enforce_retention(self.manifest.job_id)

        saved = self._saved()
        self.assertEqual(result["pruned"], [old])
        self.assertEqual(result["bytes_freed"], 10)
        self.assertEqual(saved.artifacts[old]["state"], "deleted")
        self.assertIsNotNone(saved.artifacts[old]["deleted_at"])
        # A source artifact is never auto-pruned, and other states stay put.
        self.assertEqual(saved.artifacts[source_copy]["state"], "superseded")
        self.assertEqual(saved.artifacts[recent]["state"], "current")
        self.assertFalse(Path(saved.artifacts[old]["path"]).exists())
        self.assertTrue(Path(saved.artifacts[recent]["path"]).exists())

    def test_age_pruning_never_touches_a_stale_artifact(self):
        first = self._render("primary", 10)
        second = self._render("primary", 10)
        self.manifest.artifacts[second]["state"] = "stale"
        self.manifest.save(self.service.jobs_dir)
        self._backdate(first, days=-200)
        self._policy(artifacts={"max_age_days": 1})

        result = self.service.enforce_retention(self.manifest.job_id)

        saved = self._saved()
        self.assertEqual(result["pruned"], [first])
        self.assertEqual(saved.artifacts[second]["state"], "stale")
        self.assertTrue(Path(saved.artifacts[second]["path"]).exists())

    def test_max_bytes_evicts_oldest_obsolete_first_until_under_the_cap(self):
        first = self._render("primary", 1000)
        second = self._render("primary", 1000)
        third = self._render("primary", 1000)
        self._backdate(first, days=-3)
        self._backdate(second, days=-2)
        self._backdate(third, days=-1)
        # 5-byte source + three 1000-byte renders = 3005 bytes.
        self._policy(artifacts={"max_bytes": 1500})

        result = self.service.enforce_retention(self.manifest.job_id)

        saved = self._saved()
        self.assertEqual(result["pruned"], [first, second])
        self.assertEqual(result["bytes_freed"], 2000)
        self.assertEqual(saved.artifacts[third]["state"], "current")
        self.assertTrue(Path(saved.artifacts[third]["path"]).exists())

    def test_retention_keeps_manifest_history_for_pruned_artifacts(self):
        first = self._render("primary", 10)
        self._render("primary", 20)
        self._backdate(first, days=-200)
        self._policy(artifacts={"max_age_days": 1})

        self.service.enforce_retention(self.manifest.job_id)

        saved = self._saved()
        self.assertIn(first, saved.artifacts)
        self.assertEqual(saved.artifacts[first]["kind"], "primary")
        self.assertTrue(saved.artifacts[first]["sha256"])
        self.assertTrue(saved.artifacts[first]["path"])

    def test_uploading_a_pruned_artifact_reports_unavailable_bytes(self):
        first = self._render("primary", 10)
        self._render("primary", 20)
        self._backdate(first, days=-200)
        self._policy(artifacts={"max_age_days": 1})
        self.service.enforce_retention(self.manifest.job_id)

        with self.assertRaisesRegex(ValueError, "artifact bytes are unavailable"):
            self.service.submit_upload(
                self.manifest.job_id, ["youtube"], first,
                confirm_historical_artifact=True)

    def test_retention_runs_automatically_after_a_job_completes(self):
        first = self._render("primary", 10)
        self._render("primary", 20)
        self._backdate(first, days=-200)
        self._policy(artifacts={"max_age_days": 1})
        jobs_dir = self.service.jobs_dir

        def run_to_completion(manifest, _token):
            checkpoint = manifest.checkpoints["upload"]
            manifest.transition_checkpoint(
                "upload", "running", checkpoint["revision"], jobs_dir)
            manifest.transition_checkpoint(
                "upload", "completed", checkpoint["revision"], jobs_dir)

        self.service._run(self.manifest.job_id, run_to_completion,
                          CancellationToken())

        saved = self._saved()
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.artifacts[first]["state"], "deleted")

    def test_age_policy_below_the_threshold_prunes_nothing(self):
        first = self._render("primary", 10)
        self._render("primary", 20)
        self._policy(artifacts={"max_age_days": 365})

        result = self.service.enforce_retention(self.manifest.job_id)

        self.assertEqual(result, {"pruned": [], "bytes_freed": 0})
        self.assertEqual(self._saved().artifacts[first]["state"], "superseded")


class BackupRotationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.data_dir = Path(self._temp.name)

    def _backups(self) -> list[Path]:
        return sorted(
            (path for path in self.data_dir.glob("auth.yaml.backup*")
             if path.is_file()),
            key=lambda path: path.name)

    def test_rotate_backup_keeps_exactly_keep_n_copies(self):
        target = self.data_dir / "auth.yaml"
        for index in range(8):
            target.write_text(f"value-{index}\n", encoding="utf-8")
            rotate_backup(target, 3)

        backups = self._backups()
        self.assertEqual([path.name for path in backups],
                         ["auth.yaml.backup", "auth.yaml.backup1",
                          "auth.yaml.backup2"])
        self.assertEqual([path.read_text(encoding="utf-8") for path in backups],
                         ["value-7\n", "value-6\n", "value-5\n"])

    def test_rotate_backup_keeps_a_single_copy_when_asked(self):
        target = self.data_dir / "auth.yaml"
        for index in range(4):
            target.write_text(f"value-{index}\n", encoding="utf-8")
            rotate_backup(target, 1)

        backups = self._backups()
        self.assertEqual([path.name for path in backups], ["auth.yaml.backup"])
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "value-3\n")

    def test_backup_keep_n_comes_from_the_adjacent_app_configuration(self):
        app_path = self.data_dir / "app.yml"
        save_app_configuration(app_path, {"retention": {"backups": {"keep_n": 2}}})
        target = self.data_dir / "auth.yaml"
        for index in range(5):
            target.write_text(f"value-{index}\n", encoding="utf-8")
            rotate_backup(target, resolve_backup_keep_n(app_path))

        self.assertEqual([path.name for path in self._backups()],
                         ["auth.yaml.backup", "auth.yaml.backup1"])

    def test_backup_keep_n_falls_back_to_the_default(self):
        for name, content in (("absent.yml", None),
                              ("legacy.yml", "source_dir: sources\n"),
                              ("broken.yml", "config_version: 99\n")):
            with self.subTest(app_config=name):
                app_path = self.data_dir / name
                if content is not None:
                    app_path.write_text(content, encoding="utf-8")
                self.assertEqual(resolve_backup_keep_n(app_path),
                                 DEFAULT_BACKUP_KEEP_N)
        self.assertEqual(resolve_backup_keep_n(None), DEFAULT_BACKUP_KEEP_N)

    def test_auth_template_regeneration_honours_the_configured_limit(self):
        from clipmorph.auth import create_auth_template

        save_app_configuration(
            self.data_dir / "app.yml",
            {"retention": {"backups": {"keep_n": 2}}})
        for index in range(4):
            (self.data_dir / "auth.yaml").write_text(
                f"youtube:\n  client_id: value-{index}\n", encoding="utf-8")
            create_auth_template(self.data_dir)

        backups = self._backups()
        self.assertEqual([path.name for path in backups],
                         ["auth.yaml.backup", "auth.yaml.backup1"])
        self.assertIn("value-3", backups[0].read_text(encoding="utf-8"))
        self.assertIn("value-2", backups[1].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
