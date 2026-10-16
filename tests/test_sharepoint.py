import unittest
from urllib.parse import quote

from acmais_link.sharepoint import (
    extract_company_identity,
    navigation_cover_script,
    navigation_state_script,
    navigation_toolbar_script,
    password_submission_script,
)


class SharePointScriptTests(unittest.TestCase):
    def test_password_is_json_escaped(self):
        script = password_submission_script('a"b\\c')
        self.assertIn('a\\"b\\\\c', script)
        self.assertIn('input[type="password"]', script)
        self.assertIn("#btnSubmitPassword", script)
        self.assertIn('input[type="button"]', script)

    def test_extracts_company_from_sharepoint_id(self):
        url = (
            "https://tenant.sharepoint.com/sites/docs/Forms/AllItems.aspx"
            "?id=%2Fsites%2Fdocs%2FShared%20Documents%2F0000%20-%20Teste%2F2026"
        )
        self.assertEqual(extract_company_identity(url), ("0000", "Teste"))

    def test_rejects_folder_without_standard_name(self):
        self.assertIsNone(extract_company_identity("https://tenant.sharepoint.com/sites/docs"))

    def test_existing_company_identity_must_match_selected_code(self):
        self.assertIsNone(extract_company_identity('https://tenant.sharepoint.com/share', '0000 - Teste', expected_code='150'))
        self.assertEqual(extract_company_identity('https://tenant.sharepoint.com/share', '150-Empresa', expected_code='150'), ('150', 'Empresa'))

    def test_existing_company_matches_ancestor_in_numbered_subfolder(self):
        url = 'https://tenant.sharepoint.com/AllItems.aspx?id=' + quote('/docs/150-Empresa/01 - Janeiro', safe='')
        self.assertEqual(extract_company_identity(url, '01 - Janeiro', expected_code='150'), ('150', 'Empresa'))

    def test_extracts_company_from_rootfolder_and_encoded_name(self):
        url = (
            "https://tenant.sharepoint.com/sites/docs/Forms/AllItems.aspx"
            "?RootFolder=%2Fsites%2Fdocs%2FDocumentos%2F0042%20-%20Com%C3%A9rcio%20Exemplo%2F2026"
        )
        self.assertEqual(extract_company_identity(url), ("0042", "Comércio Exemplo"))

    def test_normalizes_reported_company_heading_with_crlf(self):
        heading = "150 - \r\nEMPRESA EXEMPLO DE SERVICOS LTDA"
        self.assertEqual(
            extract_company_identity("https://tenant.sharepoint.com/share", heading),
            ("150", "EMPRESA EXEMPLO DE SERVICOS LTDA"),
        )

    def test_numeric_company_separator_spaces_are_optional(self):
        name = "EMPRESA EXEMPLO DE SERVICOS LTDA"
        for separator in ("-", " -", "- ", " - "):
            heading = "150" + separator + name
            with self.subTest(heading=heading):
                self.assertEqual(extract_company_identity("https://tenant.sharepoint.com/share", heading), ("150", name))

    def test_numeric_unspaced_company_is_extracted_from_query_and_path(self):
        folder_path = quote("/docs/00150-Empresa - Filial/2026", safe="")
        for url in ("https://tenant.sharepoint.com/AllItems.aspx?id=" + folder_path,
                    "https://tenant.sharepoint.com/AllItems.aspx?RootFolder=" + folder_path,
                    "https://tenant.sharepoint.com/" + folder_path):
            with self.subTest(url=url):
                self.assertEqual(extract_company_identity(url), ("00150", "Empresa - Filial"))

    def test_alphanumeric_codes_keep_the_standard_spaced_separator(self):
        for code in ("ACME150", "ACME-150", "ABC"):
            with self.subTest(code=code):
                self.assertEqual(
                    extract_company_identity("https://tenant.sharepoint.com/share", code + " - Empresa"),
                    (code, "Empresa"),
                )

    def test_unspaced_hyphenated_words_and_empty_numeric_names_are_not_companies(self):
        for heading in ("marketing-list", "marketing- list", "marketing -list", "ACME150-Empresa", "150-", "150 - "):
            with self.subTest(heading=heading):
                self.assertIsNone(extract_company_identity("https://tenant.sharepoint.com/share", heading))

    def test_normalizes_internal_heading_whitespace(self):
        self.assertEqual(
            extract_company_identity("https://tenant.sharepoint.com/share", " \t0042\u00a0 - \r\nEmpresa\n  Exemplo\t"),
            ("0042", "Empresa Exemplo"),
        )

    def test_normalizes_reported_company_inside_query_folder_path(self):
        path = "/sites/docs/150 - \r\nEMPRESA EXEMPLO DE SERVICOS LTDA/2026"
        for key in ("id", "RootFolder"):
            with self.subTest(key=key):
                url = "https://tenant.sharepoint.com/AllItems.aspx?" + key + "=" + quote(path, safe="")
                self.assertEqual(extract_company_identity(url), ("150", "EMPRESA EXEMPLO DE SERVICOS LTDA"))

    def test_query_prefers_deepest_matching_folder_over_named_ancestor(self):
        path = "/sites/2026 - Arquivos/0042 - Empresa Exemplo/2026/09"
        for key in ("id", "RootFolder"):
            with self.subTest(key=key):
                url = "https://tenant.sharepoint.com/AllItems.aspx?" + key + "=" + quote(path, safe="")
                self.assertEqual(extract_company_identity(url), ("0042", "Empresa Exemplo"))

    def test_extracts_decoded_url_path_only_as_fallback(self):
        url = "https://tenant.sharepoint.com/:f:/r/sites/docs/0042%20-%20Empresa%20Exemplo?web=1"
        self.assertEqual(extract_company_identity(url), ("0042", "Empresa Exemplo"))
        self.assertEqual(extract_company_identity(url, "0050 - Pasta atual"), ("0050", "Pasta atual"))
        self.assertEqual(
            extract_company_identity(url + "&id=" + quote("/docs/0060 - Pasta do query", safe="")),
            ("0060", "Pasta do query"),
        )

    def test_percent_decoding_is_limited_to_two_total_passes(self):
        path = "/docs/0042 - Empresa Exemplo"
        once = quote(path, safe="")
        twice = quote(once, safe="")
        thrice = quote(twice, safe="")
        for encoded, expected in ((once, ("0042", "Empresa Exemplo")),
                                  (twice, ("0042", "Empresa Exemplo")), (thrice, None)):
            with self.subTest(encoded=encoded):
                self.assertEqual(extract_company_identity("https://tenant.sharepoint.com/AllItems.aspx?id=" + encoded), expected)
                self.assertEqual(extract_company_identity("https://tenant.sharepoint.com/" + encoded), expected)

    def test_snapshot_reads_page_identity_and_password_together(self):
        script = navigation_state_script()
        self.assertIn("url: location.href", script)
        self.assertIn("hasPassword: Boolean(acmaisPasswordInput())", script)
        self.assertIn(".ms-Breadcrumb-itemLink", script)
        self.assertIn("getClientRects()", script)

    def test_snapshot_restricts_attribute_names_to_breadcrumbs_and_headings(self):
        script = navigation_state_script()
        self.assertIn('[data-automationid="breadcrumb"]', script)
        self.assertIn('[data-automation-id="breadcrumb"]', script)
        self.assertIn('[aria-label="breadcrumb" i]', script)
        self.assertIn("root.querySelectorAll('a, button, [aria-current]')", script)
        self.assertIn("document.querySelectorAll('h1, h2, [role=\"heading\"]')", script)
        self.assertIn("item.getAttribute('title')", script)
        self.assertIn("item.getAttribute('aria-label')", script)
        self.assertIn("replace(/\\s+/g, ' ')", script)
        self.assertNotIn('document.title,', script)
        self.assertNotIn('document.body.textContent', script)

    def test_snapshot_counts_frames_without_reading_them(self):
        script = navigation_state_script()
        self.assertIn("frameCount: document.querySelectorAll('iframe, frame').length", script)
        self.assertNotIn('contentDocument', script)
        self.assertNotIn('contentWindow', script)

    def test_scripts_include_native_navigation_generation(self):
        cover = navigation_cover_script(navigation_token=41)
        toolbar = navigation_toolbar_script("0042 - Exemplo", navigation_token=42)
        self.assertIn("acmaisPrevious.token > 41", cover)
        self.assertIn('phase: "loading"', cover)
        self.assertIn("acmaisPrevious.token > 42", toolbar)
        self.assertIn('phase: "active"', toolbar)

    def test_password_fallback_never_selects_injected_controls(self):
        script = password_submission_script("example", "https://tenant.sharepoint.com", navigation_token=41)
        self.assertIn("!item.closest('#acmais-loading-cover, #acmais-link-toolbar')", script)
        self.assertIn("if (!button) return false", script)
        self.assertIn("input.disabled || input.readOnly", script)

    def test_navigation_cover_is_added_and_then_removed_from_folder(self):
        cover = navigation_cover_script()
        toolbar = navigation_toolbar_script("0000 - Teste")
        self.assertIn("acmais-loading-cover", cover)
        self.assertIn("Abrindo documentos", cover)
        self.assertIn("document.getElementById('acmais-loading-cover')?.remove()", toolbar)

    def test_native_password_submission_never_injects_a_late_dom_cover(self):
        script = password_submission_script('example', 'https://tenant.sharepoint.com',
                                            expected_url='https://tenant.sharepoint.com/link', include_cover=False)
        self.assertNotIn('const acmaisCover', script)
        self.assertIn('if (location.href !== "https://tenant.sharepoint.com/link") return false;', script)


if __name__ == "__main__":
    unittest.main()
