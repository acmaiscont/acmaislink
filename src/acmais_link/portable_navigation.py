"""Bounded navigation and request-scoped sessions for WKWebView and WebKitGTK."""
from __future__ import annotations

import json
import re
from threading import Event, Thread
from urllib.parse import urlsplit

from .models import is_allowed_sharepoint_url


_COOKIE_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_COOKIE_VALUE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*")


def _cookie_header(cookies):
    return "; ".join(
        f"{name}={value}" for name, value in cookies
        if _COOKIE_NAME.fullmatch(name) and _COOKIE_VALUE.fullmatch(value)
    )


def _cocoa_cookies(cookies, url):
    target = urlsplit(url)
    path = target.path or "/"
    for cookie in cookies:
        domain = str(cookie.domain()).lower()
        host = domain.lstrip(".")
        if target.hostname != host and not (domain.startswith(".") and target.hostname.endswith("." + host)):
            continue
        scope = str(cookie.path()) or "/"
        if path != scope and not path.startswith(scope if scope.endswith("/") else scope + "/"):
            continue
        expiry = cookie.expiresDate()
        if expiry is None or expiry.timeIntervalSinceNow() > 0:
            yield str(cookie.name()), str(cookie.value())


class PortableNavigationWindow:
    def __init__(self, window, backend, return_home, open_external, select_company):
        self._window = window
        self._backend = backend
        self._actions = (return_home, open_external, select_company)
        self._chrome = None

    def __getattr__(self, name):
        return getattr(self._window, name)

    def _post(self, callback):
        if self._backend == "cocoa":
            from PyObjCTools import AppHelper
            AppHelper.callAfter(callback)
        else:
            from gi.repository import GLib
            GLib.idle_add(callback)

    def _browser(self):
        # pywebview 6.2.1 exposes the native window but not its browser control
        # or a cookie API scoped to a different request path on the same site.
        return self._window.gui.BrowserView.instances[self._window.uid]

    def _request(self, operation, is_current=lambda: True, timeout=3):
        done, expired = Event(), Event()
        result = {}

        def complete(value=None, error=None):
            result.update(value=value, error=error)
            done.set()

        def begin():
            if expired.is_set() or not is_current():
                complete()
                return
            try:
                operation(self._browser(), complete)
            except Exception as exc:
                complete(error=exc)

        self._post(begin)
        if not done.wait(timeout):
            expired.set()
            raise TimeoutError("O navegador integrado não respondeu.")
        if result["error"] is not None:
            raise result["error"]
        if is_current():
            return result["value"]
        return None

    def _on_ui(self, operation, is_current=lambda: True):
        return self._request(lambda browser, complete: complete(operation(browser)), is_current)

    def _url(self, browser):
        view = browser.webview
        if self._backend == "cocoa":
            url = view.URL()
            return str(url.absoluteString()) if url is not None else ""
        return view.get_uri() or ""

    def get_current_url(self):
        return self._on_ui(self._url)

    def navigate(self, url, is_current):
        def load(browser):
            self._window.real_url = url
            for event in (self._window.events.loaded, self._window.events.before_load,
                          self._window.events._pywebviewready):
                event.clear()
            if self._backend == "cocoa":
                from Foundation import NSURL, NSURLRequest

                address = NSURL.URLWithString_(url)
                if address.isFileURL():
                    browser.webview.loadFileURL_allowingReadAccessToURL_(address, address.URLByDeletingLastPathComponent())
                else:
                    browser.webview.loadRequest_(NSURLRequest.requestWithURL_(address))
            else:
                browser.load_url(url)

        return self._on_ui(load, is_current)

    def evaluate_navigation_js(self, script, is_current):
        expression = f"JSON.stringify(({script.strip()}))"

        def evaluate(browser, complete):
            view = browser.webview
            if self._backend == "cocoa":
                def finished(value, error):
                    try:
                        if error is not None:
                            raise RuntimeError("O documento não respondeu ao JavaScript.")
                        complete(json.loads(value) if isinstance(value, str) else None)
                    except Exception as exc:
                        complete(error=exc)
                view.evaluateJavaScript_completionHandler_(expression, finished)
            else:
                def finished(source, task):
                    try:
                        value = source.evaluate_javascript_finish(task)
                        complete(json.loads(value.to_string()) if value.is_string() else None)
                    except Exception as exc:
                        complete(error=exc)
                view.evaluate_javascript(expression, -1, None, None, None, finished)

        return self._request(evaluate, is_current)

    def delivery_cookies(self, url, is_current):
        def collect(browser, complete):
            def same_site():
                page = self._url(browser)
                return (is_allowed_sharepoint_url(page) and is_allowed_sharepoint_url(url)
                        and urlsplit(page).hostname == urlsplit(url).hostname)

            if not same_site():
                raise RuntimeError("A sessão não está no SharePoint da empresa.")

            def finish(cookies):
                complete(_cookie_header(cookies) if is_current() and same_site() else "")

            if self._backend == "cocoa":
                def finished(cookies):
                    try:
                        finish(_cocoa_cookies(cookies, url))
                    except Exception as exc:
                        complete(error=exc)
                browser.webview.configuration().websiteDataStore().httpCookieStore().getAllCookies_(finished)
            else:
                def finished(manager, task, _data):
                    try:
                        cookies = manager.get_cookies_finish(task)
                        finish((cookie.get_name(), cookie.get_value()) for cookie in cookies)
                    except Exception as exc:
                        complete(error=exc)
                browser.cookie_manager.get_cookies(url, None, finished, None)

        return self._request(collect, is_current) or ""

    def choose_delivery_files(self):
        from webview import FileDialog
        return self._window.create_file_dialog(FileDialog.OPEN, allow_multiple=True)

    def choose_delivery_folder(self):
        from webview import FileDialog
        return self._window.create_file_dialog(FileDialog.FOLDER)

    def _controls(self, browser):
        if self._chrome is None:
            if self._backend == "cocoa":
                from .cocoa_controls import CocoaControls
                controls = CocoaControls
            else:
                from .gtk_controls import GtkControls
                controls = GtkControls
            actions = tuple(self._dispatch_action(action) for action in self._actions)
            self._chrome = controls(browser, *actions)
        return self._chrome

    @staticmethod
    def _dispatch_action(action):
        def invoke(*args):
            Thread(target=action, args=args, daemon=True).start()
        return invoke

    def show_loading(self, is_current, *, delivery=False, group=False):
        title = "Preparando envio…" if delivery else "Atualizando grupo…" if group else "Abrindo documentos…"
        detail = ("Conferindo a pasta de destino." if delivery else "Validando o acesso no SharePoint.")
        cancel = "Cancelar envio" if delivery else "Cancelar e voltar às empresas"
        return self._on_ui(
            lambda browser: self._controls(browser).show_loading(title, detail, cancel), is_current,
        )

    def delivery_progress(self, index, total, sent, size, waiting, directory, is_current):
        fraction = min(1.0, sent / size) if size else 0
        if directory:
            status = "Preparando a subpasta…"
        elif waiting:
            status = "Aguardando confirmação do SharePoint…"
        elif sent:
            status = f"{fraction:.0%} do arquivo"
        else:
            status = "Verificando o destino…"
        self._on_ui(lambda browser: self._controls(browser).update_loading(
            f"Item {index} de {total} · {status}", fraction if sent and not waiting else None,
        ), is_current)

    def set_company_choices(self, choices, current_code, is_current):
        def update(browser):
            self._controls(browser).set_choices(choices, current_code)
        self._on_ui(update, is_current)

    def show_folder(self, label, is_current):
        return self._on_ui(lambda browser: self._controls(browser).show_folder(label), is_current)

    def show_home(self, is_current):
        def show(_browser):
            if self._chrome is not None:
                self._chrome.show_home()
        self._on_ui(show, is_current)
