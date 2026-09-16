from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .models import Company


class ConfigStore:
    """Atomic store for non-sensitive company configuration."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def list(self) -> list[Company]:
        with self._lock:
            data = self._read()
            companies = [Company.from_payload(item) for item in data.get("companies", [])]
            return sorted(companies, key=lambda item: (item.code.casefold(), item.name.casefold()))

    def get(self, code: str) -> Company | None:
        normalized = code.strip().casefold()
        return next((item for item in self.list() if item.code.casefold() == normalized), None)

    def upsert(self, company: Company, original_code: str | None = None) -> None:
        with self._lock:
            companies = self.list()
            original = (original_code or company.code).strip().casefold()
            duplicate = next(
                (item for item in companies if item.code.casefold() == company.code.casefold() and item.code.casefold() != original),
                None,
            )
            if duplicate:
                raise ValueError("Já existe uma empresa com este código.")
            companies = [item for item in companies if item.code.casefold() != original]
            companies.append(company)
            self._write(companies)

    def delete(self, code: str) -> bool:
        with self._lock:
            companies = self.list()
            kept = [item for item in companies if item.code.casefold() != code.strip().casefold()]
            if len(kept) == len(companies):
                return False
            self._write(kept)
            return True

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "companies": []}
        with self.path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if data.get("version") != 1 or not isinstance(data.get("companies"), list):
            raise ValueError("O arquivo de configuração possui um formato incompatível.")
        return data

    def _write(self, companies: list[Company]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "companies": [item.to_dict() for item in companies]}
        fd, temporary_name = tempfile.mkstemp(prefix="companies-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
            if os.name != "nt":
                self.path.chmod(0o600)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

