from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .models import Company


class ConfigStore:
    """Atomic store for company configuration and confidential sharing links."""

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
            normalized = code.strip().casefold()
            company = next((item for item in companies if item.code.casefold() == normalized), None)
            if company is None:
                return False
            hidden = self._read().get("hidden_group_members", {})
            if company.group_code:
                codes = hidden.setdefault(company.group_code, [])
                if company.code not in codes:
                    codes.append(company.code)
            self._write([item for item in companies if item.code.casefold() != normalized], hidden)
            return True

    def replace_group(self, group_code: str, members: list[Company]) -> tuple[int, int]:
        """Refresh the group's list in one write and retain independent accesses."""
        with self._lock:
            kept = [item for item in self.list() if item.group_code != group_code]
            existing_codes = {item.code.casefold() for item in kept}
            admitted = [item for item in members if item.code.casefold() not in existing_codes]
            if not admitted:
                raise ValueError("As empresas deste grupo já estão cadastradas por outro acesso.")
            hidden = self._read().get("hidden_group_members", {})
            hidden.pop(group_code, None)
            self._write(kept + admitted, hidden)
            return len(admitted), len(members) - len(admitted)

    def add_group_members(self, source: Company, members: list[Company]) -> int:
        with self._lock:
            companies = self.list()
            if source not in companies:
                raise ValueError("O acesso do grupo mudou. Abra a lista de empresas e tente novamente.")
            hidden = self._read().get("hidden_group_members", {})
            excluded = {item.code.casefold() for item in companies}
            excluded.update(code.casefold() for code in hidden.get(source.group_code, []))
            additions = [item for item in members if item.code.casefold() not in excluded]
            if additions:
                self._write(companies + additions, hidden)
            return len(additions)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "companies": []}
        with self.path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("companies"), list):
            raise ValueError("O arquivo de configuração possui um formato incompatível.")
        return data

    def _write(self, companies: list[Company], hidden_group_members: dict | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "companies": [item.to_dict() for item in companies]}
        if hidden_group_members is None:
            hidden_group_members = self._read().get("hidden_group_members", {})
        if hidden_group_members:
            payload["hidden_group_members"] = hidden_group_members
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

