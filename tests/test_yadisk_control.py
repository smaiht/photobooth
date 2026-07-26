import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect

from backend import config as backend_config
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

    async def test_writes_response_and_deletes_command_before_restart(self):
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

        async def delete(filename):
            calls.append("delete")
            return True

        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        with patch.object(yadisk_control, "_root", "/control"), \
             patch("backend.yadisk_control._download_bytes", AsyncMock(return_value=body)), \
             patch("backend.yadisk_control._upload_bytes", side_effect=upload), \
             patch("backend.yadisk_control._delete_command", side_effect=delete):
            self.assertTrue(await yadisk_control._process_command(item, handler))
            await __import__("asyncio").sleep(0)

        self.assertEqual(calls, ["handler", "response", "delete", "restart"])

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
            "backend.yadisk_control._delete_command", AsyncMock()
        ) as delete_command:
            self.assertFalse(
                await yadisk_control._process_command(item, handler))

        handler.assert_not_awaited()
        delete_command.assert_not_awaited()

    async def test_downloaded_invalid_json_is_deleted(self):
        command_id = "c" * 32
        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        with patch(
            "backend.yadisk_control._download_bytes",
            AsyncMock(return_value=b"not-json"),
        ), patch(
            "backend.yadisk_control._delete_command",
            AsyncMock(return_value=True),
        ) as delete_command:
            self.assertTrue(await yadisk_control._process_command(
                item, AsyncMock()))

        delete_command.assert_awaited_once_with(item["name"])


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


class CafeUnlockTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_and_invalid_persistent_state_fail_closed(self):
        invalid_payloads = (
            "not-json",
            json.dumps({}),
            json.dumps({"remaining_sessions": True}),
            json.dumps({"remaining_sessions": -1}),
            json.dumps({"remaining_sessions": 1001}),
        )
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)):
            state_path = Path(tmpdir) / "cafe_unlock_state.json"
            self.assertEqual(main._load_cafe_unlock_sessions(), 0)
            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    state_path.write_text(payload, encoding="utf-8")
                    self.assertEqual(main._load_cafe_unlock_sessions(), 0)

    async def test_state_payload_locks_only_exact_technical_event(self):
        config = {
            "technical_event_name": "Кафе",
            "yadisk_folder": "Кафе",
        }
        with patch.object(main, "CONFIG", config), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 0), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"):
            locked = main._state_message("idle")
        with patch.object(main, "CONFIG", config), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 0), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="кафе"):
            other_case = main._state_message("idle")
        with patch.object(main, "CONFIG", config), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 2), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"):
            unlocked = main._state_message("idle")

        self.assertTrue(locked["start_locked"])
        self.assertEqual(locked["unlock_sessions_remaining"], 0)
        self.assertFalse(other_case["start_locked"])
        self.assertFalse(unlocked["start_locked"])
        self.assertEqual(unlocked["unlock_sessions_remaining"], 2)

    async def test_technical_event_name_falls_back_to_cafe(self):
        with patch.object(main, "CONFIG", {"yadisk_folder": "Кафе"}), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 0), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"):
            self.assertEqual(main._technical_event_name(), "Кафе")
            self.assertTrue(main._start_locked())

    async def test_unblock_persists_allowance_and_rebroadcasts_idle(self):
        command = {
            "command_id": "a" * 32,
            "command": "unblock",
            "data": {"sessions": 3},
        }
        config = {
            "technical_event_name": "Кафе",
            "yadisk_folder": "Кафе",
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "CONFIG", config), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 9), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"), \
             patch("backend.main.broadcast", new_callable=AsyncMock) as broadcast:
            result = await main.handle_disk_command(command)
            persisted = json.loads(
                (Path(tmpdir) / "cafe_unlock_state.json").read_text(encoding="utf-8"))
            temporary_exists = (
                Path(tmpdir) / "cafe_unlock_state.json.tmp").exists()

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["start_locked"])
        self.assertEqual(result["unlock_sessions_remaining"], 3)
        self.assertEqual(persisted, {"remaining_sessions": 3})
        self.assertFalse(temporary_exists)
        broadcast.assert_awaited_once()
        state_payload = broadcast.await_args.args[0]
        self.assertFalse(state_payload["start_locked"])
        self.assertEqual(state_payload["unlock_sessions_remaining"], 3)

    async def test_unblock_rejects_non_integer_or_out_of_range_sessions(self):
        invalid_values = (None, True, 1.5, "2", -1, 1001)
        with patch("backend.main._set_cafe_unlock_sessions") as save:
            for sessions in invalid_values:
                with self.subTest(sessions=sessions):
                    result = await main.handle_disk_command({
                        "command_id": "a" * 32,
                        "command": "unblock",
                        "data": {"sessions": sessions},
                    })
                    self.assertEqual(result["status"], "error")
        save.assert_not_called()

    async def test_zero_allowance_relocks_idle_immediately(self):
        command = {
            "command_id": "a" * 32,
            "command": "unblock",
            "data": {"sessions": 0},
        }
        config = {
            "technical_event_name": "Кафе",
            "yadisk_folder": "Кафе",
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "CONFIG", config), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 5), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"), \
             patch("backend.main.broadcast", new_callable=AsyncMock) as broadcast:
            result = await main.handle_disk_command(command)
            persisted = json.loads(
                (Path(tmpdir) / "cafe_unlock_state.json").read_text(
                    encoding="utf-8"))

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["start_locked"])
        self.assertEqual(result["unlock_sessions_remaining"], 0)
        self.assertEqual(persisted, {"remaining_sessions": 0})
        self.assertTrue(broadcast.await_args.args[0]["start_locked"])

    async def test_remote_run_is_blocked_before_camera_checks(self):
        config = {
            "technical_event_name": "Кафе",
            "yadisk_folder": "Кафе",
        }
        with patch.object(main, "CONFIG", config), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 0), \
             patch.object(main, "camera", None), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"):
            result = await main.handle_disk_command({
                "command_id": "a" * 32,
                "command": "run",
                "data": None,
            })

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["start_locked"])
        self.assertNotIn("_post_action", result)

    async def test_run_session_has_a_final_central_lock_guard(self):
        with patch.object(main, "_session_running", False), \
             patch("backend.main._start_locked", return_value=True), \
             patch("backend.main._run_session", new_callable=AsyncMock) as run, \
             patch("backend.main.broadcast", new_callable=AsyncMock) as broadcast:
            await main.run_session()

        run.assert_not_awaited()
        broadcast.assert_awaited_once()

    async def test_websocket_start_is_blocked_without_scheduling_session(self):
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "start_session"}),
            WebSocketDisconnect(),
        ])
        config = {
            "technical_event_name": "Кафе",
            "yadisk_folder": "Кафе",
        }
        camera = MagicMock()
        camera.is_connected = True
        with patch.object(main, "CONFIG", config), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "CLIENTS", []), \
             patch.object(main, "camera", camera), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 0), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"), \
             patch("backend.main.run_session", new_callable=AsyncMock) as run:
            await main.websocket_endpoint(ws)

        run.assert_not_called()
        self.assertEqual(ws.send_text.await_count, 2)
        blocked_payload = json.loads(ws.send_text.await_args_list[-1].args[0])
        self.assertTrue(blocked_payload["start_locked"])

    async def test_allowance_is_consumed_after_print_enqueue_before_done(self):
        order = []

        async def enqueue(*_args):
            order.append("print")

        def require(_generation):
            order.append("camera")

        def consume():
            order.append("consume")

        async def state(value):
            self.assertEqual(value, "done")
            order.append("done")

        with patch.object(main, "CONFIG", {"print_enabled": True}), \
             patch("backend.printer.enqueue_print", side_effect=enqueue), \
             patch("backend.main._require_session_camera", side_effect=require), \
             patch("backend.main._consume_cafe_unlock_session",
                   side_effect=consume), \
             patch("backend.main.set_state", side_effect=state):
            await main._finish_successful_session(
                Path("print.jpg"), "grid", 7, True)

        self.assertEqual(order, ["print", "camera", "consume", "done"])

    async def test_print_enqueue_error_does_not_consume_allowance(self):
        with patch.object(main, "CONFIG", {"print_enabled": True}), \
             patch("backend.printer.enqueue_print", new_callable=AsyncMock,
                   side_effect=RuntimeError("printer unavailable")), \
             patch("backend.main._consume_cafe_unlock_session") as consume, \
             patch("backend.main.set_state", new_callable=AsyncMock) as state:
            with self.assertRaisesRegex(RuntimeError, "printer unavailable"):
                await main._finish_successful_session(
                    Path("print.jpg"), "grid", 7, True)

        consume.assert_not_called()
        state.assert_not_awaited()

    async def test_consumption_persists_exactly_one_session(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 2):
            remaining = main._consume_cafe_unlock_session()
            persisted = json.loads(
                (Path(tmpdir) / "cafe_unlock_state.json").read_text(encoding="utf-8"))

        self.assertEqual(remaining, 1)
        self.assertEqual(persisted, {"remaining_sessions": 1})

    async def test_failed_consumption_removes_stale_positive_allowance(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 2), \
             patch("backend.main._write_cafe_unlock_sessions",
                   side_effect=OSError("disk full")):
            state_path = Path(tmpdir) / "cafe_unlock_state.json"
            state_path.write_text(
                json.dumps({"remaining_sessions": 2}), encoding="utf-8")
            remaining = main._consume_cafe_unlock_session()
            state_exists = state_path.exists()
            in_memory_remaining = main._cafe_unlock_sessions_remaining

        self.assertEqual(remaining, 0)
        self.assertEqual(in_memory_remaining, 0)
        self.assertFalse(state_exists)

    async def test_status_reports_lock_and_remaining_sessions(self):
        config = {
            "technical_event_name": "Кафе",
            "yadisk_folder": "Кафе",
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "CONFIG", config), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "camera", None), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 0), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"), \
             patch("backend.main.yadisk_cloud.pending_count", return_value=0):
            result = await main.handle_disk_command({
                "command_id": "a" * 32,
                "command": "status",
                "data": None,
            })

        self.assertTrue(result["start_locked"])
        self.assertEqual(result["unlock_sessions_remaining"], 0)
        self.assertIn("Start locked: yes", result["message"])
        self.assertIn("Unlock sessions remaining: 0", result["message"])

    async def test_set_event_rebroadcasts_idle_lock_state(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_event",
            "data": {"name": "Кафе"},
        }
        config = {
            "technical_event_name": "Кафе",
            "yadisk_folder": "old_event",
        }
        with patch.object(main, "CONFIG", config), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch.object(main, "_cafe_unlock_sessions_remaining", 0), \
             patch("backend.main.yadisk_cloud.set_event_folder",
                   new_callable=AsyncMock), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"), \
             patch("backend.main._save_event_folder"), \
             patch("backend.main.broadcast", new_callable=AsyncMock) as broadcast:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        broadcast.assert_awaited_once()
        self.assertTrue(broadcast.await_args.args[0]["start_locked"])


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


