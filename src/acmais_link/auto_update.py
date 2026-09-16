"""Download verified updates in the background and apply only on normal exit."""
from __future__ import annotations

import json
import logging
import math
import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from .updater import UpdateService, version_tuple


CHECK_INTERVAL = 4 * 60 * 60
MANIFEST_LIMIT = 16 * 1024


@dataclass(frozen=True)
class PendingUpdate:
    path: Path
    release: dict


class AutoUpdateController:
    """One worker, one trusted in-memory candidate, and a recoverable disk cache.

    The manifest is only a cache index, not proof of authenticity. Every process
    must confirm its metadata over HTTPS before cached bytes become executable.
    """

    def __init__(self, data_dir: Path, current_version: str, logger=None,
                 service=None, interval: float = CHECK_INTERVAL):
        version_tuple(current_version)
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("The update check interval must be positive")
        self._data_dir = Path(data_dir).resolve()
        self._cache_dir = self._data_dir / "updates"
        self._current_version = current_version
        self._logger = logger or logging.getLogger(__name__)
        self._service = service if service is not None else UpdateService(current_version)
        self._interval = interval
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: PendingUpdate | None = None
        self._exit_candidate: PendingUpdate | None = None
        self._launch_attempted = False
        self._state = "checking"
        self._version = None

    def start(self) -> None:
        """Start once, after the app window is shown; never block its UI thread."""
        with self._lock:
            if self._thread is not None or self._stop_event.is_set():
                return
            self._thread = threading.Thread(
                target=self._run, name="acmais-auto-update", daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Freeze the candidate already ready at exit; never wait for network I/O."""
        with self._lock:
            if not self._stop_event.is_set():
                self._exit_candidate = self._pending
                self._stop_event.set()

    def status(self) -> dict:
        with self._lock:
            return {"state": self._state, "version": self._version,
                    "currentVersion": self._current_version}

    def launch_pending(self) -> bool:
        """Apply at most once, after stop(), against the trusted memory snapshot."""
        with self._lock:
            candidate = self._exit_candidate
            if not self._stop_event.is_set() or candidate is None or self._launch_attempted:
                return False
            self._launch_attempted = True
        try:
            path = self._cache_path(candidate.path.name)
            if path != candidate.path:
                raise ValueError("Cached package changed location")
            metadata = dict(candidate.release)
            self._service.validate_package(path, release=metadata)
            self._service.launch(path, silent=True, release=metadata)
            # Launch is not installation success: NSIS may defer if another app
            # instance reopened. Keep the manifest/package for the next session.
            self._logger.info("Instalador de atualização iniciado após o fechamento")
            return True
        except Exception as exc:
            self._logger.warning("Atualização adiada: %s", type(exc).__name__)
            with self._lock:
                self._state = "retry"
            return False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._check_once()
            if self._stop_event.wait(self._interval):
                return

    def _set_state(self, state: str, version=None) -> bool:
        with self._lock:
            if self._stop_event.is_set():
                return False
            self._state = state
            self._version = version
            return True

    def _check_once(self) -> None:
        if not self._set_state("checking"):
            return
        downloaded = None
        try:
            result = self._service.check()
            if self._stop_event.is_set():
                return
            if not isinstance(result, dict) or not result.get("ok"):
                raise ValueError("Update check did not succeed")
            if not result.get("available"):
                with self._lock:
                    if not self._stop_event.is_set():
                        self._pending = None
                        self._state = "current"
                        self._version = None
                return

            # Trust only the release selected by this session's HTTPS query.
            metadata = self._service.validate_release(self._service.release)
            metadata = dict(metadata)
            package = self._cached_package(metadata)
            if package is None:
                if not self._set_state("downloading", metadata["version"]):
                    return
                downloaded = Path(self._service.download())
                if self._stop_event.is_set():
                    return
                package = self._store_package(downloaded, metadata)

            with self._lock:
                if self._stop_event.is_set():
                    return
                self._pending = PendingUpdate(package, dict(metadata))
                self._state = "ready"
                self._version = metadata["version"]
        except Exception as exc:
            self._logger.info("Consulta automática adiada: %s", type(exc).__name__)
            with self._lock:
                if not self._stop_event.is_set():
                    # A transient outage need not discard bytes already checked
                    # against trusted metadata earlier in this same process.
                    self._state = "ready" if self._pending else "retry"
                    self._version = self._pending.release["version"] if self._pending else None
        finally:
            if downloaded is not None:
                self._discard_download(downloaded)

    @staticmethod
    def _is_redirected(path: Path) -> bool:
        if path.is_symlink():
            return True
        try:
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        except FileNotFoundError:
            return False

    def _ensure_cache(self) -> None:
        if self._is_redirected(self._cache_dir):
            raise ValueError("The update cache cannot be redirected")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        if self._cache_dir.resolve() != self._cache_dir:
            raise ValueError("The update cache changed location")

    def _cache_path(self, name: str) -> Path:
        self._ensure_cache()
        if not name or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Invalid cached filename")
        path = self._cache_dir / name
        if self._is_redirected(path) or path.resolve().parent != self._cache_dir:
            raise ValueError("The cached file cannot be redirected")
        return path

    @staticmethod
    def _package_name(metadata: dict) -> str:
        return (f"ACMAIS-LINK-{metadata['version'].removeprefix('v')}-"
                f"{metadata['digest'][:16]}-x64-update.exe")

    def _cached_package(self, metadata: dict) -> Path | None:
        try:
            manifest = self._cache_path("manifest.json")
            with manifest.open("rb") as stream:
                raw = stream.read(MANIFEST_LIMIT + 1)
            if len(raw) > MANIFEST_LIMIT:
                raise ValueError("Update manifest is too large")
            payload = json.loads(raw)
            if (not isinstance(payload, dict) or type(payload.get("schema")) is not int
                    or payload["schema"] != 1):
                raise ValueError("Invalid update manifest")
            cached_release = self._service.validate_release(payload.get("release"))
            expected_name = self._package_name(metadata)
            if cached_release != metadata or payload.get("package") != expected_name:
                return None
            package = self._cache_path(expected_name)
            self._service.validate_package(package, release=metadata)
            return package
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def _store_package(self, source: Path, metadata: dict) -> Path:
        self._service.validate_package(source, release=metadata)
        target = self._cache_path(self._package_name(metadata))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self._cache_dir, prefix=".download-", suffix=".part", delete=False,
            ) as output:
                temporary = Path(output.name)
                with source.open("rb") as incoming:
                    total = 0
                    while block := incoming.read(256 * 1024):
                        if self._stop_event.is_set():
                            raise InterruptedError("Application is closing")
                        total += len(block)
                        if total > metadata["size"]:
                            raise ValueError("The source package changed size")
                        output.write(block)
                output.flush()
                os.fsync(output.fileno())
            self._service.validate_package(temporary, release=metadata)
            os.replace(temporary, target)
            temporary = None
            self._write_manifest(target.name, metadata)
            return target
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _write_manifest(self, package_name: str, metadata: dict) -> None:
        manifest = self._cache_path("manifest.json")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._cache_dir,
                prefix=".manifest-", suffix=".part", delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump({"schema": 1, "package": package_name, "release": metadata}, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, manifest)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _discard_download(self, downloaded: Path) -> None:
        # Only remove the disposable file returned by UpdateService.download().
        # Injected services may own another source file; leave those untouched.
        try:
            folder = downloaded.parent
            temp_root = Path(tempfile.gettempdir()).resolve()
            if (downloaded.name != "ACMAIS-LINK-update.exe"
                    or not folder.name.startswith("acmais-update-")
                    or folder.parent.resolve() != temp_root
                    or self._is_redirected(downloaded) or self._is_redirected(folder)):
                return
            downloaded.unlink(missing_ok=True)
            folder.rmdir()
        except OSError:
            pass
