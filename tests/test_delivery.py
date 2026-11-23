import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

from acmais_link.delivery import (
    CATALOG, DeliveryHistory, DeliveryRoute, company_root_from_library_url, delivery_selection, is_fiscal_xml,
    library_destination, previous_period, suggest_delivery,
)
from acmais_link.models import ValidationError
from acmais_link.delivery_transport import DUPLICATE, SharePointDelivery


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.route = DeliveryRoute.from_payload(
            {"period": "2026-10", "sector": "Fiscal", "kind": CATALOG["Fiscal"][0]}
        )

    def test_destination_is_constructed_from_resolved_company_root(self):
        path = "/sites/Remessas/Documentos/0150-Empresa Exemplo/2025/01-2025"
        base = "https://tenant.sharepoint.com/sites/Remessas/Documentos/Forms/AllItems.aspx"
        url = base + "?" + urlencode({"id": path, "sensitive": "do-not-copy"})
        expected = "/sites/Remessas/Documentos/0150-Empresa Exemplo/2026/10-2026/Fiscal/" + CATALOG["Fiscal"][0]
        destination, address = library_destination(url, "0150", self.route)
        self.assertEqual(destination, expected)
        self.assertEqual(parse_qs(urlsplit(address).query), {"id": [expected]})
        self.assertIsNone(library_destination(url, "0151", self.route))
        self.assertIsNone(library_destination(url.replace("tenant.sharepoint.com", "example.com"), "0150", self.route))

    def test_catalog_and_period_reject_unlisted_or_invalid_inputs(self):
        props = {"period": "2026-01", "sector": "Fiscal", "kind": CATALOG["Fiscal"][0]}
        for change in ({"period": "2026-13"}, {"sector": ".."}, {"kind": "Extra"}, {"kind": ["xml"]}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                DeliveryRoute.from_payload(props | change)
        self.assertEqual(previous_period(date(2026, 1, 1)), "2025-12")

    def test_fiscal_suggestion_requires_recognized_xml_and_rejects_dtd(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nota.xml"
            path.write_text('<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"/>', encoding="utf-8")
            self.assertTrue(is_fiscal_xml(path))
            path.write_text('<arquivo/>', encoding="utf-8")
            self.assertFalse(is_fiscal_xml(path))
            path.write_text('<!DOCTYPE NFe><NFe xmlns="http://www.portalfiscal.inf.br/nfe"/>', encoding="utf-8")
            self.assertFalse(is_fiscal_xml(path))

    def test_history_is_persistent_and_marks_only_explicit_confirmation_as_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite"
            history = DeliveryHistory(database)
            first = history.start("0150", "0150 - Empresa", self.route, "teste.xml")
            history.start("0150", "0150 - Empresa", self.route, "pendente.pdf")
            history.finish(first, "sent")
            receipts = DeliveryHistory(database).recent()
            self.assertEqual(
                [(row["filename"], row["status"]) for row in receipts],
                [("pendente.pdf", "uncertain"), ("teste.xml", "sent")],
            )
            self.assertNotIn("url", receipts[0])
            self.assertNotIn("path", receipts[0])
            self.assertEqual(history.route_for(receipts[0]["id"]), ("0150", self.route))

    def test_upload_requires_sharepoint_receipt_and_never_overwrites_a_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "teste.xml"
            path.write_bytes(b"<arquivo/>")
            transport = SharePointDelivery(
                "https://tenant.sharepoint.com/sites/Remessas/Docs/Forms/AllItems.aspx",
                "/sites/Remessas/Docs/0150-Empresa/2026/10-2026/Fiscal/XML",
                lambda _: "", lambda: True,
            )
            preflight = [
                (200, {"d": {"Exists": True}}),
                (200, {"d": {"GetContextWebInformation": {"FormDigestValue": "fixture"}}}),
            ]
            existing = (200, {"d": {"UniqueId": "fixture"}})
            with patch.object(transport, "_request", side_effect=preflight + [existing]) as request:
                transport.prepare()
                self.assertEqual(transport.upload(path), DUPLICATE)
                self.assertEqual(request.call_count, 3)
                self.assertEqual(request.call_args.args[0], "GET")
            with patch.object(transport, "_request", side_effect=[(403, {})]) as request:
                outcome = transport.upload(path)
                self.assertEqual(outcome.status, "failed")
                self.assertIn("permissão", outcome.detail)
                request.assert_called_once()
            with patch.object(transport, "_request", side_effect=[(404, {}), (409, {}), existing]) as request:
                self.assertEqual(transport.upload(path), DUPLICATE)
                self.assertEqual([call.args[0] for call in request.call_args_list], ["GET", "POST", "GET"])
            with patch.object(transport, "_request", side_effect=[(404, {}), TimeoutError()]):
                outcome = transport.upload(path)
                self.assertEqual(outcome.status, "uncertain")
                self.assertIn("Confira a pasta", outcome.detail)
            for body, expected in [({}, "uncertain"), ({"d": {"UniqueId": "fixture"}}, "sent")]:
                with patch.object(transport, "_request", side_effect=[(404, {}), (200, body)]) as request:
                    self.assertEqual(transport.upload(path).status, expected)
                    self.assertIn("overwrite=false", request.call_args.args[1])

    def test_history_migrates_existing_database_and_keeps_failure_details(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite"
            history = DeliveryHistory(database)
            original = history.start("0150", "Empresa", self.route, "original.xml")
            history.finish(original, "sent")
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("ALTER TABLE receipts DROP COLUMN detail")
            duplicate = history.start("0150", "Empresa", self.route, "original.xml")
            history.finish(duplicate, DUPLICATE.status, DUPLICATE.detail)
            rows = DeliveryHistory(database).recent()
            self.assertEqual([(row["status"], row["detail"]) for row in rows],
                             [("failed", DUPLICATE.detail), ("sent", "")])

    def test_accounting_accepts_only_fixed_direct_paths(self):
        payload = {"period": "2026-10", "sector": "Contábil", "kind": "Extratos"}
        self.assertEqual(DeliveryRoute.from_payload(payload).segments, ("2026", "10-2026", "Contábil", "Extratos"))
        for alternate in ("Extrato", "Documentos Contabeis", "Documentos Contábeis"):
            with self.subTest(alternate=alternate), self.assertRaises(ValidationError):
                DeliveryRoute.from_payload({**payload, "kind": alternate})

    def test_company_root_must_be_below_the_resolved_library(self):
        base = "https://tenant.sharepoint.com/sites/0150%20-%20Site/Docs/Forms/AllItems.aspx"
        url = base + "?" + urlencode({"id": "/sites/0150 - Site/Docs/0000 - Empresa"})
        self.assertIsNone(company_root_from_library_url(url, "0150"))
        self.assertEqual(company_root_from_library_url(url, "0000"), "/sites/0150 - Site/Docs/0000 - Empresa")

    def test_existing_historical_path_stays_readable_without_a_navigation_shortcut(self):
        route = DeliveryRoute.from_payload({"period": "2026-10", "sector": "Contábil", "kind": "Extratos"})
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite"
            history = DeliveryHistory(database)
            item = history.start("0150", "Empresa", route, "teste.ofx")
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("UPDATE receipts SET destination = ? WHERE id = ?",
                                   ("2026 / 10-2026 / Contábil / Documentos Contábeis / Extrato", item))
            self.assertEqual(history.recent()[0]["filename"], "teste.ofx")
            self.assertFalse(history.recent()[0]["canOpen"])
            self.assertIsNone(history.route_for(item))

    def test_creates_only_missing_segments_below_an_existing_company(self):
        from urllib.parse import unquote
        root = "/sites/Remessas/Docs/0150-Empresa"
        parts = ("2026", "10-2026", "Contábil", "Extratos")
        transport = SharePointDelivery("https://tenant.sharepoint.com/sites/Remessas/Docs/Forms/AllItems.aspx",
                                       "/".join((root, *parts)), lambda _: "", lambda: True)
        present = (200, {"d": {"Exists": True}})
        created = (201, {"d": {"UniqueId": "fixture"}})
        missing = (404, {})
        digest = (200, {"d": {"GetContextWebInformation": {"FormDigestValue": "fixture"}}})
        with patch.object(transport, "_request", side_effect=[
            missing, present, digest, present, missing, created, missing, created, created,
        ]) as request:
            transport.prepare_destination(parts)
        additions = [unquote(args[1]) for args, _ in request.call_args_list if "AddUsingPath" in args[1]]
        self.assertEqual(additions, [
            f"/web/Folders/AddUsingPath(decodedurl='{root}/2026/10-2026')",
            f"/web/Folders/AddUsingPath(decodedurl='{root}/2026/10-2026/Contábil')",
            f"/web/Folders/AddUsingPath(decodedurl='{root}/2026/10-2026/Contábil/Extratos')",
        ])
        for responses in ([(403, {})], [missing, missing]):
            with patch.object(transport, "_request", side_effect=responses) as request, self.assertRaises(ValidationError):
                transport.prepare_destination(parts)
            self.assertTrue(all(args[0] == "GET" for args, _ in request.call_args_list))

    def test_folder_selection_retains_nested_and_empty_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Banco"
            (root / "Anexos").mkdir(parents=True)
            (root / "Movimentos").mkdir()
            (root / "Movimentos" / "Outubro.ofx").write_bytes(b"OFXHEADER:100")
            items = delivery_selection([root], folder=True)
            self.assertEqual([item.label for item in items], ["Banco/Anexos/", "Banco/Movimentos/Outubro.ofx"])
            self.assertEqual(suggest_delivery(items), {"sector": "Contábil", "kind": "Extratos", "period": None})

    def test_ambiguous_documents_are_not_routed_by_extension_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("Extrato novembro.pdf", "guia.pdf", "Balancete outubro.xlsx", "DANFE.pdf")]
            for path in paths:
                path.touch()
            self.assertEqual(suggest_delivery(delivery_selection([paths[0]]))["kind"], "Extratos")
            self.assertIsNone(suggest_delivery(delivery_selection(paths[:2])))
            self.assertEqual(suggest_delivery(delivery_selection([paths[2]]))["kind"], "Outros documentos")
            self.assertEqual(suggest_delivery(delivery_selection([paths[3]]))["sector"], "Fiscal")

    def test_progress_reports_only_consumed_bytes_and_distinguishes_confirmation(self):
        transport = SharePointDelivery("https://tenant.sharepoint.com/sites/R/Docs/Forms/AllItems.aspx",
                                       "/sites/R/Docs/0010-Empresa", lambda _: "", lambda: True)
        seen = []
        stream = transport._blocks(io.BytesIO(b"a" * 300000), 300000, lambda *args: seen.append(args))
        self.assertEqual(len(next(stream)), 262144)
        self.assertEqual(seen, [])
        self.assertEqual(len(next(stream)), 37856)
        self.assertEqual(seen, [(262144, False)])
        self.assertEqual(list(stream), [])
        self.assertEqual(seen[-1], (300000, True))
