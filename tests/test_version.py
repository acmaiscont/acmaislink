import tempfile
import unittest
from pathlib import Path

from acmais_link import APP_DISPLAY_TITLE, __version__
from acmais_link.web_home import VERSION_MARKER, home_filename, prepare_home, render_home


class VersionDisplayTests(unittest.TestCase):
    source = Path(__file__).resolve().parents[1] / "src/acmais_link/web"

    def test_footer_is_already_correct_before_running_javascript(self):
        template = (self.source / "index.html").read_text(encoding="utf-8")
        html = render_home(template)
        self.assertIn(f'<span id="app-identity">{APP_DISPLAY_TITLE}</span>', html)
        self.assertNotIn(VERSION_MARKER, html)

    def test_builds_use_different_home_urls_and_asset_keys(self):
        template = (self.source / "index.html").read_text(encoding="utf-8")
        for version in ("2.4.0", "2.4.1"):
            html = render_home(template, version)
            self.assertIn(f"index-v{version}.html", home_filename(version))
            self.assertIn(f"style.css?v={version}", html)
            self.assertIn(f"app.js?v={version}", html)
            self.assertIn(f'id="app-identity">ACMAIS LINK · v{version}', html)
        self.assertNotEqual(home_filename("2.4.0"), home_filename("2.4.1"))

    def test_runtime_and_bundle_preparation_only_supply_versioned_home(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            home = prepare_home(self.source, output)
            self.assertEqual(home.name, home_filename())
            self.assertIn(__version__, home.read_text(encoding="utf-8"))
            self.assertFalse((output / "index.html").exists())
            self.assertTrue((output / "app.js").is_file())

    def test_wrong_footer_or_missing_asset_version_blocks_build(self):
        template = (self.source / "index.html").read_text(encoding="utf-8")
        for fragment in (f"v{VERSION_MARKER}</span>", f"style.css?v={VERSION_MARKER}", f"app.js?v={VERSION_MARKER}"):
            with self.subTest(fragment=fragment), self.assertRaises(ValueError):
                render_home(template.replace(fragment, "v1.0.0"))
