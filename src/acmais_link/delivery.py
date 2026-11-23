"""Catalog and local receipt history for the guided SharePoint delivery."""
from __future__ import annotations

import os
import re
import sqlite3
import stat
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit
from xml.parsers import expat

from .models import ValidationError, is_allowed_sharepoint_url
from .sharepoint import extract_company_identity


FISCAL_TYPES = (
    "NF - Vendas de Mercadoria e Serviços Prestados",
    "NF - Serviços Contratados e Faturas de Locação",
    "NF - Compra de Mercadorias, Faturas de Telefone e Energia Elétrica",
)
CATALOG = {
    "Fiscal": FISCAL_TYPES,
    "Contábil": ("Extratos", "Outros documentos"),
}
MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_FOLDER_ITEMS = 300


@dataclass(frozen=True)
class DeliveryOutcome:
    status: str
    detail: str = ""


@dataclass(frozen=True)
class DeliveryRoute:
    year: str
    month: int
    sector: str
    kind: str

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict):
            raise ValidationError("Confira os dados do envio.")
        period = payload.get("period")
        sector, kind = payload.get("sector"), payload.get("kind")
        if not isinstance(period, str) or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])", period):
            raise ValidationError("Informe uma competência válida.")
        if not isinstance(sector, str) or not isinstance(kind, str):
            raise ValidationError("Selecione um setor e um tipo de documento do catálogo.")
        if kind not in CATALOG.get(sector, ()):
            raise ValidationError("Selecione um setor e um tipo de documento do catálogo.")
        return cls(period[:4], int(period[5:]), sector, kind)

    @property
    def period(self):
        return f"{self.year}-{self.month:02}"

    @property
    def segments(self):
        return self.year, f"{self.month:02}-{self.year}", self.sector, self.kind

def company_root_from_library_url(url: str, company_code: str) -> str | None:
    """Read the company root from a resolved library view, never from the share token."""
    if not is_allowed_sharepoint_url(url):
        return None
    parsed = urlsplit(url)
    if not parsed.path.casefold().endswith("/forms/allitems.aspx"):
        return None
    query = {key.casefold(): values for key, values in parse_qs(parsed.query).items()}
    path = (query.get("id") or query.get("rootfolder") or [""])[0]
    library = unquote(parsed.path[:-len("/Forms/AllItems.aspx")])
    if not path.casefold().startswith(library.casefold() + "/") or "\\" in path:
        return None
    parts = path[1:].split("/")
    if any(not part or part in (".", "..") or any(ord(ch) < 32 for ch in part) for part in parts):
        return None
    library_depth = len(library[1:].split("/"))
    for index in range(library_depth, len(parts)):
        part = parts[index]
        if extract_company_identity("", part, expected_code=company_code):
            return "/" + "/".join(parts[:index + 1])
    return None


def library_destination(url: str, company_code: str, route: DeliveryRoute) -> tuple[str, str] | None:
    root = company_root_from_library_url(url, company_code)
    if root is None:
        return None
    parsed = urlsplit(url)
    destination = "/".join((root, *route.segments))
    return destination, urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode({"id": destination}), ""))


class _XmlRootFound(Exception):
    pass


def is_fiscal_xml(path: Path) -> bool:
    """Inspect the first element only, with a fixed read limit and no DTD."""
    if path.suffix.casefold() != ".xml":
        return False
    accepted = False
    parser = expat.ParserCreate(namespace_separator=" ")

    def root(name, _attributes):
        nonlocal accepted
        namespace, _, tag = name.rpartition(" ")
        accepted = (
            namespace == "http://www.portalfiscal.inf.br/nfe" and tag in {"NFe", "nfeProc"}
            or namespace == "http://www.portalfiscal.inf.br/cte" and tag in {"CTe", "cteProc"}
            or namespace == "http://www.portalfiscal.inf.br/mdfe" and tag in {"MDFe", "mdfeProc"}
        )
        raise _XmlRootFound

    def reject_dtd(*_):
        raise _XmlRootFound

    parser.StartElementHandler = root
    parser.StartDoctypeDeclHandler = reject_dtd
    try:
        with path.open("rb") as source:
            parser.Parse(source.read(65536), False)
    except (_XmlRootFound, expat.ExpatError, OSError):
        pass
    return accepted


@dataclass(frozen=True)
class DeliveryItem:
    source: Path
    parts: tuple[str, ...]
    size: int
    directory: bool = False

    @property
    def label(self):
        return "/".join(self.parts) + ("/" if self.directory else "")


def _normal_path(path):
    info = path.lstat()
    # Reject symbolic links and junctions without excluding OneDrive reparse placeholders.
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003):
        raise ValidationError("Remova atalhos e links da seleção antes de enviar.")
    return info


def delivery_selection(selected, *, folder=False) -> tuple[DeliveryItem, ...]:
    limit = MAX_FOLDER_ITEMS if folder else 30
    items, seen = [], set()
    visited = 0

    def append(path, parts, info, *, directory=False):
        if not directory and (not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= MAX_FILE_SIZE):
            raise ValidationError("Selecione arquivos disponíveis neste computador, de até 100 MB cada.")
        items.append(DeliveryItem(path, parts, 0 if directory else info.st_size, directory))

    def scan(path, parts, *, descend):
        nonlocal visited
        visited += 1
        if visited > limit or len(parts) > 12:
            raise ValidationError(f"A seleção excede {limit} itens ou 12 níveis de pastas.")
        if not parts[-1] or parts[-1] in {".", ".."} or re.search(r'[/\\:*?"<>|\x00-\x1f]', parts[-1]):
            raise ValidationError("Há um nome de arquivo ou pasta incompatível com o SharePoint.")
        key = tuple(part.casefold() for part in parts)
        if key in seen:
            raise ValidationError("A seleção contém caminhos com nomes iguais.")
        seen.add(key)
        info = _normal_path(path)
        if descend and stat.S_ISDIR(info.st_mode):
            with os.scandir(path) as entries:
                empty = True
                for entry in entries:
                    empty = False
                    scan(Path(entry.path), (*parts, entry.name), descend=True)
                if empty:
                    append(path, parts, info, directory=True)
        else:
            append(path, parts, info)

    for chosen in selected:
        path = Path(chosen)
        _normal_path(path)
        path = path.resolve(strict=True)
        if not path.name:
            raise ValidationError("Selecione uma pasta de documentos, sem incluir a unidade inteira.")
        scan(path, (path.name,), descend=folder)
    return tuple(sorted(items, key=lambda item: item.parts))


