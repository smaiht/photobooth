import json
import unittest
from unittest.mock import AsyncMock, patch

from backend import main, yadisk_control


class CommandValidationTests(unittest.TestCase):
    def test_validates_command_id_and_filename(self):
        command_id = "a" * 32
        command = yadisk_control.validate_command({
            "schema_version": 1,
            "command_id": command_id,
            "command": "set_event",
            "data": {"name": "Свадьба Ивановых 2026"},
            "reply_chat_id": 123,
        }, f"{command_id}.json")
        self.assertEqual(command["command"], "set_event")

        with self.assertRaisesRegex(ValueError, "filename"):
            yadisk_control.validate_command(command, f"{'b' * 32}.json")


class CommandProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_response_and_moves_done_before_restart(self):
        command_id = "a" * 32
        body = json.dumps({
            "schema_version": 1,
            "command_id": command_id,
            "command": "restart",
            "data": None,
            "reply_chat_id": 123,
        }).encode()
        calls = []

        async def handler(command):
            calls.append("handler")

            async def restart():
                calls.append("restart")

            return {"status": "ok", "message": "ok", "_post_action": restart}

        async def upload(payload, path):
            calls.append("response")
            self.assertEqual(json.loads(payload)["command_id"], command_id)

        async def move(filename):
            calls.append("done")
            return True

        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/commands/inbox/{command_id}.json",
        }
        with patch("backend.yadisk_control._download_bytes", AsyncMock(return_value=body)), \
             patch("backend.yadisk_control._upload_bytes", side_effect=upload), \
             patch("backend.yadisk_control._move_done", side_effect=move):
            self.assertTrue(await yadisk_control._process_command(item, handler))
            await __import__("asyncio").sleep(0)

        self.assertEqual(calls, ["handler", "response", "done", "restart"])


class EventCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_switches_event_and_persists_config(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_event",
            "data": {"name": "Свадьба Ивановых 2026"},
        }
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch("backend.main.yadisk_cloud.set_event_folder", AsyncMock()), \
             patch("backend.main._save_event_folder") as save:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["event_folder"], "Свадьба Ивановых 2026")
        save.assert_called_once_with("Свадьба Ивановых 2026")

    async def test_restart_is_rejected_during_session(self):
        command = {
            "command_id": "a" * 32,
            "command": "restart",
            "data": None,
        }
        with patch.object(main, "STATE", "countdown"):
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "error")
        self.assertNotIn("_post_action", result)


if __name__ == "__main__":
    unittest.main()
