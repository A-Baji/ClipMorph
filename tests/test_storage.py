"""Pluggable artifact storage backend contract tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clipmorph.configuration import save_app_configuration
from clipmorph.job import JobManifest, MANIFEST_SCHEMA_VERSION
from clipmorph.storage import (LocalArtifactStorage, make_storage, storage_key_for)


class StorageKeyTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "output"

    def test_key_of_an_artifact_under_the_root_is_root_relative(self):
        self.assertEqual(storage_key_for(self.root, self.root / "job" / "clip.mp4"),
                         "job/clip.mp4")

    def test_key_of_a_file_outside_the_root_keeps_the_relative_path(self):
        source = Path(self._temp.name) / "sources" / "clip.mp4"
        self.assertEqual(storage_key_for(self.root, source),
                         "../sources/clip.mp4")

    def test_every_key_resolves_back_to_its_file(self):
        source = Path(self._temp.name) / "sources" / "clip.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"video")
        storage = LocalArtifactStorage(self.root)

        self.assertEqual(storage.local_path(storage_key_for(self.root, source)),
                         source.resolve())


class LocalArtifactStorageTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "output"
        self.root.mkdir()
        self.storage = LocalArtifactStorage(self.root)

    def _store(self, key: str, payload: bytes) -> str:
        source = Path(self._temp.name) / "source.mp4"
        source.write_bytes(payload)
        return self.storage.store(source, key)

    def test_store_and_open_round_trip(self):
        key = self._store("job1/artifact.mp4", b"video bytes")

        with self.storage.open(key) as handle:
            self.assertEqual(handle.read(), b"video bytes")

    def test_store_creates_missing_parent_directories(self):
        key = self._store("job1/deeper/artifact.mp4", b"nested")

        self.assertEqual(self.storage.local_path(key).read_bytes(), b"nested")

    def test_stage_copies_bytes_to_destination(self):
        key = self._store("job1/artifact.mp4", b"staged bytes")
        destination = Path(self._temp.name) / "staging"

        staged = self.storage.stage(key, destination)

        self.assertEqual(staged.read_bytes(), b"staged bytes")
        self.assertEqual(staged.parent, destination)
        # The registered bytes stay where the manifest says they are.
        self.assertNotEqual(staged, self.storage.local_path(key))

    def test_stage_missing_key_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.storage.stage("missing/artifact.mp4", Path(self._temp.name))

    def test_open_missing_key_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.storage.open("missing/artifact.mp4")

    def test_remove_is_idempotent(self):
        key = self._store("job1/artifact.mp4", b"delete me")

        self.storage.remove(key)
        self.assertFalse(self.storage.exists(key))
        # A second remove of the same key is a no-op.
        self.storage.remove(key)

    def test_exists_reports_presence(self):
        key = "job1/artifact.mp4"

        self.assertFalse(self.storage.exists(key))
        self._store(key, b"present")
        self.assertTrue(self.storage.exists(key))

    def test_signed_url_is_unsupported_for_local(self):
        with self.assertRaises(NotImplementedError):
            self.storage.signed_url("job1/artifact.mp4", 300)

    def test_health_probes_the_backend_write_path(self):
        status, detail = self.storage.health()

        self.assertEqual(status, "ok")
        self.assertIn(str(self.root), detail)
        # The probe leaves nothing behind in the artifact root.
        self.assertEqual([item.name for item in self.root.iterdir()], [])

    def test_health_fails_when_the_store_cannot_write(self):
        with patch.object(LocalArtifactStorage, "store",
                          side_effect=OSError("permission denied")):
            status, detail = self.storage.health()

        self.assertEqual(status, "failed")
        self.assertIn("permission denied", detail)

    def test_health_fails_when_the_probe_object_is_not_registered(self):
        with patch.object(LocalArtifactStorage, "store", return_value="probe"):
            status, detail = self.storage.health()

        self.assertEqual(status, "failed")
        self.assertIn("probe missing after write", detail)


class MakeStorageTests(unittest.TestCase):
    def test_make_storage_returns_local_backend_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            storage = make_storage({}, data_dir)
            self.assertIsInstance(storage, LocalArtifactStorage)
            self.assertEqual(storage.local_path("job1/clip.mp4"),
                             (data_dir / "output" / "job1" / "clip.mp4").resolve())

    def test_make_storage_roots_the_backend_at_the_configured_output_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            storage = make_storage({"storage": {"backend": "local"},
                                    "output_dir": "renders"}, data_dir)
            self.assertEqual(storage.local_path("job1/clip.mp4"),
                             (data_dir / "renders" / "job1" / "clip.mp4").resolve())

    def test_make_storage_rejects_unknown_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "unknown storage backend"):
                make_storage({"storage": {"backend": "gcs"}}, data_dir)


class ManifestStorageSchemaTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.data_dir = Path(self._temp.name) / "data"
        self.source_dir = self.data_dir / "sources"
        self.source_dir.mkdir(parents=True)
        self.source = self.source_dir / "clip.mp4"
        self.source.write_bytes(b"video")
        self.jobs_dir = self.data_dir / "jobs"
        self.jobs_dir.mkdir()

    def _record_conversion_artifact(self, jobs_dir: str | Path) -> JobManifest:
        manifest = JobManifest.create(str(self.source), {}, str(jobs_dir))
        artifact = self.data_dir / "output" / manifest.job_id / "clip.mp4"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"rendered")
        manifest.record_artifact("conversion", artifact, str(jobs_dir))
        return manifest

    def test_manifest_round_trip_carries_storage_reference(self):
        manifest = self._record_conversion_artifact(self.jobs_dir)

        loaded = JobManifest.load(manifest.job_id, str(self.jobs_dir))
        record = loaded.artifacts[loaded.current_artifact_id]
        self.assertIn("storage", record)
        self.assertNotIn("path", record)
        self.assertEqual(record["storage"], {
            "backend": "local",
            "key": f"{manifest.job_id}/clip.mp4"})
        self.assertTrue(loaded.save(self.jobs_dir).is_file())

    def test_v2_manifest_is_rejected(self):
        manifest = self._record_conversion_artifact(self.jobs_dir)
        manifest_path = self.jobs_dir / manifest.job_id / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["schema_version"] = MANIFEST_SCHEMA_VERSION - 1
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "schema version"):
            JobManifest.load(manifest.job_id, str(self.jobs_dir))

    def test_source_artifact_key_keeps_the_relative_path_to_the_source(self):
        manifest = JobManifest.create(str(self.source), {}, str(self.jobs_dir))

        manifest.record_artifact("source", self.source, str(self.jobs_dir))

        loaded = JobManifest.load(manifest.job_id, str(self.jobs_dir))
        record = loaded.artifacts[loaded.current_artifact_id]
        self.assertEqual(record["storage"]["backend"], "local")
        self.assertEqual(storage_key_for(self.data_dir / "output", self.source),
                         record["storage"]["key"])
        self.assertEqual(LocalArtifactStorage(
            self.data_dir / "output").local_path(record["storage"]["key"]),
            self.source.resolve())

    def test_recorded_key_follows_the_configured_artifact_root(self):
        save_app_configuration(
            self.data_dir / "app.yml", {"output_dir": "renders"})
        manifest = JobManifest.create(str(self.source), {}, str(self.jobs_dir))
        artifact = self.data_dir / "renders" / manifest.job_id / "clip.mp4"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"rendered")

        manifest.record_artifact("conversion", artifact, str(self.jobs_dir))

        record = manifest.artifacts[manifest.current_artifact_id]
        self.assertEqual(record["storage"]["key"],
                         f"{manifest.job_id}/clip.mp4")

    def test_explicit_key_wins_over_the_configured_artifact_root(self):
        manifest = JobManifest.create(str(self.source), {}, str(self.jobs_dir))
        artifact = self.data_dir / "output" / manifest.job_id / "clip.mp4"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"rendered")

        manifest.record_artifact("conversion", artifact, str(self.jobs_dir),
                                 storage_key=f"custom/{manifest.job_id}.mp4")

        record = manifest.artifacts[manifest.current_artifact_id]
        self.assertEqual(record["storage"]["key"],
                         f"custom/{manifest.job_id}.mp4")


if __name__ == "__main__":
    unittest.main()
