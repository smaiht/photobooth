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

    def test_clear_removes_active_history_and_all_backups(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)):
            active = Path(tmpdir) / "photobooth.log"
            backup = Path(tmpdir) / "photobooth.log.1"
            legacy_backup = Path(tmpdir) / "photobooth.log.2"
            backup.write_bytes(b"old backup\n")
            legacy_backup.write_bytes(b"even older backup\n")
            active.write_bytes(b"current history\n")

            main._clear_local_logs()

            self.assertEqual(active.read_bytes(), b"")
            self.assertFalse(backup.exists())
            self.assertFalse(legacy_backup.exists())

    def test_clear_truncates_the_open_rotating_log_stream(self):
        import logging
        from logging.handlers import RotatingFileHandler

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)):
            active = Path(tmpdir) / "photobooth.log"
            backup = Path(tmpdir) / "photobooth.log.1"
            handler = RotatingFileHandler(
                active, encoding="utf-8", maxBytes=200_000, backupCount=1)
            root = logging.getLogger()
            root.addHandler(handler)
            try:
                handler.stream.write("current history\n")
                handler.flush()
                backup.write_text("old backup\n", encoding="utf-8")

                main._clear_local_logs()
                handler.stream.write("after clear\n")
                handler.flush()

                self.assertEqual(active.read_text(encoding="utf-8"), "after clear\n")
                self.assertFalse(backup.exists())
            finally:
                root.removeHandler(handler)
                handler.close()


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
