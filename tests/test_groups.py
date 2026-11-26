import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from acmais_link.api import AppApi
from acmais_link.config_store import ConfigStore
from acmais_link.delivery import DeliveryRoute, group_identity, library_destination, library_folder_path, library_folder_url
from acmais_link.delivery_transport import SharePointDelivery
from acmais_link.models import Company, ValidationError


LIBRARY = "https://tenant.sharepoint.com/sites/Remessas/Docs/Forms/AllItems.aspx"
GROUP = "/sites/Remessas/Docs/Grupo/90002 - Grupo Exemplo"
LINK = "https://tenant.sharepoint.com/sites/Remessas/fixture"


class GroupTests(unittest.TestCase):
    def test_group_requires_the_parent_folder_and_keeps_company_path_below_it(self):
        self.assertEqual(group_identity(library_folder_path(library_folder_url(LIBRARY, GROUP))), "90002")
        self.assertIsNone(group_identity(GROUP.replace("/Grupo/", "/Empresas/")))
        self.assertIsNone(group_identity(GROUP + "/0004 - Empresa"))
        company = GROUP + "/90002 - Empresa com o mesmo código"
        view = library_folder_url(LIBRARY, company)
        route = DeliveryRoute.from_payload({"period": "2026-11", "sector": "Contábil", "kind": "Extratos"})
        destination, target_url = library_destination(view, "90002", route, company_folder=view)
        self.assertEqual(destination, company + "/2026/11-2026/Contábil/Extratos")
        self.assertEqual(library_folder_path(target_url), destination)

    def test_import_saves_one_password_and_preserves_individual_access(self):
        with tempfile.TemporaryDirectory() as root:
            config = ConfigStore(Path(root) / "companies.json")
            individual = Company("002", "Empresa individual", LINK + "-individual")
            config.upsert(individual)
            credentials = Mock()
            credentials.get.return_value = None
            api = AppApi(config, credentials, logging.getLogger("group-test"), "file:///home")
            api._mode = "navigating"
            api._navigation_token = 1
            api._return_home = Mock()
            pending = {"url": LINK, "password": "fixture", "kind": "setup"}
            with patch("acmais_link.api.SharePointDelivery") as transport:
                transport.return_value.__enter__.return_value.list_subfolders.return_value = [
                    "0004 - Empresa B", "8 - Empresa A", "002 - Outra ficha", "Documentos gerais",
                ]
                api._import_group(Mock(), library_folder_url(LIBRARY, GROUP), GROUP, "90002", pending, 1)
            self.assertEqual(config.get("002"), individual)
            self.assertEqual({item.code for item in config.list()}, {"0004", "8", "002"})
            self.assertEqual(library_folder_path(config.get("0004").folder_url), GROUP + "/0004 - Empresa B")
            credentials.set.assert_called_once_with("grupo:90002", "fixture")
            self.assertIn("Cadastros de outro acesso preservados: 1", api.consume_notice()["notice"]["message"])
            self.assertTrue(api.delete_company("0004")["ok"])
            credentials.delete.assert_not_called()
            self.assertTrue(api.delete_company("8")["ok"])
            credentials.delete.assert_called_once_with("grupo:90002")

    def test_group_opening_requires_the_exact_member_path(self):
        api = AppApi(Mock(), Mock(), logging.getLogger("group-redirect"), "file:///home")
        api._load_navigation, api._retry_navigation = Mock(), Mock()
        path = GROUP + "/0004 - Empresa"
        company = Company("0004", "Empresa", LINK, "90002", library_folder_url(LIBRARY, path))
        pending = {}
        self.assertFalse(api._enter_group_company(company, library_folder_url(LIBRARY, GROUP), pending, 1))
        api._load_navigation.assert_called_once_with(company.folder_url, 1, "navigating")
        self.assertFalse(api._enter_group_company(company, library_folder_url(LIBRARY, GROUP + "/0004 - Outra"), pending, 1))
        self.assertTrue(api._enter_group_company(company, library_folder_url(LIBRARY, path + "/2026"), pending, 1))

    def test_lists_paginated_child_folders_without_following_other_tenants(self):
        transport = SharePointDelivery(LIBRARY, GROUP, lambda _: "", lambda: True)
        endpoint = transport._folder_endpoint(GROUP) + "/Folders"
        first = {"d": {"results": [{"Name": "8 - A"}],
                       "__next": "https://tenant.sharepoint.com/sites/Remessas/_api" + endpoint + "?$skiptoken=2"}}
        with patch.object(transport, "_request", side_effect=[
            (200, first), (200, {"d": {"results": [{"Name": "002 - B"}]}}),
        ]) as request:
            self.assertEqual(transport.list_subfolders(), ["8 - A", "002 - B"])
            self.assertEqual([call.args[0] for call in request.call_args_list], ["GET", "GET"])
        first["d"]["__next"] = first["d"]["__next"].replace("tenant.sharepoint.com", "other.sharepoint.com")
        with patch.object(transport, "_request", return_value=(200, first)) as request, self.assertRaises(ValidationError):
            transport.list_subfolders()
            request.assert_called_once()


