import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from acmais_link.updater import MAX_PACKAGE, SafeRedirect, UpdateService


class SilentUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.service = UpdateService("1.0.0")
        self.payload = b"verified installer bytes"
        self.metadata = {
            "url": "https://github.com/acmaiscont/acmaislink/releases/download/v1.1.0/ACMAIS-LINK-1.1.0-x64-update.exe",
            "digest": hashlib.sha256(self.payload).hexdigest(),
            "size": len(self.payload),
            "version": "v1.1.0",
        }

    def test_silent_launch_uses_verified_absolute_path_without_shell_or_wizard(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "verified package.exe"
            package.write_bytes(self.payload)
            process = Mock()
            with patch("acmais_link.updater.subprocess.Popen", return_value=process) as launch, \
                    patch("acmais_link.updater.sys.platform", "win32"):
                result = self.service.launch(package, silent=True, release=self.metadata)
            self.assertIs(result, process)
            launch.assert_called_once_with(
                [str(package.resolve()), "/S"], shell=False,
                cwd=str(package.resolve().parent), creationflags=0x08000000,
            )
            process.wait.assert_not_called()
            process.terminate.assert_not_called()

    def test_default_launch_remains_compatible_with_explicit_manual_install(self):
        self.service.release = dict(self.metadata)
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package.exe"
            package.write_bytes(self.payload)
            with patch("acmais_link.updater.subprocess.Popen") as launch:
                self.service.launch(package)
            launch.assert_called_once_with(
                [str(package.resolve())], shell=False,
                cwd=str(package.resolve().parent), creationflags=0,
            )

    def test_package_modified_after_earlier_validation_cannot_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package.exe"
            package.write_bytes(self.payload)
            self.service.validate_package(package, release=self.metadata)
            package.write_bytes(b"x" * len(self.payload))
            with patch("acmais_link.updater.subprocess.Popen") as launch, self.assertRaises(ValueError):
                self.service.launch(package, silent=True, release=self.metadata)
            launch.assert_not_called()

    def test_partial_cache_can_be_validated_but_not_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            partial = Path(temporary) / "package.part"
            partial.write_bytes(self.payload)
            self.assertEqual(self.service.validate_package(partial, self.metadata), partial.resolve())
            with patch("acmais_link.updater.subprocess.Popen") as launch, self.assertRaises(ValueError):
                self.service.launch(partial, silent=True, release=self.metadata)
            launch.assert_not_called()

    def test_wrong_size_missing_package_and_missing_metadata_cannot_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "package.exe"
            for content in (b"", self.payload + b"appended bytes"):
                package.write_bytes(content)
                with self.subTest(size=len(content)), \
                        patch("acmais_link.updater.subprocess.Popen") as launch, self.assertRaises(ValueError):
                    self.service.launch(package, silent=True, release=self.metadata)
                launch.assert_not_called()
            package.unlink()
            with self.assertRaises(FileNotFoundError):
                self.service.validate_package(package, self.metadata)
            with self.assertRaises(ValueError):
                self.service.validate_package(package)

    def test_rejects_untrusted_or_old_persisted_metadata(self):
        for changes in (
            {"url": "https://evil.example/update.exe"},
            {"url": self.metadata["url"].replace("-update.exe", "-full.exe")},
            {"digest": "z" * 64}, {"digest": None}, {"size": True},
            {"size": 0}, {"size": MAX_PACKAGE + 1}, {"version": "../v1.1.0"},
            {"version": "v1.1.0-rc.1"}, {"version": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.service.validate_release({**self.metadata, **changes})
        with self.assertRaises(ValueError):
            UpdateService("1.1.0").validate_release(self.metadata)
        with self.assertRaises(ValueError):
            UpdateService("1.2.0").validate_release(self.metadata)
        self.assertEqual(
            UpdateService("1.1.0").validate_release(self.metadata, require_newer=False), self.metadata,
        )

    def test_metadata_normalization_does_not_keep_arbitrary_paths_or_mutate_service(self):
        source = {**self.metadata, "path": "C:/untrusted/package.exe"}
        validated = self.service.validate_release(source)
        self.assertEqual(validated, self.metadata)
        self.assertIsNone(self.service.release)
        self.assertIn("path", source)

    def test_download_revalidates_release_before_network_or_temporary_files(self):
        self.service.release = {**self.metadata, "url": "https://evil.example/update.exe"}
        with patch.object(self.service, "_open") as network, \
                patch("acmais_link.updater.tempfile.mkdtemp") as temporary, self.assertRaises(ValueError):
            self.service.download()
        network.assert_not_called()
        temporary.assert_not_called()

    def test_failed_release_selection_invalidates_previous_cached_choice(self):
        self.service.release = dict(self.metadata)
        with self.assertRaises(ValueError):
            self.service._select({"tag_name": "v1.2.0", "assets": [None]})
        self.assertIsNone(self.service.release)

    def test_redirects_reject_unexpected_ports_and_control_characters(self):
        for url in ("https://github.com:444/download", "https://github.com/path\nmore"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                SafeRedirect().redirect_request(None, None, 302, "Found", {}, url)


if __name__ == "__main__":
    unittest.main()
