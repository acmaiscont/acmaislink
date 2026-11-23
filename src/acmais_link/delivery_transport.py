"""Stream a delivery through SharePoint REST with the authorized WebView session."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .delivery import DeliveryOutcome, MAX_FILE_SIZE
from .models import ValidationError, is_allowed_sharepoint_url


class MissingDestination(ValidationError):
    pass


DUPLICATE = DeliveryOutcome("failed", "Já existe um arquivo com o mesmo nome nessa pasta. O arquivo existente foi preservado.")
UNCONFIRMED = DeliveryOutcome("uncertain", "O SharePoint não confirmou o recebimento. Confira a pasta antes de tentar novamente.")
NETWORK_ERRORS = (OSError, http.client.HTTPException)
REJECTION_DETAILS = {
    400: "O SharePoint recusou o arquivo. Confira o nome e tente novamente.",
    401: "A sessão do SharePoint expirou ou não tem acesso. Abra a pasta da empresa novamente.",
    403: "O SharePoint negou o acesso. Confira a permissão de envio para esta pasta.",
    404: "O SharePoint não encontrou a pasta de destino.",
    409: "O SharePoint encontrou um conflito na pasta de destino. Confira os arquivos existentes.",
    412: "A pasta ou o arquivo mudou no SharePoint durante o envio. Confira o destino.",
    413: "O arquivo ultrapassa o limite de tamanho aceito pelo SharePoint.",
    415: "O SharePoint recusou o formato do arquivo.",
    423: "O arquivo ou a pasta está bloqueado no SharePoint. Tente novamente mais tarde.",
    429: "O SharePoint está limitando os envios. Aguarde um pouco e tente novamente.",
}


def _literal(value: str) -> str:
    return quote("'" + value.replace("'", "''") + "'", safe="")


class SharePointDelivery:
    def __init__(self, library_url: str, destination: str, cookies_for, current):
        if not is_allowed_sharepoint_url(library_url):
            raise ValidationError("Endereço do SharePoint inválido.")
        library = urlsplit(library_url)
        parts = library.path.split("/")
        self._base = "/".join(parts[:3]) if len(parts) > 3 and parts[1].casefold() in {"sites", "teams"} else ""
        self._origin = f"https://{library.hostname}"
        self._host = library.hostname
        self._destination = destination
        self._folders = set()
        self._cookies_for = cookies_for
        self._current = current
        self._digest = None
        self._connection = http.client.HTTPSConnection(self._host, timeout=15)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._connection.close()

    def _request(self, method, endpoint, body=None, size=0, digest=None, *, content_type="application/octet-stream"):
        target = self._base + "/_api" + endpoint
        if not self._current():
            raise InterruptedError()
        cookies = self._cookies_for(self._origin + target)
        if not self._current():
            raise InterruptedError()
        headers = {"Accept": "application/json;odata=verbose", "Cookie": cookies}
        if method == "POST":
            headers["Content-Length"] = str(size)
        if digest:
            headers["X-RequestDigest"] = digest
            headers["Content-Type"] = content_type
        # Reuse the TCP/TLS session without replaying a failed POST or following redirects.
        connection = self._connection
        try:
            connection.request(method, target, body, headers=headers)
            response = connection.getresponse()
            content = response.read(65537)
            if len(content) > 65536:
                connection.close()
                return response.status, {}
            try:
                data = json.loads(content) if content else {}
                return response.status, data if isinstance(data, dict) and isinstance(data.get("d", {}), dict) else {}
            except (UnicodeError, ValueError):
                return response.status, {}
        except Exception:
            connection.close()
            raise

    @staticmethod
    def _folder_endpoint(path):
        return f"/web/GetFolderByServerRelativePath(decodedurl={_literal(path)})"

    def _folder_exists(self, path):
        status, result = self._request("GET", self._folder_endpoint(path) + "?$select=Exists,UniqueId")
        if status == 404 or (status == 200 and result.get("d", {}).get("Exists") is False):
            return False
        if status != 200 or result.get("d", {}).get("Exists") is not True:
            raise ValidationError("O SharePoint não confirmou acesso à pasta de destino.")
        self._folders.add(path)
        return True

    def check_folder(self):
        if not self._folder_exists(self._destination):
            raise MissingDestination("Não foi possível encontrar a pasta deste envio.")

    def list_subfolders(self) -> list[str]:
        """List immediate child folders through the authenticated SharePoint session."""
        resource = self._folder_endpoint(self._destination) + "/Folders"
        endpoint = resource + "?$select=Name&$top=50"
        expected_path = unquote(self._base + "/_api" + resource).casefold()
        names = []
        for _ in range(20):
            status, result = self._request("GET", endpoint)
            data = result.get("d", {})
            rows = data.get("results")
            if status != 200 or not isinstance(rows, list):
                raise ValidationError("O SharePoint não confirmou a lista de empresas do grupo.")
            for row in rows:
                name = row.get("Name") if isinstance(row, dict) else None
                if not isinstance(name, str):
                    raise ValidationError("O SharePoint retornou uma subpasta sem nome no grupo.")
                names.append(name)
            next_page = data.get("__next")
            if not next_page:
                return names
            if not is_allowed_sharepoint_url(next_page):
                raise ValidationError("A próxima página do grupo tem um endereço inválido.")
            next_url = urlsplit(next_page)
            if (next_url.hostname != self._host or unquote(next_url.path).casefold() != expected_path
                    or not next_url.query or next_url.fragment):
                raise ValidationError("O SharePoint informou uma próxima página fora da pasta do grupo.")
            endpoint = next_url.path[len(self._base + "/_api"):] + "?" + next_url.query
        raise ValidationError("O grupo retornou muitas páginas. A lista não foi importada parcialmente.")

    def prepare_destination(self, parts):
        suffix = "/" + "/".join(parts)
        if not parts or not self._destination.endswith(suffix) or len(self._destination) == len(suffix):
            raise ValidationError("O destino não pertence à pasta da empresa.")
        if self._folder_exists(self._destination):
            return
        root = self._destination[:-len(suffix)]
        if not self._folder_exists(root):
            raise ValidationError("A pasta raiz da empresa não está disponível.")
        self._authorize_write()
        self._ensure_subfolders(root, parts, known_missing=self._destination)

    def prepare(self, *, checked=False):
        if not checked:
            self.check_folder()
        self._folders.add(self._destination)
        self._authorize_write()

    def _authorize_write(self):
        status, result = self._request("POST", "/contextinfo")
        digest = result.get("d", {}).get("GetContextWebInformation", {}).get("FormDigestValue") if isinstance(result, dict) else None
        if status != 200 or not isinstance(digest, str) or not digest:
            raise ValidationError("O SharePoint não autorizou o envio nesta sessão.")
        self._digest = digest

    def ensure_folder(self, parts):
        return self._ensure_subfolders(self._destination, parts)

    def _ensure_subfolders(self, root, parts, *, known_missing=None):
        path = root
        for name in parts:
            path += "/" + name
            if path in self._folders:
                continue
            if path != known_missing and self._folder_exists(path):
                continue
            endpoint = f"/web/Folders/AddUsingPath(decodedurl={_literal(path)})"
            status, result = self._request("POST", endpoint, digest=self._digest, content_type="application/json;odata=verbose")
            if status in (200, 201) and result.get("d", {}).get("UniqueId"):
                self._folders.add(path)
            elif status not in (200, 201, 409, 500) or not self._folder_exists(path):
                raise ValidationError("O SharePoint não confirmou a criação da pasta. Confira a permissão para criar pastas.")
        return path

    def upload(self, path: Path, *, parts=None, progress=None, expected_size=None) -> DeliveryOutcome:
        if self._digest is None:
            raise RuntimeError("Delivery has not been prepared")
        parts = parts or (path.name,)
        try:
            source = path.open("rb")
        except OSError:
            return DeliveryOutcome("failed", "Não foi possível abrir o arquivo no computador. Confira se ele está disponível.")
        with source:
            try:
                size = os.fstat(source.fileno()).st_size
            except OSError:
                return DeliveryOutcome("failed", "Não foi possível ler o arquivo no computador.")
            if not 0 <= size <= MAX_FILE_SIZE:
                return DeliveryOutcome("failed", "O arquivo ultrapassa o limite de 100 MB por arquivo.")
            if expected_size is not None and size != expected_size:
                return DeliveryOutcome("failed", "O arquivo mudou depois da seleção. Selecione-o novamente.")
            try:
                parent = self.ensure_folder(parts[:-1])
            except NETWORK_ERRORS:
                return DeliveryOutcome("failed", "A conexão falhou antes do envio, enquanto o app conferia a pasta.")
            item = _literal(f"{parent}/{parts[-1]}")
            lookup = f"/web/GetFileByServerRelativePath(decodedurl={item})?$select=UniqueId"
            try:
                status, result = self._request("GET", lookup)
            except NETWORK_ERRORS:
                return DeliveryOutcome("failed", "A conexão falhou antes do envio, enquanto o app verificava o nome do arquivo.")
            if status == 200 and result.get("d", {}).get("UniqueId"):
                return DUPLICATE
            if status != 404:
                return DeliveryOutcome("failed", REJECTION_DETAILS.get(
                    status, "O SharePoint não permitiu verificar se o nome já estava em uso."))
            endpoint = self._folder_endpoint(parent) + f"/Files/AddUsingPath(decodedurl={_literal(parts[-1])},overwrite=false)"
            try:
                status, result = self._request("POST", endpoint, self._blocks(source, size, progress), size, self._digest)
            except NETWORK_ERRORS:
                return UNCONFIRMED
        if status in (200, 201) and result.get("d", {}).get("UniqueId"):
            return DeliveryOutcome("sent")
        if status == 409:
            # Another sender may have created the file after our first lookup.
            # Verify the name before reporting a duplicate.
            try:
                found, existing = self._request("GET", lookup)
                if found == 200 and existing.get("d", {}).get("UniqueId"):
                    return DUPLICATE
            except NETWORK_ERRORS:
                pass
        if status in REJECTION_DETAILS:
            return DeliveryOutcome("failed", REJECTION_DETAILS[status])
        return UNCONFIRMED

    def _blocks(self, source, size, progress):
        sent = 0
        while sent < size:
            if not self._current():
                raise InterruptedError()
            block = source.read(min(256 * 1024, size - sent))
            if not block:
                raise OSError("Selected file shrank while being sent")
            yield block
            sent += len(block)
            if progress:
                progress(sent, False)
        if progress:
            progress(sent, True)
