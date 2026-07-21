import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend import main
from backend.log import LOG_BACKUP_COUNT, LOG_MAX_BYTES, read_log_snapshot


class LogSnapshotTests(unittest.TestCase):
    def test_log_rotation_keeps_two_200kb_segments(self):
        self.assertEqual(LOG_MAX_BYTES, 200_000)
        self.assertEqual(LOG_BACKUP_COUNT, 1)

    def test_snapshot_combines_backup_then_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            active = Path(tmpdir) / "photobooth.log"
            backup = Path(tmpdir) / "photobooth.log.1"
            backup.write_bytes(b"oldest line\nolder line")
            active.write_bytes(b"current line\n")

            snapshot = read_log_snapshot(active)

        self.assertEqual(
            snapshot,
            b"oldest line\nolder line\ncurrent line\n",
        )

    def test_clear_replaces_old_backup_with_current_log(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)):
            active = Path(tmpdir) / "photobooth.log"
            backup = Path(tmpdir) / "photobooth.log.1"
            backup.write_bytes(b"old backup\n")
            active.write_bytes(b"current history\n")

            main._clear_local_logs()

            self.assertEqual(active.read_bytes(), b"")
            self.assertEqual(backup.read_bytes(), b"current history\n")


class LogCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_logs_uploads_one_chronological_file(self):
        command_id = "a" * 32
        command = {
            "command_id": command_id,
            "command": "send_logs",
            "data": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch("backend.main.yadisk_control.upload_log", new_callable=AsyncMock,
                   return_value=f"/control/logs/{command_id}.log") as upload:
            active = Path(tmpdir) / "photobooth.log"
            backup = Path(tmpdir) / "photobooth.log.1"
            backup.write_bytes(b"old\n")
            active.write_bytes(b"new\n")

            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        upload.assert_awaited_once_with(command_id, b"old\nnew\n")


if __name__ == "__main__":
    unittest.main()
