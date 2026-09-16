from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse


class ValidationError(ValueError):
    """Raised when a company configuration is unsafe or incomplete."""


def is_allowed_sharepoint_url(url: str) -> bool:
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url) or "\\" in url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and hostname.endswith(".sharepoint.com")
        and not parsed.username
        and not parsed.password
    )


@dataclass(frozen=True, slots=True)
class Company:
    code: str
    name: str
    url: str

    @classmethod
    def from_payload(cls, payload: dict) -> "Company":
        code = str(payload.get("code", "")).strip()
        name = str(payload.get("name", "")).strip()
        url = str(payload.get("url", "")).strip()

        if not code:
            raise ValidationError("Informe o código da empresa.")
        if len(code) > 40:
            raise ValidationError("O código deve ter no máximo 40 caracteres.")
        if not name:
            raise ValidationError("Informe o nome da empresa.")
        if len(name) > 120:
            raise ValidationError("O nome deve ter no máximo 120 caracteres.")

        if not is_allowed_sharepoint_url(url):
            raise ValidationError("Use uma URL HTTPS válida do SharePoint.")

        return cls(code=code, name=name, url=url)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
