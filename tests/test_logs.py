import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import main
from backend.log import read_log_snapshot


class LogSnapshotTests(unittest.TestCase):
    def test_snapshot_of_a_small_log_is_the_whole_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "photobooth.log"
            log.write_bytes(b"first line\nsecond line\n")

            self.assertEqual(read_log_snapshot(log), b"first line\nsecond line\n")

    def test_snapshot_of_a_big_log_is_its_tail_from_a_whole_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "photobooth.log"
            log.write_bytes(b"old line\nmiddle line\nnewest line\n")

            snapshot = read_log_snapshot(log, limit=len(b"ddle line\nnewest line\n"))

        self.assertEqual(snapshot, b"newest line\n")

    def test_clear_empties_the_log_when_no_handler_has_it_open(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)):
            active = Path(tmpdir) / "photobooth.log"
            active.write_bytes(b"current history\n")

            main._clear_local_logs()

            self.assertEqual(active.read_bytes(), b"")

    def test_clear_truncates_the_open_log_stream(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)):
            active = Path(tmpdir) / "photobooth.log"
            handler = logging.FileHandler(active, encoding="utf-8")
            root = logging.getLogger()
            root.addHandler(handler)
            try:
                handler.stream.write("current history\n")
                handler.flush()

                main._clear_local_logs()
                handler.stream.write("after clear\n")
                handler.flush()

                self.assertEqual(active.read_text(encoding="utf-8"), "after clear\n")
            finally:
                root.removeHandler(handler)
                handler.close()


class LogCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_logs_embeds_the_log_in_the_response(self):
        command = {
            "command_id": "a" * 32,
            "command": "send_logs",
            "data": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)):
            (Path(tmpdir) / "photobooth.log").write_bytes(b"first\nsecond\n")

            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["document"], "first\nsecond\n")
        self.assertNotIn("artifact_path", result)


if __name__ == "__main__":
    unittest.main()
