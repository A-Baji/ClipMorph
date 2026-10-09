"""Desktop launcher for the ClipMorph UI executable.

The ``clipmorph-ui`` console script runs the native desktop shell on Windows
(pywebview window + pystray tray, see ``clipmorph.desktop_app``) and falls back
to the original browser launcher elsewhere. Both front ends start the same
local API service in-process and serve the same built dashboard, so
``clipmorph web`` (``clipmorph.web``) stays the headless service. Kept separate
from ``clipmorph.web`` so the headless ``clipmorph web`` command and CLI-only
builds never require this module.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser


def find_free_port(host: str = "127.0.0.1", preferred: int | None = None) -> int:
    """Return an available TCP port on the given loopback host."""
    for candidate in ([preferred] if preferred else []) + [0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise RuntimeError("No available loopback port could be found")


def wait_for_health(url: str, timeout: float = 15.0, interval: float = 0.1,
                     requester=None) -> bool:
    """Poll the health endpoint until it responds or the timeout elapses."""
    import urllib.error
    import urllib.request

    request = requester or (lambda: urllib.request.urlopen(url, timeout=1))
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with request() as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError) as error:
            last_error = error
        time.sleep(interval)
    raise TimeoutError(f"Health check at {url} did not succeed: {last_error}")


class LocalUiServer:
    """A running local UI service that can be shut down cleanly."""

    def __init__(self, server, thread, url: str, port: int) -> None:
        self.server = server
        self.thread = thread
        self.url = url
        self.port = port

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def start_local_server(host: str = "127.0.0.1", port: int | None = None,
                       data_dir=None, health_timeout: float = 15.0,
                       uvicorn_module=None, create_app_fn=None,
                       health_check=None) -> LocalUiServer:
    """Start the local API in a background thread and wait for readiness."""
    if uvicorn_module is None:
        try:
            import uvicorn as uvicorn_module
        except ImportError as error:
            raise RuntimeError(
                "The UI requires the optional 'web' dependencies. "
                "Install them with: python -m pip install 'clipmorph[web]'"
            ) from error

    if create_app_fn is None:
        from clipmorph.web import create_app as create_app_fn

    selected_port = find_free_port(host, port)
    app = create_app_fn(data_dir)
    config = uvicorn_module.Config(app, host=host, port=selected_port,
                                    log_level="warning")
    server = uvicorn_module.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://{host}:{selected_port}/"
    health_url = f"http://{host}:{selected_port}/api/v1/health"
    checker = health_check or wait_for_health
    try:
        checker(health_url, timeout=health_timeout)
    except TimeoutError:
        server.should_exit = True
        thread.join(timeout=5)
        raise

    return LocalUiServer(server, thread, url, selected_port)


def run_ui(host: str = "127.0.0.1", port: int | None = None, data_dir=None,
           open_browser: bool = True, health_timeout: float = 15.0,
           uvicorn_module=None, create_app_fn=None, browser_opener=None,
           health_check=None, run_forever: bool = True,
           _force_import_error: bool = False) -> int:
    """Start the local API, wait for readiness, open the browser, and block until shutdown."""
    if _force_import_error:
        raise RuntimeError(
            "The UI requires the optional 'web' dependencies. "
            "Install them with: python -m pip install 'clipmorph[web]'")

    server = start_local_server(
        host=host, port=port, data_dir=data_dir, health_timeout=health_timeout,
        uvicorn_module=uvicorn_module, create_app_fn=create_app_fn,
        health_check=health_check)

    if open_browser:
        opener = browser_opener or webbrowser.open
        opener(server.url)

    if run_forever:
        try:
            while server.thread.is_alive():
                server.thread.join(timeout=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
    else:
        server.stop()

    return server.port


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the ClipMorph desktop UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--no-browser", action="store_true",
                        help="Run the local service without a native window or "
                             "browser (the headless service is `clipmorph web`).")
    args = parser.parse_args()

    from clipmorph.desktop_app import desktop_available, run_desktop

    if not args.no_browser and desktop_available():
        try:
            run_desktop(host=args.host, port=args.port, data_dir=args.data_dir)
            return
        except RuntimeError as error:
            print(f"Failed to start ClipMorph desktop: {error}", file=sys.stderr)
            sys.exit(1)

    try:
        run_ui(host=args.host, port=args.port, data_dir=args.data_dir,
               open_browser=not args.no_browser)
    except RuntimeError as error:
        print(f"Failed to start ClipMorph UI: {error}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as error:
        print(f"ClipMorph UI failed to become ready: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
