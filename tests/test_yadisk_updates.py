import ctypes
import hashlib
import io
import json
import sys
import unittest
import urllib.request
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
            scheduled_stages = []

            def download(_artifact, destination):
                destinations.append(destination)
                destination.write_bytes(payload)
                return len(payload), digest

            def schedule(stage, _app_dir, _version):
                scheduled_stages.append(stage)
                self.assertEqual((stage / "app.py").read_text(), "updated")
                return False

            with patch.object(app, "__file__", str(fake_app)), \
                 patch.object(app, "_HASH_FILE", str(root / ".update_hash")), \
                 patch.object(app.sys, "platform", "win32"), \
                 patch.object(app.os, "getpid", return_value=4242), \
                 patch("backend.yadisk_updates.read_status", return_value=status), \
                 patch("backend.yadisk_updates.download_artifact", side_effect=download), \
                 patch.object(app, "_schedule_full_update", side_effect=schedule):
                self.assertEqual(app._update_from_disk(), "external")

            expected_download = root.resolve() / ".update_download.4242.zip"
            expected_stage = root.resolve() / ".update_stage.4242"
            self.assertEqual(destinations, [expected_download])
            self.assertEqual(scheduled_stages, [expected_stage])
            self.assertFalse(destinations[0].exists())
            self.assertFalse(expected_stage.exists())


