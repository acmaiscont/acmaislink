import hashlib
import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path

from acmais_link.auto_update import AutoUpdateController
from acmais_link.updater import REPOSITORY, UpdateService


def release_metadata(content=b"verified installer", version="v1.1.0"):
    name = f"ACMAIS-LINK-{version.removeprefix('v')}-x64-update.exe"
    return {"version": version, "digest": hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "url": f"https://github.com/{REPOSITORY}/releases/download/{version}/{name}"}


class FakeService(UpdateService):
    def __init__(self, source, metadata=None, current="1.0.0"):
        super().__init__(current)
        self.source = source
        self.latest = release_metadata() if metadata is None else metadata
        self.checks = 0
        self.downloads = 0
        self.launches = []
        self.failure = None
        self.check_entered = None
        self.check_release = None
        self.download_entered = None
        self.download_release = None

    def check(self):
        self.checks += 1
        if self.check_entered:
            self.check_entered.set()
            self.check_release.wait(3)
        if self.failure:
            raise self.failure
        self.release = dict(self.latest) if self.latest else None
        return {"ok": True, "available": self.release is not None}

    def download(self):
        self.downloads += 1
        if self.download_entered:
            self.download_entered.set()
            self.download_release.wait(3)
        return self.source

    def launch(self, path, silent=False, release=None):
        # Intentionally never execute a real installer in this suite.
        self.validate_package(path, release=release)
        self.launches.append((path, silent, dict(release)))
        return object()


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "profile"
        self.source = self.root / "installer.exe"
        self.source.write_bytes(b"verified installer")
        self.logger = logging.getLogger("auto-update-tests")

    def controller(self, service=None, interval=14400, current="1.0.0"):
        service = service or FakeService(self.source, current=current)
        controller = AutoUpdateController(self.data, current, self.logger, service, interval)
        self.addCleanup(controller.stop)
        return controller, service

    def test_download_once_and_launch_only_after_stop(self):
        controller, service = self.controller()
        controller._check_once()
        controller._check_once()
        self.assertEqual(service.downloads, 1)
        self.assertEqual(controller.status()["state"], "ready")
        self.assertFalse(controller.launch_pending())
        self.assertEqual(service.launches, [])
        controller.stop()
        self.assertTrue(controller.launch_pending())
        self.assertFalse(controller.launch_pending())
        path, silent, metadata = service.launches[0]
        self.assertTrue(silent)
        self.assertEqual(metadata, release_metadata())
        self.assertEqual(path.parent, self.data / "updates")
        self.assertTrue((path.parent / "manifest.json").exists())

    def test_new_session_confirms_cache_without_redownloading(self):
        first, _ = self.controller()
        first._check_once()
        first.stop()
        second, service = self.controller()
        self.assertFalse(second.launch_pending())
        second._check_once()
        self.assertEqual(service.checks, 1)
        self.assertEqual(service.downloads, 0)
        second.stop()
        self.assertTrue(second.launch_pending())

    def test_offline_session_never_executes_cached_manifest(self):
        first, _ = self.controller()
        first._check_once()
        second, service = self.controller()
        service.failure = OSError("offline")
        second._check_once()
        self.assertEqual(second.status()["state"], "retry")
        second.stop()
        self.assertFalse(second.launch_pending())
        self.assertEqual(service.launches, [])

    def test_stop_during_network_is_nonblocking_and_idempotent(self):
        controller, service = self.controller()
        service.check_entered = threading.Event()
        service.check_release = threading.Event()
        controller.start()
        controller.start()
        self.assertTrue(service.check_entered.wait(2))
        self.assertTrue(controller._thread.daemon)
        controller.stop()
        controller.stop()
        self.assertTrue(controller._thread.is_alive())
        self.assertFalse(controller.launch_pending())
        service.check_release.set()
        controller._thread.join(2)
        self.assertFalse(controller._thread.is_alive())
        self.assertEqual(service.checks, 1)
        self.assertEqual(service.downloads, 0)

    def test_download_finishing_after_stop_is_not_applied(self):
        controller, service = self.controller()
        service.download_entered = threading.Event()
        service.download_release = threading.Event()
        controller.start()
        self.assertTrue(service.download_entered.wait(2))
        controller.stop()
        service.download_release.set()
        controller._thread.join(2)
        self.assertFalse(controller.launch_pending())
        self.assertEqual(service.launches, [])

    def test_stop_freezes_only_the_previously_ready_candidate(self):
        controller, service = self.controller()
        controller._check_once()
        self.source.write_bytes(b"next verified installer")
        service.latest = release_metadata(b"next verified installer", "v1.2.0")
        service.download_entered = threading.Event()
        service.download_release = threading.Event()
        controller.start()
        self.assertTrue(service.download_entered.wait(2))
        controller.stop()
        service.download_release.set()
        controller._thread.join(2)
        self.assertTrue(controller.launch_pending())
        self.assertEqual(service.launches[0][2], release_metadata())
        self.assertEqual(service.launches[0][0].read_bytes(), b"verified installer")

    def test_outage_preserves_candidate_confirmed_in_this_same_session(self):
        controller, service = self.controller()
        controller._check_once()
        service.failure = OSError("offline after successful confirmation")
        controller._check_once()
        self.assertEqual(controller.status()["state"], "ready")
        controller.stop()
        self.assertTrue(controller.launch_pending())

    def test_byte_tampering_is_rejected_again_at_exit(self):
        controller, service = self.controller()
        controller._check_once()
        manifest_path = self.data / "updates" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        package = manifest_path.parent / manifest["package"]
        package.write_bytes(b"tampered installer")
        # Altering both disk digest and bytes must not replace trusted memory.
        manifest["release"]["digest"] = hashlib.sha256(package.read_bytes()).hexdigest()
        manifest["release"]["size"] = package.stat().st_size
        manifest_path.write_text(json.dumps(manifest))
        controller.stop()
        self.assertFalse(controller.launch_pending())
        self.assertEqual(service.launches, [])
        self.assertEqual(controller.status()["state"], "retry")

    def test_untrusted_manifest_path_and_metadata_cannot_select_an_executable(self):
        first, _ = self.controller()
        first._check_once()
        manifest_path = self.data / "updates" / "manifest.json"
        original = json.loads(manifest_path.read_text())
        for change in ({"package": "../../installer.exe"},
                       {"release": release_metadata(b"forged installer")},
                       {"release": {**release_metadata(), "url": "https://evil.example/update.exe"}}):
            with self.subTest(change=change):
                manifest_path.write_text(json.dumps({**original, **change}))
                controller, service = self.controller()
                controller._check_once()
                self.assertEqual(service.downloads, 1)
                self.assertEqual(controller.status()["state"], "ready")
                controller.stop()
                self.assertTrue(controller.launch_pending())
                self.assertNotEqual(service.launches[0][0], self.source)
                self.assertEqual(service.launches[0][2], release_metadata())

    def test_old_cache_cannot_downgrade_current_installation(self):
        first, _ = self.controller()
        first._check_once()
        current, service = self.controller(current="1.2.0")
        current._check_once()
        self.assertEqual(current.status()["state"], "retry")
        self.assertEqual(service.downloads, 0)
        current.stop()
        self.assertFalse(current.launch_pending())

    def test_corrupt_download_does_not_commit_manifest_or_execute(self):
        controller, service = self.controller()
        self.source.write_bytes(b"corrupt download")
        controller._check_once()
        self.assertEqual(controller.status()["state"], "retry")
        self.assertFalse((self.data / "updates" / "manifest.json").exists())
        controller.stop()
        self.assertFalse(controller.launch_pending())
        self.assertEqual(service.launches, [])

    def test_successful_check_without_release_clears_pending_candidate(self):
        controller, service = self.controller()
        controller._check_once()
        service.latest = None
        controller._check_once()
        self.assertEqual(controller.status()["state"], "current")
        controller.stop()
        self.assertFalse(controller.launch_pending())

    def test_worker_retries_on_injected_interval(self):
        controller, service = self.controller(interval=0.02)
        service.failure = OSError("offline")
        retried = threading.Event()
        check = service.check

        def observe_check():
            if service.checks >= 1:
                retried.set()
            return check()

        service.check = observe_check
        controller.start()
        self.assertTrue(retried.wait(2))
        controller.stop()
        controller._thread.join(2)
        self.assertGreaterEqual(service.checks, 2)
        self.assertEqual(service.downloads, 0)


if __name__ == "__main__":
    unittest.main()
