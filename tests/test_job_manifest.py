import tempfile
import unittest
from pathlib import Path

from clipmorph.job import JobManifest, MANIFEST_SCHEMA_VERSION


class JobManifestTests(unittest.TestCase):
    def test_job_manifest_persists_source_hash_and_platform_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            jobs_dir = Path(temp_dir) / "jobs"
            manifest = JobManifest.create(str(source), {"dry_run": False},
                                          str(jobs_dir))
            loaded = JobManifest.load(manifest.job_id, str(jobs_dir))
            self.assertEqual(loaded.schema_version, MANIFEST_SCHEMA_VERSION)
            self.assertEqual(loaded.source_sha256, manifest.source_sha256)
            self.assertEqual(loaded.platforms, {})

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

    def test_source_artifact_does_not_move_the_display_pointer_off_a_render(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            render = Path(temp_dir) / "render.mp4"
            render.write_bytes(b"render")
            manifest = JobManifest.create(str(source), {}, temp_dir)

            manifest.record_artifact("conversion", render, temp_dir)
            render_id = manifest.current_artifact_id
            manifest.record_artifact("source", source, temp_dir)
            loaded = JobManifest.load(manifest.job_id, temp_dir)

            # A ``conversion.skip`` group's source copy must not move the
            # display pointer off the latest render nor supersede it.
            self.assertEqual(loaded.current_artifact_id, render_id)
            self.assertEqual(loaded.artifacts[render_id]["state"], "current")

    def test_manifest_keeps_mixed_platforms_as_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            manifest = JobManifest.create(str(source), {}, temp_dir)
            manifest.platforms["youtube"] = {"success": False}
            manifest.platforms["tiktok"] = {"success": True}
            manifest.save(temp_dir)
            loaded = JobManifest.load(manifest.job_id, temp_dir)
            self.assertFalse(loaded.platforms["youtube"]["success"])
            self.assertTrue(loaded.platforms["tiktok"]["success"])


if __name__ == "__main__":
    unittest.main()
