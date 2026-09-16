import hashlib
import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from acmais_link.bridge import SecureBridge
from acmais_link.models import is_allowed_sharepoint_url, Company
from acmais_link.updater import UpdateService, SafeRedirect, version_tuple
import test_single_window_flow as flows
from test_single_window_flow import FakeWindow, FakeCredentials


class ReleaseSecurityTests(unittest.TestCase):
    def release(self, **overrides):
        asset = {"name": "ACMAIS-LINK-1.1.0-x64-update.exe", "size": 4,
                 "digest": "sha256:" + hashlib.sha256(b"test").hexdigest(),
                 "browser_download_url": "https://github.com/acmaiscont/acmaislink/releases/download/v1.1.0/ACMAIS-LINK-1.1.0-x64-update.exe"}
        asset.update(overrides)
        return {"tag_name": "v1.1.0", "draft": False, "prerelease": False, "assets": [asset]}

    def test_bridge_rejects_remote_and_private_calls(self):
        api = Mock()
        bridge = SecureBridge(api)
        self.assertFalse(bridge.command("", "delete_company", ["0000"])["ok"])
        api.delete_company.assert_not_called()
        self.assertFalse(bridge.command(bridge._token, "_credentials", [])["ok"])
        bridge.command(bridge._token, "list_companies", [])
        api.list_companies.assert_called_once_with()

    def test_release_selection_and_numeric_versions(self):
        service = UpdateService("1.0.0")
        self.assertTrue(service._select(self.release())["available"])
        self.assertGreater(version_tuple("1.10.0"), version_tuple("1.9.0"))
        self.assertFalse(UpdateService("1.2.0")._select(self.release())["available"])
        with self.assertRaises(ValueError):
            version_tuple("1.0.0-rc.1")

    def test_rejects_invalid_release_assets(self):
        for fields in ({"digest": None}, {"size": 0}, {"size": 9999999999},
                       {"browser_download_url": "https://evil.example/update.exe"},
                       {"name": "ACMAIS-LINK-1.1.0-x64-full.exe"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                UpdateService("1.0.0")._select(self.release(**fields))
        for flag in ("draft", "prerelease"):
            release = self.release()
            release[flag] = True
            with self.assertRaises(ValueError):
                UpdateService("1.0.0")._select(release)

    def test_download_validates_bytes_and_cleans_corrupt_package(self):
        service = UpdateService("1.0.0")
        service._select(self.release())
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "download"
            folder.mkdir()
            with patch("acmais_link.updater.tempfile.mkdtemp", return_value=str(folder)), \
                 patch.object(service, "_open", return_value=io.BytesIO(b"evil")):
                with self.assertRaises(ValueError):
                    service.download()
                self.assertFalse(folder.exists())
            folder.mkdir()
            with patch("acmais_link.updater.tempfile.mkdtemp", return_value=str(folder)), \
                 patch.object(service, "_open", return_value=io.BytesIO(b"test")):
                self.assertEqual(service.download().read_bytes(), b"test")

    def test_rejects_unsafe_sharepoint_urls(self):
        for url in ("https://x.sharepoint.com:444/a", "https://x.sharepoint.com:bad/a",
                    "https://x.sharepoint.com\\@evil.example", "https://x.sharepoint.com\n/a",
                    "https://[bad", "http://x.sharepoint.com", "https://x.sharepoint.com.evil.example"):
            self.assertFalse(is_allowed_sharepoint_url(url), url)

    def test_no_password_sent_to_another_tenant(self):
        with tempfile.TemporaryDirectory() as temp:
            api, config = flows.SingleWindowFlowTests().make_api(temp)
            window = FakeWindow()
            api._bind_window(window)
            api.begin_company_setup({"url": "https://tenant.sharepoint.com/link", "password": "secret"})
            window.url = "https://other.sharepoint.com/link"
            window.password_page = True
            api._on_loaded(window)
            self.assertFalse(window.submitted)
            self.assertEqual(api._mode, "home")

    def test_duplicate_setup_does_not_overwrite_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            credentials = FakeCredentials()
            credentials.set("0000", "original")
            api, config = flows.SingleWindowFlowTests().make_api(temp, credentials)
            config.upsert(Company("0000", "Original", "https://tenant.sharepoint.com/link"))
            window = FakeWindow()
            api._bind_window(window)
            api.begin_company_setup({"url": "https://tenant.sharepoint.com/link", "password": "new"})
            api._on_loaded(window)
            self.assertEqual(credentials.get("0000"), "original")
            self.assertEqual(config.get("0000").name, "Original")

    def test_timeout_without_loaded_event_and_stale_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            api, _ = flows.SingleWindowFlowTests().make_api(temp)
            api._bind_window(FakeWindow())
            api.begin_company_setup({"url": "https://tenant.sharepoint.com/link", "password": "secret"})
            token = api._navigation_token
            api._navigation_timeout(token - 1)
            self.assertEqual(api._mode, "navigating")
            api._navigation_timeout(token)
            self.assertEqual(api._mode, "home")
            self.assertIsNone(api._pending)

    def test_failed_config_write_restores_password(self):
        with tempfile.TemporaryDirectory() as temp:
            credentials = FakeCredentials()
            credentials.set("0000", "original")
            api, config = flows.SingleWindowFlowTests().make_api(temp, credentials)
            company = Company("0000", "Original", "https://tenant.sharepoint.com/link")
            config.upsert(company)
            api._mode = "navigating"
            with patch.object(config, "upsert", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    api._persist_company(company, {"original_code": "0000", "password": "new"}, 0)
            self.assertEqual(credentials.get("0000"), "original")

    def test_cancelled_setup_cannot_save_later(self):
        with tempfile.TemporaryDirectory() as temp:
            api, config = flows.SingleWindowFlowTests().make_api(temp)
            company = Company("0000", "Test", "https://tenant.sharepoint.com/link")
            self.assertFalse(api._persist_company(company, {"password": "new"}, -1))
            self.assertEqual(config.list(), [])
