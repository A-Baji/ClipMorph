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


if __name__ == "__main__":
    unittest.main()
