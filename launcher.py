from __future__ import annotations

import ctypes
import sys
import tempfile
import traceback
from pathlib import Path

from acmais_link.main import main


def report_startup_error() -> None:
    details = traceback.format_exc()
    log_path = Path(tempfile.gettempdir()) / "ACMAIS_LINK_startup_error.log"
    try:
        log_path.write_text(details, encoding="utf-8")
    except OSError:
        pass

    if sys.platform == "win32":
        message = (
            "O ACMAIS LINK não conseguiu iniciar.\n\n"
            f"O diagnóstico foi salvo em:\n{log_path}\n\n"
            "Envie esse arquivo para a equipe de TI."
        )
        ctypes.windll.user32.MessageBoxW(None, message, "ACMAIS LINK", 0x10)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        report_startup_error()
        raise
