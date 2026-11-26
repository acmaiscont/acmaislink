from pathlib import Path
import sys

root = Path(SPECPATH)
sys.path.insert(0, str(root / "src"))
from acmais_link import __version__
from acmais_link.web_home import prepare_home

macos = sys.platform == "darwin"
web_dir = Path(workpath) / f"web-v{__version__}"
prepare_home(root / "src" / "acmais_link" / "web", web_dir)

a = Analysis(
    [str(root / "launcher.py")],
    pathex=[str(root / "src")],
    datas=[
        (str(web_dir), "web"),
        (str(root / "src" / "acmais_link" / "assets"), "assets"),
    ],
    hiddenimports=(
        ["webview.platforms.cocoa", "keyring.backends.macOS"]
        if macos else
        ["webview.platforms.gtk", "gi.repository.WebKit2", "keyring.backends.SecretService"]
    ),
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ACMAIS LINK",
    console=not macos,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="ACMAIS LINK")

if macos:
    app = BUNDLE(
        coll,
        name="ACMAIS LINK.app",
        icon=str(root / "src" / "acmais_link" / "assets" / "logo.png"),
        bundle_identifier="br.com.acmaiscont.acmaislink",
        version=__version__,
        info_plist={"CFBundleVersion": __version__},
    )
