from __future__ import annotations

import os
import sys
from pathlib import Path


APP_VENDOR = "ACMAIS"
APP_NAME = "ACMAIS LINK"


def user_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / APP_VENDOR / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_VENDOR / APP_NAME
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "acmais-link"


def ensure_data_dirs() -> Path:
    base = user_data_dir()
    (base / "logs").mkdir(parents=True, exist_ok=True)
    (base / "webview").mkdir(parents=True, exist_ok=True)
    return base

