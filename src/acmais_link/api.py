from __future__ import annotations

import logging
import threading
import time
import webbrowser
from typing import Any
from urllib.parse import urlparse

from .config_store import ConfigStore
from .credential_store import CredentialStore, CredentialStoreError
from .models import Company, ValidationError, is_allowed_sharepoint_url
from .sharepoint import (
    extract_company_identity,
    navigation_cover_script,
    navigation_state_script,
    navigation_toolbar_script,
    password_submission_script,
)


class AppApi:
    def __init__(
        self,
        config: ConfigStore,
        credentials: CredentialStore,
        logger: logging.Logger,
        home_url: str,
        *,
        updates=None,
    ):
        # pywebview exposes public members of js_api. Keep every dependency and
        # native object private so the bridge never tries to serialize them.
        self._config = config
        self._credentials = credentials
        self._logger = logger
        self._home_url = home_url
        self._window: Any | None = None
        self._mode = "home"
        self._pending: dict[str, Any] | None = None
        self._current_company: Company | None = None
        self._notice: dict[str, Any] | None = None
        self._navigation_token = 0
        self._probe_scheduled = False
        self._probe_inflight: int | None = None
        self._probe_requested: int | None = None
        self._lock = threading.RLock()
        self._persistence_lock = threading.Lock()
        self._updates = updates

    def get_update_status(self) -> dict:
        # Read-only: the local UI cannot trigger installation or close a window.
        if self._updates is None:
            return {"ok": True, "status": "disabled"}
        snapshot = self._updates.status()
        return {"ok": True, "status": snapshot["state"], "version": snapshot.get("version")}

    def _bind_window(self, window: Any) -> None:
        self._window = window

    def consume_notice(self) -> dict:
        with self._lock:
            notice = self._notice
            self._notice = None
        return {"ok": True, "notice": notice}

    def list_companies(self) -> dict:
        try:
            return {
                "ok": True,
                "companies": [
                    # A configuration is only persisted after the credential is saved.
                    # Avoid touching Windows Credential Manager while rendering the home
                    # screen: a slow keyring provider must not freeze app initialization.
                    {**company.to_dict(), "hasCredential": True}
                    for company in self._config.list()
                ],
            }
        except Exception as exc:
            self._logger.exception("Falha ao listar empresas")
            return self._error(exc)

    def begin_company_setup(self, payload: dict) -> dict:
        try:
            with self._lock:
                request_token = self._navigation_token
            url = str(payload.get("url") or "").strip()
            if not is_allowed_sharepoint_url(url):
                raise ValidationError("Use uma URL HTTPS válida do SharePoint.")
            original_code = str(payload.get("originalCode") or "").strip()
            password = str(payload.get("password") or "")
            if original_code and not password:
                password = self._credentials.get(original_code) or ""
            if not password:
                raise ValidationError("Informe a senha no primeiro cadastro.")

            self._queue_navigation({
                "kind": "setup",
                "url": url,
                "password": password,
                "original_code": original_code,
                "attempts": 0,
            }, expected_token=request_token)
            return {"ok": True}
        except Exception as exc:
            self._logger.warning("Falha ao iniciar cadastro: %s", type(exc).__name__)
            return self._error(exc)

    def delete_company(self, code: str) -> dict:
        try:
            with self._persistence_lock:
                original = self._config.get(code)
                removed = self._config.delete(code)
                try:
                    self._credentials.delete(code)
                except Exception:
                    if original is not None:
                        self._config.upsert(original)
                    raise
            self._logger.info("Empresa removida: code=%s", code)
            return {"ok": True, "removed": removed}
        except Exception as exc:
            self._logger.exception("Falha ao remover empresa: code=%s", code)
            return self._error(exc)

    def open_company(self, code: str) -> dict:
        try:
            with self._lock:
                request_token = self._navigation_token
            company = self._config.get(code)
            if company is None:
                raise ValidationError("Empresa não encontrada.")
            password = self._credentials.get(company.code)
            if not password:
                raise CredentialStoreError("A empresa não possui uma senha salva.")

            self._queue_navigation({
                "kind": "open",
                "url": company.url,
                "password": password,
                "company": company,
                "attempts": 0,
            }, expected_token=request_token)
            return {"ok": True}
        except Exception as exc:
            self._logger.warning("Falha ao abrir empresa: code=%s error=%s", code, type(exc).__name__)
            return self._error(exc)

    def open_external(self, code: str) -> dict:
        try:
            company = self._config.get(code)
            if company is None:
                raise ValidationError("Empresa não encontrada.")
            webbrowser.open(company.url, new=2)
            self._logger.info("Navegador externo aberto: code=%s", company.code)
            return {"ok": True}
        except Exception as exc:
            return self._error(exc)

    def open_current_external(self) -> dict:
        if self._current_company is None:
            return {"ok": False, "error": "Nenhuma empresa está aberta."}
        return self.open_external(self._current_company.code)

    def return_home(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "A janela principal não está disponível."}
        with self._lock:
            self._navigation_token += 1
            self._mode = "home"
            self._pending = None
            self._current_company = None
            self._probe_scheduled = False
            token = self._navigation_token
        # Cancellation must not wait for JavaScript in a stalled remote page.
        # Navigate natively to the local document before doing any decoration.
        if not self._is_current(token, "home"):
            return {"ok": True}
        self._window.load_url(self._home_url)
        if self._is_current(token, "home"):
            self._window.show()
        return {"ok": True}

    def _is_current(self, token: int, mode: str | None = None) -> bool:
        with self._lock:
            return token == self._navigation_token and (mode is None or self._mode == mode)

    def _on_loaded(self, window: Any) -> None:
        with self._lock:
            mode = self._mode
            token = self._navigation_token
        if mode == "home":
            if not self._is_current(token, "home"):
                return
            window.set_title("ACMAIS LINK")
            window.show()
            return

        if mode == "active":
            self._decorate_active_page(window, token)
            return

        if mode != "navigating":
            return

        self._inspect_navigation(window, token)

    def _inspect_navigation(self, window: Any, token: int) -> None:
        with self._lock:
            if token != self._navigation_token or self._mode != "navigating":
                return
            if self._probe_inflight == token:
                self._probe_requested = token
                return
            self._probe_inflight = token
            pending = self._pending
            self._probe_scheduled = False
        try:
            if pending:
                self._inspect_current_navigation(window, token, pending)
        finally:
            reschedule = False
            with self._lock:
                if self._probe_inflight == token:
                    self._probe_inflight = None
                if self._probe_requested == token:
                    self._probe_requested = None
                    if token == self._navigation_token and self._mode == "navigating":
                        # A timer may have fired while native JS was still busy.
                        # Its request must survive, without starting a parallel probe.
                        self._probe_scheduled = False
                        reschedule = True
            if reschedule:
                self._retry_navigation(token)

    def _inspect_current_navigation(self, window: Any, token: int, pending: dict) -> None:

        try:
            state = window.evaluate_js(navigation_state_script())
        except Exception:
            self._retry_navigation(token)
            return
        if not self._is_current(token, "navigating"):
            return
        if not isinstance(state, dict):
            self._retry_navigation(token)
            return
        current_url = str(state.get("url") or "")
        if not current_url or current_url.startswith(("about:", "data:", "file:")):
            self._retry_navigation(token)
            return
        if (not is_allowed_sharepoint_url(current_url)
                or urlparse(current_url).hostname != urlparse(pending["url"]).hostname):
            self._fail_navigation("O SharePoint redirecionou para um endereço não permitido.", token)
            return

        try:
            window.evaluate_js(navigation_cover_script(navigation_token=token))
        except Exception:
            self._retry_navigation(token)
            return

        if not self._is_current(token, "navigating"):
            return
        if state.get("hasPassword"):
            submitted_at = pending.get("submitted_at")
            if submitted_at is not None:
                if time.monotonic() - submitted_at >= 12:
                    self._fail_navigation("A senha foi recusada pelo SharePoint. Atualize o acesso e tente novamente.", token)
                else:
                    self._retry_navigation(token)
                return
            password = pending.get("password") or ""
            if not password and pending.get("company"):
                password = self._credentials.get(pending["company"].code) or ""
            if not self._is_current(token, "navigating"):
                return
            try:
                origin = "https://" + urlparse(pending["url"]).hostname
                submitted = bool(window.evaluate_js(password_submission_script(
                    password, origin, navigation_token=token,
                )))
            except Exception:
                self._retry_navigation(token)
                return
            finally:
                password = None
            if not self._is_current(token, "navigating"):
                return
            if not submitted:
                self._retry_navigation(token)
                return
            pending["attempts"] += 1
            pending["submitted_at"] = time.monotonic()
            pending["ready_checks"] = 0
            self._logger.info("Credencial enviada à página protegida")
            self._retry_navigation(token)
            return

        try:
            if pending["kind"] == "setup":
                heading = str(state.get("heading") or "")
                identity = extract_company_identity(current_url, heading)
                if identity is None:
                    self._retry_navigation(token)
                    return
                code, name = identity
                company = Company.from_payload({"code": code, "name": name, "url": pending["url"]})
                if not self._persist_company(company, pending, token):
                    return
            else:
                company = pending["company"]
                heading = str(state.get("heading") or "")
                if extract_company_identity(current_url, heading) is None:
                    self._retry_navigation(token)
                    return

                # Shared-link pages render their password component asynchronously.
                # Wait through several clean probes before considering the folder ready.
                pending["ready_checks"] = pending.get("ready_checks", 0) + 1
                if pending["ready_checks"] < 5:
                    self._retry_navigation(token)
                    return

                if self._activate_company(company, token) is None:
                    return
            with self._lock:
                if self._mode != "active" or self._current_company is not company:
                    return
                active_token = self._navigation_token
            shown = self._show_company(window, company, active_token)
            if shown and pending["kind"] == "setup":
                self._cleanup_previous_credential(company, pending)
        except Exception as exc:
            if self._is_current(token, "navigating"):
                self._logger.exception("Falha ao concluir navegação")
                self._fail_navigation(self._error(exc)["error"], token)

    def _activate_company(self, company: Company, token: int) -> int | None:
        with self._lock:
            if token != self._navigation_token or self._mode != "navigating":
                return None
            self._navigation_token += 1
            self._mode = "active"
            self._current_company = company
            self._pending = None
            self._probe_scheduled = False
            return self._navigation_token

    def _persist_company(self, company: Company, pending: dict, token: int) -> bool:
        # Native credential and disk I/O must not prevent cancellation/watchdogs.
        # Serialize persistence separately, then commit the state atomically.
        with self._persistence_lock:
            if not self._is_current(token, "navigating"):
                return False
            original_code = pending.get("original_code") or ""
            target = self._config.get(company.code)
            if target is not None and target.code.casefold() != original_code.casefold():
                raise ValidationError("Já existe uma empresa com o código extraído deste link.")
            original_code = original_code or company.code
            original = self._config.get(original_code)
            previous_password = self._credentials.get(company.code)
            if not self._is_current(token, "navigating"):
                return False
            wrote_config = False
            committed = False
            try:
                self._credentials.set(company.code, pending["password"])
                if not self._is_current(token, "navigating"):
                    return False
                self._config.upsert(company, original_code=original_code)
                wrote_config = True
                with self._lock:
                    if self._activate_company(company, token) is None:
                        return False
                    self._notice = {"message": f"Empresa {company.code} - {company.name} configurada.", "error": False}
                    committed = True
            finally:
                if not committed:
                    try:
                        if wrote_config:
                            if original is not None:
                                self._config.upsert(original, original_code=company.code)
                            else:
                                self._config.delete(company.code)
                    finally:
                        if previous_password is not None:
                            self._credentials.set(company.code, previous_password)
                        else:
                            self._credentials.delete(company.code)
            self._logger.info("Empresa extraída e salva: code=%s", company.code)
            return True

    def _cleanup_previous_credential(self, company: Company, pending: dict) -> None:
        # Non-critical cleanup runs only after the folder and its controls appear.
        original_code = pending.get("original_code") or ""
        if not original_code or original_code.casefold() == company.code.casefold():
            return
        try:
            with self._persistence_lock:
                if self._config.get(original_code) is None:
                    self._credentials.delete(original_code)
        except Exception:
            self._logger.warning("Cadastro salvo; limpeza da credencial antiga pendente")

    def _queue_navigation(self, pending: dict[str, Any], *, expected_token: int | None = None,
                          expected_mode: str | None = None) -> None:
        if self._window is None:
            raise RuntimeError("A janela principal não está disponível.")
        with self._lock:
            if expected_token is not None and (
                    expected_token != self._navigation_token
                    or (expected_mode is not None and self._mode != expected_mode)):
                return
            if self._mode == "navigating":
                raise ValidationError("Aguarde a abertura atual ou volte para as empresas.")
            self._navigation_token += 1
            self._mode = "navigating"
            pending["deadline"] = time.monotonic() + 35
            pending["submitted_at"] = None
            pending["ready_checks"] = 0
            self._pending = pending
            self._current_company = None
            self._probe_scheduled = False
            token = self._navigation_token
        watchdog = threading.Timer(36, self._navigation_timeout, args=(token,))
        watchdog.daemon = True
        watchdog.start()
        if not self._is_current(token, "navigating"):
            return
        self._window.set_title("ACMAIS LINK - Abrindo documentos...")
        if not self._is_current(token, "navigating"):
            return
        self._window.show()
        if not self._is_current(token, "navigating"):
            return
        self._window.load_url(pending["url"])

    def _navigation_timeout(self, token: int) -> None:
        with self._lock:
            if token != self._navigation_token or self._mode != "navigating":
                return
        self._fail_navigation("O SharePoint demorou demais para responder. Verifique sua conexão e tente novamente.", token)

    def _retry_navigation(self, token: int) -> None:
        with self._lock:
            if token != self._navigation_token or self._mode != "navigating":
                return
            pending = self._pending
            if not pending:
                return
            if time.monotonic() >= pending["deadline"]:
                message = (
                    "Não foi possível identificar a pasta. Confirme se o nome segue código - nome da empresa."
                    if pending["kind"] == "setup"
                    else "O SharePoint demorou demais para abrir. Tente novamente."
                )
            else:
                message = None
            if message is None and self._probe_scheduled:
                return
            if message is None:
                self._probe_scheduled = True

        if message is not None:
            self._fail_navigation(message, token)
            return

        timer = threading.Timer(0.45, self._inspect_navigation, args=(self._window, token))
        timer.daemon = True
        timer.start()

    def _decorate_active_page(self, window: Any, token: int) -> None:
        with self._lock:
            if token != self._navigation_token or self._mode != "active":
                return
            company = self._current_company
        if company is None:
            return
        try:
            state = window.evaluate_js(navigation_state_script())
            if not self._is_current(token, "active") or not isinstance(state, dict):
                return
            current_url = str(state.get("url") or "")
            if (not is_allowed_sharepoint_url(current_url)
                    or urlparse(current_url).hostname != urlparse(company.url).hostname):
                self._fail_navigation("A navegação saiu do domínio SharePoint da empresa.", token)
                return
            if state.get("hasPassword"):
                password = self._credentials.get(company.code) or ""
                self._queue_navigation({
                    "kind": "open",
                    "url": current_url,
                    "password": password,
                    "company": company,
                    "attempts": 0,
                }, expected_token=token, expected_mode="active")
                return
            self._show_company(window, company, token)
        except Exception:
            if self._is_current(token, "active"):
                self._logger.exception("Falha ao restaurar os controles de navegação")

    def _show_company(self, window: Any, company: Company, token: int) -> bool:
        if not self._is_current(token, "active"):
            return False
        try:
            shown = window.evaluate_js(navigation_toolbar_script(
                f"{company.code} - {company.name}", navigation_token=token,
            ))
            if not self._is_current(token, "active"):
                return False
            if shown is not True:
                raise RuntimeError("Navigation toolbar was not installed")
            window.set_title(f"ACMAIS LINK - {company.code} - {company.name}")
            if self._is_current(token, "active"):
                window.show()
                return True
        except Exception:
            self._fail_navigation("Não foi possível concluir a exibição da pasta. Tente abrir novamente.", token)
        return False

    def _fail_navigation(self, message: str, token: int) -> None:
        with self._lock:
            if token != self._navigation_token:
                return
            self._navigation_token += 1
            home_token = self._navigation_token
            self._mode = "home"
            self._pending = None
            self._current_company = None
            self._probe_scheduled = False
            self._notice = {"message": message, "error": True}
        self._logger.warning("Navegação interrompida: %s", message)
        if self._window and self._is_current(home_token, "home"):
            self._window.load_url(self._home_url)
            if self._is_current(home_token, "home"):
                self._window.show()

    @staticmethod
    def _error(exc: Exception) -> dict:
        if isinstance(exc, (ValidationError, CredentialStoreError, ValueError)):
            message = str(exc)
        else:
            message = "Ocorreu um erro inesperado. Consulte o log técnico."
        return {"ok": False, "error": message}
