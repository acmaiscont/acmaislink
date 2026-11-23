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