class GroupRefreshTests(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        self.config = ConfigStore(Path(root) / "companies.json")
        self.company = Company("0004", "Empresa B", LINK, "90002",
                               library_folder_url(LIBRARY, GROUP + "/0004 - Empresa B"))
        self.config.upsert(self.company)
        self.credentials = Mock()
        self.credentials.get.return_value = "fixture"
        self.api = AppApi(self.config, self.credentials, logging.getLogger("group-refresh"), "file:///home")
        self.window = Mock()
        self.window.show_loading.return_value = True
        self.window.show_folder.return_value = True
        self.window.get_current_url.return_value = "file:///home"
        self.api._bind_window(self.window)
        self.api._retry_navigation = Mock()
        self.enterContext(patch("acmais_link.api.threading.Timer"))
        transport = self.enterContext(patch("acmais_link.api.SharePointDelivery"))
        self.list_folders = transport.return_value.__enter__.return_value.list_subfolders
        self.list_folders.return_value = ["0004 - Empresa B", "0015 - Empresa Nova", "Material do grupo"]

    def test_manual_refresh_uses_saved_access_and_updates_existing_profiles(self):
        self.assertTrue(self.api.refresh_group("0004")["ok"])
        self.window.show_loading.assert_called_once()
        self.assertEqual(self.window.show_loading.call_args.kwargs, {"group": True})
        self.window.navigate.assert_called_once()
        self.assertEqual(self.window.navigate.call_args.args[0], LINK)
        self.credentials.get.assert_called_once_with("grupo:90002")
        self.window.evaluate_navigation_js.return_value = {"url": library_folder_url(LIBRARY, GROUP), "ready": True}
        self.api._inspect_navigation(self.window, self.api._navigation_token)

        new_company = ConfigStore(self.config.path).get("0015")
        self.assertEqual(new_company.url, LINK)
        self.assertEqual(new_company.credential_key, "grupo:90002")
        self.assertEqual(library_folder_path(new_company.folder_url), GROUP + "/0015 - Empresa Nova")
        self.credentials.set.assert_not_called()
        self.assertEqual(self.api._mode, "home")
        self.assertIn("1 nova empresa adicionada", self.api.consume_notice()["notice"]["message"])

        self.assertTrue(self.api.refresh_group("0004")["ok"])
        with patch.object(self.config, "_write", wraps=self.config._write) as write:
            self.api._inspect_navigation(self.window, self.api._navigation_token)
            write.assert_not_called()
        self.assertIn("nenhuma empresa nova", self.api.consume_notice()["notice"]["message"])

    def test_refresh_preserves_other_accesses_and_local_removals(self):
        self.config.upsert(Company("0015", "Outra empresa", LINK + "-individual"))
        self.config.upsert(Company("0016", "Removida", LINK, "90002",
                                   library_folder_url(LIBRARY, GROUP + "/0016 - Removida")))
        self.assertTrue(self.api.delete_company("0016")["ok"])
        self.list_folders.return_value = ["0015 - Empresa Nova", "0016 - Removida", "0017 - Nova"]
        self.api._mode = "active"
        self.api._check_group_in_background(self.window, self.company, self.company.folder_url, 0)

        self.assertEqual(self.config.get("0004"), self.company)
        self.assertEqual(self.config.get("0015").url, LINK + "-individual")
        self.assertIsNone(self.config.get("0016"))
        self.assertEqual(self.config.get("0017").group_code, "90002")
        choices = self.window.set_company_choices.call_args.args[0]
        self.assertEqual({item["code"] for item in choices}, {"0004", "0015", "0017"})

    def test_opening_company_starts_check_after_the_folder_is_visible(self):
        self.assertTrue(self.api.open_company("0004")["ok"])
        self.window.evaluate_navigation_js.return_value = {"url": self.company.folder_url, "ready": True}
        self.api._pending["ready_checks"] = 4

        def check_after_open(*_, **__):
            self.window.show_folder.assert_called_once()

        with patch("acmais_link.api.threading.Thread") as worker:
            worker.return_value.start.side_effect = check_after_open
            self.api._inspect_navigation(self.window, self.api._navigation_token)
            self.api._check_group_after_open(self.window, self.company, self.company.folder_url,
                                             self.api._navigation_token)
            worker.assert_called_once()
            self.assertEqual(self.api._mode, "active")

    def test_failed_or_cancelled_refresh_does_not_update_local_companies(self):
        self.api._mode = "navigating"
        group_url = library_folder_url(LIBRARY, GROUP)
        with self.assertRaises(ValidationError):
            self.api._refresh_group_members(self.window, self.company,
                                             library_folder_url(LIBRARY, GROUP + " errado"), 0, manual=True)
        self.list_folders.assert_not_called()
        self.list_folders.return_value = ["0015 - Empresa A", "0015 - Empresa B"]
        with self.assertRaises(ValidationError):
            self.api._refresh_group_members(self.window, self.company, group_url, 0, manual=True)

        def cancel_during_list():
            self.api.return_home()
            return ["0015 - Empresa Nova"]

        self.list_folders.side_effect = cancel_during_list
        self.assertEqual(self.api._refresh_group_members(self.window, self.company, group_url, 0, manual=True), 0)
        self.assertEqual(self.config.list(), [self.company])