class UpdateExtractionTests(unittest.TestCase):
    def test_extracts_code_and_replaces_repository_config(self):
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
            self.assertEqual((target / "config_app.json").read_text(), "release")
            self.assertFalse((target / "python/runtime.dll").exists())

    def test_preserves_cafe_unlock_runtime_state(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "update.zip"
            target = root / "app"
            target.mkdir()
            state_path = target / "cafe_unlock_state.json"
            state_path.write_text('{"remaining_sessions":5}', encoding="utf-8")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("backend/main.py", "updated")
                zf.writestr(
                    "cafe_unlock_state.json",
                    '{"remaining_sessions":0}',
                )

            app._extract_update(str(archive), str(target))

            self.assertEqual(
                state_path.read_text(encoding="utf-8"),
                '{"remaining_sessions":5}',
            )

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

    def test_prepares_complete_release_before_application_exit(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "update.zip"
            stage = root / ".update_stage.4242"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("app.py", "updated")
                zf.writestr("config_app.json", "release default")
                zf.writestr("python/runtime.dll", b"new runtime")

            extracted = app._prepare_update_stage(archive, stage)

            self.assertEqual(extracted, 3)
            self.assertEqual((stage / "app.py").read_text(), "updated")
            self.assertEqual(
                (stage / "python/runtime.dll").read_bytes(), b"new runtime")

    def test_failed_stage_preparation_is_removed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "update.zip"
            stage = root / ".update_stage.4242"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("app.py", "updated")
                zf.writestr("../outside.txt", "bad")

            with self.assertRaisesRegex(ValueError, "escapes update stage"):
                app._prepare_update_stage(archive, stage)

            self.assertFalse(stage.exists())
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
            stage = root / ".update_stage.4242"
            stage.mkdir()
            (stage / "app.py").write_text("updated", encoding="utf-8")
            self.assertTrue(app._claim_update_marker(
                root / ".update_in_progress.json"))

            scheduled = app._schedule_full_update(stage, root, "a" * 64)

            self.assertTrue(scheduled)
            script = (root / ".update_apply.4242.ps1").read_text(encoding="utf-8")
            self.assertIn("Wait-Process -Id $ParentPid", script)
            self.assertNotIn("Expand-Archive", script)
            self.assertIn('Write-UpdateLog "Prepared full release found"', script)
            self.assertNotIn('"config_app.json"', script)
            self.assertIn('".git"', script)
            self.assertIn('"cafe_unlock_state.json"', script)
            self.assertIn("Get-PhotoboothProcesses", script)
            self.assertIn("robocopy.exe", script)
            self.assertIn("if ($copyExitCode -ge 8)", script)
            self.assertIn('Move-Item -LiteralPath $hashTempPath', script)
            self.assertIn('$relaunchArgumentLine += " --dev"', script)
            self.assertIn('if ($installed)', script)
            self.assertNotIn("--post-installer", script)
            self.assertNotIn("--skip-update-once", script)
            marker_removal = script.index(
                "Remove-Item -LiteralPath $MarkerPath")
            relaunch = script.index("Start-Process -FilePath $PythonExe")
            self.assertLess(marker_removal, relaunch)
            self.assertIn('Start-Process -FilePath $PythonExe', script)
            self.assertIn("-ArgumentList $relaunchArgumentLine", script)
            self.assertIn("-PassThru", script)
            self.assertIn("$launched.HasExited", script)

            marker = json.loads(
                (root / ".update_in_progress.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["owner_pid"], 4242)
            self.assertEqual(marker["installer_pid"], 9876)

            args = popen.call_args.args[0]
            self.assertEqual(args[0], "powershell.exe")
            self.assertIn("-ParentPid", args)
            self.assertIn("-StagePath", args)
            self.assertEqual(args[args.index("-StagePath") + 1], str(stage.resolve()))
            self.assertEqual(args[args.index("-Mode") + 1], "dev")
            self.assertIn("-MarkerPath", args)
            self.assertNotIn("-ArgsPath", args)

    def test_existing_marker_prevents_a_second_installer(self):
        with TemporaryDirectory() as tmpdir, \
             patch("subprocess.Popen") as popen, \
             patch.object(app.os, "getpid", return_value=4242):
            root = Path(tmpdir)
            stage = root / ".update_stage.4242"
            stage.mkdir()
            (root / ".update_in_progress.json").write_text("{}", encoding="utf-8")

            self.assertFalse(app._schedule_full_update(stage, root, "a" * 64))
            popen.assert_not_called()
            self.assertFalse((root / ".update_apply.4242.ps1").exists())

    def test_failed_powershell_launch_cleans_ownership_files(self):
        with TemporaryDirectory() as tmpdir, \
             patch("subprocess.Popen", side_effect=OSError("no PowerShell")), \
             patch.object(app.os, "getpid", return_value=4242), \
             patch.object(app.sys, "argv", ["app.py", "--dev"]):
            root = Path(tmpdir)
            stage = root / ".update_stage.4242"
            stage.mkdir()

            with self.assertRaisesRegex(OSError, "no PowerShell"):
                app._schedule_full_update(stage, root, "a" * 64)

            self.assertFalse((root / ".update_in_progress.json").exists())
            self.assertFalse((root / ".update_apply.4242.ps1").exists())


class UpdateMarkerTests(unittest.TestCase):
    @staticmethod
    def _run_main_immediately(argv, installer_active=False):
        class EventHook:
            def __iadd__(self, _callback):
                return self

        class ImmediateThread:
            def __init__(self, target, args=(), **_kwargs):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

            def join(self, timeout=None):
                return None

            def is_alive(self):
                return False

        window = SimpleNamespace(
            events=SimpleNamespace(loaded=EventHook()),
            evaluate_js=Mock(),
        )
        webview = SimpleNamespace(
            create_window=Mock(return_value=window),
            start=Mock(),
        )
        with patch.object(app.sys, "argv", argv), \
             patch.object(app, "_external_update_active",
                          return_value=installer_active), \
             patch.object(app, "_build_loading_html", return_value="loading"), \
             patch.object(app, "wait_and_load"), \
             patch.object(app.threading, "Thread", ImmediateThread), \
             patch.object(app, "auto_update") as auto_update, \
             patch.object(app, "start_server") as start_server, \
             patch.dict(sys.modules, {"webview": webview}):
            app.main()
            return auto_update, start_server, list(app.sys.argv)

    def test_windows_process_check_uses_pointer_sized_handle(self):
        large_handle = 0x1234567887654321
        open_process = Mock(return_value=large_handle)
        wait_for_single_object = Mock(return_value=0x00000102)
        close_handle = Mock(return_value=True)
        kernel32 = SimpleNamespace(
            OpenProcess=open_process,
            WaitForSingleObject=wait_for_single_object,
            CloseHandle=close_handle,
        )
        fake_windll = SimpleNamespace(kernel32=kernel32)

        with patch.object(app.sys, "platform", "win32"), \
             patch.object(ctypes, "windll", fake_windll, create=True):
            self.assertTrue(app._windows_process_is_running(9876))

        self.assertIs(open_process.restype, ctypes.wintypes.HANDLE)
        wait_for_single_object.assert_called_once_with(large_handle, 0)
        close_handle.assert_called_once_with(large_handle)

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
             patch.object(app, "_acquire_single_instance", return_value=True), \
             patch.object(app, "_release_single_instance") as release:
            app.main()

            release.assert_called_once_with()

    def test_ordinary_launch_runs_normal_update_check(self):
        auto_update, start_server, argv = self._run_main_immediately(
            ["app.py", "--dev"])

        auto_update.assert_called_once_with()
        start_server.assert_called_once_with()
        self.assertEqual(argv, ["app.py", "--dev"])

    def test_stale_current_artifacts_are_cleaned(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in (
                ".update_download.123.zip",
                ".update_apply.123.ps1",
                ".update_in_progress.json.123.tmp",
                ".update_hash.tmp",
            ):
                (root / name).write_text("stale", encoding="utf-8")
            (root / ".update_stage.123").mkdir()

            app._cleanup_stale_update_artifacts(root)

            self.assertEqual(list(root.iterdir()), [])

    def test_second_windows_instance_does_not_kill_or_replace_first(self):
        create_mutex = Mock(return_value=1234)
        get_last_error = Mock(return_value=app._ERROR_ALREADY_EXISTS)
        close_handle = Mock(return_value=True)
        kernel32 = SimpleNamespace(
            CreateMutexW=create_mutex,
            GetLastError=get_last_error,
            CloseHandle=close_handle,
        )
        with patch.object(app.sys, "platform", "win32"), \
             patch.object(ctypes, "windll",
                          SimpleNamespace(kernel32=kernel32), create=True):
            self.assertFalse(app._acquire_single_instance())

        close_handle.assert_called_once_with(1234)


class WindowsGitSyncTests(unittest.TestCase):
    def test_scripts_align_with_origin_without_touching_ignored_state(self):
        root = Path(__file__).resolve().parents[1]
        sync = (root / "_sync_from_git.bat").read_text(encoding="utf-8")
        dev_start = (root / "script_devstart.bat").read_text(encoding="utf-8")
        git_pull = (root / "script_gitpull.bat").read_text(encoding="utf-8")

        self.assertIn("git fetch --prune origin main", sync)
        self.assertIn("git reset --hard origin/main", sync)
        self.assertIn('.update_in_progress.json', sync)
        self.assertIn("PHOTOBOOTH_SYNC_PYTHONW", sync)
        self.assertNotIn("git pull", sync)
        self.assertNotIn("config_app.json", sync)
        self.assertNotIn("config_camera.json", sync)
        self.assertNotIn(".env", sync)
        self.assertNotIn("CommandLine", sync)
        self.assertIn('_sync_from_git.bat', dev_start)
        self.assertIn('_sync_from_git.bat', git_pull)


class WindowsPowerTests(unittest.TestCase):
    def test_app_prevents_system_sleep_and_display_timeout(self):
        set_execution_state = Mock(return_value=1)
        kernel32 = SimpleNamespace(SetThreadExecutionState=set_execution_state)
        fake_windll = SimpleNamespace(kernel32=kernel32)

        with patch.object(app.sys, "platform", "win32"), \
             patch.object(ctypes, "windll", fake_windll, create=True):
            self.assertTrue(app._prevent_windows_sleep())
            app._restore_windows_sleep(True)

        expected_flags = (
            app._ES_CONTINUOUS
            | app._ES_SYSTEM_REQUIRED
            | app._ES_DISPLAY_REQUIRED
        )
        self.assertEqual(
            set_execution_state.call_args_list[0].args,
            (expected_flags,),
        )
        self.assertEqual(
            set_execution_state.call_args_list[1].args,
            (app._ES_CONTINUOUS,),
        )


if __name__ == "__main__":
    unittest.main()
