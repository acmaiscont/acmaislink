import unittest

from acmais_link.sharepoint import (
    extract_company_identity,
    navigation_cover_script,
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

    def test_navigation_cover_is_added_and_then_removed_from_folder(self):
        cover = navigation_cover_script()
        toolbar = navigation_toolbar_script("0000 - Teste")
        self.assertIn("acmais-loading-cover", cover)
        self.assertIn("Abrindo documentos", cover)
        self.assertIn("document.getElementById('acmais-loading-cover')?.remove()", toolbar)


if __name__ == "__main__":
    unittest.main()
