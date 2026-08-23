import ctypes
import hashlib
import io
import json
import ssl
import sys
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app
from backend import yadisk_updates


def folder_archive(folder: str, filename: str, payload: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(f"{folder}/{filename}", payload)
    return output.getvalue()


class LoadingScreenTests(unittest.TestCase):
    def test_embeds_bundled_font_when_available(self):
        with TemporaryDirectory() as tmpdir:
            font_path = Path(tmpdir) / "font.ttf"
            font_path.write_bytes(b"test font")

            with patch.object(app, "FONT_PATH", font_path):
                html = app._build_loading_html()

        self.assertIn("@font-face", html)
        self.assertIn("dGVzdCBmb250", html)

    def test_missing_font_uses_system_fallback_so_updater_can_start(self):
        with TemporaryDirectory() as tmpdir, \
             patch.object(app, "FONT_PATH", Path(tmpdir) / "missing.ttf"), \
             self.assertLogs("update", level="WARNING") as logs:
            html = app._build_loading_html()

        self.assertNotIn("@font-face", html)
        self.assertIn("'Segoe UI',Arial,sans-serif", html)
        self.assertIn("Загрузка", html)
        self.assertIn("using a system fallback", "\n".join(logs.output))


class DiskUpdateStatusTests(unittest.TestCase):
    def _api_response(self, link: str):
        return io.BytesIO(json.dumps({"href": link}).encode())

    def _status_response(self):
        payload = json.dumps({
            "schema_version": 1,
            "active": "full",
        }).encode()
        return io.BytesIO(folder_archive(
            "status_bundle", "status.json", payload))

    def test_reads_status_with_short_startup_timeouts(self):
        with patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch(
                 "backend.yadisk_updates._request",
                 return_value=self._api_response("https://storage.test/status"),
             ) as request_link, \
             patch.object(
                 urllib.request,
                 "urlopen",
                 return_value=self._status_response(),
             ) as urlopen:
            status = yadisk_updates.read_status(
                "updates",
                retry_delays=(),
            )

        self.assertEqual(status["schema_version"], 1)
        self.assertEqual(
            request_link.call_args.kwargs["timeout"],
            yadisk_updates.STATUS_REQUEST_TIMEOUT,
        )
        self.assertEqual(
            request_link.call_args.kwargs["params"]["path"],
            "/updates/status_bundle",
        )
        self.assertEqual(
            urlopen.call_args.kwargs["timeout"],
            yadisk_updates.STATUS_REQUEST_TIMEOUT,
        )

    def test_retries_api_dns_failure_then_fetches_status(self):
        retries = []
        api_responses = [
            urllib.error.URLError("getaddrinfo failed"),
            self._api_response("https://storage.test/status"),
        ]
        with patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch(
                 "backend.yadisk_updates._request",
                 side_effect=api_responses,
             ) as request_link, \
             patch.object(
                 urllib.request,
                 "urlopen",
                 return_value=self._status_response(),
             ) as urlopen, \
             patch("backend.yadisk_updates.time.sleep") as sleep:
            status = yadisk_updates.read_status(
                "updates",
                on_retry=lambda *values: retries.append(values),
                retry_delays=(2,),
            )

        self.assertEqual(status["active"], "full")
        self.assertEqual(request_link.call_count, 2)
        urlopen.assert_called_once()
        self.assertEqual(retries[0][:3], (1, 2, 2.0))
        sleep.assert_called_once_with(2.0)

    def test_storage_failure_requests_a_fresh_link_before_retry(self):
        links = [
            self._api_response("https://storage.test/first"),
            self._api_response("https://storage.test/second"),
        ]
        downloads = [
            urllib.error.URLError("connection refused"),
            self._status_response(),
        ]
        with patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch(
                 "backend.yadisk_updates._request",
                 side_effect=links,
             ) as request_link, \
             patch.object(
                 urllib.request,
                 "urlopen",
                 side_effect=downloads,
             ) as urlopen, \
             patch("backend.yadisk_updates.time.sleep"):
            status = yadisk_updates.read_status(
                "updates",
                retry_delays=(0,),
            )

        self.assertEqual(status["active"], "full")
        self.assertEqual(request_link.call_count, 2)
        self.assertEqual(
            [call.args[0].full_url for call in urlopen.call_args_list],
            ["https://storage.test/first", "https://storage.test/second"],
        )

    def test_certificate_failure_is_retried_without_disabling_ssl(self):
        certificate_error = ssl.SSLCertVerificationError(
            1,
            "self-signed certificate in certificate chain",
        )
        with patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch(
                 "backend.yadisk_updates._request",
                 side_effect=[
                     urllib.error.URLError(certificate_error),
                     self._api_response("https://storage.test/status"),
                 ],
             ), \
             patch.object(
                 urllib.request,
                 "urlopen",
                 return_value=self._status_response(),
             ), \
             patch("backend.yadisk_updates.time.sleep") as sleep:
            status = yadisk_updates.read_status(
                "updates",
                retry_delays=(0,),
            )

        self.assertEqual(status["active"], "full")
        sleep.assert_called_once_with(0.0)

    def test_missing_status_and_permanent_errors_are_not_retried(self):
        for code, expected in ((404, None), (401, "raise")):
            error = urllib.error.HTTPError(
                "https://cloud-api.yandex.net",
                code,
                "error",
                {},
                None,
            )
            with self.subTest(code=code), \
                 patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
                 patch(
                     "backend.yadisk_updates._request",
                     side_effect=error,
                 ) as request_link, \
                 patch("backend.yadisk_updates.time.sleep") as sleep:
                if expected == "raise":
                    with self.assertRaises(urllib.error.HTTPError):
                        yadisk_updates.read_status(
                            "updates",
                            retry_delays=(0, 0),
                        )
                else:
                    self.assertIsNone(yadisk_updates.read_status(
                        "updates",
                        retry_delays=(0, 0),
                    ))

            request_link.assert_called_once()
            sleep.assert_not_called()
            error.close()

    def test_exhausts_five_attempts_for_a_transient_failure(self):
        error = urllib.error.URLError("network unavailable")
        with patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch(
                 "backend.yadisk_updates._request",
                 side_effect=error,
             ) as request_link, \
             patch("backend.yadisk_updates.time.sleep") as sleep:
            with self.assertRaises(urllib.error.URLError):
                yadisk_updates.read_status("updates")

        self.assertEqual(request_link.call_count, 5)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [2.0, 3.0, 3.0, 3.0],
        )

    def test_cancel_stops_before_the_next_status_attempt(self):
        cancel_event = app.threading.Event()
        error = urllib.error.URLError("network unavailable")

        def cancel_on_retry(*_args):
            cancel_event.set()

        with patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch(
                 "backend.yadisk_updates._request",
                 side_effect=error,
             ) as request_link, \
             patch("backend.yadisk_updates.time.sleep") as sleep:
            status = yadisk_updates.read_status(
                "updates",
                on_retry=cancel_on_retry,
                retry_delays=(3, 3),
                cancel_event=cancel_event,
            )

        self.assertIsNone(status)
        request_link.assert_called_once()
        sleep.assert_not_called()

    def test_loading_screen_reports_the_next_status_attempt(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_app = root / "app.py"
            fake_app.write_text("", encoding="utf-8")
            (root / "config_app.json").write_text("{}", encoding="utf-8")

            def read_status(_folder, *, on_retry, cancel_event=None):
                on_retry(
                    1,
                    5,
                    2.0,
                    urllib.error.URLError("getaddrinfo failed"),
                )
                return None

            with patch.object(app, "__file__", str(fake_app)), \
                 patch(
                     "backend.yadisk_updates.read_status",
                     side_effect=read_status,
                 ), \
                 patch.object(app, "_ui_progress") as progress, \
                 patch.object(app, "_ui_log"), \
                 self.assertLogs("update", level="WARNING") as logs:
                self.assertIsNone(app._update_from_disk())

        progress.assert_called_once_with(
            "Нет связи с Яндекс Диском · повтор 2/5 через 2 с"
        )
        self.assertIn(
            "status check attempt 1/5 failed",
            "\n".join(logs.output),
        )


class DiskUpdateDownloadTests(unittest.TestCase):
    def test_selects_full_artifact(self):
        artifact = {
            "path": "/photobooth_system/updates/artifacts/full_bundle/full.zip",
            "bundle_path": "/photobooth_system/updates/artifacts/full_bundle",
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
            "path": "/photobooth_system/updates/artifacts/test-full_bundle/test-full.zip",
            "bundle_path": "/photobooth_system/updates/artifacts/test-full_bundle",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        api_response = io.BytesIO(json.dumps({"href": "https://download.test/file"}).encode())
        file_response = io.BytesIO(folder_archive(
            "test-full_bundle", "test-full.zip", payload))
        progress = []

        with TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch(
                 "backend.yadisk_updates._request",
                 return_value=api_response,
             ) as request_link, \
             patch.object(urllib.request, "urlopen", return_value=file_response), \
             patch("backend.yadisk_updates.time.monotonic",
                   side_effect=[10.0, 12.0, 14.0]):
            destination = Path(tmpdir) / "update.zip"
            with self.assertLogs("update", level="INFO") as logs:
                size, digest = yadisk_updates.download_artifact(
                    status,
                    destination,
                    progress=lambda *values: progress.append(values),
                )

            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(size, len(payload))
            self.assertEqual(digest, status["sha256"])
            self.assertEqual(progress[0], (0, len(payload), 0.0, 1, 5))
            self.assertEqual(progress[-1][:2], (len(payload), len(payload)))
            self.assertGreater(progress[-1][2], 0)
            self.assertIn("storage host download.test", "\n".join(logs.output))
            self.assertEqual(
                request_link.call_args.kwargs["params"]["path"],
                status["bundle_path"],
            )

    def test_rejects_bad_hash(self):
        payload = b"corrupt"
        status = {
            "path": "/photobooth_system/updates/artifacts/test-full_bundle/test-full.zip",
            "bundle_path": "/photobooth_system/updates/artifacts/test-full_bundle",
            "size": len(payload),
            "sha256": "0" * 64,
        }
        api_response = io.BytesIO(json.dumps({"href": "https://download.test/file"}).encode())
        file_response = io.BytesIO(folder_archive(
            "test-full_bundle", "test-full.zip", payload))

        with TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch("backend.yadisk_updates._request", return_value=api_response), \
             patch.object(urllib.request, "urlopen", return_value=file_response):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                yadisk_updates.download_artifact(
                    status,
                    Path(tmpdir) / "update.zip",
                    retry_delays=(),
                )

    def test_component_download_uses_size_without_comparing_folder_sha_to_zip(self):
        payload = b"valid ZIP bytes would be checked by the extraction stage"
        artifact = {
            "path": "/photobooth_system/updates/artifacts/app_bundle/app.zip",
            "bundle_path": "/photobooth_system/updates/artifacts/app_bundle",
            "size": len(payload),
            "sha256": "f" * 64,
        }
        api_response = io.BytesIO(
            json.dumps({"href": "https://download.test/app"}).encode()
        )
        file_response = io.BytesIO(folder_archive(
            "app_bundle", "app.zip", payload))

        with TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch("backend.yadisk_updates._request", return_value=api_response), \
             patch.object(urllib.request, "urlopen", return_value=file_response):
            destination = Path(tmpdir) / "app.zip"
            size, archive_sha = yadisk_updates.download_artifact(
                artifact,
                destination,
                retry_delays=(),
                verify_sha256=False,
            )

        self.assertEqual(size, len(payload))
        self.assertEqual(archive_sha, hashlib.sha256(payload).hexdigest())

    def test_retries_with_fresh_link_and_discards_partial_file(self):
        class FailingResponse(io.BytesIO):
            def __init__(self, payload):
                super().__init__(payload)
                self._read_once = False

            def read(self, size=-1):
                if self._read_once:
                    raise urllib.error.URLError("storage connection refused")
                self._read_once = True
                return super().read(size)

        payload = b"complete update"
        status = {
            "path": "/photobooth_system/updates/artifacts/test-full_bundle/test-full.zip",
            "bundle_path": "/photobooth_system/updates/artifacts/test-full_bundle",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        links = [
            io.BytesIO(json.dumps({"href": "https://download.test/first"}).encode()),
            io.BytesIO(json.dumps({"href": "https://download.test/second"}).encode()),
        ]
        downloads = [
            FailingResponse(b"partial"),
            io.BytesIO(folder_archive(
                "test-full_bundle", "test-full.zip", payload)),
        ]
        retries = []
        progress = []

        with TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch("backend.yadisk_updates._request", side_effect=links) as request_link, \
             patch.object(urllib.request, "urlopen", side_effect=downloads) as urlopen, \
             patch("backend.yadisk_updates.time.sleep") as sleep:
            destination = Path(tmpdir) / "update.zip"
            destination.write_bytes(b"stale bytes")
            size, digest = yadisk_updates.download_artifact(
                status,
                destination,
                progress=lambda *values: progress.append(values),
                on_retry=lambda *values: retries.append(values),
                retry_delays=(0,),
            )
            downloaded = destination.read_bytes()

        self.assertEqual(size, len(payload))
        self.assertEqual(digest, status["sha256"])
        self.assertEqual(downloaded, payload)
        self.assertEqual(request_link.call_count, 2)
        self.assertEqual(
            [call.args[0].full_url for call in urlopen.call_args_list],
            ["https://download.test/first", "https://download.test/second"],
        )
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0][:3], (1, 2, 0.0))
        self.assertEqual([item[3] for item in progress if item[0] == 0], [1, 2])
        sleep.assert_called_once_with(0.0)

    def test_does_not_retry_permanent_http_error(self):
        status = {
            "path": "/photobooth_system/updates/artifacts/test-full_bundle/test-full.zip",
            "bundle_path": "/photobooth_system/updates/artifacts/test-full_bundle",
            "size": 10,
            "sha256": "a" * 64,
        }
        error = urllib.error.HTTPError(
            "https://cloud-api.yandex.net", 404, "not found", {}, None)

        with TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch("backend.yadisk_updates._request", side_effect=error) as request_link, \
             patch("backend.yadisk_updates.time.sleep") as sleep:
            destination = Path(tmpdir) / "update.zip"
            destination.write_bytes(b"stale bytes")
            with self.assertRaises(urllib.error.HTTPError):
                yadisk_updates.download_artifact(
                    status, destination, retry_delays=(0,))
            self.assertFalse(destination.exists())

        request_link.assert_called_once()
        sleep.assert_not_called()
        error.close()

    def test_transient_connection_uses_five_attempts_with_short_delays(self):
        status = {
            "path": "/photobooth_system/updates/artifacts/test-full_bundle/test-full.zip",
            "bundle_path": "/photobooth_system/updates/artifacts/test-full_bundle",
            "size": 10,
            "sha256": "a" * 64,
        }
        error = urllib.error.URLError("storage connection refused")

        with TemporaryDirectory() as tmpdir, \
             patch.dict("os.environ", {"YADISK_TOKEN": "test-token"}), \
             patch("backend.yadisk_updates._request", side_effect=error) as request_link, \
             patch("backend.yadisk_updates.time.sleep") as sleep:
            with self.assertRaises(urllib.error.URLError):
                yadisk_updates.download_artifact(status, Path(tmpdir) / "update.zip")

        self.assertEqual(request_link.call_count, 5)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [2.0, 3.0, 3.0, 3.0],
        )

    def test_formats_download_progress_for_loading_screen(self):
        self.assertEqual(
            app._format_download_progress(0, 125 * 1048576, 0, 1, 5),
            "Подключение к Яндекс Диску · попытка 1/5",
        )
        self.assertEqual(
            app._format_download_progress(
                53 * 1048576, 126 * 1048576, 4.3 * 1048576, 2, 5),
            "Скачивание 42% · 53.00/126.00 МБ · 4.30 МБ/с · попытка 2/5",
        )

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
                    "path": "/photobooth_system/updates/artifacts/full_bundle/full.zip",
                    "bundle_path": "/photobooth_system/updates/artifacts/full_bundle",
                    "size": len(payload),
                    "sha256": digest,
                }},
            }
            destinations = []
            scheduled_stages = []

            def download(_artifact, destination, **kwargs):
                self.assertTrue(callable(kwargs.get("progress")))
                self.assertTrue(callable(kwargs.get("on_retry")))
                destinations.append(destination)
                destination.write_bytes(payload)
                return len(payload), digest

            def schedule(stage, _app_dir, versions, components):
                scheduled_stages.append(stage)
                self.assertEqual((stage / "app.py").read_text(), "updated")
                self.assertEqual(versions, {"full": digest})
                self.assertEqual(components, ["full"])
                return False

            with patch.object(app, "__file__", str(fake_app)), \
                 patch.object(app, "_HASH_FILE", str(root / ".update_hash")), \
                 patch.object(app.sys, "platform", "win32"), \
                 patch.object(app.os, "getpid", return_value=4242), \
                 patch("backend.yadisk_updates.read_status", return_value=status), \
                 patch("backend.yadisk_updates.download_artifact", side_effect=download), \
                 patch.object(app, "_schedule_staged_update", side_effect=schedule):
                self.assertEqual(app._update_from_disk(), "external")

            expected_download = root.resolve() / ".update_download.4242.full.zip"
            expected_stage = root.resolve() / ".update_stage.4242"
            self.assertEqual(destinations, [expected_download])
            self.assertEqual(scheduled_stages, [expected_stage])
            self.assertFalse(destinations[0].exists())
            self.assertFalse(expected_stage.exists())

    def test_windows_downloads_only_changed_app_component(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_app = root / "app.py"
            fake_app.write_text("old", encoding="utf-8")
            (root / "config_app.json").write_text("{}", encoding="utf-8")
            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, "w") as zf:
                zf.writestr("app.py", "updated")
                zf.writestr("backend/main.py", "updated")
            payload = archive_bytes.getvalue()
            versions = {
                "full": "0" * 64,
                "app": "1" * 64,
                "assets": "7" * 64,
                "python": "2" * 64,
                "bin": "3" * 64,
                "templates": "4" * 64,
                "edsdk": "5" * 64,
                "drivers": "6" * 64,
            }
            artifacts = {
                name: {
                    "path": f"/updates/artifacts/{name}_bundle/{name}.zip",
                    "bundle_path": f"/updates/artifacts/{name}_bundle",
                    "size": len(payload) if name == "app" else 10,
                    "sha256": version,
                }
                for name, version in versions.items()
            }
            status = {
                "schema_version": 1,
                "active": "full",
                "artifacts": artifacts,
            }
            installed = versions.copy()
            installed["full"] = "a" * 64
            installed["app"] = "b" * 64
            app._write_update_versions(root / ".update_hash", installed)
            downloads = []
            schedules = []

            def download(artifact, destination, **kwargs):
                downloads.append((artifact, destination, kwargs))
                destination.write_bytes(payload)
                return len(payload), hashlib.sha256(payload).hexdigest()

            def schedule(stage, _app_dir, target, components):
                schedules.append((target, components))
                self.assertEqual((stage / "app.py").read_text(), "updated")
                return False

            with patch.object(app, "__file__", str(fake_app)), \
                 patch.object(app, "_HASH_FILE", str(root / ".update_hash")), \
                 patch.object(app.sys, "platform", "win32"), \
                 patch.object(app.os, "getpid", return_value=4242), \
                 patch("backend.yadisk_updates.read_status", return_value=status), \
                 patch("backend.yadisk_updates.download_artifact", side_effect=download), \
                 patch.object(app, "_schedule_staged_update", side_effect=schedule):
                self.assertEqual(app._update_from_disk(), "external")

            self.assertEqual(len(downloads), 1)
            self.assertIs(downloads[0][0], artifacts["app"])
            self.assertTrue(downloads[0][1].name.endswith(".app.zip"))
            self.assertFalse(downloads[0][2]["verify_sha256"])
            self.assertEqual(schedules, [(versions, ["app"])])


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

    def test_prepares_multiple_folder_archives_in_one_stage(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_archive = root / "app.zip"
            python_archive = root / "python.zip"
            stage = root / ".update_stage.4242"
            with zipfile.ZipFile(app_archive, "w") as zf:
                zf.writestr("app.py", "updated")
                zf.writestr("backend/main.py", "updated backend")
            with zipfile.ZipFile(python_archive, "w") as zf:
                zf.writestr("python/python.exe", b"runtime")

            extracted = app._prepare_update_stage(
                [("app", app_archive), ("python", python_archive)],
                stage,
            )

            self.assertEqual(extracted, 3)
            self.assertEqual((stage / "app.py").read_text(), "updated")
            self.assertEqual(
                (stage / "python" / "python.exe").read_bytes(), b"runtime",
            )

    def test_rejects_component_archive_outside_its_folder(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "python.zip"
            stage = root / ".update_stage.4242"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("app.py", "not python")

            with self.assertRaisesRegex(ValueError, "outside python"):
                app._prepare_update_stage([("python", archive)], stage)

            self.assertFalse(stage.exists())

    def test_prepares_assets_as_an_independent_folder_component(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "assets.zip"
            stage = root / ".update_stage.4242"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("assets/dots.svg", "<svg/>")

            extracted = app._prepare_update_stage(
                [("assets", archive)], stage,
            )

            self.assertEqual(extracted, 1)
            self.assertEqual(
                (stage / "assets" / "dots.svg").read_text(), "<svg/>",
            )

    def test_rejects_assets_inside_app_component(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "app.zip"
            stage = root / ".update_stage.4242"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("app.py", "updated")
                zf.writestr("assets/dots.svg", "not an app file")

            with self.assertRaisesRegex(ValueError, "overlaps component folder"):
                app._prepare_update_stage([("app", archive)], stage)

            self.assertFalse(stage.exists())


class UpdateVersionStateTests(unittest.TestCase):
    @staticmethod
    def _artifacts(**versions):
        return {
            name: {
                "path": f"/updates/artifacts/{name}_bundle/{name}.zip",
                "bundle_path": f"/updates/artifacts/{name}_bundle",
                "size": 10,
                "sha256": version,
            }
            for name, version in versions.items()
        }

    def test_hash_file_round_trips_component_json(self):
        versions = {
            "full": "0" * 64,
            "app": "1" * 64,
            "assets": "7" * 64,
            "python": "2" * 64,
            "bin": "3" * 64,
            "templates": "4" * 64,
            "edsdk": "5" * 64,
            "drivers": "6" * 64,
        }
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".update_hash"
            app._write_update_versions(path, versions)

            self.assertEqual(app._read_update_versions(path), versions)
            self.assertEqual(json.loads(path.read_text(encoding="ascii")), versions)

    def test_missing_hash_selects_full(self):
        versions = {
            "full": "0" * 64,
            "app": "1" * 64,
            "assets": "7" * 64,
            "python": "2" * 64,
            "bin": "3" * 64,
            "templates": "4" * 64,
            "edsdk": "5" * 64,
            "drivers": "6" * 64,
        }
        selected, target = app._select_update_archives(
            self._artifacts(**versions), None,
        )

        self.assertEqual(selected, ["full"])
        self.assertEqual(target, versions)

    def test_old_mapping_without_assets_selects_only_assets(self):
        target = {
            "full": "0" * 64,
            "app": "1" * 64,
            "assets": "7" * 64,
            "python": "2" * 64,
            "bin": "3" * 64,
            "templates": "4" * 64,
            "edsdk": "5" * 64,
            "drivers": "6" * 64,
        }
        installed = {
            name: version
            for name, version in target.items()
            if name != "assets"
        }

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".update_hash"
            app._write_update_versions(path, installed)
            parsed = app._read_update_versions(path)

        selected, versions = app._select_update_archives(
            self._artifacts(**target), parsed,
        )

        self.assertEqual(selected, ["assets"])
        self.assertEqual(versions, target)

    def test_empty_corrupt_or_unknown_mapping_uses_full_fallback(self):
        valid_sha = "a" * 64
        invalid_payloads = (
            "",
            "{}",
            "not json",
            json.dumps({"full": "bad"}),
            json.dumps({"full": valid_sha, "unknown": valid_sha}),
        )

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".update_hash"
            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    path.write_text(payload, encoding="utf-8")
                    self.assertIsNone(app._read_update_versions(path))

    def test_selects_only_changed_folder(self):
        target = {
            "full": "0" * 64,
            "app": "1" * 64,
            "assets": "7" * 64,
            "python": "2" * 64,
            "bin": "3" * 64,
            "templates": "4" * 64,
            "edsdk": "5" * 64,
            "drivers": "6" * 64,
        }
        installed = target.copy()
        installed["full"] = "a" * 64
        installed["app"] = "b" * 64

        selected, versions = app._select_update_archives(
            self._artifacts(**target), installed,
        )

        self.assertEqual(selected, ["app"])
        self.assertEqual(versions, target)

    def test_old_full_hash_migrates_without_download(self):
        target = {
            "full": "0" * 64,
            "app": "1" * 64,
            "assets": "7" * 64,
            "python": "2" * 64,
            "bin": "3" * 64,
            "templates": "4" * 64,
            "edsdk": "5" * 64,
            "drivers": "6" * 64,
        }

        selected, versions = app._select_update_archives(
            self._artifacts(**target), target["full"],
        )

        self.assertEqual(selected, [])
        self.assertEqual(versions, target)


class StagedUpdateSchedulingTests(unittest.TestCase):
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

            scheduled = app._schedule_staged_update(
                stage, root, {"full": "a" * 64}, ["full"],
            )

            self.assertTrue(scheduled)
            script = (root / ".update_apply.4242.ps1").read_text(encoding="utf-8")
            self.assertIn("Wait-Process -Id $ParentPid", script)
            self.assertNotIn("Expand-Archive", script)
            self.assertIn("Get-PhotoboothProcesses", script)
            self.assertIn("Install-StagedEntry", script)
            self.assertIn("Rollback-StagedEntries", script)
            self.assertNotIn("robocopy.exe", script)
            self.assertIn('Move-Item -LiteralPath $hashTempPath', script)
            self.assertIn("ConvertTo-Json -Compress", script)
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
            self.assertIn("-PlanPath", args)
            plan_path = Path(args[args.index("-PlanPath") + 1])
            plan = json.loads(plan_path.read_text(encoding="ascii"))
            self.assertEqual(plan["components"], ["full"])
            self.assertEqual(plan["versions"], {"full": "a" * 64})
            self.assertEqual(args[args.index("-Mode") + 1], "dev")
            self.assertIn("-MarkerPath", args)

    def test_existing_marker_prevents_a_second_installer(self):
        with TemporaryDirectory() as tmpdir, \
             patch("subprocess.Popen") as popen, \
             patch.object(app.os, "getpid", return_value=4242):
            root = Path(tmpdir)
            stage = root / ".update_stage.4242"
            stage.mkdir()
            (root / ".update_in_progress.json").write_text("{}", encoding="utf-8")

            self.assertFalse(app._schedule_staged_update(
                stage, root, {"full": "a" * 64}, ["full"],
            ))
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
                app._schedule_staged_update(
                    stage, root, {"full": "a" * 64}, ["full"],
                )

            self.assertFalse((root / ".update_in_progress.json").exists())
            self.assertFalse((root / ".update_apply.4242.ps1").exists())
            self.assertFalse((root / ".update_args.4242.json").exists())


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
                ".update_args.123.json",
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
