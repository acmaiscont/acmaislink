import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from acmais_link import __version__
from acmais_link.api import AppApi
from acmais_link.bridge import SecureBridge
from acmais_link.single_instance import SingleInstance
import acmais_link.main as application


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in self.handlers:
            handler()


class UpdateLifecycleTests(unittest.TestCase):
    def test_bridge_only_exposes_read_only_update_status(self):
        controller = Mock()
        controller.status.return_value = {"state": "ready", "version": "v1.1.0"}
        api = AppApi(Mock(), Mock(), logging.getLogger("test"), "file:///home", updates=controller)
        bridge = SecureBridge(api)
        self.assertEqual(bridge.command(bridge._token, "get_update_status", [])["status"], "ready")
        for command in ("check_update", "install_update", "launch_pending", "_updates"):
            self.assertFalse(bridge.command(bridge._token, command, [])["ok"])
        self.assertFalse(bridge.command("wrong", "get_update_status", [])["ok"])
        controller.launch_pending.assert_not_called()

    def test_source_and_uninstalled_build_do_not_auto_update(self):
        with patch.object(application.sys, "platform", "win32"), \
             patch.object(application.sys, "frozen", False, create=True):
            self.assertFalse(application._automatic_updates_enabled())
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(application.os.environ, {"LOCALAPPDATA": temporary}), \
             patch.object(application.sys, "platform", "win32"), \
             patch.object(application.sys, "frozen", True, create=True):
            folder = Path(temporary) / "Programs/ACMAIS LINK/versions" / __version__
            folder.mkdir(parents=True)
            installed = folder / "ACMAIS LINK.exe"
            installed.write_bytes(b"test fixture")
            with patch.object(application.sys, "executable", str(installed)):
                self.assertFalse(application._automatic_updates_enabled())
                (folder / ".complete").write_text(__version__)
                self.assertTrue(application._automatic_updates_enabled())
            avulso = Path(temporary) / "ACMAIS LINK.exe"
            avulso.write_bytes(b"test fixture")
            with patch.object(application.sys, "executable", str(avulso)):
                self.assertFalse(application._automatic_updates_enabled())

    def run_lifecycle(self, error=False, installed=True):
        calls = []
        instance, controller = Mock(), Mock()
        instance.acquire.return_value = True
        instance.close.side_effect = lambda: calls.append("mutex_closed")
        controller.start.side_effect = lambda: calls.append("background_started")
        controller.stop.side_effect = lambda: calls.append("background_stopped")
        controller.launch_pending.side_effect = lambda: calls.append("silent_install")
        window = Mock()
        window.events = SimpleNamespace(initialized=Event(), loaded=Event(), shown=Event())

        def gui(**kwargs):
            window.events.shown.fire()
            self.assertNotIn("silent_install", calls)
            calls.append("window_closed")
            if error:
                raise RuntimeError("GUI failed")

        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(application, "SingleInstance", return_value=instance), \
             patch.object(application, "webview_available", return_value=True), \
             patch.object(application, "ensure_data_dirs", return_value=Path(temporary)), \
             patch.object(application, "configure_logging", return_value=Mock()), \
             patch.object(application, "CredentialStore", return_value=Mock()), \
             patch.object(application, "_automatic_updates_enabled", return_value=installed), \
             patch.object(application, "AutoUpdateController", return_value=controller) as factory, \
             patch.object(application, "initial_window_geometry", return_value=SimpleNamespace(width=900, height=600, min_size=(480, 360), x=0, y=0, maximized=False)), \
             patch.object(application.webview, "create_window", return_value=window), \
             patch.object(application.webview, "start", side_effect=gui):
            if error:
                with self.assertRaises(RuntimeError):
                    application.main()
            else:
                application.main()
            if not installed:
                factory.assert_not_called()
        return calls

    def test_install_only_after_normal_close_and_mutex_release(self):
        self.assertEqual(self.run_lifecycle(), ["background_started", "window_closed", "background_stopped", "mutex_closed", "silent_install"])

    def test_gui_failure_does_not_launch_installer(self):
        self.assertEqual(self.run_lifecycle(error=True), ["background_started", "window_closed", "background_stopped", "mutex_closed"])

    def test_development_run_never_starts_updater(self):
        self.assertEqual(self.run_lifecycle(installed=False), ["window_closed", "mutex_closed"])


class RelaunchDuringUpdateTests(unittest.TestCase):
    def test_waits_for_installer_then_acquires_single_instance(self):
        instance = SingleInstance()
        with patch("acmais_link.single_instance.sys.platform", "win32"), \
             patch.object(instance, "_try_acquire_mutex", side_effect=[False, False, True]), \
             patch.object(instance, "_installer_running", return_value=True), \
             patch.object(instance, "_focus_existing_window", return_value=False) as focus, \
             patch("acmais_link.single_instance.time.sleep"):
            self.assertTrue(instance.acquire())
            focus.assert_called_with(attempts=1)

    def test_existing_window_is_focused_not_restarted(self):
        instance = SingleInstance()
        with patch("acmais_link.single_instance.sys.platform", "win32"), \
             patch.object(instance, "_try_acquire_mutex", return_value=False) as acquire, \
             patch.object(instance, "_installer_running", return_value=True), \
             patch.object(instance, "_focus_existing_window", return_value=True):
            self.assertFalse(instance.acquire())
            acquire.assert_called_once()

    def test_wait_for_installer_has_deadline(self):
        instance = SingleInstance()
        with patch("acmais_link.single_instance.sys.platform", "win32"), \
             patch.object(instance, "_try_acquire_mutex", return_value=False), \
             patch.object(instance, "_installer_running", return_value=True), \
             patch.object(instance, "_focus_existing_window", return_value=False), \
             patch("acmais_link.single_instance.time.monotonic", side_effect=[0, 31]):
            self.assertFalse(instance.acquire())

    def test_retry_when_previous_process_exits_before_focus(self):
        instance = SingleInstance()
        with patch("acmais_link.single_instance.sys.platform", "win32"), \
             patch.object(instance, "_try_acquire_mutex", side_effect=[False, True]), \
             patch.object(instance, "_installer_running", return_value=False), \
             patch.object(instance, "_focus_existing_window", return_value=False):
            self.assertTrue(instance.acquire())
