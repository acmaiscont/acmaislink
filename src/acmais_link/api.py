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
            if not password and not original_code:
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
            self._queue_navigation({
                "kind": "open",
                "code": code,
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
        self._load_navigation(self._home_url, token, 'home')
        if self._is_current(token, "home"):
            self._window.show()
        return {"ok": True}

    def _is_current(self, token: int, mode: str | None = None) -> bool:
        with self._lock:
            return token == self._navigation_token and (mode is None or self._mode == mode)

    def _evaluate_navigation(self, window: Any, script: str, token: int, mode: str):
        evaluate = getattr(window, 'evaluate_navigation_js', None)
        if callable(evaluate):
            return evaluate(script, lambda: self._is_current(token, mode))
        return window.evaluate_js(script)

    def _load_navigation(self, url: str, token: int, mode: str):
        navigate = getattr(self._window, 'navigate', None)
        if callable(navigate):
            return navigate(url, lambda: self._is_current(token, mode))
        if self._is_current(token, mode):
            self._window.load_url(url)

    def _on_loaded(self, window: Any) -> None:
        # Remote DOM reads use the native adapter, not pywebview's late bridge.
        window = self._window or window
        with self._lock:
            mode = self._mode
            token = self._navigation_token
        if mode == "home":
            if not self._is_current(token, "home"):
                return
            show_home = getattr(window, 'show_home', None)
            if callable(show_home):
                current = window.get_current_url() or ''
                if current == self._home_url or urlparse(current).hostname in ('localhost', '127.0.0.1'):
                    show_home(lambda: self._is_current(token, 'home'))
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
            state = self._evaluate_navigation(window, navigation_state_script(), token, 'navigating')
        except Exception as exc:
            pending['ready_checks'] = 0
            self._navigation_phase(pending, 'document-unavailable', error=type(exc).__name__)
            self._retry_navigation(token)
            return
        if not self._is_current(token, "navigating"):
            return
        if not isinstance(state, dict):
            pending['ready_checks'] = 0
            self._navigation_phase(pending, 'document-unavailable')
            self._retry_navigation(token)
            return
        current_url = str(state.get("url") or "")
        # A company switch can receive a late snapshot from the old folder
        # while WebView2 is replacing its document. Never save that identity.
        if (not pending.get('remote_seen') and current_url == pending.get('previous_url')
                and current_url != pending['url']):
            self._retry_navigation(token)
            return
        if (not current_url or current_url.startswith(("about:", "data:", "file:"))
                or (urlparse(current_url).hostname in ('127.0.0.1', 'localhost')
                    and not pending.get('remote_seen'))):
            self._retry_navigation(token)
            return
        if (not is_allowed_sharepoint_url(current_url)
                or urlparse(current_url).hostname != urlparse(pending["url"]).hostname):
            self._fail_navigation("O SharePoint redirecionou para um endereço não permitido.", token)
            return
        pending['remote_seen'] = True
        if state.get('ready') is False:
            pending['ready_checks'] = 0
            self._navigation_phase(pending, 'document-loading')
            self._retry_navigation(token)
            return

        # On Windows the cover belongs to the window and was shown BEFORE the
        # navigation. Never put a late overlay over an already visible folder.
        if not callable(getattr(window, 'show_loading', None)):
            try:
                window.evaluate_js(navigation_cover_script(navigation_token=token))
            except Exception:
                self._retry_navigation(token)
                return

        if not self._is_current(token, "navigating"):
            return
        if state.get("hasPassword"):
            pending['ready_checks'] = 0
            pending['mismatch_checks'] = 0
            self._navigation_phase(pending, 'password')
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
                submitted = bool(self._evaluate_navigation(window, password_submission_script(
                    password, origin, navigation_token=token, expected_url=current_url,
                    include_cover=not callable(getattr(window, 'show_loading', None)),
                ), token, 'navigating'))
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
                    self._navigation_phase(pending, 'identity-missing')
                    self._retry_navigation(token)
                    return
                self._navigation_phase(pending, 'saving')
                code, name = identity
                company = Company.from_payload({"code": code, "name": name, "url": pending["url"]})
                if not self._persist_company(company, pending, token):
                    return
            else:
                company = pending["company"]
                heading = str(state.get("heading") or "")
                # Match the selected company, including its ancestor when the
                # session resumes in a numbered subfolder (e.g. 01 - Janeiro).
                # Never label another company's documents as this one.
                if extract_company_identity(current_url, heading, expected_code=company.code) is None:
                    pending['ready_checks'] = 0
                    if extract_company_identity(current_url, heading) is not None:
                        pending['mismatch_checks'] = pending.get('mismatch_checks', 0) + 1
                        self._navigation_phase(pending, 'identity-mismatch')
                        if pending['mismatch_checks'] >= 5:
                            self._fail_navigation('A pasta aberta não corresponde à empresa selecionada. Edite o acesso e confira o link.', token)
                            return
                    else:
                        pending['mismatch_checks'] = 0
                        self._navigation_phase(pending, 'identity-missing')
                    self._retry_navigation(token)
                    return
                pending['mismatch_checks'] = 0

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
                          expected_mode: str | None = None, navigate: bool = True) -> None:
        if self._window is None:
            raise RuntimeError("A janela principal não está disponível.")
        with self._lock:
            if expected_token is not None and (
                    expected_token != self._navigation_token
                    or (expected_mode is not None and self._mode != expected_mode)):
                return
            if self._mode in ("preparing", "navigating"):
                raise ValidationError("Aguarde a abertura atual ou volte para as empresas.")
            self._navigation_token += 1
            # Loaded events and probes must not run until the loading screen
            # is painted and all pre-navigation preparation has finished.
            self._mode = "preparing"
            pending["deadline"] = time.monotonic() + 60
            pending["submitted_at"] = None
            pending["ready_checks"] = 0
            self._pending = pending
            self._current_company = None
            self._probe_scheduled = False
            token = self._navigation_token
        watchdog = threading.Timer(61, self._navigation_timeout, args=(token,))
        watchdog.daemon = True
        watchdog.start()
        if not self._is_current(token, "preparing"):
            return
        try:
            self._window.set_title("ACMAIS LINK - Abrindo documentos...")
            if not self._is_current(token, "preparing"):
                return
            self._window.show()
            if not self._is_current(token, "preparing"):
                return
            show_loading = getattr(self._window, 'show_loading', None)
            if callable(show_loading):
                shown = show_loading(lambda: self._is_current(token, 'preparing'))
            else:
                shown = self._evaluate_navigation(self._window, navigation_cover_script(
                    navigation_token=token), token, 'preparing')
            if not self._is_current(token, 'preparing'):
                return
            if shown is not True:
                raise RuntimeError('Loading screen was not presented')
            self._navigation_phase(pending, 'preparing')
            if not self._prepare_navigation(pending, token):
                return
            if navigate:
                pending['previous_url'] = self._window.get_current_url() or ''
                self._load_navigation(pending['url'], token, 'preparing')
            with self._lock:
                if not self._is_current(token, 'preparing'):
                    return
                self._mode = 'navigating'
            self._navigation_phase(pending, 'connecting')
            # Poll from the start, including redirects that never fire loaded.
            self._retry_navigation(token)
        except Exception as exc:
            message = self._error(exc)['error'] if isinstance(exc, (ValidationError, CredentialStoreError)) else (
                'Não foi possível iniciar a abertura da pasta. Tente novamente.')
            self._fail_navigation(message, token)
            raise

    def _prepare_navigation(self, pending: dict, token: int) -> bool:
        # Credential Manager/disk may be slow. They run only after the cover
        # acknowledges its paint, without holding the cancellation/state lock.
        if pending['kind'] == 'open':
            company = pending.get('company') or self._config.get(pending['code'])
            if not self._is_current(token, 'preparing'):
                return False
            if company is None:
                raise ValidationError('Empresa não encontrada.')
            pending['company'] = company
            pending.setdefault('url', company.url)
            pending['password'] = self._credentials.get(company.code) or ''
            missing = CredentialStoreError('A empresa não possui uma senha salva.')
        else:
            if not pending.get('password'):
                pending['password'] = self._credentials.get(pending['original_code']) or ''
            missing = ValidationError('Informe a senha no primeiro cadastro.')
        if not self._is_current(token, 'preparing'):
            return False
        if not pending['password']:
            raise missing
        return True

    def _navigation_phase(self, pending: dict, phase: str, *, error: str = '') -> None:
        if pending.get('phase') != phase:
            pending['phase'] = phase
            # No sharing URLs, page contents or passwords in diagnostics.
            self._logger.info('Navegação: kind=%s phase=%s error=%s', pending['kind'], phase, error)

    @staticmethod
    def _timeout_message(pending: dict) -> str:
        if pending.get('phase') == 'identity-missing' and pending['kind'] == 'setup':
            return 'Não foi possível identificar a pasta. Confirme se o nome segue código - nome da empresa.'
        return 'O SharePoint demorou demais para responder. Verifique sua conexão e tente novamente.'

    def _navigation_timeout(self, token: int) -> None:
        with self._lock:
            if token != self._navigation_token or self._mode not in ("preparing", "navigating"):
                return
            message = self._timeout_message(self._pending or {})
        self._fail_navigation(message, token)

    def _retry_navigation(self, token: int) -> None:
        with self._lock:
            if token != self._navigation_token or self._mode != "navigating":
                return
            pending = self._pending
            if not pending:
                return
            if time.monotonic() >= pending["deadline"]:
                message = self._timeout_message(pending)
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
            state = self._evaluate_navigation(window, navigation_state_script(), token, 'active')
            if not self._is_current(token, "active") or not isinstance(state, dict):
                return
            current_url = str(state.get("url") or "")
            if (not is_allowed_sharepoint_url(current_url)
                    or urlparse(current_url).hostname != urlparse(company.url).hostname):
                self._fail_navigation("A navegação saiu do domínio SharePoint da empresa.", token)
                return
            if state.get("hasPassword"):
                self._queue_navigation({
                    "kind": "open",
                    "url": current_url,
                    "company": company,
                    "attempts": 0,
                }, expected_token=token, expected_mode="active", navigate=False)
                return
            self._show_company(window, company, token)
        except Exception:
            if self._is_current(token, "active"):
                self._logger.exception("Falha ao restaurar os controles de navegação")

    def _show_company(self, window: Any, company: Company, token: int) -> bool:
        if not self._is_current(token, "active"):
            return False
        try:
            show_folder = getattr(window, 'show_folder', None)
            if callable(show_folder):
                set_choices = getattr(window, 'set_company_choices', None)
                if callable(set_choices):
                    choices = [{'code': item.code, 'name': item.name} for item in self._config.list()]
                    set_choices(choices, company.code, lambda: self._is_current(token, 'active'))
                shown = show_folder(f'{company.code} - {company.name}', lambda: self._is_current(token, 'active'))
            else:
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
            self._load_navigation(self._home_url, home_token, 'home')
            if self._is_current(home_token, "home"):
                self._window.show()

    @staticmethod
    def _error(exc: Exception) -> dict:
        if isinstance(exc, (ValidationError, CredentialStoreError, ValueError)):
            message = str(exc)
        else:
            message = "Ocorreu um erro inesperado. Consulte o log técnico."
        return {"ok": False, "error": message}
