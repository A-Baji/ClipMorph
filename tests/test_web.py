from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from clipmorph.configuration import APP_CONFIG_VERSION, save_app_configuration
from clipmorph.metrics import append_snapshot
from clipmorph.service import JobService
from clipmorph.service import conversion_groups
from clipmorph.upload_pipeline.platforms.base import BaseUploadPipeline

try:
    from fastapi.testclient import TestClient
    from clipmorph.web import create_app
except ImportError:  # CLI-only installations do not include the web extra.
    TestClient = None
    create_app = None


def _fake_youtube_adapter(percent, fail=False):
    """Build a fake YouTube adapter that reports exactly one progress step.

    The allocations sum to 100 so the normalized percent after the single
    ``upload`` step equals ``percent``.
    """

    class FakeYouTubeAdapter(BaseUploadPipeline):
        def __init__(self):
            self.progress_allocations = {"upload": percent,
                                         "finalize": 100 - percent}
            self.progress_bar = None
            self.platform_name = "YouTube"
            # Prevent the orchestrator's interactive-auth pass from firing.
            self.credentials = True
            super().__init__()

        def run(self, video_path, **kwargs):
            self._update_progress("upload")
            if fail:
                raise RuntimeError("upload failed")
            return {"success": True, "result": "remote-id",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "completed_at": "2026-01-01T00:00:01+00:00"}

    return FakeYouTubeAdapter()


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
                self.assertEqual(app_config["config_version"], APP_CONFIG_VERSION)
                self.assertFalse((data_dir / "config.json").exists())
                self.assertFalse((data_dir / "layouts.json").exists())

    def test_artifact_prune_reports_a_failed_recycle_as_a_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                with patch.object(JobService, "enforce_retention",
                                  side_effect=OSError("file is in use")):
                    response = client.post(
                        "/api/v1/jobs/any-job/artifacts/prune")

            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["error"]["code"], "conflict")
            self.assertIn("could not be recycled", response.json()["error"]["message"])

    def test_configuration_version_guards_put_without_touching_the_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                client.put("/api/v1/configuration", json={
                    "configuration": {"source_dir": "sources"}})
                stored = (data_dir / "app.yml").read_text(encoding="utf-8")

                rejected = client.put("/api/v1/configuration", json={
                    "configuration": {"config_version": APP_CONFIG_VERSION + 1,
                                      "source_dir": "elsewhere"}})
                self.assertEqual(rejected.status_code, 422)
                self.assertEqual(rejected.json()["error"]["code"], "invalid_configuration")
                self.assertIn("clipmorph init", rejected.json()["error"]["message"])
                self.assertEqual((data_dir / "app.yml").read_text(encoding="utf-8"), stored)

                unstamped = client.put("/api/v1/configuration", json={
                    "configuration": {"source_dir": "inbox"}})
                self.assertEqual(unstamped.status_code, 200, unstamped.text)
                self.assertEqual(unstamped.json()["configuration"]["config_version"],
                                 APP_CONFIG_VERSION)
                self.assertEqual(
                    client.get("/api/v1/configuration").json()["configuration"][
                        "config_version"], APP_CONFIG_VERSION)

    def test_artifact_prune_route_applies_retention_and_404s_for_unknown_jobs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}}})
            job_id = manifest.job_id
            manifest_dir = service.jobs_dir
            artifact_dir = data_dir / "output" / job_id
            artifact_dir.mkdir(parents=True)
            obsolete_path = artifact_dir / "obsolete.mp4"
            obsolete_path.write_bytes(b"0" * 40)
            manifest.record_artifact("primary", obsolete_path, manifest_dir)
            kept_path = artifact_dir / "kept.mp4"
            kept_path.write_bytes(b"0" * 5)
            manifest.record_artifact("primary", kept_path, manifest_dir)
            states = {artifact["state"] for artifact in manifest.artifacts.values()}
            self.assertEqual(states, {"superseded", "current"})
            obsolete = [artifact_id for artifact_id, artifact in manifest.artifacts.items()
                        if artifact["state"] == "superseded"]
            kept_id = manifest.current_artifact_id
            manifest.artifacts[obsolete[0]]["superseded_at"] = "2000-01-01T00:00:00+00:00"
            manifest.save(manifest_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                missing = client.post("/api/v1/jobs/unknown/artifacts/prune")
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(missing.json()["error"]["code"], "not_found")

                client.put("/api/v1/configuration", json={"configuration": {
                    "retention": {"artifacts": {"max_age_days": 1}}}})
                pruned = client.post(f"/api/v1/jobs/{job_id}/artifacts/prune")
                self.assertEqual(pruned.status_code, 202, pruned.text)
                self.assertEqual(pruned.json(), {"pruned": obsolete, "bytes_freed": 40})
                self.assertFalse(obsolete_path.exists())
                kept = {artifact["id"]: artifact for artifact
                        in client.get(f"/api/v1/jobs/{job_id}/artifacts").json()}
                self.assertEqual(kept[obsolete[0]]["state"], "deleted")
                self.assertEqual(kept[kept_id]["state"], "current")

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

    def test_form_spec_route_serves_the_generated_spec(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                response = client.get("/form-spec.json")
                self.assertEqual(response.status_code, 200, response.text)
                spec = response.json()
                self.assertIn("sections", spec)
                self.assertEqual(spec["source"], "clipmorph.configuration")

    def test_bulk_validate_and_create_accept_out_of_folder_transient_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            (data_dir / "sources" / "inside.mp4").write_bytes(b"inside")
            outside_dir = Path(temp_dir) / "elsewhere"
            outside_dir.mkdir(parents=True)
            outside = outside_dir / "extra.mp4"
            outside.write_bytes(b"outside")
            (outside_dir / "note.txt").write_bytes(b"not a clip")
            with TestClient(create_app(data_dir)) as client:
                validation = client.post("/api/v1/jobs/validate", json={
                    "source_names": [],
                    "sources": [str(outside)],
                    "job_configs": [],
                    "overrides": {},
                })
                self.assertEqual(validation.status_code, 200, validation.text)
                body = validation.json()
                self.assertTrue(body["valid"])
                self.assertEqual(
                    body["effective_configurations"][0]["source"], "extra.mp4")

                created = client.post("/api/v1/jobs/bulk", json={
                    "source_names": [],
                    "sources": [str(outside)],
                    "job_configs": [],
                    "overrides": {},
                })
                self.assertEqual(created.status_code, 202, created.text)
                self.assertEqual(created.json()["created"][0]["source"], "extra.mp4")
                job_id = created.json()["created"][0]["job_id"]
                job = client.get(f"/api/v1/jobs/{job_id}").json()
                self.assertEqual(job["configuration"]["general"]["source"], "extra.mp4")
                self.assertTrue(Path(job["source_path"]).samefile(outside))

                rejected = client.post("/api/v1/jobs/validate", json={
                    "source_names": [],
                    "sources": [str(outside_dir / "note.txt")],
                    "job_configs": [],
                    "overrides": {},
                })
                self.assertEqual(rejected.status_code, 200, rejected.text)
                self.assertEqual(rejected.json()["skipped"][0]["code"],
                                 "unsupported_extension")

    def test_source_upload_is_sanitized_and_checkpoint_transcript_is_versioned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            app = create_app(data_dir)
            with TestClient(app) as client:
                uploaded = client.post(
                    "/api/v1/sources",
                    files={"file": ("../clip.mp4", b"video", "video/mp4")})
                self.assertEqual(uploaded.status_code, 201)
                name = uploaded.json()["name"]
                with patch("clipmorph.workflow.execute_job") as execute_job:
                    job = client.post("/api/v1/jobs", json={
                        "source": name, "configuration": {},
                    }).json()
                    app.state.job_service._futures[job["job_id"]].result(timeout=2)
                execute_job.assert_called_once()
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
                "upload": {"skip": True},
                "platforms": {"youtube": {"upload": {"skip": False}}},
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
                self.assertEqual(attempts[1]["status"], "published")
                deleted = client.delete(
                    f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}?confirm=true")
                self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_events_payload_contains_live_upload_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"skip": True},
                "platforms": {"youtube": {"upload": {"skip": False}}},
            })
            # A terminal status ends the SSE stream after one event.
            manifest.set_status("completed", service.jobs_dir)
            service.close()

            app = create_app(data_dir)
            with TestClient(app) as client:
                job_id = manifest.job_id
                # Simulate an in-flight upload's live progress.
                app.state.job_service._live_progress[job_id] = {"youtube": 42}

                response = client.get(f"/api/v1/jobs/{job_id}/events")
                self.assertEqual(response.status_code, 200)
                events = [line[6:] for line in response.text.splitlines()
                          if line.startswith("data: ")]
                self.assertTrue(events)
                payload = json.loads(events[0])
                self.assertEqual(payload["upload_progress"], {"youtube": 42})

                # The polling fallback carries the same field.
                job = client.get(f"/api/v1/jobs/{job_id}").json()
                self.assertEqual(job["upload_progress"], {"youtube": 42})

    def test_final_attempt_result_carries_progress_percent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"skip": True},
                "platforms": {"youtube": {"upload": {"skip": False}}},
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
                draft = client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": 0,
                          "upload": {"content": {"title": "Frozen title"}}})
                self.assertEqual(draft.status_code, 200, draft.text)

                with patch("clipmorph.upload_pipeline.YouTubeUploadPipeline") as adapter_type:
                    adapter_type.return_value = _fake_youtube_adapter(75)
                    submitted = client.post(f"/api/v1/jobs/{job_id}/upload", json={})
                    self.assertEqual(submitted.status_code, 202, submitted.text)
                    app.state.job_service._futures[f"upload:{job_id}"].result(timeout=2)

                attempts = client.get(f"/api/v1/jobs/{job_id}/uploads").json()
                self.assertEqual(attempts[0]["result"]["progress_percent"], 75)
                self.assertEqual(app.state.job_service.live_progress_for(job_id), {})

    def test_failed_attempt_retains_last_observed_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"skip": True},
                "platforms": {"youtube": {"upload": {"skip": False}}},
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
                draft = client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": 0,
                          "upload": {"content": {"title": "Frozen title"}}})
                self.assertEqual(draft.status_code, 200, draft.text)

                with patch("clipmorph.upload_pipeline.YouTubeUploadPipeline") as adapter_type:
                    adapter_type.return_value = _fake_youtube_adapter(30, fail=True)
                    submitted = client.post(f"/api/v1/jobs/{job_id}/upload", json={})
                    self.assertEqual(submitted.status_code, 202, submitted.text)
                    app.state.job_service._futures[f"upload:{job_id}"].result(timeout=2)

                attempts = client.get(f"/api/v1/jobs/{job_id}/uploads").json()
                self.assertEqual(attempts[0]["status"], "failed")
                self.assertEqual(attempts[0]["result"]["progress_percent"], 30)

    def test_credential_probe_route_returns_the_verdict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                with patch("clipmorph.auth_probe.probe_credentials",
                           return_value={"youtube": {
                               "configured": True, "probe": "ok",
                               "detail": "refresh token accepted"}}) as probe_fn:
                    response = client.post("/api/v1/credentials/youtube/probe")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {
                "configured": True, "probe": "ok",
                "detail": "refresh token accepted"})
            probe_fn.assert_called_once_with(["youtube"])

    def test_uploads_filter_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"skip": True},
                "platforms": {"youtube": {"upload": {"skip": False}}},
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
                client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": 0,
                          "upload": {"content": {"title": "Frozen title"}}})

                with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline_type:
                    pipeline_type.return_value.run.return_value = {
                        "YouTube": {"success": True, "result": "video-id"}}
                    submitted = client.post(f"/api/v1/jobs/{job_id}/upload", json={})
                    self.assertEqual(submitted.status_code, 202, submitted.text)
                    app.state.job_service._futures[f"upload:{job_id}"].result(timeout=2)

                # Filter by status
                published = client.get(
                    f"/api/v1/jobs/{job_id}/uploads?status=published")
                self.assertEqual(published.status_code, 200)
                self.assertEqual(len(published.json()), 1)
                self.assertEqual(published.json()[0]["status"], "published")

                # Filter by platform
                youtube = client.get(
                    f"/api/v1/jobs/{job_id}/uploads?platform=youtube")
                self.assertEqual(youtube.status_code, 200)
                self.assertEqual(len(youtube.json()), 1)

                # Filter by since — use a cutoff before the attempt was created
                before = (datetime.now(timezone.utc)
                          - timedelta(hours=1)).isoformat()
                recent = client.get(
                    f"/api/v1/jobs/{job_id}/uploads?since={quote(before)}")
                self.assertEqual(recent.status_code, 200)
                self.assertEqual(len(recent.json()), 1)

                # Invalid since -> 422
                invalid = client.get(
                    f"/api/v1/jobs/{job_id}/uploads?since=not-a-timestamp")
                self.assertEqual(invalid.status_code, 422)

    def test_facebook_content_kind_flows_into_the_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "platforms": {
                    "youtube": {"upload": {"skip": True}},
                    "instagram": {"upload": {"skip": True}},
                    "tiktok": {"upload": {"skip": True}},
                    "twitter": {"upload": {"skip": True}},
                    "facebook": {"content_kind": "video"},
                },
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
                client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": 0,
                          "upload": {"content": {"title": "Frozen title"}}})
                with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline_type:
                    pipeline_type.return_value.run.return_value = {
                        "Facebook": {"success": True, "result": "video-id"}}
                    submitted = client.post(
                        f"/api/v1/jobs/{job_id}/upload", json={})
                    self.assertEqual(submitted.status_code, 202, submitted.text)
                    app.state.job_service._futures[
                        f"upload:{job_id}"].result(timeout=2)

                sent = pipeline_type.return_value.run.call_args.kwargs
                self.assertEqual(sent["facebook_content_kind"], "video")
                attempts = client.get(f"/api/v1/jobs/{job_id}/uploads").json()
                self.assertEqual(attempts[0]["platform"], "facebook")
                self.assertEqual(attempts[0]["status"], "published")

    def test_cancel_scheduled_route_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "platforms": {
                    "instagram": {"upload": {"skip": True}},
                    "tiktok": {"upload": {"skip": True}},
                    "twitter": {"upload": {"skip": True}},
                    "facebook": {"upload": {"skip": True}},
                },
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
                publish_at = (datetime.now(timezone.utc)
                              + timedelta(hours=2)).isoformat()
                client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": 0,
                          "upload": {
                              "content": {"title": "Frozen title"},
                              "schedule": {"publish_at": publish_at,
                                           "mode": "local"}}})
                with patch("clipmorph.upload_pipeline.UploadPipeline") as pipeline_type:
                    pipeline_type.return_value.run.return_value = {
                        "YouTube": {"success": True, "result": "video-id"}}
                    submitted = client.post(f"/api/v1/jobs/{job_id}/upload", json={})
                    self.assertEqual(submitted.status_code, 202, submitted.text)
                attempt_id = submitted.json()["attempts"][0]["attempt_id"]
                self.assertEqual(submitted.json()["scheduled_via"], "local")

                cancelled = client.delete(
                    f"/api/v1/jobs/{job_id}/scheduled/{attempt_id}")
                self.assertEqual(cancelled.status_code, 202, cancelled.text)
                self.assertEqual(cancelled.json()["status"], "cancelled")
                self.assertEqual(cancelled.json()["scheduled_via"], "local")
                self.assertEqual(
                    client.get(
                        f"/api/v1/jobs/{job_id}/uploads").json()[0]["status"],
                    "cancelled")

                # An unknown attempt is 404, an unscheduled one is 422.
                missing = client.delete(
                    f"/api/v1/jobs/{job_id}/scheduled/does-not-exist")
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(missing.json()["error"]["code"], "not_found")
                again = client.delete(
                    f"/api/v1/jobs/{job_id}/scheduled/{attempt_id}")
                self.assertEqual(again.status_code, 422)
                self.assertIn("not scheduled", again.json()["error"]["message"])

    def test_queue_event_payload_with_scheduled_attempts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"skip": True},
                "platforms": {"youtube": {"upload": {"skip": False}}},
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
                future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": 0,
                          "upload": {
                              "content": {"title": "Scheduled"},
                              "schedule": {"publish_at": future}}})

                submitted = client.post(f"/api/v1/jobs/{job_id}/upload", json={})
                self.assertEqual(submitted.status_code, 202, submitted.text)

                job = client.get(f"/api/v1/jobs/{job_id}").json()
                self.assertEqual(job["status"], "scheduled")
                self.assertEqual(job["upload_attempts"][0]["status"], "scheduled")

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

    def test_upload_draft_put_accepts_platforms_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}}})
            upload_cp = manifest.checkpoints["upload"]
            manifest.transition_checkpoint(
                "upload", "awaiting_review", upload_cp["revision"],
                service.jobs_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                # Re-read the manifest to get the current revision.
                current = client.get(f"/api/v1/jobs/{job_id}").json()
                revision = current["checkpoints"]["upload"]["revision"]
                response = client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={
                        "expected_revision": revision,
                        "upload": {"content": {"title": "New title"}},
                        "platforms": {
                            "youtube": {"upload": {"skip": False}},
                            "tiktok": {"upload": {"skip": True}},
                        },
                    })
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["upload"]["content"]["title"], "New title")
                self.assertIn("platforms", body)
                self.assertEqual(
                    body["platforms"]["youtube"]["upload"]["skip"], False)
                self.assertEqual(
                    body["platforms"]["tiktok"]["upload"]["skip"], True)

    def test_explicit_submission_to_skipped_platform_returns_422(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}},
                "upload": {"skip": True},
                "platforms": {"youtube": {"upload": {"skip": True}}}})
            # Register a source artifact so the upload checkpoint can be
            # transitioned to awaiting_review.
            manifest.record_artifact("source", source, service.jobs_dir)
            # Move the upload checkpoint out of skipped so it can be
            # transitioned to awaiting_review.
            manifest = service.get_job(manifest.job_id)
            upload_cp = manifest.checkpoints["upload"]
            manifest.transition_checkpoint(
                "upload", "pending", upload_cp["revision"], service.jobs_dir)
            manifest = service.get_job(manifest.job_id)
            upload_cp = manifest.checkpoints["upload"]
            manifest.transition_checkpoint(
                "upload", "awaiting_review", upload_cp["revision"],
                service.jobs_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                response = client.post(
                    f"/api/v1/jobs/{job_id}/upload",
                    json={"platforms": ["youtube"]})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("skipped", response.json()["error"]["message"])

    def test_conversion_accept_accepts_one_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": False, "subtitles": {"skip": True}},
                # A different effective conversion section, so the job renders
                # twice and has two groups to accept independently.
                "platforms": {"youtube": {"conversion": {"strict": True}}}})
            groups = manifest.checkpoints["conversion"]["groups"]
            self.assertEqual(len(groups), 2)
            # Drive both groups to the review gate; a group transition matches
            # that group's own revision.
            for group_id in list(groups):
                for status in ("running", "awaiting_review"):
                    manifest = service.get_job(manifest.job_id)
                    revision = manifest.checkpoints["conversion"]["groups"][
                        group_id]["revision"]
                    manifest.transition_checkpoint(
                        "conversion", status, revision, service.jobs_dir,
                        group_id=group_id)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                current = client.get(f"/api/v1/jobs/{job_id}").json()
                groups = current["checkpoints"]["conversion"]["groups"]
                group_id = next(iter(groups))
                # The expected revision belongs to the addressed group.
                response = client.post(
                    f"/api/v1/jobs/{job_id}/checkpoints/conversion/accept",
                    json={"expected_revision": groups[group_id]["revision"],
                          "group": group_id})
                self.assertEqual(response.status_code, 200, response.text)
                groups = service.get_job(job_id).checkpoints["conversion"]["groups"]
                self.assertEqual(groups[group_id]["status"], "completed")
                others = {key: value["status"]
                          for key, value in groups.items() if key != group_id}
                self.assertEqual(set(others.values()), {"awaiting_review"})

    def test_render_stales_only_the_named_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": False, "subtitles": {"skip": True}},
                "platforms": {"youtube": {"conversion": {"strict": True}}}})
            groups = manifest.checkpoints["conversion"]["groups"]
            self.assertEqual(len(groups), 2)
            for group_id in list(groups):
                for status in ("running", "awaiting_review", "completed"):
                    manifest = service.get_job(manifest.job_id)
                    revision = manifest.checkpoints["conversion"]["groups"][
                        group_id]["revision"]
                    manifest.transition_checkpoint(
                        "conversion", status, revision, service.jobs_dir,
                        group_id=group_id)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                groups = service.get_job(job_id).checkpoints["conversion"]["groups"]
                group_id = next(iter(groups))
                # The render route takes the addressed group in the body, the
                # same binding the accept route uses.
                with patch.object(JobService, "resume_job",
                                  return_value=service.get_job(job_id)):
                    response = client.post(
                        f"/api/v1/jobs/{job_id}/render",
                        json={"group": group_id})
                self.assertEqual(response.status_code, 202, response.text)
                after = service.get_job(job_id).checkpoints["conversion"]["groups"]
                self.assertEqual(after[group_id]["status"], "stale")
                others = {key: value["status"]
                          for key, value in after.items() if key != group_id}
                self.assertEqual(set(others.values()), {"completed"})

    def test_upload_draft_reports_per_platform_summaries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": False, "subtitles": {"skip": True}},
                "upload": {"content": {"title": "Job title"}},
                "platforms": {
                    "youtube": {"conversion": {"skip": True},
                                "upload": {"skip": True}},
                    "tiktok": {"privacy_level": "SELF_ONLY"},
                }})
            # The group that skips conversion binds the registered source copy,
            # which is what its upload attempt would send; the rendering group
            # binds its own render.
            groups = conversion_groups(manifest.configuration)
            skip_group = next(group["id"] for group in groups
                              if group["conversion"].get("skip"))
            render_group = next(group["id"] for group in groups
                                if group["id"] != skip_group)
            manifest.record_artifact("source", source, service.jobs_dir,
                                     group_id=skip_group)
            render_dir = data_dir / "output" / manifest.job_id
            render_dir.mkdir(parents=True)
            render_path = render_dir / "vertical.mp4"
            render_path.write_bytes(b"rendered artifact")
            manifest.record_artifact("primary", render_path, service.jobs_dir,
                                     group_id=render_group)
            manifest = service.get_job(manifest.job_id)
            upload_cp = manifest.checkpoints["upload"]
            manifest.transition_checkpoint(
                "upload", "awaiting_review", upload_cp["revision"],
                service.jobs_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                draft = client.get(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload").json()
                summaries = draft["platform_summaries"]
                self.assertEqual(set(summaries),
                                 {"youtube", "instagram", "tiktok", "twitter",
                                  "facebook"})
                # YouTube skips the upload entirely; the others participate.
                self.assertFalse(summaries["youtube"]["participates"])
                self.assertTrue(summaries["tiktok"]["participates"])
                # YouTube renders nothing, so it would upload the source.
                self.assertEqual(summaries["youtube"]["kind"], "source")
                self.assertEqual(summaries["tiktok"]["kind"], "vertical")
                self.assertNotEqual(
                    summaries["youtube"]["group_id"],
                    summaries["tiktok"]["group_id"])
                self.assertEqual(
                    summaries["tiktok"]["upload"]["content"]["title"],
                    "Job title")

    def _reviewed_upload_job(self, data_dir: Path):
        """Create a job at the upload review gate."""
        (data_dir / "sources").mkdir(parents=True)
        source = data_dir / "sources" / "clip.mp4"
        source.write_bytes(b"source")
        service = JobService(data_dir)
        manifest = service.create_job(source.name, {
            "conversion": {"skip": True, "subtitles": {"skip": True}},
        })
        manifest.transition_checkpoint(
            "upload", "awaiting_review",
            manifest.checkpoints["upload"]["revision"], service.jobs_dir)
        return service, manifest

    def test_upload_draft_rejects_a_per_platform_conversion_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_upload_job(data_dir)
            revision = service.get_job(
                manifest.job_id).checkpoints["upload"]["revision"]
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                # ``platforms.<p>.conversion`` flows through the composition
                # review, not the upload draft.
                rejected = client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": revision,
                          "upload": {"content": {"title": "x"}},
                          "platforms": {"tiktok": {"conversion": {"skip": True}}}})
                self.assertEqual(rejected.status_code, 422, rejected.text)

                # The upload slice remains editable at the same revision.
                accepted = client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": revision,
                          "upload": {"content": {"title": "x"}},
                          "platforms": {"tiktok": {"upload": {"skip": False}}}})
                self.assertEqual(accepted.status_code, 200, accepted.text)

    def test_suggest_route_writes_block_and_get_carries_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_upload_job(data_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                response = client.post(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload/suggest", json={})
                self.assertEqual(response.status_code, 202, response.text)
                body = response.json()
                self.assertIn("upload", body)
                self.assertIn("suggestions", body["upload"])
                self.assertIn("youtube", body["upload"]["suggestions"])

                # GET carries the block
                fetched = client.get(f"/api/v1/jobs/{job_id}/checkpoints/upload")
                self.assertEqual(fetched.status_code, 200)
                self.assertIn("suggestions", fetched.json()["upload"])

    def test_suggest_round_trips_through_a_following_draft_put(self):
        # The generated block lives inside ``upload``, so the validator must
        # accept the platform rows or every subsequent draft PUT would fail.
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_upload_job(data_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                suggested = client.post(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload/suggest", json={})
                self.assertEqual(suggested.status_code, 202, suggested.text)
                revision = suggested.json()["checkpoint"]["revision"]

                put = client.put(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload",
                    json={"expected_revision": revision,
                          "upload": {"content": {"title": "Edited after generate"}}})
                self.assertEqual(put.status_code, 200, put.text)
                body = put.json()
                self.assertEqual(body["upload"]["content"]["title"],
                                 "Edited after generate")
                self.assertIn("youtube", body["upload"]["suggestions"])

    def test_suggest_route_404_for_unknown_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                response = client.post(
                    "/api/v1/jobs/unknown/checkpoints/upload/suggest", json={})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_suggest_route_422_before_awaiting_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {})
            service.close()

            with TestClient(create_app(data_dir)) as client:
                response = client.post(
                    f"/api/v1/jobs/{manifest.job_id}/checkpoints/upload/suggest",
                    json={})
                self.assertEqual(response.status_code, 409)

    def test_accept_suggestions_route_copies_and_clears(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_upload_job(data_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                suggested = client.post(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload/suggest", json={})
                self.assertEqual(suggested.status_code, 202, suggested.text)
                suggestion = suggested.json()["upload"]["suggestions"]["youtube"]

                accepted = client.post(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload/suggestions/accept",
                    json={"platforms": ["youtube"]})
                self.assertEqual(accepted.status_code, 202, accepted.text)
                body = accepted.json()
                self.assertEqual(body["upload"]["content"]["title"],
                                 suggestion["title"])
                self.assertNotIn("youtube", body["upload"]["suggestions"])

    def test_accept_suggestions_route_404_for_unknown_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                response = client.post(
                    "/api/v1/jobs/unknown/checkpoints/upload/suggestions/accept",
                    json={"platforms": ["youtube"]})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_accept_suggestions_route_422_for_missing_platform(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            service, manifest = self._reviewed_upload_job(data_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                client.post(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload/suggest",
                    json={"platforms": ["youtube"]})
                response = client.post(
                    f"/api/v1/jobs/{job_id}/checkpoints/upload/suggestions/accept",
                    json={"platforms": ["tiktok"]})
                self.assertEqual(response.status_code, 422)


class _PretendRemoteStorage:
    """A non-local backend that owns no bytes on this machine."""

    def __init__(self):
        self.removed: list[str] = []

    def remove(self, key):
        self.removed.append(key)

    def health(self):
        return ("ok", "pretend backend at gs://bucket")


@unittest.skipUnless(TestClient and create_app, "web extra is not installed")
class WebArtifactStorageTests(unittest.TestCase):
    def test_artifact_routes_run_on_the_injected_storage_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"skip": True, "subtitles": {"skip": True}}})
            job_id = manifest.job_id
            manifest_dir = service.jobs_dir
            artifact_dir = data_dir / "output" / job_id
            artifact_dir.mkdir(parents=True)
            rendered = artifact_dir / "clip.mp4"
            rendered.write_bytes(b"0" * 20)
            manifest.record_artifact("primary", rendered, manifest_dir)
            artifact_id = manifest.current_artifact_id
            storage_key = manifest.artifacts[artifact_id]["storage"]["key"]
            service.close()

            app = create_app(data_dir)
            pretend = _PretendRemoteStorage()
            app.state.job_service._storage = pretend
            with TestClient(app) as client:
                listed = client.get(f"/api/v1/jobs/{job_id}/artifacts")
                self.assertEqual(listed.status_code, 200, listed.text)
                for record in listed.json():
                    self.assertNotIn("path", record)
                    self.assertEqual(record["storage"]["backend"], "local")
                fetched = client.get(
                    f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}")
                self.assertEqual(fetched.json()["storage"],
                                 {"backend": "local", "key": storage_key})
                renamed = client.patch(
                    f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}",
                    json={"display_name": "renamed.mp4"})
                self.assertEqual(renamed.status_code, 200, renamed.text)
                self.assertEqual(renamed.json()["display_name"], "renamed.mp4")

                # A backend without local bytes cannot stream a preview.
                for route in ("preview", "download"):
                    response = client.get(
                        f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}/{route}")
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(response.json()["error"]["code"],
                                     "storage_unavailable")

                deleted = client.delete(
                    f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}"
                    "?confirm=true")
                self.assertEqual(deleted.status_code, 200, deleted.text)

            # Delete recycles through the backend, not through the local file.
            self.assertEqual(pretend.removed, [storage_key])
            self.assertTrue(rendered.exists())
            tombstoned = client.get(
                f"/api/v1/jobs/{job_id}/artifacts/{artifact_id}")
            self.assertEqual(tombstoned.status_code, 404)


@unittest.skipUnless(TestClient and create_app, "web extra is not installed")
class WebMetricsTests(unittest.TestCase):
    def test_metrics_routes_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {})
            service.close()

            with TestClient(create_app(data_dir)) as client:
                job_id = manifest.job_id
                response = client.get(f"/api/v1/jobs/{job_id}/metrics")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), [])

    def test_metrics_pull_route_404_for_unknown_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                response = client.post("/api/v1/jobs/unknown/metrics/pull")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_metrics_pull_route_with_mocked_collectors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {})
            job_id = manifest.job_id

            # Add a published attempt.
            attempt = {
                "attempt_id": "test-attempt",
                "platform": "youtube",
                "artifact_id": manifest.current_artifact_id,
                "artifact_hash": "abc",
                "configuration_snapshot": {},
                "configuration_hash": "hash",
                "content_hash": "content",
                "created_at": "2026-01-01T00:00:00+00:00",
                "started_at": "2026-01-01T00:00:01+00:00",
                "completed_at": "2026-01-01T00:00:02+00:00",
                "status": "published",
                "result": {
                    "success": True,
                    "message": "ok",
                    "platform_post_id": "yt123",
                    "platform_url": "https://www.youtube.com/watch?v=yt123",
                    "published_at": "2026-01-01T00:00:02+00:00",
                },
            }
            manifest.upload_attempts.append(attempt)
            manifest.save(service.jobs_dir)
            service.close()

            with TestClient(create_app(data_dir)) as client:
                with patch("clipmorph.service.collect_platform_metrics",
                           return_value={"yt123": {"views": 42}}):
                    response = client.post(f"/api/v1/jobs/{job_id}/metrics/pull")
                self.assertEqual(response.status_code, 202)
                body = response.json()
                self.assertEqual(body["pulled"], 1)
                self.assertEqual(body["snapshots"][0]["platform"], "youtube")
                self.assertEqual(body["snapshots"][0]["metrics"], {"views": 42})

                # Verify the snapshot is persisted.
                listed = client.get(f"/api/v1/jobs/{job_id}/metrics")
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(len(listed.json()), 1)

    def _seed_published_attempt(self, service, manifest, configuration=None):
        attempt = {
            "attempt_id": "test-attempt",
            "platform": "youtube",
            "artifact_id": manifest.current_artifact_id,
            "configuration_snapshot": configuration or {},
            "configuration_hash": "hash",
            "content_hash": "content",
            "created_at": "2026-01-01T00:00:00+00:00",
            "status": "published",
            "result": {
                "success": True,
                "message": "ok",
                "platform_post_id": "yt123",
                "platform_url": "https://www.youtube.com/watch?v=yt123",
                "published_at": "2026-01-01T00:00:02+00:00",
            },
        }
        manifest.upload_attempts.append(attempt)
        manifest.save(service.jobs_dir)

    def test_metrics_include_dimensions_join(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            save_app_configuration(data_dir / "app.yml", {
                "layouts": [{"id": "l1", "name": "L1", "layout": {}}],
            })
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {
                    "layout_id": "l1",
                    "subtitles": {"renderer": "overlay"},
                },
            })
            job_id = manifest.job_id
            self._seed_published_attempt(service, manifest, {
                "upload": {"content": {"title": "Clip Title"}},
            })
            append_snapshot(service.jobs_dir / job_id, {
                "captured_at": "2026-01-01T00:00:00+00:00",
                "platform": "youtube",
                "platform_post_id": "yt123",
                "metrics": {"views": 100},
                "unavailable": False,
                "unavailable_reason": None,
                "duration_seconds": 45,
            })
            service.close()

            with TestClient(create_app(data_dir)) as client:
                raw = client.get(f"/api/v1/jobs/{job_id}/metrics")
                self.assertEqual(raw.status_code, 200)
                self.assertNotIn("layout_id", raw.json()[0])

                joined = client.get(
                    f"/api/v1/jobs/{job_id}/metrics?include=dimensions")
                self.assertEqual(joined.status_code, 200)
                record = joined.json()[0]
                self.assertEqual(record["layout_id"], "l1")
                self.assertEqual(record["subtitles_renderer"], "overlay")
                self.assertEqual(record["title"], "Clip Title")
                self.assertEqual(record["duration_seconds"], 45)
                self.assertIsNone(record["platform_overrides"])

                bad = client.get(f"/api/v1/jobs/{job_id}/metrics?include=nope")
                self.assertEqual(bad.status_code, 422)
                self.assertEqual(bad.json()["error"]["code"], "invalid_include")

    def test_metrics_empty_include_is_raw(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {})
            job_id = manifest.job_id
            service.close()

            with TestClient(create_app(data_dir)) as client:
                response = client.get(f"/api/v1/jobs/{job_id}/metrics?include=")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), [])

    def test_comparison_route_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            with TestClient(create_app(data_dir)) as client:
                response = client.get("/api/v1/metrics/comparison")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), [])

    def test_comparison_route_returns_latest_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "sources").mkdir(parents=True)
            source = data_dir / "sources" / "clip.mp4"
            source.write_bytes(b"source")
            save_app_configuration(data_dir / "app.yml", {
                "layouts": [{"id": "l1", "name": "L1", "layout": {}}],
            })
            service = JobService(data_dir)
            manifest = service.create_job(source.name, {
                "conversion": {"layout_id": "l1",
                               "subtitles": {"renderer": "overlay"}},
            })
            job_id = manifest.job_id
            self._seed_published_attempt(service, manifest, {
                "upload": {"content": {"title": "Clip"}},
            })
            job_dir = service.jobs_dir / job_id
            append_snapshot(job_dir, {
                "captured_at": "2026-01-01T00:00:00+00:00",
                "platform": "youtube", "platform_post_id": "yt123",
                "metrics": {"views": 100, "likes": 10},
                "unavailable": False, "unavailable_reason": None,
            })
            append_snapshot(job_dir, {
                "captured_at": "2026-01-02T00:00:00+00:00",
                "platform": "youtube", "platform_post_id": "yt123",
                "metrics": {"views": 150, "likes": 15},
                "unavailable": False, "unavailable_reason": None,
            })
            service.close()

            with TestClient(create_app(data_dir)) as client:
                response = client.get("/api/v1/metrics/comparison")
                self.assertEqual(response.status_code, 200)
                rows = response.json()
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row["platform"], "youtube")
                self.assertEqual(row["views"], 150)
                self.assertEqual(row["views_delta"], 50)
                self.assertEqual(row["likes_delta"], 5)
                self.assertEqual(row["duration_bucket"], "unknown")
                self.assertEqual(row["title"], "Clip")
                self.assertEqual(row["layout_id"], "l1")

    def test_comparison_route_platform_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                response = client.get("/api/v1/metrics/comparison?platform=unknown")
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "invalid_platform")

    def test_comparison_route_limit_bounds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with TestClient(create_app(data_dir)) as client:
                self.assertEqual(
                    client.get("/api/v1/metrics/comparison?limit=0").status_code, 422)
                self.assertEqual(
                    client.get("/api/v1/metrics/comparison?limit=501").status_code, 422)
                self.assertEqual(
                    client.get("/api/v1/metrics/comparison?limit=100").status_code, 200)


if __name__ == "__main__":
    unittest.main()
