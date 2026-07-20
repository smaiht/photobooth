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
    def test_selects_full_artifact(self):
        artifact = {
            "path": "/photobooth_system/updates/artifacts/full.zip",
            "size": 10,
            "sha256": "a" * 64,
        }
        selected = app._full_update({
            "schema_version": 1,
            "active": "full",
            "artifacts": {"full": artifact},
        })
        self.assertEqual(selected, artifact)

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


class FullUpdateSchedulingTests(unittest.TestCase):
    def test_creates_one_shot_windows_apply_script(self):
        with TemporaryDirectory() as tmpdir, \
             patch("subprocess.Popen") as popen, \
             patch.object(app.sys, "argv", ["app.py"]), \
             patch.object(app.sys, "executable", r"C:\photobooth\python\pythonw.exe"):
            root = Path(tmpdir)
            archive = root / ".update_download.zip"
            archive.write_bytes(b"zip")

            app._schedule_full_update(archive, root, "a" * 16)

            script = (root / ".update_apply.ps1").read_text(encoding="utf-8")
            self.assertIn("Wait-Process -Id $ParentPid", script)
            self.assertIn("Expand-Archive -LiteralPath $ZipPath", script)
            self.assertIn('"config_app.json"', script)
            self.assertIn('Start-Process -FilePath $PythonExe', script)
            args = popen.call_args.args[0]
            self.assertEqual(args[0], "powershell.exe")
            self.assertIn("-ParentPid", args)
            self.assertIn("-ArgsJson", args)


if __name__ == "__main__":
    unittest.main()
