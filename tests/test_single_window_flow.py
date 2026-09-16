import logging
import tempfile
import unittest
from pathlib import Path

from acmais_link.api import AppApi
from acmais_link.config_store import ConfigStore
from acmais_link.models import Company


class FakeCredentials:
    def __init__(self):
        self.values = {}

    def get(self, code):
        return self.values.get(code)

    def has(self, code):
        return code in self.values

    def set(self, code, password):
        self.values[code] = password

    def delete(self, code):
        self.values.pop(code, None)


class FakeWindow:
    def __init__(self):
        self.url = "file:///home/index.html"
        self.hidden = 0
        self.shown = 0
        self.title = "ACMAIS LINK"
        self.password_page = False
        self.submitted = False
        self.toolbar = False

    def hide(self):
        self.hidden += 1

    def show(self):
        self.shown += 1

    def load_url(self, url):
        self.url = url

    def get_current_url(self):
        return self.url

    def set_title(self, title):
        self.title = title

    def evaluate_js(self, script):
        if "Boolean(document.querySelector" in script:
            return self.password_page
        if "setter.call" in script:
            self.submitted = True
            return True
        if "const headings" in script:
            return "0000 - Teste"
        if "acmais-link-toolbar" in script:
            self.toolbar = True
            return True
        return None


class SingleWindowFlowTests(unittest.TestCase):
    def make_api(self, tempdir, credentials=None):
        config = ConfigStore(Path(tempdir) / "companies.json")
        api = AppApi(
            config,
            credentials or FakeCredentials(),
            logging.getLogger("test"),
            "file:///home/index.html",
        )
        api._retry_navigation = lambda token: None
        return api, config

    def test_setup_reuses_visible_window_and_extracts_identity(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = ConfigStore(Path(tempdir) / "companies.json")
            credentials = FakeCredentials()
            api = AppApi(config, credentials, logging.getLogger("test"), "file:///home/index.html")
            window = FakeWindow()
            api._bind_window(window)

            result = api.begin_company_setup({
                "url": "https://tenant.sharepoint.com/shared-link",
                "password": "secret-value",
            })
            self.assertTrue(result["ok"])
            self.assertEqual(window.hidden, 0)
            self.assertEqual(window.shown, 1)

            window.password_page = True
            api._on_loaded(window)
            self.assertTrue(window.submitted)
            self.assertEqual(window.hidden, 0)

            window.password_page = False
            window.url = (
                "https://tenant.sharepoint.com/sites/docs/Forms/AllItems.aspx"
                "?id=%2Fsites%2Fdocs%2FShared%20Documents%2F0000%20-%20Teste"
            )
            api._on_loaded(window)

            self.assertEqual(window.shown, 2)
            self.assertTrue(window.toolbar)
            self.assertEqual(window.title, "ACMAIS LINK - 0000 - Teste")
            self.assertEqual(config.get("0000").name, "Teste")
            self.assertEqual(credentials.get("0000"), "secret-value")
            self.assertEqual(api._mode, "active")
            self.assertIsNone(api._pending)

            # A stale password timer/probe must not send an already-open folder home.
            api._retry_navigation(1)
            self.assertEqual(api._mode, "active")
            self.assertEqual(window.url, (
                "https://tenant.sharepoint.com/sites/docs/Forms/AllItems.aspx"
                "?id=%2Fsites%2Fdocs%2FShared%20Documents%2F0000%20-%20Teste"
            ))

    def test_home_listing_does_not_query_the_credential_manager(self):
        class BlockingCredentials(FakeCredentials):
            def has(self, code):
                raise AssertionError("credential manager must not be queried while rendering")

        with tempfile.TemporaryDirectory() as tempdir:
            config = ConfigStore(Path(tempdir) / "companies.json")
            config.upsert(Company(
                code="0000",
                name="Teste",
                url="https://tenant.sharepoint.com/example",
            ))
            api = AppApi(config, BlockingCredentials(), logging.getLogger("test"), "file:///home/index.html")

            result = api.list_companies()

            self.assertTrue(result["ok"])
            self.assertTrue(result["companies"][0]["hasCredential"])

    def test_edit_can_reuse_saved_password_and_close_navigation_as_active(self):
        with tempfile.TemporaryDirectory() as tempdir:
            credentials = FakeCredentials()
            credentials.set("0000", "saved-secret")
            api, config = self.make_api(tempdir, credentials)
            config.upsert(Company(
                code="0000",
                name="Nome antigo",
                url="https://tenant.sharepoint.com/old",
            ))
            window = FakeWindow()
            api._bind_window(window)

            result = api.begin_company_setup({
                "originalCode": "0000",
                "url": "https://tenant.sharepoint.com/new",
                "password": "",
            })
            self.assertTrue(result["ok"])

            window.url = (
                "https://tenant.sharepoint.com/sites/docs/Forms/AllItems.aspx"
                "?id=%2Fsites%2Fdocs%2F0000%20-%20Nome%20novo"
            )
            api._on_loaded(window)

            self.assertEqual(config.get("0000").name, "Nome novo")
            self.assertEqual(credentials.get("0000"), "saved-secret")
            self.assertEqual(api._mode, "active")

    def test_open_waits_for_async_password_ui_then_stays_on_folder(self):
        with tempfile.TemporaryDirectory() as tempdir:
            credentials = FakeCredentials()
            credentials.set("0000", "saved-secret")
            api, config = self.make_api(tempdir, credentials)
            company = Company(
                code="0000",
                name="Teste",
                url="https://tenant.sharepoint.com/shared-link",
            )
            config.upsert(company)
            window = FakeWindow()
            api._bind_window(window)

            self.assertTrue(api.open_company("0000")["ok"])
            for _ in range(4):
                api._on_loaded(window)
                self.assertEqual(api._mode, "navigating")

            api._on_loaded(window)
            self.assertEqual(api._mode, "active")
            self.assertEqual(window.title, "ACMAIS LINK - 0000 - Teste")
            self.assertTrue(window.toolbar)

    def test_native_window_and_dependencies_are_private_to_js_bridge(self):
        with tempfile.TemporaryDirectory() as tempdir:
            api, _ = self.make_api(tempdir)
            api._bind_window(FakeWindow())
            self.assertTrue(all(name.startswith("_") for name in vars(api)))


class MenuMarkupTests(unittest.TestCase):
    def test_cancel_and_close_buttons_do_not_submit_required_fields(self):
        index_path = Path(__file__).parents[1] / "src" / "acmais_link" / "web" / "index.html"
        markup = index_path.read_text(encoding="utf-8")
        self.assertIn('id="close-company-dialog" type="button"', markup)
        self.assertIn('id="cancel-company" type="button"', markup)
        self.assertIn('id="save-company" type="submit"', markup)
        self.assertIn('app.js?v=1.0.0', markup)
        self.assertIn('style.css?v=1.0.0', markup)


if __name__ == "__main__":
    unittest.main()
