import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from clipmorph.web import create_app
except ImportError:  # CLI-only installations do not include the web extra.
    TestClient = None
    create_app = None


@unittest.skipUnless(TestClient and create_app, "web extra is not installed")
class WebApiTests(unittest.TestCase):
    def test_job_lifecycle_endpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            client = TestClient(create_app(Path(temp_dir) / "data"))

            self.assertEqual(client.get("/api/v1/health").status_code, 200)
            response = client.post(
                "/api/v1/jobs",
                json={"source_path": str(source), "configuration": {}})
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}").status_code, 200)
            manifest = client.get(f"/api/v1/jobs/{job_id}").json()
            transcript = {
                "schema_version": 1,
                "source_sha256": manifest["source_sha256"],
                "media_duration": 2.0,
                "original_segments": [{"start": 0, "end": 1, "text": "Hi"}],
                "segments": [{"start": 0, "end": 1, "text": "Hello"}],
            }
            self.assertEqual(
                client.put(f"/api/v1/jobs/{job_id}/transcript",
                           json=transcript).status_code, 200)
            self.assertEqual(
                client.get(f"/api/v1/jobs/{job_id}/transcript").json()["segments"][0]["text"],
                "Hello")
            self.assertEqual(
                client.post(f"/api/v1/jobs/{job_id}/cancel",
                            json={"confirm": True}).status_code, 200)

    def test_invalid_job_requests_return_client_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = TestClient(create_app(Path(temp_dir) / "data"))
            self.assertEqual(
                client.post("/api/v1/jobs", json={"source_path": "missing"}).status_code,
                400)
            self.assertEqual(client.get("/api/v1/jobs/missing").status_code, 404)

    def test_upload_requires_a_rendered_artifact_and_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            with TestClient(create_app(Path(temp_dir) / "data")) as client:
                job = client.post("/api/v1/jobs", json={
                    "source_path": str(source), "configuration": {}}).json()
                response = client.post(
                    f"/api/v1/jobs/{job['job_id']}/upload",
                    json={"platforms": ["youtube"]})
                self.assertEqual(response.status_code, 409)

    def test_job_creation_uses_shared_execution_runner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            with TestClient(create_app(Path(temp_dir) / "data")) as client:
                response = client.post("/api/v1/jobs", json={
                    "source_path": str(source),
                    "configuration": {"no_upload": True},
                })
                self.assertEqual(response.status_code, 202)

    def test_configuration_masks_credentials_and_artifacts_are_listed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.mp4"
            source.write_bytes(b"video")
            client = TestClient(create_app(Path(temp_dir) / "data"))
            saved = client.put("/api/v1/configuration", json={
                "configuration": {
                    "title": "Clip",
                    "youtube_client_secret": "secret-value",
                }
            })
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(
                client.get("/api/v1/configuration").json()["configuration"][
                    "youtube_client_secret"], "••••••••")
            job = client.post("/api/v1/jobs", json={
                "source_path": str(source), "configuration": {}}).json()
            self.assertEqual(
                client.get(f"/api/v1/jobs/{job['job_id']}/artifacts").status_code, 200)


if __name__ == "__main__":
    unittest.main()
