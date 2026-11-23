"""Generate the local home document using the release version."""
from os.path import normcase
from pathlib import Path
from shutil import copy2
from urllib.parse import unquote, urlsplit

from . import __version__


VERSION_MARKER = "__ACMAIS_VERSION__"


def is_home_document(current: str, home: str) -> bool:
    if current == home:
        return True
    # System.Uri.ToString() can display paths with spaces instead of %20.
    page, expected = urlsplit(current), urlsplit(home)
    return (page.scheme == expected.scheme == "file"
            and page.netloc == expected.netloc and not page.query and not page.fragment
            and normcase(unquote(page.path)) == normcase(unquote(expected.path)))


def home_filename(version=__version__):
    # A different URL per release avoids reusing older WebView2 HTML.
    return f"index-v{version}.html"


def render_home(template: str, version=__version__) -> str:
    expected = (
        f'<span id="app-identity">ACMAIS LINK · v{VERSION_MARKER}</span>',
        f'app.js?v={VERSION_MARKER}',
        f'style.css?v={VERSION_MARKER}',
    )
    if any(template.count(text) != 1 for text in expected):
        raise ValueError("O rodapé ou os recursos da interface perderam o marcador de versão.")
    return template.replace(VERSION_MARKER, version)


def prepare_home(source: Path, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    template = source / "index.html"
    for asset in source.iterdir():
        if asset.is_file() and asset != template:
            copy2(asset, output / asset.name)
    home = output / home_filename()
    home.write_text(render_home(template.read_text(encoding="utf-8")), encoding="utf-8")
    return home
