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

    def test_windows_download_is_unique_and_yields_to_existing_installer(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_app = root / "app.py"
            fake_app.write_text("", encoding="utf-8")
            (root / "config_app.json").write_text("{}", encoding="utf-8")
            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, "w") as zf:
                zf.writestr("app.py", "updated")
            payload = archive_bytes.getvalue()
            digest = hashlib.sha256(payload).hexdigest()
            status = {
                "schema_version": 1,
                "active": "full",
                "artifacts": {"full": {
                    "path": "/photobooth_system/updates/artifacts/full.zip",
                    "size": len(payload),
                    "sha256": digest,
                }},
            }
            destinations = []

            def download(_artifact, destination):
                destinations.append(destination)
                destination.write_bytes(payload)
                return len(payload), digest

            with patch.object(app, "__file__", str(fake_app)), \
                 patch.object(app, "_HASH_FILE", str(root / ".update_hash")), \
                 patch.object(app.sys, "platform", "win32"), \
                 patch.object(app.os, "getpid", return_value=4242), \
                 patch("backend.yadisk_updates.read_status", return_value=status), \
                 patch("backend.yadisk_updates.download_artifact", side_effect=download), \
                 patch.object(app, "_schedule_full_update", return_value=False) as schedule:
                self.assertEqual(app._update_from_disk(), "external")

            expected_download = root.resolve() / ".update_download.4242.zip"
            self.assertEqual(destinations, [expected_download])
            self.assertFalse(destinations[0].exists())
            schedule.assert_called_once_with(destinations[0], root.resolve(), digest)


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
             patch.object(app.os, "getpid", return_value=4242), \
             patch.object(app.sys, "argv", ["app.py", "--dev"]), \
             patch.object(app.sys, "executable", r"C:\photobooth\python\pythonw.exe"):
            popen.return_value.pid = 9876
            root = Path(tmpdir)
            archive = root / ".update_download.4242.zip"
            archive.write_bytes(b"zip")
            self.assertTrue(app._claim_update_marker(
                root / ".update_in_progress.json"))

            scheduled = app._schedule_full_update(archive, root, "a" * 64)

            self.assertTrue(scheduled)
            script = (root / ".update_apply.4242.ps1").read_text(encoding="utf-8")
            self.assertIn("Wait-Process -Id $ParentPid", script)
            self.assertIn("Expand-Archive -LiteralPath $ZipPath", script)
            self.assertIn('"config_app.json"', script)
            self.assertIn('".git"', script)
            self.assertIn("Get-PhotoboothProcesses", script)
            self.assertIn("robocopy.exe", script)
            self.assertIn("if ($copyExitCode -ge 8)", script)
            self.assertIn('Move-Item -LiteralPath $hashTempPath', script)
            self.assertIn("foreach ($argument in $parsed)", script)
            self.assertIn("[string[]]$relaunchArguments", script)
            self.assertIn('"--skip-update-once"', script)
            self.assertIn('Start-Process -FilePath $PythonExe', script)

            saved_args = json.loads(
                (root / ".update_args.4242.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_args, ["app.py", "--dev"])
            marker = json.loads(
                (root / ".update_in_progress.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["owner_pid"], 4242)
            self.assertEqual(marker["installer_pid"], 9876)

            args = popen.call_args.args[0]
            self.assertEqual(args[0], "powershell.exe")
            self.assertIn("-ParentPid", args)
            self.assertIn("-ArgsPath", args)
            self.assertIn("-MarkerPath", args)
            self.assertNotIn("-ArgsJson", args)

    def test_existing_marker_prevents_a_second_installer(self):
        with TemporaryDirectory() as tmpdir, \
             patch("subprocess.Popen") as popen, \
             patch.object(app.os, "getpid", return_value=4242):
            root = Path(tmpdir)
            archive = root / ".update_download.4242.zip"
            archive.write_bytes(b"zip")
            (root / ".update_in_progress.json").write_text("{}", encoding="utf-8")

            self.assertFalse(app._schedule_full_update(archive, root, "a" * 64))
            popen.assert_not_called()
            self.assertFalse((root / ".update_apply.4242.ps1").exists())
            self.assertFalse((root / ".update_args.4242.json").exists())

    def test_failed_powershell_launch_cleans_ownership_files(self):
        with TemporaryDirectory() as tmpdir, \
             patch("subprocess.Popen", side_effect=OSError("no PowerShell")), \
             patch.object(app.os, "getpid", return_value=4242), \
             patch.object(app.sys, "argv", ["app.py", "--dev"]):
            root = Path(tmpdir)
            archive = root / ".update_download.4242.zip"
            archive.write_bytes(b"zip")

            with self.assertRaisesRegex(OSError, "no PowerShell"):
                app._schedule_full_update(archive, root, "a" * 64)

            self.assertFalse((root / ".update_in_progress.json").exists())
            self.assertFalse((root / ".update_apply.4242.ps1").exists())
            self.assertFalse((root / ".update_args.4242.json").exists())


class UpdateMarkerTests(unittest.TestCase):
    def test_running_installer_marker_is_active(self):
        with TemporaryDirectory() as tmpdir, patch.object(app.time, "time", return_value=100):
            marker = Path(tmpdir) / ".update_in_progress.json"
            marker.write_text(json.dumps({
                "started_at": 90,
                "installer_pid": 9876,
            }), encoding="utf-8")
            with patch.object(app, "_windows_process_is_running", return_value=True):
                self.assertTrue(app._external_update_active(marker))
            self.assertTrue(marker.exists())

    def test_new_marker_without_installer_pid_is_temporarily_active(self):
        with TemporaryDirectory() as tmpdir, patch.object(app.time, "time", return_value=100):
            marker = Path(tmpdir) / ".update_in_progress.json"
            marker.write_text(json.dumps({
                "started_at": 90,
                "installer_pid": 0,
            }), encoding="utf-8")
            self.assertTrue(app._external_update_active(marker))

    def test_stale_marker_is_removed(self):
        with TemporaryDirectory() as tmpdir, patch.object(app.time, "time", return_value=100):
            marker = Path(tmpdir) / ".update_in_progress.json"
            marker.write_text(json.dumps({
                "started_at": 10,
                "installer_pid": 9876,
            }), encoding="utf-8")
            with patch.object(app, "_windows_process_is_running", return_value=False):
                self.assertFalse(app._external_update_active(marker))
            self.assertFalse(marker.exists())

    def test_check_owner_releases_only_before_installer_takes_over(self):
        with TemporaryDirectory() as tmpdir, patch.object(app.os, "getpid", return_value=4242):
            marker = Path(tmpdir) / ".update_in_progress.json"
            self.assertTrue(app._claim_update_marker(marker))
            app._release_update_marker(marker)
            self.assertFalse(marker.exists())

            self.assertTrue(app._claim_update_marker(marker))
            payload = json.loads(marker.read_text(encoding="utf-8"))
            payload["installer_pid"] = 9876
            marker.write_text(json.dumps(payload), encoding="utf-8")
            app._release_update_marker(marker)
            self.assertTrue(marker.exists())

    def test_extra_app_launch_exits_before_loading_backend(self):
        with patch.object(app.sys, "argv", ["app.py", "--dev"]), \
             patch.object(app, "_external_update_active", return_value=True), \
             patch.object(app, "kill_port") as kill_port:
            app.main()

            kill_port.assert_not_called()

    def test_stale_legacy_and_unique_artifacts_are_cleaned(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in (
                ".update_download.zip",
                ".update_download.123.zip",
                ".update_apply.ps1",
                ".update_apply.123.ps1",
                ".update_args.123.json",
                ".update_in_progress.json.123.tmp",
                ".update_hash.tmp",
            ):
                (root / name).write_text("stale", encoding="utf-8")
            (root / ".update_stage").mkdir()
            (root / ".update_stage.123").mkdir()

            app._cleanup_stale_update_artifacts(root)

            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
