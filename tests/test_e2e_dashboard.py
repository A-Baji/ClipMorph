"""Packaged browser E2E smoke tests for the dashboard, at desktop and mobile sizes.

Skipped unless both the web extra and the ``playwright`` package (with its
browsers installed) are available. See ``.github/workflows/tests.yml`` for the
dedicated CI job that installs both before running this file.
"""

import tempfile
import unittest
from pathlib import Path

try:
    import uvicorn
    from playwright.sync_api import sync_playwright

    from clipmorph.ui_launcher import find_free_port, wait_for_health
    from clipmorph.web import create_app
except ImportError:
    uvicorn = None
    sync_playwright = None
    create_app = None

DESKTOP_VIEWPORT = {"width": 1280, "height": 800}
MOBILE_VIEWPORT = {"width": 375, "height": 667}


@unittest.skipUnless(uvicorn and sync_playwright and create_app,
                      "requires the web extra and an installed playwright browser")
class DashboardBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.port = find_free_port("127.0.0.1")
        cls.server = uvicorn.Server(
            uvicorn.Config(create_app(Path(cls._temp_dir.name)),
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


if __name__ == "__main__":
    unittest.main()
