"""Open the actual Unix app in an isolated profile and check its initial page."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def check_startup(command):
    with tempfile.TemporaryDirectory(prefix="acmais-smoke-") as temporary:
        profile = Path(temporary)
        environment = {
            **os.environ,
            "HOME": str(profile),
            "XDG_CONFIG_HOME": str(profile / "config"),
        }
        data = (profile / "Library/Application Support/ACMAIS/ACMAIS LINK"
                if sys.platform == "darwin" else profile / "config/acmais-link")
        log = data / "logs/acmais-link.log"
        output = profile / "output.log"
        with output.open("wb") as stream:
            process = subprocess.Popen(command, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            try:
                for _ in range(75):
                    if process.poll() is not None:
                        raise RuntimeError(f"O aplicativo encerrou durante a abertura ({process.returncode}).")
                    if log.exists() and "Interface local carregada." in log.read_text(encoding="utf-8"):
                        print("Janela e recursos da interface carregados no renderer nativo.")
                        return
                    time.sleep(1)
                raise TimeoutError("A interface local não carregou em 75 segundos.")
            except (RuntimeError, TimeoutError):
                for diagnostic in (log, output):
                    if diagnostic.exists():
                        print(diagnostic.read_text(encoding="utf-8", errors="replace"), flush=True)
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    check_startup(sys.argv[1:] or [sys.executable, "launcher.py"])
