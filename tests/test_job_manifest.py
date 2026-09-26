import tempfile
import unittest
from pathlib import Path

from clipmorph.job import JobManifest


class JobManifestTests(unittest.TestCase):
    def test_job_manifest_persists_source_hash_and_platform_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            jobs_dir = Path(temp_dir) / "jobs"
            manifest = JobManifest.create(str(source), {"dry_run": False},
                                          str(jobs_dir))
            manifest.record_platform("YouTube", {"success": True},
                                     str(jobs_dir))
            loaded = JobManifest.load(manifest.job_id, str(jobs_dir))
            self.assertEqual(loaded.schema_version, 2)
            self.assertEqual(loaded.source_sha256, manifest.source_sha256)
            self.assertTrue(loaded.platforms["YouTube"]["success"])

    def test_manifest_persists_step_and_artifact_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            artifact = Path(temp_dir) / "converted.mp4"
            manifest = JobManifest.create(str(source), {}, temp_dir)
            manifest.set_step("conversion", "running", temp_dir)
            manifest.set_artifact(str(artifact), temp_dir)
            loaded = JobManifest.load(manifest.job_id, temp_dir)

            self.assertEqual(loaded.steps["conversion"]["status"], "running")
            artifact = loaded.artifacts[loaded.current_artifact_id]
            self.assertEqual(artifact["source_sha256"], manifest.source_sha256)

    def test_rerender_artifacts_are_immutable_revisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            first = Path(temp_dir) / "first.mp4"
            second = Path(temp_dir) / "second.mp4"
            first.write_bytes(b"first revision")
            second.write_bytes(b"second revision")
            manifest = JobManifest.create(str(source), {}, temp_dir)

            manifest.set_artifact(str(first), temp_dir)
            first_id = manifest.current_artifact_id
            manifest.set_artifact(str(second), temp_dir)
            loaded = JobManifest.load(manifest.job_id, temp_dir)

            self.assertEqual(len(loaded.artifacts), 2)
            self.assertEqual(loaded.artifacts[first_id]["state"], "superseded")
            self.assertEqual(loaded.artifacts[loaded.current_artifact_id]["state"], "current")
            self.assertNotEqual(loaded.artifacts[first_id]["sha256"],
                                loaded.artifacts[loaded.current_artifact_id]["sha256"])

    def test_manifest_keeps_mixed_platforms_as_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            manifest = JobManifest.create(str(source), {}, temp_dir)
            manifest.record_platform("YouTube", {"success": False}, temp_dir)
            manifest.record_platform("TikTok", {"success": True}, temp_dir)
            self.assertEqual(manifest.status, "partial_failure")


if __name__ == "__main__":
    unittest.main()
