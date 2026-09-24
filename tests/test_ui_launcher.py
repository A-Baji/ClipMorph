import socket
import threading
import time
import unittest
from unittest.mock import MagicMock

from clipmorph.ui_launcher import find_free_port
from clipmorph.ui_launcher import run_ui
from clipmorph.ui_launcher import wait_for_health


class FindFreePortTests(unittest.TestCase):
    def test_returns_available_loopback_port(self):
        port = find_free_port("127.0.0.1")
        self.assertIsInstance(port, int)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))

    def test_falls_back_when_preferred_port_is_taken(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen(1)
            taken_port = blocker.getsockname()[1]
            port = find_free_port("127.0.0.1", preferred=taken_port)
            self.assertNotEqual(port, taken_port)
        finally:
            blocker.close()


class WaitForHealthTests(unittest.TestCase):
    def test_returns_when_request_succeeds(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        requester = MagicMock(return_value=response)

        self.assertTrue(
            wait_for_health("http://127.0.0.1:1/api/v1/health",
                             timeout=1, interval=0.01, requester=requester))

    def test_raises_timeout_when_never_ready(self):
        requester = MagicMock(side_effect=OSError("connection refused"))

        with self.assertRaises(TimeoutError):
            wait_for_health("http://127.0.0.1:1/api/v1/health",
                             timeout=0.2, interval=0.05, requester=requester)


class RunUiTests(unittest.TestCase):
    def test_starts_server_waits_for_health_opens_browser_and_shuts_down(self):
        server = MagicMock()
        server.should_exit = False

        def fake_run():
            while not server.should_exit:
                time.sleep(0.01)

        server.run.side_effect = fake_run

        uvicorn_module = MagicMock()
        uvicorn_module.Config.return_value = "config"
        uvicorn_module.Server.return_value = server

        browser_opener = MagicMock()
        health_check = MagicMock(return_value=True)
        create_app_fn = MagicMock(return_value="app")

        shutdown_event = threading.Event()

        def fake_health_check(url, timeout):
            shutdown_event.set()
            return True

        health_check.side_effect = fake_health_check

        def stop_after_health(*_args, **_kwargs):
            shutdown_event.wait(timeout=2)

        result_port = run_ui(
            host="127.0.0.1",
            port=5000,
            data_dir=None,
            open_browser=True,
            uvicorn_module=uvicorn_module,
            create_app_fn=create_app_fn,
            browser_opener=browser_opener,
            health_check=health_check,
            run_forever=False)

        self.assertEqual(result_port, 5000)
        create_app_fn.assert_called_once_with(None)
        uvicorn_module.Server.assert_called_once_with("config")
        health_check.assert_called_once()
        browser_opener.assert_called_once_with("http://127.0.0.1:5000/")
        self.assertTrue(server.should_exit)

    def test_raises_when_web_dependencies_missing(self):
        with self.assertRaises(RuntimeError):
            run_ui(uvicorn_module=None, _force_import_error=True)

    def test_shuts_down_and_reraises_when_health_check_times_out(self):
        server = MagicMock()
        server.should_exit = False
        server.run.side_effect = lambda: None

        uvicorn_module = MagicMock()
        uvicorn_module.Config.return_value = "config"
        uvicorn_module.Server.return_value = server

        health_check = MagicMock(side_effect=TimeoutError("not ready"))

        with self.assertRaises(TimeoutError):
            run_ui(
                uvicorn_module=uvicorn_module,
                create_app_fn=MagicMock(return_value="app"),
                browser_opener=MagicMock(),
                health_check=health_check,
                run_forever=False)

        self.assertTrue(server.should_exit)


if __name__ == "__main__":
    unittest.main()
