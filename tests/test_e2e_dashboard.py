"""Packaged browser E2E smoke tests for the dashboard, at desktop and mobile sizes.

Skipped unless both the web extra and the ``playwright`` package (with its
browsers installed) are available. See ``.github/workflows/tests.yml`` for the
dedicated CI job that installs both before running this file.
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

try:
    import uvicorn
    from playwright.sync_api import sync_playwright

    from clipmorph.ui_launcher import find_free_port, wait_for_health
    from clipmorph.transcript import create_edit_session
    from clipmorph.web import create_app
except ImportError:
    uvicorn = None
    sync_playwright = None
    create_app = None
    create_edit_session = None

DESKTOP_VIEWPORT = {"width": 1280, "height": 800}
MOBILE_VIEWPORT = {"width": 375, "height": 667}


@unittest.skipUnless(uvicorn and sync_playwright and create_app,
                      "requires the web extra and an installed playwright browser")
class DashboardBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.source_dir = Path(cls._temp_dir.name) / "sources"
        cls.source_dir.mkdir()
        (cls.source_dir / "clip.mp4").write_bytes(b"test source")
        cls.port = find_free_port("127.0.0.1")
        cls.app = create_app(Path(cls._temp_dir.name))
        cls.server = uvicorn.Server(
            uvicorn.Config(cls.app,
                           host="127.0.0.1", port=cls.port, log_level="warning"))
        import threading
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        wait_for_health(f"http://127.0.0.1:{cls.port}/api/v1/health", timeout=15)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls._temp_dir.cleanup()

    def _dashboard_loads(self, viewport):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport=viewport)
                response = page.goto(f"http://127.0.0.1:{self.port}/")
                page.wait_for_load_state("networkidle")
                self.assertTrue(response.ok)
                self.assertGreater(len(page.content()), 0)
            finally:
                browser.close()

    def test_dashboard_loads_at_desktop_size(self):
        self._dashboard_loads(DESKTOP_VIEWPORT)

    def test_dashboard_loads_at_mobile_size(self):
        self._dashboard_loads(MOBILE_VIEWPORT)

    def test_per_source_title_override_reaches_validation_on_desktop_and_mobile(self):
        for viewport in (DESKTOP_VIEWPORT, MOBILE_VIEWPORT):
            with self.subTest(viewport=viewport), sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport=viewport)
                    page.goto(f"http://127.0.0.1:{self.port}/")
                    page.wait_for_load_state("networkidle")
                    # The create/upload surface is the default queue view.
                    page.locator(".source-option input").check()
                    page.get_by_role(
                        "button", name="Overrides: clip.mp4").click()
                    page.get_by_label("Clip title").fill("Per-clip title")
                    page.get_by_label("Validate only").check()

                    with page.expect_response(
                            lambda response: response.url.endswith(
                                "/api/v1/jobs/validate")
                            and response.request.method == "POST") as response_info:
                        page.get_by_role("button", name="Validate").click()

                    response = response_info.value
                    self.assertEqual(response.status, 200)
                    effective = response.json()["effective_configurations"]
                    self.assertEqual(len(effective), 1)
                    self.assertEqual(
                        effective[0]["configuration"]["upload"]["content"]["title"],
                        "Per-clip title")
                finally:
                    browser.close()

    def test_review_ui_edits_transcript_composition_and_upload_draft(self):
        service = self.app.state.job_service
        manifest = service.create_job("clip.mp4", {})
        session = create_edit_session(
            manifest.source_sha256,
            [{"id": "segment-1", "start": 0.0, "end": 1.0, "text": "Before"}],
            media_duration=2.0)
        service.save_transcript_session(
            manifest.job_id, session, expected_revision=0,
            expected_checkpoint_revision=manifest.checkpoints["transcript"]["revision"])

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport=DESKTOP_VIEWPORT)
                page.goto(f"http://127.0.0.1:{self.port}/")
                page.wait_for_load_state("networkidle")
                # Depth is one deliberate step: open the job, then its Review tab.
                page.locator(".job-card").first.click()
                page.get_by_role("tab", name="Review").click()
                page.get_by_label("Segment 1 start time").fill("0.25")
                page.get_by_label("Segment 1 end time").fill("1.5")
                page.get_by_label("Transcript segment 1").fill("After")
                page.locator(".segment-typography summary").click()
                page.get_by_label("Segment 1 font size").fill("32")
                page.get_by_label("Segment 1 italic").check()
                with page.expect_response(
                        lambda response: response.url.endswith(
                            f"/api/v1/jobs/{manifest.job_id}/transcript")
                        and response.request.method == "PUT") as transcript_response:
                    page.get_by_role("button", name="Save transcript revision").click()
                saved_session = transcript_response.value.json()
                self.assertEqual(saved_session["segments"][0]["start"], 0.25)
                self.assertEqual(saved_session["segments"][0]["typography"]["size"], 32)
                self.assertTrue(saved_session["segments"][0]["typography"]["italic"])

                page.get_by_label("Job composition layout").fill(
                    '{"captions":{"overlay":{"items":[]}}}')
                with page.expect_response(
                        lambda response: response.url.endswith(
                            f"/api/v1/jobs/{manifest.job_id}/configuration")
                        and response.request.method == "PATCH") as composition_response:
                    page.get_by_role("button", name="Save job composition").click()
                self.assertEqual(composition_response.value.status, 200)

                page.get_by_role("tab", name="Publish").click()
                page.get_by_label("Upload description").fill("Upload description")
                page.get_by_label("Upload tags").fill("one, two")
                page.get_by_label("Upload schedule for").fill("2027-03-04T05:06")
                self.assertEqual(page.get_by_label("Upload description").input_value(),
                                 "Upload description")
                checkpoint = service.get_job(manifest.job_id).checkpoints["upload"]
                with page.expect_response(
                        lambda response: response.url.endswith(
                            f"/api/v1/jobs/{manifest.job_id}/checkpoints/upload")
                        and response.request.method == "PUT") as draft_response:
                    page.get_by_role("button", name="Save draft").click()
                self.assertEqual(draft_response.value.status, 200)
                saved_job = service.get_job(manifest.job_id)
                self.assertEqual(saved_job.configuration["upload"]["content"][
                    "description"], "Upload description")
                self.assertEqual(saved_job.configuration["upload"]["content"][
                    "tags"], ["one", "two"])
                # The browser sends UTC; this checks the local-time round trip.
                scheduled = saved_job.configuration["upload"]["schedule"]["publish_at"]
                self.assertEqual(
                    datetime.fromisoformat(scheduled).astimezone().strftime(
                        "%Y-%m-%dT%H:%M"), "2027-03-04T05:06")
                self.assertGreaterEqual(
                    saved_job.checkpoints["upload"]["revision"], checkpoint["revision"])
            finally:
                browser.close()


    def test_metrics_view_renders_cross_job_table_with_deltas(self):
        import shutil
        from clipmorph.metrics import append_snapshot
        # Use a dedicated source and clean up afterward so the shared
        # clip.mp4 source and single-source layout the other dashboard tests
        # rely on are restored.
        (self.source_dir / "metrics.mp4").write_bytes(b"metrics source")
        service = self.app.state.job_service
        manifest = service.create_job("metrics.mp4", {})
        job_id = manifest.job_id
        job_dir = service.jobs_dir / job_id
        try:
            attempt = {
                "attempt_id": "test-attempt",
                "platform": "youtube",
                "artifact_id": manifest.current_artifact_id,
                "configuration_snapshot": {
                    "upload": {"content": {"title": "Fixture clip"}},
                },
                "configuration_hash": "hash",
                "content_hash": "content",
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "published",
                "result": {
                    "success": True,
                    "platform_post_id": "yt123",
                    "platform_url": "https://www.youtube.com/watch?v=yt123",
                },
            }
            manifest.upload_attempts.append(attempt)
            manifest.save(service.jobs_dir)
            append_snapshot(job_dir, {
                "captured_at": "2026-01-01T00:00:00+00:00",
                "platform": "youtube",
                "platform_post_id": "yt123",
                "platform_url": "https://www.youtube.com/watch?v=yt123",
                "metrics": {"views": 100, "likes": 10, "comments": 2},
                "source": "youtube:videos.list",
                "unavailable": False,
                "unavailable_reason": None,
                "duration_seconds": 45,
            })
            append_snapshot(job_dir, {
                "captured_at": "2026-01-02T00:00:00+00:00",
                "platform": "youtube",
                "platform_post_id": "yt123",
                "platform_url": "https://www.youtube.com/watch?v=yt123",
                "metrics": {"views": 150, "likes": 15, "comments": 3},
                "source": "youtube:videos.list",
                "unavailable": False,
                "unavailable_reason": None,
                "duration_seconds": 45,
            })

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport=DESKTOP_VIEWPORT)
                    page.goto(f"http://127.0.0.1:{self.port}/")
                    page.wait_for_load_state("networkidle")
                    page.locator(
                        'nav[aria-label="Primary navigation"] button'
                    ).filter(has_text="Metrics").click()
                    page.wait_for_selector(".metric-table")
                    content = page.content()
                    self.assertIn("youtube", content)
                    self.assertIn("Fixture clip", content)
                    self.assertIn("150", content)
                    self.assertIn("+50", content)
                    self.assertIn("[30,60)", content)
                finally:
                    browser.close()
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
            (self.source_dir / "metrics.mp4").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
