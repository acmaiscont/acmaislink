import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from acmais_link.portable_navigation import PortableNavigationWindow, _cocoa_cookies, _cookie_header
from acmais_link.single_instance import SingleInstance


def cookie(name, domain, path="/", expiry=None):
    return Mock(**{
        "name.return_value": name, "value.return_value": "session",
        "domain.return_value": domain, "path.return_value": path,
        "expiresDate.return_value": expiry,
    })


class PortableCookieTests(unittest.TestCase):
    def test_cocoa_respects_domain_path_and_expiration(self):
        cookies = [
            cookie("root", "acmais.sharepoint.com"),
            cookie("domain", ".sharepoint.com"),
            cookie("sibling", "other.sharepoint.com"),
            cookie("substring", ".mais.sharepoint.com"),
            cookie("site", "acmais.sharepoint.com", "/sites/Docs"),
            cookie("prefix", "acmais.sharepoint.com", "/sites/Do"),
            cookie("trailing", "acmais.sharepoint.com", "/sites/Docs/"),
            cookie("expired", "acmais.sharepoint.com", expiry=Mock(timeIntervalSinceNow=lambda: -1)),
        ]
        target = "https://acmais.sharepoint.com/sites/Docs/_api/web"
        names = [name for name, _ in _cocoa_cookies(cookies, target)]
        self.assertEqual(names, ["root", "domain", "site", "trailing"])

    def test_cookie_header_rejects_header_injection(self):
        self.assertEqual(_cookie_header([
            ("FedAuth", "a//+=.b"), ("two names", "secret"), ("bad", "first; Next=second"),
            ("injected", "private\r\nOther: header"),
        ]), "FedAuth=a//+=.b")

    def make_gtk(self, url):
        browser = Mock()
        browser.webview.get_uri.return_value = url
        native = PortableNavigationWindow(Mock(), "gtk", Mock(), Mock(), Mock())
        native._post = lambda callback: callback()
        native._browser = lambda: browser
        return native, browser

    def test_gtk_queries_request_path_and_rejects_redirected_session(self):
        target = "https://acmais.sharepoint.com/sites/Docs/_api/web"
        native, browser = self.make_gtk("https://acmais.sharepoint.com/:f:/s/Docs/example")
        manager = browser.cookie_manager
        manager.get_cookies_finish.return_value = [Mock(get_name=lambda: "rtFa", get_value=lambda: "value")]

        def reply(url, _cancel, handler, data):
            self.assertEqual(url, target)
            handler(manager, None, data)
        manager.get_cookies.side_effect = reply
        self.assertEqual(native.delivery_cookies(target, lambda: True), "rtFa=value")

        def redirect(url, cancel, handler, data):
            browser.webview.get_uri.return_value = "https://other.sharepoint.com/sites/Docs"
            reply(url, cancel, handler, data)
        manager.get_cookies.side_effect = redirect
        self.assertEqual(native.delivery_cookies(target, lambda: True), "")
        with self.assertRaises(RuntimeError):
            native.delivery_cookies(target, lambda: True)

    def test_expired_ui_request_is_never_executed(self):
        native, browser = self.make_gtk("https://acmais.sharepoint.com/")
        queued = []
        native._post = queued.append
        operation = Mock()
        with self.assertRaises(TimeoutError):
            native._request(operation, timeout=0)
        queued.pop()()
        operation.assert_not_called()


@unittest.skipIf(sys.platform == "win32", "requires POSIX file locking")
class PortableInstanceTests(unittest.TestCase):
    def test_only_one_process_owns_the_data_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = SingleInstance(root), SingleInstance(root)
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                first.close()
                self.assertTrue(second.acquire())
            finally:
                first.close()
                second.close()
