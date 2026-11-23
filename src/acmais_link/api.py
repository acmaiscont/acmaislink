from __future__ import annotations

import http.client
import logging
import sqlite3
import threading
import time
import webbrowser
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import APP_DISPLAY_TITLE
from .config_store import ConfigStore
from .credential_store import CredentialStore, CredentialStoreError
from .delivery import (
    CATALOG, DeliveryItem, DeliveryOutcome, DeliveryRoute, delivery_selection,
    group_identity, library_destination, library_folder_path, library_folder_url,
    previous_period, suggest_delivery,
)
from .delivery_transport import SharePointDelivery, UNCONFIRMED
from .models import Company, ValidationError, is_allowed_sharepoint_url
from .web_home import is_home_document
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
        history=None,
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
        self._history = history
        self._selected_files: tuple[DeliveryItem, ...] = ()
        self._delivery_lock = threading.Lock()
        self._selection_lock = threading.Lock()

    def delivery_options(self) -> dict:
        today = date.today()
        return {"ok": True, "catalog": CATALOG, "currentPeriod": today.isoformat()[:7],
                "previousPeriod": previous_period(today)}

    def _restart_activity(self):
        with self._lock:
            if self._mode == "delivering" or self._delivery_lock.locked():
                return "Há um envio de documentos em andamento."
            if self._persistence_lock.locked():
                return "Há uma alteração de cadastro em andamento."
            if self._mode in ("preparing", "navigating"):
                return "Há uma operação com o SharePoint em andamento."
            if self._selection_lock.locked():
                return "Há uma seleção de arquivos ou pastas em andamento."
        return ""

    def _stop_for_restart(self):
        with self._lock:
            self._navigation_token += 1
            self._mode = "closing"
            self._pending = None
        # Let in-flight credential transactions roll back and let the upload
        # worker record its final known status before disposing of WebView2.
        with self._persistence_lock, self._delivery_lock, self._selection_lock:
            pass

    def choose_delivery_files(self) -> dict:
        return self._choose_delivery_items(folder=False)

    def choose_delivery_folder(self) -> dict:
        return self._choose_delivery_items(folder=True)

    def _choose_delivery_items(self, *, folder: bool) -> dict:
        with self._lock:
            if self._mode != "home":
                return {"ok": False, "error": "Volte à lista antes de selecionar arquivos."}
            token = self._navigation_token
        choose = getattr(self._window, "choose_delivery_folder" if folder else "choose_delivery_files", None)
        if not callable(choose):
            return {"ok": False, "error": "O envio guiado está disponível no Windows com WebView2."}
        try:
            with self._selection_lock:
                if not self._is_current(token, "home"):
                    return {"ok": True, "cancelled": True}
                chosen = choose()
        except Exception as exc:
            self._logger.warning("Falha no seletor de envio (%s)", type(exc).__name__)
            return {"ok": False, "error": "Não foi possível abrir o seletor de pastas." if folder
                    else "Não foi possível abrir o seletor de arquivos."}
        try:
            if not chosen:
                return {"ok": True, "cancelled": True}
            if isinstance(chosen, str):
                chosen = (chosen,)
            files = delivery_selection(chosen, folder=folder)
            suggestion = suggest_delivery(files)
            with self._lock:
                if not self._is_current(token, "home"):
                    return {"ok": True, "cancelled": True}
                self._selected_files = files
            return {"ok": True, "files": [item.label for item in files], "suggestion": suggestion}
        except (OSError, ValidationError) as exc:
            message = str(exc) if isinstance(exc, ValidationError) else "Não foi possível ler os arquivos selecionados."
            return {"ok": False, "error": message}

    def recent_deliveries(self) -> dict:
        try:
            return {"ok": True, "receipts": self._history.recent() if self._history else []}
        except (OSError, sqlite3.Error):
            return {"ok": False, "error": "O histórico está indisponível."}

    def begin_delivery(self, code: str, payload: dict) -> dict:
        try:
            route = DeliveryRoute.from_payload(payload)
            with self._lock:
                if self._mode != "home" or self._delivery_lock.locked():
                    raise ValidationError("Aguarde o envio em andamento.")
                token, files = self._navigation_token, self._selected_files
            if not self._history or not callable(getattr(self._window, "delivery_cookies", None)):
                raise ValidationError("O envio guiado requer Windows com WebView2.")
            if not files:
                raise ValidationError("Selecione os arquivos para enviar.")
            self._queue_navigation({"kind": "open", "code": code, "attempts": 0,
                                    "delivery": route, "files": files}, expected_token=token, expected_mode="home")
            return {"ok": True}
        except Exception as exc:
            return self._error(exc)

    def open_delivery_folder(self, receipt_id: int) -> dict:
        try:
            with self._lock:
                request_token = self._navigation_token
            record = self._history.route_for(receipt_id) if self._history and type(receipt_id) is int else None
            if record is None:
                raise ValidationError("Este registro não tem um destino disponível na estrutura atual.")
            code, route = record
            self._queue_navigation({"kind": "open", "code": code, "attempts": 0,
                                    "delivery": route, "open_only": True},
                                   expected_token=request_token, expected_mode="home")
            return {"ok": True}
        except Exception as exc:
            return self._error(exc)

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
                    key = original.credential_key if original else code
                    if not original or not original.group_code or not any(
                        item.group_code == original.group_code for item in self._config.list()
                    ):
                        self._credentials.delete(key)
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
        return self._return_home()

    def _return_home(self, expected_token=None) -> dict:
        with self._lock:
            if self._mode == "closing" or (expected_token is not None and expected_token != self._navigation_token):
                return {"ok": True}
            self._navigation_token += 1
            self._mode = "home"
            self._pending = None
            self._selected_files = ()
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
                if is_home_document(current, self._home_url):
                    show_home(lambda: self._is_current(token, 'home'))
            window.set_title(APP_DISPLAY_TITLE)
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
                password = self._credentials.get(pending["company"].credential_key) or ""
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
                folder = library_folder_path(current_url)
                group_code = group_identity(folder)
                if group_code:
                    self._import_group(window, current_url, folder, group_code, pending, token)
                    return
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
                if company.group_code and not self._enter_group_company(company, current_url, pending, token):
                    return
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
                if pending["ready_checks"] < (2 if pending.get("delivery") is not None else 5):
                    self._retry_navigation(token)
                    return

                if pending.get("delivery") is not None:
                    self._continue_delivery(window, company, current_url, pending, token)
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

    def _import_group(self, window, current_url, folder, group_code, pending, token):
        self._navigation_phase(pending, "listing-group")
        current = lambda: self._is_current(token, "navigating")
        with SharePointDelivery(current_url, folder,
                                lambda url: window.delivery_cookies(url, current), current) as transport:
            names = transport.list_subfolders()
        members = []
        codes = set()
        skipped = 0
        for name in names:
            identity = (extract_company_identity("", name) if name not in ("", ".", "..")
                        and "/" not in name and "\\" not in name and all(ord(char) >= 32 for char in name) else None)
            if not identity or not identity[0].isascii() or not identity[0].isdecimal():
                skipped += 1
                continue
            code, company_name = identity
            if code in codes:
                raise ValidationError(f"O grupo tem duas pastas com o código {code}. Confira os nomes no SharePoint.")
            codes.add(code)
            members.append(Company.from_payload({
                "code": code, "name": company_name, "url": pending["url"], "group_code": group_code,
                "folder_url": library_folder_url(current_url, folder + "/" + name),
            }))
        if not members:
            raise ValidationError("O grupo não tem subpastas no padrão código - nome da empresa.")
        with self._persistence_lock:
            if not current():
                return
            for company in self._config.list():
                if company.group_code != group_code:
                    continue
                previous = library_folder_path(company.folder_url)
                same_tenant = urlparse(company.folder_url).hostname == urlparse(current_url).hostname
                if not previous or previous.rsplit("/", 1)[0].casefold() != folder.casefold() or not same_tenant:
                    raise ValidationError("Já existe um grupo com esse código em outra pasta.")
            key = members[0].credential_key
            previous_password = self._credentials.get(key)
            self._credentials.set(key, pending["password"])
            committed = False
            try:
                with self._lock:
                    if not current():
                        return
                    imported, conflicts = self._config.replace_group(group_code, members)
                    committed = True
                    message = f"Grupo {group_code} cadastrado. Empresas disponíveis: {imported}."
                    if conflicts:
                        message += f" Cadastros de outro acesso preservados: {conflicts}."
                    if skipped:
                        message += f" Subpastas sem o padrão de empresa: {skipped}."
                    self._notice = {"message": message, "error": False}
            finally:
                if not committed:
                    if previous_password is None:
                        self._credentials.delete(key)
                    else:
                        self._credentials.set(key, previous_password)
        self._return_home(expected_token=token)

    def _enter_group_company(self, company, current_url, pending, token):
        target, opened = library_folder_path(company.folder_url), library_folder_path(current_url)
        if target and opened:
            destination_url, current = urlparse(company.folder_url), urlparse(current_url)
            same_library = (destination_url.hostname == current.hostname
                            and destination_url.path.casefold() == current.path.casefold())
            if same_library:
                target_key, opened_key = target.casefold(), opened.casefold()
                # The authenticated group link must resolve to the stored group or the exact child.
                if opened_key == target_key or opened_key.startswith(target_key + "/"):
                    return True
                if opened_key == target_key.rsplit("/", 1)[0] and not pending.get("group_redirected"):
                    pending["group_redirected"] = True
                    pending["ready_checks"] = 0
                    self._load_navigation(company.folder_url, token, "navigating")
        self._retry_navigation(token)
        return False

    def _continue_delivery(self, window, company, current_url, pending, token):
        if "destination" not in pending:
            current = lambda: self._is_current(token, "navigating")
            route = pending["delivery"]
            canonical = library_destination(current_url, company.code, route, company_folder=company.folder_url)
            if canonical is None:
                raise ValidationError("Não foi possível localizar a raiz da empresa no SharePoint.")
            destination, destination_url = canonical
            with SharePointDelivery(current_url, destination,
                                    lambda url: window.delivery_cookies(url, current), current) as transport:
                if pending.get("open_only"):
                    transport.check_folder()
                else:
                    transport.prepare_destination(route.segments)
            pending["destination"] = destination
            pending["ready_checks"] = 0
            if destination_url != current_url:
                self._load_navigation(destination_url, token, "navigating")
                self._retry_navigation(token)
                return
        query = {key.casefold(): values for key, values in parse_qs(urlparse(current_url).query).items()}
        folders = query.get("id") or query.get("rootfolder") or []
        if folders != [pending["destination"]]:
            self._retry_navigation(token)
            return
        if pending.get("open_only"):
            active_token = self._activate_company(company, token)
            if active_token is not None:
                self._show_company(window, company, active_token)
            return
        with self._lock:
            if not self._is_current(token, "navigating"):
                return
            self._mode = "delivering"
        self._run_delivery(window, company, current_url, pending, token)

    def _run_delivery(self, window, company, current_url, pending, token):
        current = lambda: self._is_current(token, "delivering")
        with self._delivery_lock:
            if not current():
                return
            try:
                with SharePointDelivery(
                    current_url, pending["destination"],
                    lambda url: window.delivery_cookies(url, current), current,
                ) as transport:
                    transport.prepare(checked=True)
                    counts, issues = self._send_selection(window, company, pending, transport, current)
                with self._lock:
                    if not current():
                        return
                    self._notice = {
                        "message": (f"{counts['sent']} enviado(s), {counts['failed']} com falha "
                                    f"e {counts['uncertain']} a confirmar." if issues
                                    else f"Envio concluído. {counts['sent']} item(ns) enviado(s)."),
                        "error": bool(issues),
                        "deliveryIssues": issues,
                    }
                self._return_home(expected_token=token)
            except Exception as exc:
                self._logger.warning("Falha no envio guiado: %s", type(exc).__name__)
                message = str(exc) if isinstance(exc, ValidationError) else "Não foi possível concluir o envio. Confira o histórico."
                self._fail_navigation(message, token)

    def _send_selection(self, window, company, pending, transport, current):
        counts = {"sent": 0, "failed": 0, "uncertain": 0}
        issues = []
        files = pending["files"]
        progress = getattr(window, "delivery_progress", None)
        for index, item in enumerate(files, 1):
            if not current():
                break
            last_update, last_sent = -1.0, 0

            def report(sent, waiting):
                nonlocal last_update, last_sent
                now = time.monotonic()
                if callable(progress) and current() and (waiting or (sent and not last_sent) or now - last_update >= .25):
                    try:
                        progress(index, len(files), sent, item.size, waiting, item.directory, current)
                    except (TimeoutError, RuntimeError):
                        pass  # A progress update must not change the transfer outcome.
                    last_update, last_sent = now, sent

            report(0, False)
            receipt = self._history.start(
                company.code, f"{company.code} - {company.name}", pending["delivery"],
                item.label,
            )
            pending["started_files"] = True
            try:
                same_path = item.source.resolve(strict=True) == item.source
            except (OSError, RuntimeError):
                same_path = False
            if not same_path:
                outcome = DeliveryOutcome("failed", "O item foi movido, alterado ou não está disponível. Selecione-o novamente.")
            else:
                try:
                    if item.directory:
                        transport.ensure_folder(item.parts)
                        outcome = DeliveryOutcome("sent")
                    else:
                        outcome = transport.upload(item.source, parts=item.parts, progress=report, expected_size=item.size)
                except ValidationError as exc:
                    outcome = DeliveryOutcome("failed", str(exc))
                except (OSError, http.client.HTTPException):
                    outcome = (DeliveryOutcome("uncertain", "O SharePoint não confirmou a criação da subpasta. Confira o destino.")
                               if item.directory else UNCONFIRMED)
            self._history.finish(receipt, outcome.status, outcome.detail)
            counts[outcome.status] += 1
            if outcome.detail:
                issues.append({"filename": item.label, "status": outcome.status, "detail": outcome.detail})
        return counts, issues

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
            if self._mode in ("preparing", "navigating", "delivering", "closing"):
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
            self._window.set_title(f"{APP_DISPLAY_TITLE} - Abrindo documentos...")
            if not self._is_current(token, "preparing"):
                return
            self._window.show()
            if not self._is_current(token, "preparing"):
                return
            show_loading = getattr(self._window, 'show_loading', None)
            if callable(show_loading):
                guard = lambda: self._is_current(token, 'preparing')
                if "files" in pending:
                    shown = show_loading(guard, delivery=True)
                else:
                    shown = show_loading(guard)
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
            pending['password'] = self._credentials.get(company.credential_key) or ''
            missing = CredentialStoreError('A empresa não possui uma senha salva.')
        else:
            if not pending.get('password'):
                original = self._config.get(pending['original_code'])
                key = original.credential_key if original else pending['original_code']
                pending['password'] = self._credentials.get(key) or ''
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
            window.set_title(f"{APP_DISPLAY_TITLE} - {company.code} - {company.name}")
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
            pending = self._pending or {}
            self._navigation_token += 1
            home_token = self._navigation_token
            self._mode = "home"
            self._pending = None
            self._current_company = None
            self._probe_scheduled = False
            self._notice = {"message": message, "error": True}
            route = pending.get("delivery")
            if route and not pending.get("open_only") and not pending.get("started_files"):
                self._notice["deliveryDraft"] = {
                    "code": pending["code"], "period": route.period, "sector": route.sector,
                    "kind": route.kind, "files": [item.label for item in pending["files"]],
                }
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