class EventConfigEncodingTests(unittest.TestCase):
    def test_event_config_is_always_read_as_utf8(self):
        payload = json.dumps(
            {"yadisk_folder": "Кафе"}, ensure_ascii=False,
        ).encode("utf-8")
        self.assertNotEqual(
            json.loads(payload.decode("cp1252"))["yadisk_folder"],
            "Кафе",
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            backend_config, "ROOT_DIR", Path(tmpdir),
        ):
            (Path(tmpdir) / "config_app.json").write_bytes(payload)
            config = backend_config.load_event_config()

        self.assertEqual(config["yadisk_folder"], "Кафе")


class ConfigExportTests(unittest.TestCase):
    def test_text_export_starts_with_cafe_state_then_both_configs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_payload = b'{\n    "remaining_sessions": 5\n}\n'
            app_payload = b'{\n  "event": "test"\n}\n'
            camera_payload = b'{\n  "iso": 200\n}\n'
            (root / "cafe_unlock_state.json").write_bytes(state_payload)
            (root / "config_app.json").write_bytes(app_payload)
            (root / "config_camera.json").write_bytes(camera_payload)

            payload = main._build_config_export(root)

        self.assertEqual(
            payload,
            b"===== cafe_unlock_state.json =====\n" + state_payload + b"\n"
            b"===== config_app.json =====\n" + app_payload + b"\n"
            b"===== config_camera.json =====\n" + camera_payload + b"\n",
        )

    def test_text_export_synthesizes_missing_cafe_state(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(main, "_cafe_unlock_sessions_remaining", 0):
            root = Path(temporary)
            (root / "config_app.json").write_text("{}", encoding="utf-8")
            (root / "config_camera.json").write_text("{}", encoding="utf-8")

            payload = main._build_config_export(root)

        self.assertTrue(payload.startswith(
            b'===== cafe_unlock_state.json =====\n{\n'
            b'    "remaining_sessions": 0\n}\n\n'
        ))


class FrontendCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_versioned_frontend_files_are_not_reused_after_update(self):
        for endpoint in (main.index, main.style, main.script):
            with self.subTest(endpoint=endpoint.__name__):
                response = await endpoint()
                self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
