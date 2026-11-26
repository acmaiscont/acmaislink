from __future__ import annotations

import sys
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import webview

from . import APP_DISPLAY_TITLE, __version__
from .api import AppApi
from .auto_update import AutoUpdateController
from .bridge import SecureBridge
from .config_store import ConfigStore
from .credential_store import CredentialStore
from .delivery import DeliveryHistory
from .logging_config import configure_logging
from .paths import ensure_data_dirs
from .single_instance import SingleInstance
from .runtime import webview_available
from .web_home import home_filename, is_home_document, prepare_home
from .window_geometry import initial_window_geometry
from .navigation_window import NavigationWindow
from .portable_navigation import PortableNavigationWindow


def webview_backend():
    if sys.platform == "win32":
        return "edgechromium"
    if sys.platform == "darwin":
        return "cocoa"
    if sys.platform.startswith("linux"):
        return "gtk"
    raise RuntimeError("Sistema operacional sem suporte para o ACMAIS LINK.")

def resource_path(relative: str) -> Path:
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if getattr(sys, "frozen", False):
        return bundle / relative
    return Path(__file__).resolve().parent / relative


def _automatic_updates_enabled() -> bool:
    """Only the installed app may update the per-user installation.

    Source runs and unpacked build/QA copies must never silently replace it.
    samefile also handles Windows package path redirection when available.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    local_data = os.environ.get("LOCALAPPDATA")
    if not local_data:
        return False
    folder = Path(local_data) / "Programs" / "ACMAIS LINK" / "versions" / __version__
    try:
        return (folder / ".complete").is_file() and Path(sys.executable).samefile(folder / "ACMAIS LINK.exe")
    except OSError:
        return False


def main() -> None:
    backend = webview_backend()
    data_dir = ensure_data_dirs()
    instance = SingleInstance(data_dir)
    if not instance.acquire():
        return
    if not webview_available():
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,
            "O Microsoft Edge WebView2 Runtime não está instalado.\nExecute o instalador do ACMAIS LINK com acesso à internet para instalar o componente.",
            "ACMAIS LINK", 0x10)
        instance.close()
        return
    logger = configure_logging(data_dir / "logs")
    development_web = None
    if getattr(sys, "frozen", False):
        home_url = resource_path(f"web/{home_filename()}").resolve().as_uri()
    else:
        development_web = TemporaryDirectory(prefix="acmais-web-", ignore_cleanup_errors=True)
        home_url = prepare_home(resource_path("web"), Path(development_web.name)).as_uri()
    updates = AutoUpdateController(data_dir, __version__, logger=logger) if _automatic_updates_enabled() else None
    api = AppApi(ConfigStore(data_dir / "companies.json"), CredentialStore(), logger, home_url,
                 history=DeliveryHistory(data_dir / "deliveries.sqlite"))
    bridge = SecureBridge(api)
    icon = resource_path("assets/logo.ico" if sys.platform == "win32" else "assets/logo.png")
    geometry = initial_window_geometry()

    window = webview.create_window(
        APP_DISPLAY_TITLE,
        home_url,
        js_api=bridge,
        width=geometry.width,
        height=geometry.height,
        min_size=geometry.min_size,
        x=geometry.x,
        y=geometry.y,
        maximized=geometry.maximized,
        background_color="#F7F8FA",
        text_select=False,
    )
    actions = (api.return_home, api.open_current_external, api.open_company)
    adapter = (NavigationWindow(window, *actions) if backend == "edgechromium"
               else PortableNavigationWindow(window, backend, *actions))
    api._bind_window(adapter)
    window.events.loaded += api._on_loaded

    def initialize_local_ui(window):
        if backend == "edgechromium":
            current = window.get_current_url() or ""
            if is_home_document(current, home_url):
                window.evaluate_js(
                    f"if (location.href === {json.dumps(home_url)}) "
                    f"window.bootstrapAcmais?.({json.dumps(bridge._token)})"
                )
            return
        try:
            current = adapter.get_current_url() or ""
            if is_home_document(current, home_url):
                initialized = adapter.evaluate_navigation_js(
                    f"location.href === {json.dumps(home_url)} && "
                    f"typeof window.bootstrapAcmais === 'function' && "
                    f"(window.bootstrapAcmais({json.dumps(bridge._token)}), true)",
                    lambda: True,
                )
                if initialized:
                    logger.info("Interface local carregada.")
        except (TimeoutError, RuntimeError):
            logger.exception("A interface local não respondeu à inicialização.")
    window.events.loaded += initialize_local_ui
    if sys.platform == "win32":
        def listen_for_restart():
            instance.listen(lambda: adapter.offer_restart(
                api._restart_activity, api._stop_for_restart, instance.decline))

        window.events.before_show += listen_for_restart
    if updates is not None:
        # Native lifecycle, independent of which local or SharePoint page is open.
        window.events.shown += updates.start
    logger.info(
        "Aplicativo iniciado: version=%s executable=%s data_dir=%s navigation=%s",
        __version__,
        sys.executable,
        data_dir,
        backend,
    )
    normal_exit = False
    try:
        webview.start(
            gui=backend,
            private_mode=False,
            storage_path=str(data_dir / "webview"),
            icon=str(icon),
            debug=False,
        )
        normal_exit = True
    finally:
        if updates is not None:
            updates.stop()
        instance.close()
        if development_web is not None:
            development_web.cleanup()
    # The user has already closed the window. Never terminate it to install.
    if normal_exit and updates is not None:
        updates.launch_pending()


if __name__ == "__main__":
    main()
