"""Only the local UI possesses the capability for privileged native commands."""
import hmac
import secrets


class SecureBridge:
    def __init__(self, api):
        self._api = api
        self._token = secrets.token_urlsafe(32)

    def command(self, token, name, args=None):
        if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
            return {"ok": False, "error": "Comando não autorizado."}
        allowed = {
            "list_companies", "consume_notice", "begin_company_setup", "delete_company",
            "open_company", "open_external", "get_update_status",
            "delivery_options", "choose_delivery_files", "choose_delivery_folder",
            "begin_delivery", "recent_deliveries", "open_delivery_folder",
        }
        if name not in allowed or not isinstance(args, list):
            return {"ok": False, "error": "Comando inválido."}
        return getattr(self._api, name)(*args)

    def return_home(self):
        return self._api.return_home()

    def open_current_external(self):
        return self._api.open_current_external()
