import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from backend.yadisk_cloud import _upload_job, build_session_job


class SessionJobTests(unittest.TestCase):
    def test_builds_stable_full_session_names(self):
        job = build_session_job(
            "abc123def456",
            [r"C:\photos\IMG_0001.JPG", r"C:\photos\IMG_0002.JPG"],
            r"C:\photos\print.jpg",
            r"C:\photos\session.mp4",
            datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc),
            "/event_2026",
        )

        self.assertIn("abc123def456", job["manifest_name"])
        self.assertEqual(job["schema_version"], 2)
        self.assertEqual(job["event_folder"], "/event_2026")
        self.assertEqual(
            [entry["kind"] for entry in job["files"]],
            ["photo", "photo", "print", "video"],
        )
        self.assertEqual(len({entry["name"] for entry in job["files"]}), 4)

    def test_rejects_invalid_or_empty_sessions(self):
        with self.assertRaises(ValueError):
            build_session_job("bad/session", ["photo.jpg"], None, None)
        with self.assertRaises(ValueError):
            build_session_job("abc123", [], None, None)


class UploadOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_manifest_is_uploaded_after_every_media_file(self):
        with TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first.jpg"
            second = Path(tmpdir) / "video.mp4"
            first.write_bytes(b"photo")
            second.write_bytes(b"video")
            job = build_session_job(
                "abc123", [str(first)], None, str(second),
                event_folder="/event",
            )
            calls = []

            async def upload_path(local_path, remote_path):
                calls.append(("media", remote_path))
                return True, {"size": local_path.stat().st_size, "md5": "0" * 32}

            async def upload_bytes(data, remote_path):
                calls.append(("manifest", remote_path, json.loads(data)))
                return True

            with patch("backend.yadisk_cloud._ensure_directory", AsyncMock(return_value=True)), \
                 patch("backend.yadisk_cloud._upload_path", side_effect=upload_path), \
                 patch("backend.yadisk_cloud._upload_bytes", side_effect=upload_bytes), \
                 patch("backend.yadisk_cloud._bus_root", "/photobooth_system/control"):
                self.assertTrue(await _upload_job(job))

            self.assertEqual([call[0] for call in calls], ["media", "media", "manifest"])
            self.assertIn("/to_vps/session_", calls[-1][1])
            self.assertEqual(calls[-1][2]["message_type"], "session_ready")
            self.assertEqual(calls[-1][2]["event_folder"], "event")


if __name__ == "__main__":
    unittest.main()
