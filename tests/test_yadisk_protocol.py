import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from backend.yadisk_cloud import (
    _copy_path,
    _migrate_queue_jobs,
    _upload_job,
    build_session_job,
    prepare_session_share,
    sessions_root,
)


class SessionJobTests(unittest.TestCase):
    def test_builds_originals_and_video_without_print_file(self):
        photos = [rf"C:\photos\IMG_{index:04d}.JPG" for index in range(1, 5)]
        job = build_session_job(
            "abc123def456",
            photos,
            r"C:\photos\session.mp4",
            datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
            "/event_2026",
        )

        self.assertIn("abc123def456", job["manifest_name"])
        self.assertEqual(job["schema_version"], 2)
        self.assertEqual(job["event_folder"], "/event_2026")
        self.assertEqual(
            [entry["kind"] for entry in job["files"]],
            ["photo", "photo", "photo", "photo", "video"],
        )
        self.assertEqual(
            [entry["session_name"] for entry in job["files"]],
            ["photo_01.jpg", "photo_02.jpg", "photo_03.jpg", "photo_04.jpg", "video.mp4"],
        )
        self.assertNotIn("print", json.dumps(job).lower())

    def test_session_collection_is_a_sibling_of_event(self):
        self.assertEqual(sessions_root("/wedding"), "/wedding_by_sessions")
        self.assertEqual(
            sessions_root("/events/wedding"),
            "/events/wedding_by_sessions",
        )

    def test_rejects_invalid_or_empty_sessions(self):
        with self.assertRaises(ValueError):
            build_session_job("bad/session", ["photo.jpg"], None)
        with self.assertRaises(ValueError):
            build_session_job("abc123", [], None)

    def test_legacy_queue_migration_drops_print_but_keeps_media(self):
        legacy = [{
            "schema_version": 2,
            "session_id": "abc123",
            "created_at": "2026-07-17T12:00:00+00:00",
            "event_folder": "/event",
            "manifest_name": "20260717_150000_abc123.json",
            "public_url": "https://disk.yandex.ru/d/old-layout",
            "files": [
                {"local_path": "/tmp/one.JPG", "name": "one.jpg", "kind": "photo", "index": 1, "session_uploaded": True},
                {"local_path": "/tmp/print_grid.jpg", "name": "print.jpg", "kind": "print"},
                {"local_path": "/tmp/movie.MP4", "name": "movie.mp4", "kind": "video"},
            ],
        }]

        migrated, changed = _migrate_queue_jobs(legacy)

        self.assertTrue(changed)
        self.assertEqual([entry["kind"] for entry in migrated[0]["files"]], ["photo", "video"])
        self.assertEqual(
            [entry["session_name"] for entry in migrated[0]["files"]],
            ["photo_01.jpg", "video.mp4"],
        )
        self.assertIn("abc123", migrated[0]["session_folder_name"])
        self.assertNotIn("public_url", migrated[0])
        self.assertNotIn("session_uploaded", migrated[0]["files"][0])


class UploadOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_session_folder_can_be_published_before_media(self):
        calls = []

        async def ensure(path):
            calls.append(("mkdir", path))
            return True

        async def publish(path):
            calls.append(("publish", path))
            return "https://disk.yandex.ru/d/link"

        async def notify(session_id, url):
            calls.append(("qr", session_id, url))

        with patch("backend.yadisk_cloud._connect", AsyncMock(return_value=True)), \
             patch("backend.yadisk_cloud._ensure_directory", side_effect=ensure), \
             patch("backend.yadisk_cloud._publish_directory", side_effect=publish), \
             patch("backend.yadisk_cloud._notify_session_link", side_effect=notify), \
             patch("backend.yadisk_cloud._prepared_links", {}):
            url = await prepare_session_share(
                "abc123",
                datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
                event_folder="event",
                session_folder="session-folder",
            )

        self.assertEqual(url, "https://disk.yandex.ru/d/link")
        self.assertEqual(
            calls,
            [
                ("mkdir", "/event_by_sessions/session-folder"),
                ("publish", "/event_by_sessions/session-folder"),
                ("qr", "abc123", "https://disk.yandex.ru/d/link"),
            ],
        )

    async def test_upload_then_fallback_publish_then_copy_then_manifest(self):
        with TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first.jpg"
            second = Path(tmpdir) / "video.mp4"
            first.write_bytes(b"photo")
            second.write_bytes(b"video")
            job = build_session_job(
                "abc123",
                [str(first)],
                str(second),
                event_folder="/event",
                session_folder="session-folder",
            )
            calls = []

            async def upload_path(local_path, remote_path):
                calls.append(("upload", remote_path))
                return True, {"size": local_path.stat().st_size}

            async def publish(path):
                calls.append(("publish", path))
                return "https://disk.yandex.ru/d/link"

            async def notify(session_id, url):
                calls.append(("qr", session_id, url))

            async def copy_path(source_path, destination_path):
                calls.append(("copy", source_path, destination_path))
                return True

            async def upload_bytes(data, remote_path):
                calls.append(("manifest", remote_path, json.loads(data)))
                return True

            with patch("backend.yadisk_cloud._ensure_directory", AsyncMock(return_value=True)), \
                 patch("backend.yadisk_cloud._publish_directory", side_effect=publish), \
                 patch("backend.yadisk_cloud._notify_session_link", side_effect=notify), \
                 patch("backend.yadisk_cloud._upload_path", side_effect=upload_path), \
                 patch("backend.yadisk_cloud._copy_path", side_effect=copy_path), \
                 patch("backend.yadisk_cloud._upload_bytes", side_effect=upload_bytes), \
                 patch("backend.yadisk_cloud._bus_root", "/photobooth_system/control"):
                self.assertTrue(await _upload_job(job))

            self.assertEqual(
                [call[0] for call in calls],
                ["upload", "upload", "publish", "qr", "copy", "copy", "manifest"],
            )
            session_path = "/event_by_sessions/session-folder"
            self.assertEqual(calls[0][1], f"{session_path}/photo_01.jpg")
            self.assertEqual(calls[1][1], f"{session_path}/video.mp4")
            self.assertEqual(calls[2][1], session_path)
            self.assertEqual(calls[3][1:], ("abc123", "https://disk.yandex.ru/d/link"))
            self.assertEqual(calls[4][1], calls[0][1])
            self.assertTrue(calls[4][2].startswith("/event/202"))
            self.assertIn("/to_vps/session_", calls[-1][1])
            manifest = calls[-1][2]
            self.assertEqual(manifest["message_type"], "session_ready")
            self.assertEqual(manifest["event_folder"], "event")
            self.assertEqual([entry["kind"] for entry in manifest["files"]], ["photo", "video"])
            self.assertTrue(all("session_name" not in entry for entry in manifest["files"]))
            self.assertTrue(all("md5" not in entry for entry in manifest["files"]))

    async def test_retry_skips_already_uploaded_session_file_by_size(self):
        with TemporaryDirectory() as tmpdir:
            photo = Path(tmpdir) / "first.jpg"
            photo.write_bytes(b"photo")
            job = build_session_job(
                "abc123", [str(photo)], None,
                event_folder="/event", session_folder="session-folder",
            )
            job["files"][0].update({"size": 5, "session_uploaded": True})

            with patch("backend.yadisk_cloud._ensure_directory", AsyncMock(return_value=True)), \
                 patch("backend.yadisk_cloud._resource_size_matches", AsyncMock(return_value=True)), \
                 patch("backend.yadisk_cloud._upload_path", new_callable=AsyncMock) as upload, \
                 patch("backend.yadisk_cloud._publish_directory", AsyncMock(return_value="https://disk.yandex.ru/d/link")), \
                 patch("backend.yadisk_cloud._notify_session_link", new_callable=AsyncMock), \
                 patch("backend.yadisk_cloud._copy_path", AsyncMock(return_value=True)), \
                 patch("backend.yadisk_cloud._upload_bytes", AsyncMock(return_value=True)), \
                 patch("backend.yadisk_cloud._bus_root", "/photobooth_system/control"):
                self.assertTrue(await _upload_job(job))

            upload.assert_not_awaited()

    async def test_server_side_copy_does_not_read_size_or_md5(self):
        class Response:
            status = 201

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        class Session:
            def post(self, *_args, **_kwargs):
                return Response()

        with patch("backend.yadisk_cloud._session", Session()), \
             patch("backend.yadisk_cloud._resource_size_matches", new_callable=AsyncMock) as metadata_read:
            self.assertTrue(await _copy_path("/session/photo.jpg", "/event/photo.jpg"))

        metadata_read.assert_not_awaited()


class FrontendProtocolTests(unittest.TestCase):
    def test_frontend_uses_direct_session_link_not_vps_redirect(self):
        root = Path(__file__).resolve().parent.parent
        backend_source = (root / "backend" / "main.py").read_text(encoding="utf-8")
        frontend_source = (root / "frontend" / "app.js").read_text(encoding="utf-8")
        frontend_html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
        config = json.loads((root / "config_app.json").read_text(encoding="utf-8"))

        self.assertNotIn("VPS_URL", backend_source)
        self.assertNotIn("VPS_SESSION_PATH", backend_source)
        self.assertNotIn("session_url", backend_source)
        self.assertIn('"type": "session_link"', backend_source)
        self.assertIn('case "session_link"', frontend_source)
        self.assertIn('new Set(["composing", "printing", "done", "idle"])', frontend_source)
        self.assertIn("Фото с последней съёмки загружаются сюда", frontend_source)
        self.assertIn("dismissedQrSessionId === currentSessionId", frontend_source)
        self.assertIn('id="qr-modal-close"', frontend_html)
        self.assertTrue(config["show_qr"])


if __name__ == "__main__":
    unittest.main()