def suggest_delivery(items):
    """Suggest only destinations shared by every selected file with recognizable evidence."""
    def classify(path):
        extension = path.suffix.casefold()
        name = unicodedata.normalize("NFKD", path.stem.casefold())
        words = set(re.findall("[a-z0-9]+", "".join(ch for ch in name if not unicodedata.combining(ch))))
        if is_fiscal_xml(path):
            return "Fiscal", None
        if extension in {".ofx", ".qfx", ".qif"} or (
            extension in {".pdf", ".csv", ".xlsx", ".xls", ".txt"} and words & {"extrato", "extratos"}
        ):
            return "Contábil", "Extratos"
        if extension == ".pdf" and words & {"danfe", "dacte", "nfse", "nfe"}:
            return "Fiscal", None
        if extension in {".pdf", ".csv", ".xlsx", ".xls"} and words & {"balancete", "balanco", "dre", "razao"}:
            return "Contábil", "Outros documentos"
        return None, None

    matches = [classify(item.source) for item in items if not item.directory]
    if not matches or not matches[0][0] or any(sector != matches[0][0] for sector, _ in matches):
        return None
    sector, kind = matches[0]
    if any(other != kind for _, other in matches):
        kind = None
    return {"sector": sector, "kind": kind, "period": previous_period() if sector == "Fiscal" else None}


def previous_period(today: date | None = None) -> str:
    today = today or date.today()
    year = today.year - (today.month == 1)
    month = (today.month - 2) % 12 + 1
    return f"{year:04}-{month:02}"


class DeliveryHistory:
    """Recent receipts only. Local paths, URLs, credentials and bytes are excluded."""

    def __init__(self, database: Path):
        self._database = database

    def _connect(self):
        connection = sqlite3.connect(self._database, timeout=3)
        try:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS receipts (
                    id INTEGER PRIMARY KEY, company TEXT NOT NULL, period TEXT NOT NULL,
                    destination TEXT NOT NULL, filename TEXT NOT NULL,
                    status TEXT NOT NULL, recorded_at TEXT NOT NULL,
                    company_code TEXT NOT NULL, sector TEXT NOT NULL, kind TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                )"""
            )
            def has_detail():
                return any(column[1] == "detail" for column in connection.execute("PRAGMA table_info(receipts)"))

            if not has_detail():
                # Recheck under the write lock in case another worker migrated first.
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    if not has_detail():
                        connection.execute("ALTER TABLE receipts ADD COLUMN detail TEXT NOT NULL DEFAULT ''")
            return connection
        except Exception:
            connection.close()
            raise

    def start(self, company_code: str, company: str, route: DeliveryRoute, filename: str) -> int:
        with closing(self._connect()) as connection, connection:
            entry = connection.execute(
                """INSERT INTO receipts (company, period, destination, filename, status, recorded_at,
                                         company_code, sector, kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (company, route.period, " / ".join(route.segments), filename,
                 "uncertain", datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 company_code, route.sector, route.kind),
            )
            connection.execute(
                "DELETE FROM receipts WHERE id IN (SELECT id FROM receipts ORDER BY id DESC LIMIT -1 OFFSET ?)",
                (MAX_FOLDER_ITEMS,),
            )
            return entry.lastrowid

    def finish(self, receipt_id: int, status: str, detail: str = "") -> None:
        if status not in {"sent", "failed", "uncertain"}:
            raise ValueError("Invalid delivery status")
        with closing(self._connect()) as connection, connection:
            connection.execute("UPDATE receipts SET status = ?, detail = ? WHERE id = ?", (status, detail, receipt_id))

    def recent(self) -> list[dict]:
        with closing(self._connect()) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT id, company, period, destination, filename, status, recorded_at, sector, kind, detail
                   FROM receipts ORDER BY id DESC LIMIT ?""",
                (MAX_FOLDER_ITEMS,),
            )
            receipts = []
            for row in rows:
                receipt = dict(row)
                sector, kind = receipt.pop("sector"), receipt.pop("kind")
                receipt["canOpen"] = self._receipt_route(receipt["period"], sector, kind, receipt["destination"]) is not None
                receipts.append(receipt)
            return receipts

    def route_for(self, receipt_id: int) -> tuple[str, DeliveryRoute] | None:
        with closing(self._connect()) as connection:
            entry = connection.execute(
                "SELECT company_code, period, sector, kind, destination FROM receipts WHERE id = ?", (receipt_id,),
            ).fetchone()
        if entry is None:
            return None
        code, period, sector, kind, destination = entry
        route = self._receipt_route(period, sector, kind, destination)
        return (code, route) if route is not None else None

    @staticmethod
    def _receipt_route(period, sector, kind, destination):
        try:
            route = DeliveryRoute.from_payload({"period": period, "sector": sector, "kind": kind})
        except ValidationError:
            return None
        return route if destination == " / ".join(route.segments) else None
