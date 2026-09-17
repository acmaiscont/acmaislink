import logging
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from acmais_link.api import AppApi
from acmais_link.config_store import ConfigStore
from acmais_link.models import Company
from test_single_window_flow import FakeCredentials, FakeWindow


class RaceWindow(FakeWindow):
    def __init__(self):
        super().__init__()
        self.cover = False
        self.before_url = None
        self.before_heading = None
        self.before_cover = None
        self.toolbar_result = True

    def get_current_url(self):
        callback, self.before_url = self.before_url, None
        if callback:
            return callback()
        return super().get_current_url()

    def evaluate_js(self, script):
        if "acmaisNavigationSnapshot" in script:
            current_url = self.get_current_url()
            heading = "0000 - Teste"
            if self.before_heading:
                callback, self.before_heading = self.before_heading, None
                heading = callback()
            return {"url": current_url, "hasPassword": self.password_page, "heading": heading}
        if "const bar = document.createElement" in script:
            if isinstance(self.toolbar_result, Exception):
                raise self.toolbar_result
            if self.toolbar_result is not True:
                return self.toolbar_result
            self.cover = False
        elif "const acmaisCover = document.createElement" in script:
            self.cover = True
            if self.before_cover:
                callback, self.before_cover = self.before_cover, None
                callback()
        return super().evaluate_js(script)


class NavigationRaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.timer_patch = patch("acmais_link.api.threading.Timer")
        self.timer_patch.start()
        self.addCleanup(self.timer_patch.stop)
        self.credentials = FakeCredentials()
        self.config = ConfigStore(Path(self.temp.name) / "companies.json")
        self.api = AppApi(self.config, self.credentials, logging.getLogger("races"), "file:///home/index.html")
        self.window = RaceWindow()
        self.api._bind_window(self.window)

    def begin(self):
        self.assertTrue(self.api.begin_company_setup({
            "url": "https://tenant.sharepoint.com/shared-link", "password": "test-only",
        })["ok"])
        self.window.url = "https://tenant.sharepoint.com/Forms/AllItems.aspx?id=%2Fdocs%2F0000%20-%20Teste"
        return self.api._navigation_token

    def supersede(self):
        self.api.return_home()
        self.assertTrue(self.api.begin_company_setup({
            "url": "https://tenant.sharepoint.com/new-link", "password": "new-test-only",
        })["ok"])

    def test_overlapping_loaded_and_timer_cannot_reapply_cover_after_success(self):
        token = self.begin()
        original_url = self.window.url

        def concurrent_probe():
            self.api._inspect_navigation(self.window, token)
            return original_url

        self.window.before_url = concurrent_probe
        with patch.object(self.config, "upsert", wraps=self.config.upsert) as save:
            self.api._inspect_navigation(self.window, token)
        self.assertEqual(self.api._mode, "active")
        self.assertFalse(self.window.cover)
        self.assertEqual(save.call_count, 1)
        self.api._navigation_timeout(token)
        self.assertFalse(self.window.cover)

    def test_late_url_failure_does_not_cancel_a_new_navigation(self):
        token = self.begin()

        def old_result():
            self.supersede()
            return "https://another-tenant.sharepoint.com/old-response"

        self.window.before_url = old_result
        self.api._inspect_navigation(self.window, token)
        self.assertEqual(self.api._mode, "navigating")
        self.assertEqual(self.api._pending["url"], "https://tenant.sharepoint.com/new-link")
        self.assertIsNone(self.api._notice)

    def test_late_script_exception_does_not_cancel_a_new_navigation(self):
        token = self.begin()

        def old_exception():
            self.supersede()
            raise RuntimeError("old document disposed")

        self.window.before_heading = old_exception
        self.api._inspect_navigation(self.window, token)
        self.assertEqual(self.api._mode, "navigating")
        self.assertEqual(self.api._pending["url"], "https://tenant.sharepoint.com/new-link")
        self.assertEqual(self.config.list(), [])

    def test_watchdog_remains_responsive_while_native_script_is_blocked(self):
        token = self.begin()
        entered, resume = threading.Event(), threading.Event()

        def slow_heading():
            entered.set()
            self.assertTrue(resume.wait(3))
            return "0000 - Teste"

        self.window.before_heading = slow_heading
        worker = threading.Thread(target=self.api._inspect_navigation, args=(self.window, token), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.api._navigation_timeout(token)
            self.assertEqual(self.api._mode, "home")
        finally:
            resume.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.config.list(), [])

    def test_cancel_during_credential_write_does_not_save_and_restores_password(self):
        token = self.begin()
        entered, resume, cancelled = threading.Event(), threading.Event(), threading.Event()
        original_set = self.credentials.set

        def slow_set(code, password):
            original_set(code, password)
            entered.set()
            self.assertTrue(resume.wait(3))

        self.credentials.set = slow_set
        worker = threading.Thread(target=self.api._inspect_navigation, args=(self.window, token), daemon=True)
        worker.start()
        self.assertTrue(entered.wait(2))
        cancel_worker = threading.Thread(target=lambda: (self.api.return_home(), cancelled.set()), daemon=True)
        cancel_worker.start()
        try:
            self.assertTrue(cancelled.wait(.5), "Cancel must not wait for Credential Manager")
        finally:
            resume.set()
            worker.join(3)
            cancel_worker.join(3)
        self.assertEqual(self.config.list(), [])
        self.assertIsNone(self.credentials.get("0000"))
        self.assertEqual(self.api._mode, "home")

    def test_cancellation_during_edit_file_write_restores_original_company_and_password(self):
        original = Company("0000", "Original", "https://tenant.sharepoint.com/original")
        self.config.upsert(original)
        self.credentials.set("0000", "original-secret")
        self.assertTrue(self.api.begin_company_setup({
            "url": "https://tenant.sharepoint.com/new-link", "password": "replacement-secret",
            "originalCode": "0000",
        })["ok"])
        token = self.api._navigation_token
        real_upsert = self.config.upsert
        first_write = True

        def write_then_cancel(company, original_code=None):
            nonlocal first_write
            real_upsert(company, original_code=original_code)
            if first_write:
                first_write = False
                self.api.return_home()

        self.config.upsert = write_then_cancel
        self.api._inspect_navigation(self.window, token)
        self.assertEqual(self.config.get("0000"), original)
        self.assertEqual(self.credentials.get("0000"), "original-secret")
        self.assertEqual(self.api._mode, "home")

    def test_late_return_home_does_not_load_home_over_new_navigation(self):
        self.begin()
        real_is_current = self.api._is_current
        interrupted = False

        def new_navigation_before_native_load(token, mode=None):
            nonlocal interrupted
            if mode == "home" and not interrupted:
                interrupted = True
                self.assertTrue(self.api.begin_company_setup({
                    "url": "https://tenant.sharepoint.com/new-link", "password": "replacement",
                })["ok"])
            return real_is_current(token, mode)

        with patch.object(self.api, "_is_current", side_effect=new_navigation_before_native_load):
            self.api.return_home()
        self.assertEqual(self.api._mode, "navigating")
        self.assertEqual(self.window.url, "https://tenant.sharepoint.com/new-link")

    def test_toolbar_failure_does_not_leave_active_state_with_infinite_cover(self):
        for result in (RuntimeError("document changed"), False, None):
            with self.subTest(result=result):
                self.config.delete("0000")
                self.api.return_home()
                token = self.begin()
                self.window.toolbar_result = result
                self.api._inspect_navigation(self.window, token)
                self.assertEqual(self.api._mode, "home")
                self.assertEqual(self.window.url, "file:///home/index.html")
                self.assertIsNotNone(self.config.get("0000"))
                self.assertTrue(self.api._notice["error"])

    def test_password_button_not_ready_retries_without_marking_submission(self):
        token = self.begin()
        self.window.password_page = True
        original_evaluate = self.window.evaluate_js

        def not_ready(script):
            return False if "setter.call" in script else original_evaluate(script)

        self.window.evaluate_js = not_ready
        self.api._inspect_navigation(self.window, token)
        self.assertEqual(self.api._mode, "navigating")
        self.assertIsNone(self.api._pending["submitted_at"])
        self.assertEqual(self.config.list(), [])

    def test_timer_fired_during_a_probe_is_rescheduled_after_it_finishes(self):
        token = self.begin()

        def paused_probe(window, current_token, pending):
            self.api._retry_navigation(current_token)
            # Simulate its timer firing while this probe is still running.
            self.api._inspect_navigation(window, current_token)

        self.api._inspect_current_navigation = paused_probe
        with patch("acmais_link.api.threading.Timer") as timer:
            self.api._inspect_navigation(self.window, token)
        self.assertEqual(timer.call_count, 2)
        self.assertTrue(self.api._probe_scheduled)
        self.assertIsNone(self.api._probe_inflight)

    def test_slow_old_credential_cleanup_runs_only_after_folder_is_visible(self):
        self.config.upsert(Company("0001", "Original", "https://tenant.sharepoint.com/original"))
        self.credentials.set("0001", "original-secret")
        self.assertTrue(self.api.begin_company_setup({
            "url": "https://tenant.sharepoint.com/new-link", "password": "replacement-secret",
            "originalCode": "0001",
        })["ok"])
        entered, resume = threading.Event(), threading.Event()
        original_delete = self.credentials.delete

        def slow_delete(code):
            if code == "0001":
                entered.set()
                self.assertTrue(resume.wait(3))
            original_delete(code)

        self.credentials.delete = slow_delete
        worker = threading.Thread(target=self.api._inspect_navigation,
                                  args=(self.window, self.api._navigation_token), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.window.toolbar)
            self.assertFalse(self.window.cover)
            self.assertEqual(self.api._mode, "active")
            self.assertIsNotNone(self.config.get("0000"))
        finally:
            resume.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_cancel_during_initial_credential_read_does_not_open_or_edit_later(self):
        self.config.upsert(Company("0000", "Original", "https://tenant.sharepoint.com/original"))
        self.credentials.set("0000", "original-secret")
        original_get = self.credentials.get
        for action in (
                lambda: self.api.open_company("0000"),
                lambda: self.api.begin_company_setup({
                    "url": "https://tenant.sharepoint.com/edit", "originalCode": "0000", "password": "",
                })):
            with self.subTest(action=action):
                entered, resume = threading.Event(), threading.Event()

                def slow_get(code):
                    entered.set()
                    self.assertTrue(resume.wait(3))
                    return original_get(code)

                self.credentials.get = slow_get
                worker = threading.Thread(target=action, daemon=True)
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    self.api.return_home()
                finally:
                    resume.set()
                    worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(self.api._mode, "home")
                self.assertEqual(self.window.url, "file:///home/index.html")
                self.assertIsNone(self.api._pending)

    def test_cancel_never_waits_for_remote_javascript(self):
        self.begin()
        with patch.object(self.window, "evaluate_js", side_effect=AssertionError("Remote JS is unresponsive")) as script:
            self.assertTrue(self.api.return_home()["ok"])
        script.assert_not_called()
        self.assertEqual(self.window.url, "file:///home/index.html")
        self.assertEqual(self.api._mode, "home")
        self.assertIsNone(self.api._pending)


if __name__ == "__main__":
    unittest.main()
