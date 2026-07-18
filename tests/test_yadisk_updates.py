import hashlib
import io
import json
import unittest
import urllib.request
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import app
from backend import yadisk_updates


class DiskUpdateDownloadTests(unittest.TestCase):
    def test_downloads_and_verifies_artifact(self):
        payload = b"update zip bytes"
        status = {
            "path": "/photobooth_system/updates/artifacts/test-full.zip",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        api_response = io.BytesIO(json.dumps({"href": "https://download.test/file"}).encode())
        file_response = io.BytesIO(payload)

        with TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch("backend.yadisk_updates._request", return_value=api_response), \
             patch.object(urllib.request, "urlopen", return_value=file_response):
            destination = Path(tmpdir) / "update.zip"
            size, digest = yadisk_updates.download_artifact(status, destination)

            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(size, len(payload))
            self.assertEqual(digest, status["sha256"])

    def test_rejects_bad_hash(self):
        payload = b"corrupt"
        status = {
            "path": "/photobooth_system/updates/artifacts/test-full.zip",
            "size": len(payload),
            "sha256": "0" * 64,
        }
        api_response = io.BytesIO(json.dumps({"href": "https://download.test/file"}).encode())
        file_response = io.BytesIO(payload)

        with TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch("backend.yadisk_updates._request", return_value=api_response), \
             patch.object(urllib.request, "urlopen", return_value=file_response):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                yadisk_updates.download_artifact(status, Path(tmpdir) / "update.zip")


class UpdateExtractionTests(unittest.TestCase):
    def test_extracts_code_and_preserves_local_state(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "update.zip"
            target = root / "app"
            target.mkdir()
            (target / "config_app.json").write_text("local", encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("backend/main.py", "updated")
                zf.writestr("config_app.json", "release")
                zf.writestr("python/runtime.dll", b"locked")

            app._extract_update(str(archive), str(target))

            self.assertEqual((target / "backend/main.py").read_text(), "updated")
            self.assertEqual((target / "config_app.json").read_text(), "local")
            self.assertFalse((target / "python/runtime.dll").exists())

    def test_rejects_path_traversal(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "update.zip"
            target = root / "app"
            target.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../outside.txt", "bad")

            with self.assertRaisesRegex(ValueError, "escapes application directory"):
                app._extract_update(str(archive), str(target))
            self.assertFalse((root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
