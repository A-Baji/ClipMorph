import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from clipmorph.service import JobService

try:
    from fastapi.testclient import TestClient
    from clipmorph.web import create_app
except ImportError:  # CLI-only installations do not include the web extra.
    TestClient = None
    create_app = None


@unittest.skipUnless(TestClient and create_app, "web extra is not installed")
class WebApiTests(unittest.TestCase):
    def test_app_configuration_and_layout_registry_use_atomic_app_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                response = client.put("/api/v1/configuration", json={
                    "configuration": {
                        "source_dir": "sources",
                        "job_defaults": {"upload": {"content": {"title": "Default"}}},
                    },
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    client.get("/api/v1/configuration").json()["configuration"][
                        "source_dir"], "sources")
                layout = client.post("/api/v1/layouts", json={
                    "name": "Vertical highlight",
                    "layout": {"captions": {"overlay": {"items": []}}},
                })
                self.assertEqual(layout.status_code, 201)
                app_config = yaml.safe_load((data_dir / "app.yml").read_text(encoding="utf-8"))
                self.assertEqual(app_config["layouts"][0]["id"], layout.json()["id"])
                self.assertFalse((data_dir / "config.json").exists())
                self.assertFalse((data_dir / "layouts.json").exists())

    def test_sources_validation_single_create_and_bulk_fanout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_dir = data_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "one.mp4").write_bytes(b"one")
            (source_dir / "two.mp4").write_bytes(b"two")
            with TestClient(create_app(data_dir)) as client:
                listed = client.get("/api/v1/sources")
                self.assertEqual([item["name"] for item in listed.json()],
                                 ["one.mp4", "two.mp4"])
                validation = client.post("/api/v1/jobs/validate", json={
                    "source": "one.mp4",
                    "configuration": {"general": {"source": "one.mp4"}},
                })
                self.assertEqual(validation.status_code, 200)
                effective = validation.json()["effective_configurations"][0]["configuration"]
                self.assertEqual(effective["upload"]["content"]["title"], "one")
                created = client.post("/api/v1/jobs", json={
                    "source": "one.mp4", "configuration": {},
                })
                self.assertEqual(created.status_code, 202)
                job_id = created.json()["job_id"]
                job = client.get(f"/api/v1/jobs/{job_id}").json()
                self.assertEqual(job["configuration"]["general"]["source"], "one.mp4")
                self.assertTrue((data_dir / "jobs" / job_id / "job.yml").exists())
                bulk = client.post("/api/v1/jobs/bulk", json={
                    "job_configs": [{
                        "general": {"source": "one.mp4"},
                        "upload": {"content": {"title": "Explicit"}},
                    }],
                    "overrides": {},
                })
                self.assertIn(bulk.status_code, {200, 202}, bulk.text)
                self.assertEqual(len(bulk.json()["created"]), 1)
                self.assertEqual(bulk.json()["skipped"][0]["code"], "duplicate_content")
                self.assertEqual(client.post("/api/v1/batches", json={}).status_code, 404)

    def test_source_upload_is_sanitized_and_checkpoint_transcript_is_versioned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                uploaded = client.post(
                    "/api/v1/sources",
                    files={"file": ("../clip.mp4", b"video", "video/mp4")})
                self.assertEqual(uploaded.status_code, 201)
                name = uploaded.json()["name"]
                job = client.post("/api/v1/jobs", json={
                    "source": name, "configuration": {},
                }).json()
                job_id = job["job_id"]
                manifest = client.get(f"/api/v1/jobs/{job_id}").json()
                transcript = {
                    "schema_version": 2,
                    "revision": 1,
                    "source_sha256": manifest["source_sha256"],
                    "media_duration": 2.0,
                    "original_segments": [{"id": "segment-1", "start": 0,
                                           "end": 1, "text": "Hi"}],
                    "segments": [{"id": "segment-1", "start": 0,
                                  "end": 1, "text": "Hello"}],
                }
                response = client.put(
                    f"/api/v1/jobs/{job_id}/transcript",
                    json={**transcript, "expected_revision": 0})
                self.assertEqual(response.status_code, 200)
                self.assertTrue((data_dir / "jobs" / job_id / "transcripts" /
                                 "revision-0001.json").exists())
                self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/transcript").json()[
                    "segments"][0]["text"], "Hello")

    def test_upload_review_attempt_retry_and_artifact_routes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"platforms": {"include": ["youtube"]}},
            })
            artifact_dir = data_dir / "output" / manifest.job_id
            artifact_dir.mkdir(parents=True)
            artifact_path = artifact_dir / "output.mp4"
            artifact_path.write_bytes(b"rendered artifact")
            manifest.set_artifact(str(artifact_path), service.jobs_dir)
            service.close()

            app = create_app(data_dir)
            with TestClient(app) as client:
                job_id = manifest.job_id
                artifact_id = manifest.current_artifact_id
                draft = client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": 0,
                          "upload": {"content": {"title": "Frozen title"}}})
                self.assertEqual(draft.status_code, 200, draft.text)
                self.assertEqual(draft.json()["checkpoint"]["status"], "awaiting_review")

                self.assertEqual(
                    client.get(f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}/preview").content,
                    b"rendered artifact")
                renamed = client.patch(
                    f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}",
                    json={"display_name": "Reviewed.mp4"})
                self.assertEqual(renamed.status_code, 200, renamed.text)

                with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline_type:
                    pipeline_type.return_value.run.side_effect = [
                        {"YouTube": {"success": False, "error": "temporary"}},
                        {"YouTube": {"success": True, "result": "remote-id"}},
                    ]
                    submitted = client.post(f"/api/v1/jobs/{job_id}/upload", json={})
                    self.assertEqual(submitted.status_code, 202, submitted.text)
                    app.state.job_service._futures[f"upload:{job_id}"].result(timeout=2)
                    attempt_id = submitted.json()["attempts"][0]["attempt_id"]
                    checkpoint = client.get(
                        f"/api/v1/jobs/{job_id}/checkpoints/upload").json()["checkpoint"]
                    client.put(
                        f"/api/v1/jobs/{job_id}/checkpoints/upload",
                        json={"expected_revision": checkpoint["revision"],
                              "upload": {"content": {"title": "New draft"}}})
                    retried = client.post(
                        f"/api/v1/jobs/{job_id}/uploads/youtube/retry",
                        json={"attempt_id": attempt_id})
                    self.assertEqual(retried.status_code, 202, retried.text)
                    app.state.job_service._futures[f"upload:{job_id}"].result(timeout=2)

                attempts = client.get(f"/api/v1/jobs/{job_id}/uploads").json()
                self.assertEqual(len(attempts), 2)
                self.assertEqual(attempts[0]["configuration_snapshot"]["content"]["title"],
                                 "Frozen title")
                self.assertEqual(attempts[1]["configuration_snapshot"]["content"]["title"],
                                 "Frozen title")
                self.assertEqual(
                    client.get(f"/api/v1/jobs/{job_id}").json()["configuration"][
                        "upload"]["content"]["title"], "New draft")
                self.assertEqual(attempts[1]["status"], "completed")
                deleted = client.delete(
                    f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}?confirm=true")
                self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_checkpoint_acceptance_rejects_stale_revisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {})
            checkpoint = manifest.checkpoints["transcript"]
            checkpoint = manifest.transition_checkpoint(
                "transcript", "running", checkpoint["revision"], service.jobs_dir)
            manifest.transition_checkpoint(
                "transcript", "awaiting_review", checkpoint["revision"], service.jobs_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                path = f"/api/v1/jobs/{manifest.job_id}/checkpoints/transcript/accept"
                accepted = client.post(path, json={"expected_revision": 2})
                self.assertEqual(accepted.status_code, 200)
                stale = client.post(path, json={"expected_revision": 2})
                self.assertEqual(stale.status_code, 409)
                self.assertEqual(stale.json()["error"]["code"], "conflict")


if __name__ == "__main__":
    unittest.main()
