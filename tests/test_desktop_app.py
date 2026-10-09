"""Unit tests for the desktop shell (window, tray, logon) with mocked GUI deps.

The GUI toolkits (pywebview, pystray) are optional and absent from the test
environment, so every test injects fakes; no real window, tray, or registry is
touched.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from clipmorph import desktop_app
from clipmorph.desktop_app import (
    WINDOWS_RUN_KEY,
    WINDOWS_RUN_VALUE,
    DesktopController,
    build_menu,
    desktop_available,
    icon_path,
    is_run_at_logon_enabled,
    logon_command,
    run_desktop,
    set_run_at_logon,
)


class FakeRegistry:
    """Minimal winreg stand-in backed by a dict."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.created = 0

    def OpenKey(self, *_args):
        return self

    def CreateKeyEx(self, *_args):
        self.created += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def QueryValueEx(self, _key, name):
        if name in self.values:
            return self.values[name], self.REG_SZ
        raise FileNotFoundError(name)

    def SetValueEx(self, _key, name, _reserved, _type, value):
        self.values[name] = value

    def DeleteValue(self, _key, name):
        if name in self.values:
            del self.values[name]
        else:
            raise FileNotFoundError(name)


class EventHook:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        result = None
        for handler in self.handlers:
            result = handler(*args)
        return result


class FakeWindow:
    def __init__(self):
        self.events = SimpleNamespace(closing=EventHook())
        self.shown = False
        self.hidden = False
        self.destroyed = False

    def show(self):
        self.shown = True

    def hide(self):
        self.hidden = True

    def destroy(self):
        self.destroyed = True


class FakeWebview:
    def __init__(self, window):
        self.window = window
        self.created = None
        self.started = False
        self.start_icon = None

    def create_window(self, title, url):
        self.created = (title, url)
        return self.window

    def start(self, icon=None, **_kwargs):
        self.started = True
        self.start_icon = icon


class FakeIcon:
    def __init__(self, name, image, title, menu):
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.detached = False
        self.stopped = False
        self.updated = False

    def run_detached(self, setup=None):
        self.detached = True

    def stop(self):
        self.stopped = True

    def update_menu(self):
        self.updated = True


class FakeMenu:
    SEPARATOR = "SEP"

    def __init__(self, *items):
        self.items = items


class FakeMenuItem:
    def __init__(self, text, action, **kwargs):
        self.text = text
        self.action = action
        self.options = kwargs


def fake_pystray():
    created = {}

    def icon_factory(name, image, title, menu):
        created["icon"] = FakeIcon(name, image, title, menu)
        return created["icon"]

    module = SimpleNamespace(Icon=icon_factory, Menu=FakeMenu, MenuItem=FakeMenuItem)
    return module, created


class FakeServer:
    def __init__(self):
        self.url = "http://127.0.0.1:4321/"
        self.stopped = False

    def stop(self):
        self.stopped = True


class LogonRegistryTests(unittest.TestCase):
    def test_disabled_when_value_absent(self):
        self.assertFalse(
            is_run_at_logon_enabled(registry=FakeRegistry()))

    def test_enabled_when_value_present(self):
        registry = FakeRegistry({WINDOWS_RUN_VALUE: '"clipmorph-ui.exe"'})
        self.assertTrue(is_run_at_logon_enabled(registry=registry))

    def test_enable_writes_command_and_disable_removes_it(self):
        registry = FakeRegistry()

        self.assertTrue(set_run_at_logon(
            True, command='"C:/apps/clipmorph-ui.exe"', registry=registry))
        self.assertEqual(registry.values[WINDOWS_RUN_VALUE],
                         '"C:/apps/clipmorph-ui.exe"')

        self.assertFalse(set_run_at_logon(False, registry=registry))
        self.assertNotIn(WINDOWS_RUN_VALUE, registry.values)

    def test_disable_is_idempotent_when_already_absent(self):
        self.assertFalse(set_run_at_logon(False, registry=FakeRegistry()))


class LogonCommandTests(unittest.TestCase):
    def test_frozen_build_is_its_own_executable(self):
        self.assertEqual(
            logon_command(executable="C:/apps/clipmorph-ui.exe", frozen=True),
            '"C:/apps/clipmorph-ui.exe"')

    def test_source_checkout_launches_the_module(self):
        self.assertEqual(
            logon_command(executable="C:/python.exe", frozen=False),
            '"C:/python.exe" -m clipmorph.desktop_app')


class DesktopAvailabilityTests(unittest.TestCase):
    def test_non_windows_platform_is_unavailable(self):
        self.assertFalse(desktop_available("linux"))
        self.assertFalse(desktop_available("darwin"))

    def test_run_desktop_rejects_non_windows(self):
        with self.assertRaises(RuntimeError):
            run_desktop(platform="linux")

    def test_icon_path_points_at_packaged_resource(self):
        self.assertEqual(icon_path().name, "clipmorph.ico")
        self.assertEqual(icon_path().parent.name, "resources")


class DesktopControllerTests(unittest.TestCase):
    def test_hide_on_close_hides_and_cancels(self):
        window = FakeWindow()
        controller = DesktopController(window, FakeServer())
        self.assertFalse(controller.hide_on_close(window))
        self.assertTrue(window.hidden)
        self.assertFalse(window.destroyed)

    def test_hide_on_close_allows_close_after_quit(self):
        window = FakeWindow()
        controller = DesktopController(window, FakeServer())
        controller.quit()
        self.assertTrue(window.destroyed)
        self.assertTrue(controller.hide_on_close(window))

    def test_toggle_logon_flips_the_registry_value(self):
        registry = FakeRegistry()
        icon = MagicMock()
        controller = DesktopController(FakeWindow(), FakeServer(), registry=registry)

        self.assertTrue(controller.toggle_logon(icon, None))
        self.assertIn(WINDOWS_RUN_VALUE, registry.values)
        self.assertTrue(icon.update_menu.called)

        self.assertFalse(controller.toggle_logon(icon, None))
        self.assertNotIn(WINDOWS_RUN_VALUE, registry.values)


