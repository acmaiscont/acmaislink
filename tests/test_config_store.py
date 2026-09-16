import json
import tempfile
import unittest
from pathlib import Path

from acmais_link.config_store import ConfigStore
from acmais_link.models import Company


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "companies.json"
        self.store = ConfigStore(self.path)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_round_trip_contains_no_password_field(self):
        self.store.upsert(Company("0000", "Teste", "https://tenant.sharepoint.com/example"))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["companies"][0]["code"], "0000")
        self.assertNotIn("password", self.path.read_text(encoding="utf-8").lower())

    def test_code_is_unique_case_insensitively(self):
        self.store.upsert(Company("ABC", "Primeira", "https://tenant.sharepoint.com/a"))
        with self.assertRaises(ValueError):
            self.store.upsert(Company("abc", "Segunda", "https://tenant.sharepoint.com/b"), original_code="outro")

    def test_delete(self):
        self.store.upsert(Company("0000", "Teste", "https://tenant.sharepoint.com/example"))
        self.assertTrue(self.store.delete("0000"))
        self.assertEqual(self.store.list(), [])


if __name__ == "__main__":
    unittest.main()

