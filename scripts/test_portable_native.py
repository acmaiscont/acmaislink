"""Exercise the WebKit adapters in a real native window using a local fixture."""
from pathlib import Path
from tempfile import TemporaryDirectory

import webview

from acmais_link.main import webview_backend
from acmais_link.portable_navigation import PortableNavigationWindow


def check_native_window(window, native, home, result):
    try:
        if not window.events.loaded.wait(20):
            raise RuntimeError("O WebKit não carregou a página de teste.")
        current = lambda: True
        assert native.evaluate_navigation_js(
            "({title: document.title, text: document.querySelector('h1').textContent})", current,
        ) == {"title": "Teste nativo", "text": "Documentos"}
        assert native.show_loading(current, delivery=True)
        native.delivery_progress(2, 4, 50, 100, False, False, current)
        assert native.evaluate_navigation_js("document.querySelector('h1').textContent", current) == "Documentos"
        native.set_company_choices([{"code": "42", "name": "Empresa de teste"}], "42", current)
        assert native.show_folder("42 - Empresa de teste", current)
        native.show_home(current)
        remote = home.with_name("Pasta de teste.html")
        window.events.loaded.clear()
        native.navigate(remote.as_uri(), current)
        if not window.events.loaded.wait(20):
            raise RuntimeError("A navegação do WebKit não concluiu.")
        assert native.evaluate_navigation_js("document.title", current) == "Pasta"
        window.events.loaded.clear()
        native.navigate(home.as_uri(), current)
        if not window.events.loaded.wait(20):
            raise RuntimeError("O WebKit não voltou à interface local.")
        assert native.evaluate_navigation_js("document.title", current) == "Teste nativo"
        result.append(True)
    finally:
        window.destroy()


if __name__ == "__main__":
    backend = webview_backend()
    with TemporaryDirectory(prefix="acmais-native-") as temporary:
        home = Path(temporary) / "Tela inicial.html"
        home.write_text("<title>Teste nativo</title><h1>Documentos</h1>", encoding="utf-8")
        home.with_name("Pasta de teste.html").write_text("<title>Pasta</title>", encoding="utf-8")
        window = webview.create_window("ACMAIS LINK CI", home.as_uri(), width=900, height=600)
        native = PortableNavigationWindow(window, backend, lambda: None, lambda: None, lambda _code: None)
        result = []
        webview.start(check_native_window, (window, native, home, result), gui=backend, private_mode=False,
                      storage_path=str(Path(temporary) / "profile"))
        if not result:
            raise RuntimeError("Controles ou navegação falharam no renderer nativo.")
        print("O WebKit abriu a página, exibiu o progresso e voltou à tela inicial na mesma janela.")