class BuildMenuTests(unittest.TestCase):
    def test_menu_has_show_logon_and_quit(self):
        pystray, _created = fake_pystray()
        window = FakeWindow()
        controller = DesktopController(window, FakeServer(), registry=FakeRegistry())
        menu = build_menu(pystray, controller)

        self.assertEqual([item.text for item in menu.items if item != "SEP"],
                         ["Show ClipMorph", "Launch on logon", "Quit"])
        self.assertIs(menu.items[-1].action.__self__, controller)


class RunDesktopTests(unittest.TestCase):
    def _run(self):
        window = FakeWindow()
        webview = FakeWebview(window)
        pystray, created = fake_pystray()
        server = FakeServer()
        starter = MagicMock(return_value=server)
        result = run_desktop(platform="win32", webview_module=webview,
                             tray_module=pystray, image_loader=lambda: "IMG",
                             server_starter=starter, registry=FakeRegistry())
        return result, window, webview, created["icon"], server, starter

    def test_wires_window_tray_and_server_and_tears_down(self):
        result, window, webview, icon, server, starter = self._run()

        self.assertEqual(result, 0)
        starter.assert_called_once_with(host="127.0.0.1", port=None, data_dir=None)
        self.assertEqual(webview.created, ("ClipMorph", server.url))
        self.assertTrue(webview.started)
        self.assertEqual(webview.start_icon, str(icon_path()))
        self.assertTrue(icon.detached)
        self.assertTrue(icon.stopped)
        self.assertTrue(server.stopped)

    def test_close_hides_to_tray_and_quit_destroys_the_window(self):
        _result, window, _webview, icon, _server, _starter = self._run()

        self.assertFalse(window.events.closing.fire(window))
        self.assertTrue(window.hidden)

        icon.menu.items[-1].action(icon, None)
        self.assertTrue(window.destroyed)

    def test_logon_menu_item_toggles_the_registry(self):
        starter = MagicMock(return_value=FakeServer())
        pystray, created = fake_pystray()
        registry = FakeRegistry()
        run_desktop(platform="win32", webview_module=FakeWebview(FakeWindow()),
                    tray_module=pystray, image_loader=lambda: "IMG",
                    server_starter=starter, registry=registry)

        logon = created["icon"].menu.items[1]
        logon.action(created["icon"], None)
        self.assertIn(WINDOWS_RUN_VALUE, registry.values)

    def test_server_is_stopped_when_the_gui_loop_raises(self):
        window = FakeWindow()
        webview = FakeWebview(window)
        webview.start = MagicMock(side_effect=RuntimeError("webview failed"))
        pystray, _created = fake_pystray()
        server = FakeServer()
        starter = MagicMock(return_value=server)

        with self.assertRaises(RuntimeError):
            run_desktop(platform="win32", webview_module=webview,
                        tray_module=pystray, image_loader=lambda: "IMG",
                        server_starter=starter, registry=FakeRegistry())
        self.assertTrue(server.stopped)


class MainDispatchTests(unittest.TestCase):
    def test_desktop_shell_runs_when_available(self):
        from clipmorph import ui_launcher

        with patch.object(desktop_app, "desktop_available", return_value=True), \
                patch.object(desktop_app, "run_desktop") as run_desktop_mock, \
                patch.object(sys, "argv", ["clipmorph-ui"]):
            ui_launcher.main()

        run_desktop_mock.assert_called_once_with(
            host="127.0.0.1", port=None, data_dir=None)

    def test_browser_fallback_when_desktop_unavailable(self):
        from clipmorph import ui_launcher

        with patch.object(desktop_app, "desktop_available", return_value=False), \
                patch.object(ui_launcher, "run_ui") as run_ui_mock, \
                patch.object(sys, "argv", ["clipmorph-ui"]):
            ui_launcher.main()

        run_ui_mock.assert_called_once_with(
            host="127.0.0.1", port=None, data_dir=None, open_browser=True)

    def test_no_browser_forces_the_headless_path(self):
        from clipmorph import ui_launcher

        with patch.object(desktop_app, "desktop_available", return_value=True), \
                patch.object(ui_launcher, "run_ui") as run_ui_mock, \
                patch.object(sys, "argv", ["clipmorph-ui", "--no-browser"]):
            ui_launcher.main()

        run_ui_mock.assert_called_once_with(
            host="127.0.0.1", port=None, data_dir=None, open_browser=False)


class InstallerDriftTests(unittest.TestCase):
    """The Inno Setup script must agree with the Python Run-key constants.

    The Run key/value live in two languages (``clipmorph/desktop_app.py`` and
    ``scripts/installer/clipmorph.iss``). Cross-language duplication is
    unavoidable, so this check detects drift instead of relying on a comment.
    """

    def _script(self):
        root = Path(__file__).resolve().parent.parent
        return (root / "scripts" / "installer" / "clipmorph.iss").read_text(
            encoding="utf-8")

    def test_run_value_name_matches_desktop_app(self):
        self.assertIn(f'#define RunValueName "{WINDOWS_RUN_VALUE}"', self._script())

    def test_run_key_matches_desktop_app(self):
        text = self._script()
        self.assertIn(f'Subkey: "{WINDOWS_RUN_KEY}"', text)
        self.assertIn('ValueName: "{#RunValueName}"', text)


if __name__ == "__main__":
    unittest.main()
