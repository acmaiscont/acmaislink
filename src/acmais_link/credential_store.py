from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError


SERVICE_NAME = "ACMAIS LINK"


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore:
    def has(self, code: str) -> bool:
        return self.get(code) is not None

    def get(self, code: str) -> str | None:
        try:
            return keyring.get_password(SERVICE_NAME, code)
        except KeyringError as exc:
            raise CredentialStoreError("Não foi possível acessar o cofre de credenciais.") from exc

    def set(self, code: str, password: str) -> None:
        if not password:
            raise CredentialStoreError("Informe a senha da empresa.")
        try:
            keyring.set_password(SERVICE_NAME, code, password)
        except KeyringError as exc:
            raise CredentialStoreError("Não foi possível salvar a senha no cofre do sistema.") from exc

    def delete(self, code: str) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, code)
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise CredentialStoreError("Não foi possível excluir a senha do cofre do sistema.") from exc

    def move(self, old_code: str, new_code: str) -> None:
        if old_code == new_code:
            return
        password = self.get(old_code)
        if password is None:
            return
        self.set(new_code, password)
        self.delete(old_code)

