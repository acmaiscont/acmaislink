import unittest

from acmais_link.models import Company, ValidationError, is_allowed_sharepoint_url


class CompanyTests(unittest.TestCase):
    def test_accepts_sharepoint_https_url(self):
        company = Company.from_payload({
            "code": "0000",
            "name": "Teste",
            "url": "https://tenant.sharepoint.com/:f:/s/Documentos/example",
        })
        self.assertEqual(company.code, "0000")

    def test_rejects_non_sharepoint_domain(self):
        with self.assertRaises(ValidationError):
            Company.from_payload({"code": "1", "name": "Teste", "url": "https://example.com"})

    def test_rejects_credentials_inside_url(self):
        with self.assertRaises(ValidationError):
            Company.from_payload({"code": "1", "name": "Teste", "url": "https://u:p@tenant.sharepoint.com/x"})

    def test_redirect_guard_rejects_external_host(self):
        self.assertFalse(is_allowed_sharepoint_url("https://evil.example/password"))
        self.assertTrue(is_allowed_sharepoint_url("https://tenant.sharepoint.com/folder"))



if __name__ == "__main__":
    unittest.main()
