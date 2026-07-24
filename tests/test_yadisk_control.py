import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend import main, yadisk_control
from backend.config import update_camera_config_field


class CommandValidationTests(unittest.TestCase):
    def test_poll_interval_is_ten_seconds(self):
        self.assertEqual(yadisk_control.POLL_INTERVAL, 10)

    def test_validates_command_id_and_filename(self):
        command_id = "a" * 32
        command = yadisk_control.validate_command({
            "schema_version": 2,
            "message_type": "command",
            "command_id": command_id,
            "command": "set_event",
            "data": {"name": "Свадьба Ивановых 2026"},
            "reply_chat_id": 123,
        }, f"{command_id}.json")
        self.assertEqual(command["command"], "set_event")

        with self.assertRaisesRegex(ValueError, "filename"):
            yadisk_control.validate_command(command, f"{'b' * 32}.json")


class CommandProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def test_uploads_config_export_to_command_specific_path(self):
        command_id = "a" * 32
        with patch(
            "backend.yadisk_control._connect",
            AsyncMock(return_value=True),
        ), patch.object(
            yadisk_control,
            "_root",
            "/control",
        ), patch(
            "backend.yadisk_control._upload_bytes",
            new_callable=AsyncMock,
        ) as upload:
            remote_path = await yadisk_control.upload_config_export(
                command_id, b"configs")

        self.assertEqual(remote_path, f"/control/configs/{command_id}.txt")
        upload.assert_awaited_once_with(b"configs", remote_path)

    async def test_writes_response_and_moves_done_before_restart(self):
        command_id = "a" * 32
        body = json.dumps({
            "schema_version": 2,
            "message_type": "command",
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
            response = json.loads(payload)
            self.assertEqual(response["command_id"], command_id)
            self.assertEqual(response["message_type"], "command_response")
            self.assertEqual(path, f"/control/to_vps/response_{command_id}.json")

        async def move(filename):
            calls.append("done")
            return True

        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        with patch.object(yadisk_control, "_root", "/control"), \
             patch("backend.yadisk_control._download_bytes", AsyncMock(return_value=body)), \
             patch("backend.yadisk_control._upload_bytes", side_effect=upload), \
             patch("backend.yadisk_control._move_done", side_effect=move):
            self.assertTrue(await yadisk_control._process_command(item, handler))
            await __import__("asyncio").sleep(0)

        self.assertEqual(calls, ["handler", "response", "done", "restart"])

    async def test_transient_download_failure_keeps_command_for_retry(self):
        command_id = "b" * 32
        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        handler = AsyncMock()
        with patch(
            "backend.yadisk_control._download_bytes",
            AsyncMock(side_effect=OSError("network unavailable")),
        ), patch(
            "backend.yadisk_control._move_done", AsyncMock()
        ) as move_done:
            self.assertFalse(
                await yadisk_control._process_command(item, handler))

        handler.assert_not_awaited()
        move_done.assert_not_awaited()

    async def test_downloaded_invalid_json_is_archived(self):
        command_id = "c" * 32
        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        with patch(
            "backend.yadisk_control._download_bytes",
            AsyncMock(return_value=b"not-json"),
        ), patch(
            "backend.yadisk_control._move_done",
            AsyncMock(return_value=True),
        ) as move_done:
            self.assertTrue(await yadisk_control._process_command(
                item, AsyncMock()))

        move_done.assert_awaited_once_with(item["name"])


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

    async def test_camera_config_change_restarts_only_after_success(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_camera_config",
            "data": {"field": "iso", "value": "200"},
        }
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch("backend.main.update_camera_config_field",
                   return_value=("iso", 100, 200, True)) as update:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertIn("100 → 200", result["message"])
        self.assertIs(result["_post_action"], main._do_restart)
        update.assert_called_once_with("iso", "200")

    async def test_camera_config_change_is_rejected_during_session(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_camera_config",
            "data": {"field": "iso", "value": "200"},
        }
        with patch.object(main, "STATE", "countdown"), \
             patch("backend.main.update_camera_config_field") as update:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "error")
        self.assertNotIn("_post_action", result)
        update.assert_not_called()

    async def test_camera_config_retry_restarts_when_value_is_already_saved(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_camera_config",
            "data": {"field": "iso", "value": "200"},
        }
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch("backend.main.update_camera_config_field",
                   return_value=("iso", 200, 200, False)):
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertIn("уже равен 200", result["message"])
        self.assertIs(result["_post_action"], main._do_restart)

    async def test_get_config_uploads_one_text_export(self):
        command = {
            "command_id": "a" * 32,
            "command": "get_config",
            "data": None,
        }
        artifact_path = f"/control/configs/{'a' * 32}.txt"
        with patch(
            "backend.main._build_config_export",
            return_value=b"config export",
        ), patch(
            "backend.main.yadisk_control.upload_config_export",
            AsyncMock(return_value=artifact_path),
        ) as upload:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["artifact_path"], artifact_path)
        upload.assert_awaited_once_with("a" * 32, b"config export")

    async def test_backend_shutdown_closes_camera_and_http_sessions_once(self):
        camera = MagicMock()
        with patch.object(main, "camera", camera), \
             patch.object(main, "_service_tasks", set()), \
             patch.object(main, "_background_uploads", set()), \
             patch.object(main, "_services_stopping", False), \
             patch.object(main.video_recorder, "abort") as abort, \
             patch("backend.main.yadisk_control.control_close",
                   AsyncMock()) as control_close, \
             patch("backend.main.yadisk_cloud.yadisk_close",
                   AsyncMock()) as cloud_close:
            await main._shutdown_services()
            await main._shutdown_services()

        camera.stop.assert_called_once_with()
        abort.assert_called_once_with()
        control_close.assert_awaited_once_with()
        cloud_close.assert_awaited_once_with()


class CameraConfigValueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temporary.name) / "config_camera.json"
        self.config_path.write_text(json.dumps({
            "iso": 100,
            "_iso_options": [100, 200, "auto"],
            "white_balance": "auto",
            "_white_balance_options": ["auto", "daylight"],
            "continuous_af": True,
            "focus_delay": 0.4,
            "av": "5.6",
            "_comment": "service",
        }), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def _read(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def test_uses_option_types_including_mixed_iso(self):
        result = update_camera_config_field(
            "iso", "AUTO", self.config_path)
        self.assertEqual(result, ("iso", 100, "auto", True))
        self.assertEqual(self._read()["iso"], "auto")

        result = update_camera_config_field(
            "iso", "200", self.config_path)
        self.assertEqual(result, ("iso", "auto", 200, True))
        self.assertIs(type(self._read()["iso"]), int)

    def test_coerces_bool_float_and_string_from_current_type(self):
        update_camera_config_field(
            "continuous_af", "false", self.config_path)
        update_camera_config_field(
            "focus_delay", "0.75", self.config_path)
        update_camera_config_field("av", "6.3", self.config_path)
        config = self._read()
        self.assertIs(config["continuous_af"], False)
        self.assertEqual(config["focus_delay"], 0.75)
        self.assertEqual(config["av"], "6.3")

    def test_rejects_unknown_service_and_invalid_option_without_writing(self):
        before = self.config_path.read_bytes()
        for field, value, message in (
            ("unknown", "1", "неизвестный"),
            ("_comment", "changed", "служебные"),
            ("white_balance", "invalid", "доступно"),
            ("focus_delay", "nan", "конечным"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError, message):
                update_camera_config_field(field, value, self.config_path)
            self.assertEqual(self.config_path.read_bytes(), before)

    def test_same_typed_value_does_not_rewrite_file(self):
        before = self.config_path.read_bytes()
        result = update_camera_config_field("iso", "100", self.config_path)
        self.assertEqual(result, ("iso", 100, 100, False))
        self.assertEqual(self.config_path.read_bytes(), before)


class ConfigExportTests(unittest.TestCase):
    def test_text_export_contains_both_original_json_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_payload = b'{\n  "event": "test"\n}\n'
            camera_payload = b'{\n  "iso": 200\n}\n'
            (root / "config_app.json").write_bytes(app_payload)
            (root / "config_camera.json").write_bytes(camera_payload)

            payload = main._build_config_export(root)

        self.assertEqual(
            payload,
            b"===== config_app.json =====\n" + app_payload + b"\n"
            b"===== config_camera.json =====\n" + camera_payload + b"\n",
        )


if __name__ == "__main__":
    unittest.main()
