from pathlib import Path
import sys

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

root = Path(SPECPATH)
sys.path.insert(0, str(root / "src"))
from acmais_link import __version__
from acmais_link.web_home import prepare_home

web_source = root / "src" / "acmais_link" / "web"
web_dir = Path(workpath) / f"web-v{__version__}"
prepare_home(web_source, web_dir)
version_parts = (*map(int, __version__.split(".")), 0)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_parts, prodvers=version_parts),
    kids=[
        StringFileInfo([StringTable("041604b0", [
            StringStruct("ProductName", "ACMAIS LINK"),
            StringStruct("FileDescription", "ACMAIS LINK"),
            StringStruct("FileVersion", __version__),
            StringStruct("ProductVersion", __version__),
        ])]),
        VarFileInfo([VarStruct("Translation", [1046, 1200])]),
    ],
)

a = Analysis(
    [str(root / "launcher.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[
        (str(web_dir), "web"),
        (str(root / "src" / "acmais_link" / "assets"), "assets"),
    ],
    hiddenimports=["keyring.backends.Windows"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ACMAIS LINK",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=version_info,
    icon=str(root / "src" / "acmais_link" / "assets" / "logo.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="ACMAIS LINK",
)
