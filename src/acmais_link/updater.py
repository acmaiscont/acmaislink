"""Stable GitHub Releases; bounded HTTPS download with required SHA-256 digest."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

REPOSITORY = "acmaiscont/acmaislink"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_PACKAGE = 250 * 1024 * 1024


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?([0-9]+)\.([0-9]+)\.([0-9]+)", value) if isinstance(value, str) and len(value) < 64 else None
    if not match:
        raise ValueError("A versão publicada não é uma versão estável válida.")
    return tuple(map(int, match.groups()))


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in {
            "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"
        } or parsed.username or parsed.password or parsed.port not in {None, 443}
                or "\\" in newurl or any(ord(char) < 32 for char in newurl)):
            raise ValueError("Redirecionamento de atualização não permitido.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UpdateService:
    def __init__(self, current: str):
        version_tuple(current)
        self.current = current
        self.release = None
        self._opener = build_opener(SafeRedirect())

    def _open(self, url):
        return self._opener.open(Request(url, headers={
            "User-Agent": "ACMAIS-LINK-Updater", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }), timeout=15)

    def check(self):
        self.release = None
        try:
            with self._open(API_URL) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Resposta de atualização muito grande.")
            return self._select(json.loads(raw))
        except HTTPError as exc:
            if exc.code == 404:
                return {"ok": True, "available": False, "message": "Nenhuma versão pública disponível ainda."}
            raise

    def _select(self, release):
        self.release = None
        if not isinstance(release, dict):
            raise ValueError("A resposta de atualização é inválida.")
        if release.get("draft") or release.get("prerelease"):
            raise ValueError("A atualização não é uma versão estável publicada.")
        tag = release.get("tag_name", "")
        if version_tuple(tag) <= version_tuple(self.current):
            return {"ok": True, "available": False, "message": "Você está na versão mais recente."}
        name = f"ACMAIS-LINK-{tag.removeprefix('v')}-x64-update.exe"
        assets = release.get("assets", [])
        if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
            raise ValueError("A lista de pacotes de atualização é inválida.")
        matches = [a for a in assets if a.get("name") == name]
        if len(matches) != 1:
            raise ValueError("A versão não contém um pacote de atualização válido.")
        asset = matches[0]
        url = asset.get("browser_download_url", "")
        digest = asset.get("digest") or ""
        size = asset.get("size", 0)
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("Origem ou hash do pacote de atualização inválido.")
        self.release = self.validate_release({"url": url, "digest": digest[7:], "size": size, "version": tag})
        return {"ok": True, "available": True, "version": tag,
                "message": f"Versão {tag} disponível. Salve seu trabalho antes de instalar."}

    def validate_release(self, metadata, require_newer: bool = True) -> dict:
        """Validate downloaded or cached metadata without trusting a local path."""
        if not isinstance(metadata, dict):
            raise ValueError("Metadados de atualização inválidos.")
        tag = metadata.get("version")
        version = version_tuple(tag)
        if require_newer and version <= version_tuple(self.current):
            raise ValueError("O pacote não é mais recente que a versão instalada.")
        name = f"ACMAIS-LINK-{tag.removeprefix('v')}-x64-update.exe"
        expected = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
        digest = metadata.get("digest")
        size = metadata.get("size")
        if (metadata.get("url") != expected or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Origem ou hash do pacote de atualização inválido.")
        if type(size) is not int or not 0 < size <= MAX_PACKAGE:
            raise ValueError("Tamanho do pacote inválido.")
        return {"url": expected, "digest": digest, "size": size, "version": tag}

    def validate_package(self, path: Path, release=None) -> Path:
        """Rehash a cached installer before each use, including immediately at launch."""
        metadata = self.validate_release(self.release if release is None else release)
        package = Path(path)
        if package.is_symlink():
            raise ValueError("Caminho do pacote de atualização inválido.")
        package = package.resolve(strict=True)
        if not package.is_file() or package.stat().st_size != metadata["size"]:
            raise ValueError("Falha de integridade. O pacote não será executado.")
        digest = hashlib.sha256()
        total = 0
        with package.open("rb") as stream:
            while block := stream.read(256 * 1024):
                total += len(block)
                if total > metadata["size"]:
                    raise ValueError("Falha de integridade. O pacote não será executado.")
                digest.update(block)
        if total != metadata["size"] or digest.hexdigest() != metadata["digest"]:
            raise ValueError("Falha de integridade. O pacote não será executado.")
        return package

    def download(self) -> Path:
        if not self.release:
            raise ValueError("Consulte as atualizações antes de instalar.")
        release = self.validate_release(self.release)
        folder = Path(tempfile.mkdtemp(prefix="acmais-update-"))
        target = folder / "ACMAIS-LINK-update.exe"
        digest = hashlib.sha256()
        total = 0
        deadline = time.monotonic() + 300
        try:
            with self._open(release["url"]) as response, target.open("xb") as stream:
                while block := response.read(256 * 1024):
                    total += len(block)
                    if total > release["size"] or time.monotonic() > deadline:
                        raise ValueError("Download excedeu o tamanho ou o tempo permitido.")
                    digest.update(block)
                    stream.write(block)
            if total != release["size"] or digest.hexdigest() != release["digest"]:
                raise ValueError("Falha de integridade. O pacote não será executado.")
            return target
        except Exception:
            target.unlink(missing_ok=True)
            folder.rmdir()
            raise

    def launch(self, path: Path, silent: bool = False, release=None):
        """Start a verified installer; the caller controls when the app can exit.

        Silent callers must close the window and release the application mutex
        first. NSIS fails safely with exit code 2 if another instance has reopened.
        Starting a process is not proof of a successful installation.
        """
        package = self.validate_package(path, release=release)
        if package.suffix.lower() != ".exe":
            raise ValueError("O pacote de atualização não é um executável válido.")
        command = [str(package)]
        if silent:
            command.append("/S")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if silent and sys.platform == "win32" else 0
        return subprocess.Popen(command, shell=False, cwd=str(package.parent), creationflags=flags)
