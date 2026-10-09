"""Desktop shell for ClipMorph: native window, tray residency, and logon launch.

Windows-only for v1. The shell wraps the same local FastAPI service and the
same built ``web_assets`` dashboard that ``clipmorph web`` serves, so the web
app and the desktop app stay one application (see ``docs/CLI_WEB_PARITY.md``).
The native window (pywebview), the tray icon (pystray), and the run-at-logon
registry entry are the only additions; the backend surface is unchanged.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Optional

WINDOW_TITLE = "ClipMorph"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_RUN_VALUE = "ClipMorph"
ICON_FILENAME = "clipmorph.ico"


def icon_path() -> Path:
    """Return the packaged tray/window/installer icon path."""
    return Path(__file__).resolve().parent / "resources" / ICON_FILENAME


def _module_available(name: str) -> bool:
    try:
        importlib.import_module(name)
    except ImportError:
        return False
    return True


def _load_module(name: str, package: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as error:
        raise RuntimeError(
            "The desktop shell requires the optional 'web' dependencies "
            f"({package}). Install them with: "
            "python -m pip install 'clipmorph[web]'"
        ) from error


def desktop_available(platform: Optional[str] = None) -> bool:
    """True when the native shell can run here: Windows with pywebview + pystray."""
    if (platform or sys.platform) != "win32":
        return False
    return _module_available("webview") and _module_available("pystray")


def _winreg() -> Any:
    try:
        return importlib.import_module("winreg")
    except ImportError as error:
        raise RuntimeError(
            "Run-at-logon is only available on Windows.") from error


def logon_command(executable: Optional[str] = None,
                  frozen: Optional[bool] = None) -> str:
    """Return the command line stored in the Run key.

    A frozen build is its own executable; a source checkout is launched through
    ``python -m clipmorph.desktop_app``.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    exe = executable or sys.executable
    if frozen:
        return f'"{exe}"'
    return f'"{exe}" -m clipmorph.desktop_app'


def is_run_at_logon_enabled(run_key: str = WINDOWS_RUN_KEY,
                            value_name: str = WINDOWS_RUN_VALUE,
                            registry: Any = None) -> bool:
    """Return whether the ClipMorph Run entry exists."""
    registry = registry or _winreg()
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, run_key, 0,
                              registry.KEY_READ) as key:
            registry.QueryValueEx(key, value_name)
    except (FileNotFoundError, OSError):
        return False
    return True


def set_run_at_logon(enabled: bool, command: Optional[str] = None,
                     run_key: str = WINDOWS_RUN_KEY,
                     value_name: str = WINDOWS_RUN_VALUE,
                     registry: Any = None) -> bool:
    """Create or delete the ClipMorph Run entry; return the resulting state."""
    registry = registry or _winreg()
    with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, run_key, 0,
                              registry.KEY_SET_VALUE) as key:
        if enabled:
            registry.SetValueEx(key, value_name, 0, registry.REG_SZ,
                                command or logon_command())
        else:
            try:
                registry.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass
    return enabled


class DesktopController:
    """Window/tray state for one desktop session (the unit of testing)."""

    def __init__(self, window: Any, server: Any, registry: Any = None,
                 icon: Any = None) -> None:
        self.window = window
        self.server = server
        self.registry = registry
        self.icon = icon
        self.quitting = False

    def show(self, *_args: Any) -> None:
        self.window.show()

    def hide_on_close(self, *_args: Any) -> bool:
        """Close-to-tray: hide the window and cancel the close (return False)."""
        if self.quitting:
            return True
        self.window.hide()
        return False

    def toggle_logon(self, icon: Any = None, *_args: Any) -> bool:
        enabled = not is_run_at_logon_enabled(registry=self.registry)
        set_run_at_logon(enabled, registry=self.registry)
        target = icon if icon is not None else self.icon
        update = getattr(target, "update_menu", None)
        if callable(update):
            update()
        return enabled

    def quit(self, *_args: Any) -> None:
        self.quitting = True
        self.window.destroy()


def build_menu(pystray: Any, controller: DesktopController) -> Any:
    """Build the tray menu: Show, Launch on logon (checkable), Quit."""
    return pystray.Menu(
        pystray.MenuItem("Show ClipMorph", controller.show),
        pystray.MenuItem(
            "Launch on logon", controller.toggle_logon,
            checked=lambda item: is_run_at_logon_enabled(
                registry=controller.registry)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", controller.quit),
    )


def _load_icon_image() -> Any:
    from PIL import Image

    return Image.open(icon_path())


def _start_local_server(host: str, port: Optional[int], data_dir: Any) -> Any:
    from clipmorph.ui_launcher import start_local_server

    return start_local_server(host=host, port=port, data_dir=data_dir)


def run_desktop(host: str = "127.0.0.1", port: Optional[int] = None,
                data_dir: Any = None, *, platform: Optional[str] = None,
                webview_module: Any = None, tray_module: Any = None,
                image_loader: Any = None, server_starter: Any = None,
                registry: Any = None) -> int:
    """Start the local service, then run the native window with a tray icon.

    Closing the window hides it; Quit destroys it, which ends the GUI loop and
    shuts the local service down.
    """
    if (platform or sys.platform) != "win32":
        raise RuntimeError(
            "The ClipMorph desktop shell is Windows-only in v1; "
            "use 'clipmorph web' on this platform.")
    webview = webview_module or _load_module("webview", "pywebview")
    pystray = tray_module or _load_module("pystray", "pystray")
    if image_loader is None:
        image_loader = _load_icon_image
    start_server = server_starter or _start_local_server

    server = start_server(host=host, port=port, data_dir=data_dir)
    icon = None
    try:
        window = webview.create_window(WINDOW_TITLE, server.url)
        controller = DesktopController(window, server, registry=registry)
        icon = pystray.Icon(WINDOW_TITLE, image_loader(), WINDOW_TITLE,
                            build_menu(pystray, controller))
        controller.icon = icon
        window.events.closing += controller.hide_on_close
        icon.run_detached()
        webview.start(icon=str(icon_path()))
    finally:
        if icon is not None:
            icon.stop()
        server.stop()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ClipMorph desktop app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    try:
        run_desktop(host=args.host, port=args.port, data_dir=args.data_dir)
    except RuntimeError as error:
        print(f"Failed to start ClipMorph desktop: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
