import asyncio
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

from fastapi import WebSocketDisconnect

from backend import config as backend_config
from backend import main, yadisk_control
from backend.config import update_camera_config_field


class CommandValidationTests(unittest.TestCase):
    def test_poll_interval_is_ten_seconds(self):
        self.assertEqual(yadisk_control.POLL_INTERVAL, 5)

    def test_validates_command_id_and_filename(self):
        command_id = "a" * 32
        command = yadisk_control.validate_command({
            "schema_version": 3,
            "message_type": "command",
            "command_id": command_id,
            "command": "set_event",
            "data": {"name": "Свадьба Ивановых 2026"},
            "reply_target": {
                "provider": " Telegram ",
                "conversation_id": 123,
            },
        }, f"{command_id}.json")
        self.assertEqual(command["command"], "set_event")
        self.assertEqual(command["reply_target"], {
            "provider": "telegram",
            "conversation_id": "123",
        })

        with self.assertRaisesRegex(ValueError, "filename"):
            yadisk_control.validate_command(command, f"{'b' * 32}.json")

    def test_rejects_previous_command_schema(self):
        with self.assertRaisesRegex(ValueError, "unsupported command schema"):
            yadisk_control.validate_command({"schema_version": 2})

    def test_requires_valid_reply_target(self):
        command_id = "a" * 32
        base = {
            "schema_version": 3,
            "message_type": "command",
            "command_id": command_id,
            "command": "status",
            "data": None,
        }
        invalid_targets = (
            None,
            {"provider": "email", "conversation_id": "123"},
            {"provider": "telegram", "conversation_id": ""},
            {"provider": "vk", "conversation_id": None},
            {"provider": "vk", "conversation_id": True},
        )
        for target in invalid_targets:
            with self.subTest(target=target), self.assertRaises(ValueError):
                yadisk_control.validate_command({
                    **base,
                    "reply_target": target,
                })


class EventHistoryTests(unittest.TestCase):
    def test_photo_session_keeps_only_print_counts_and_exceptions(self):
        self.assertEqual(main._history_print_items([
            {"template": "grid", "photo_index": None,
             "with_frame": True, "copies": 2},
            {"template": "single", "photo_index": 3,
             "with_frame": False, "copies": 1},
        ]), {
            "grid": 2,
            "single_no_frame_4": 1,
        })

    def test_summary_counts_sessions_copies_and_physical_prints(self):
        summary = main._event_history_summary({
            "event": "old-event",
            "entries": [
                {"type": "photo_session", "result": "retake"},
                {
                    "type": "photo_session",
                    "result": "print_queued",
                    "items": {"grid": 2, "strips": 1,
                              "single_no_frame_3": 2},
                },
                {
                    "type": "photo_session",
                    "result": "print_queued",
                    "items": {"grid": 1},
                },
                {
                    "type": "photo_session",
                    "result": "completed_without_print",
                    "items": {"grid": 10},
                },
                {"type": "photo_session", "result": "failed"},
                {"type": "custom_print_job", "result": "print_queued"},
                {"type": "custom_print_job", "result": "failed"},
            ],
        })

        self.assertEqual(summary, (
            "📊 ИТОГ ИВЕНТА: old-event\n"
            "• Сессии: 5 · ретейки: 1 · с несколькими копиями: 1\n"
            "• Отпечатки: 7 · Grid: 3 · Strips: 1 · Single: 2 · "
            "Print jobs: 1"
        ))

    def test_event_change_archives_the_complete_old_history(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "_event_history_ready", False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="old-event"):
            main._start_event_history()
            main._record_event_history({
                "type": "photo_session",
                "session_id": "session-id",
                "result": "retake",
            })
            main._switch_event_history(
                "new-event",
                {"actor": "administrator", "via": "control"},
            )

            current = json.loads(
                (Path(tmpdir) / "event_history.json").read_text(
                    encoding="utf-8"))
            archive_paths = list(
                (Path(tmpdir) / "event_history_archive").glob("*.json"))
            archived = json.loads(
                archive_paths[0].read_text(encoding="utf-8"))

        self.assertEqual(current["event"], "new-event")
        self.assertEqual(current["entries"][0]["type"], "event_started")
        self.assertEqual(len(archive_paths), 1)
        self.assertEqual(archived["event"], "old-event")
        self.assertEqual(
            [entry["type"] for entry in archived["entries"]],
            ["application_started", "photo_session", "event_ended"],
        )

    def test_application_restart_keeps_the_current_history(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "_event_history_ready", False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"):
            main._start_event_history()
            main._record_event_history({
                "type": "photo_session",
                "session_id": "session-id",
                "result": "retake",
            })
            main._start_event_history()
            current = json.loads(
                (Path(tmpdir) / "event_history.json").read_text(
                    encoding="utf-8"))

        self.assertEqual(current["event"], "event")
        self.assertEqual(
            [entry["type"] for entry in current["entries"]],
            ["application_started", "photo_session", "application_started"],
        )

    def test_missing_previous_history_starts_the_new_journal_without_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "_event_history_ready", True):
            archived = main._switch_event_history(
                "new-event", {"actor": "administrator"})
            current = json.loads(
                (Path(tmpdir) / "event_history.json").read_text(
                    encoding="utf-8"))

        self.assertIsNone(archived)
        self.assertEqual(current["event"], "new-event")
        self.assertEqual(current["entries"][0]["type"], "event_started")

    def test_invalid_previous_history_is_replaced_when_event_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "_event_history_ready", True):
            (Path(tmpdir) / "event_history.json").write_text(
                "not json", encoding="utf-8")

            archived = main._switch_event_history(
                "new-event", {"actor": "administrator"})
            current = json.loads(
                (Path(tmpdir) / "event_history.json").read_text(
                    encoding="utf-8"))
            invalid_archives = list(
                (Path(tmpdir) / "event_history_archive").glob(
                    "*_invalid.json"))

        self.assertIsNone(archived)
        self.assertEqual(len(invalid_archives), 1)
        self.assertEqual(current["event"], "new-event")
        self.assertEqual(current["entries"][0]["type"], "event_started")


class CommandProcessingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        yadisk_control._pending_command_results.clear()

    def tearDown(self):
        yadisk_control._pending_command_results.clear()

    async def test_encodes_text_document_without_a_second_disk_resource(self):
        self.assertEqual(
            yadisk_control.response_document("конфиги".encode()),
            "конфиги",
        )
        with self.assertRaisesRegex(ValueError, "response document"):
            yadisk_control.response_document(
                b"x" * (yadisk_control.MAX_RESPONSE_DOCUMENT_SIZE + 1))

    async def test_writes_response_and_deletes_command_before_restart(self):
        command_id = "a" * 32
        body = json.dumps({
            "schema_version": 3,
            "message_type": "command",
            "command_id": command_id,
            "command": "restart",
            "data": None,
            "reply_target": {
                "provider": "vk",
                "conversation_id": 123,
            },
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
            self.assertEqual(response["schema_version"], 3)
            self.assertEqual(response["reply_target"], {
                "provider": "vk",
                "conversation_id": "123",
            })
            self.assertEqual(path, f"/control/to_vps/response_{command_id}.json")

        async def delete(filename):
            calls.append("delete")
            return True

        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        with patch.object(yadisk_control, "_root", "/control"), \
             patch("backend.yadisk_control._upload_bytes", side_effect=upload), \
             patch("backend.yadisk_control._delete_command", side_effect=delete):
            self.assertTrue(await yadisk_control._process_command(
                item, handler, body))
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
            "backend.yadisk_control._list_commands",
            AsyncMock(return_value=[item]),
        ), patch(
            "backend.yadisk_control._download_command_batch",
            AsyncMock(side_effect=OSError("network unavailable")),
        ), patch(
            "backend.yadisk_control._delete_command", AsyncMock()
        ) as delete_command:
            await yadisk_control._poll_commands_once(handler)

        handler.assert_not_awaited()
        delete_command.assert_not_awaited()

    async def test_response_upload_retry_reuses_first_command_result(self):
        command_id = "d" * 32
        body = json.dumps({
            "schema_version": 3,
            "message_type": "command",
            "command_id": command_id,
            "command": "clear_print_queue",
            "data": None,
            "reply_target": {
                "provider": "telegram",
                "conversation_id": "123",
            },
        }).encode()
        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        handler = AsyncMock(return_value={
            "status": "ok",
            "message": "было 3, удалено 3, осталось 0",
        })
        uploaded_payloads = []

        async def upload(payload, _path):
            uploaded_payloads.append(json.loads(payload))
            if len(uploaded_payloads) == 1:
                raise TimeoutError("uploader connection timeout")

        with patch.object(yadisk_control, "_root", "/control"), \
             patch("backend.yadisk_control._upload_bytes", side_effect=upload), \
             patch("backend.yadisk_control._delete_command", AsyncMock(return_value=True)) as delete:
            with self.assertRaisesRegex(TimeoutError, "connection timeout"):
                await yadisk_control._process_command(item, handler, body)

            self.assertTrue(await yadisk_control._process_command(
                item, handler, body))

        handler.assert_awaited_once()
        delete.assert_awaited_once_with(item["name"])
        self.assertEqual(len(uploaded_payloads), 2)
        self.assertEqual(uploaded_payloads[0], uploaded_payloads[1])
        self.assertIn("удалено 3", uploaded_payloads[1]["message"])
        self.assertNotIn(command_id, yadisk_control._pending_command_results)

    async def test_response_retry_defers_post_action_until_ack(self):
        command_id = "e" * 32
        body = json.dumps({
            "schema_version": 3,
            "message_type": "command",
            "command_id": command_id,
            "command": "restart",
            "data": None,
            "reply_target": {
                "provider": "telegram",
                "conversation_id": "123",
            },
        }).encode()
        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        post_action = AsyncMock()
        handler = AsyncMock(return_value={
            "status": "ok",
            "message": "Перезапуск подтверждён",
            "_post_action": post_action,
        })
        upload = AsyncMock(side_effect=[
            TimeoutError("uploader connection timeout"),
            None,
        ])

        with patch.object(yadisk_control, "_root", "/control"), \
             patch("backend.yadisk_control._upload_bytes", upload), \
             patch("backend.yadisk_control._delete_command", AsyncMock(return_value=True)):
            with self.assertRaises(TimeoutError):
                await yadisk_control._process_command(item, handler, body)
            post_action.assert_not_awaited()

            self.assertTrue(await yadisk_control._process_command(
                item, handler, body))
            await __import__("asyncio").sleep(0)

        handler.assert_awaited_once()
        post_action.assert_awaited_once()

    async def test_downloaded_invalid_json_is_deleted(self):
        command_id = "c" * 32
        item = {
            "name": f"{command_id}.json",
            "path": f"disk:/control/to_booth/{command_id}.json",
        }
        with patch(
            "backend.yadisk_control._delete_command",
            AsyncMock(return_value=True),
        ) as delete_command:
            self.assertTrue(await yadisk_control._process_command(
                item, AsyncMock(), b"not-json"))

        delete_command.assert_awaited_once_with(item["name"])

    async def test_downloads_folder_once_and_processes_listed_order(self):
        items = [
            {"name": f"{'a' * 32}.json"},
            {"name": f"{'b' * 32}.json"},
        ]
        bodies = {
            items[0]["name"]: b"first",
            items[1]["name"]: b"second",
        }
        process = AsyncMock(return_value=True)
        download = AsyncMock(return_value=(bodies, set()))
        with patch(
            "backend.yadisk_control._list_commands",
            AsyncMock(return_value=items),
        ), patch(
            "backend.yadisk_control._download_command_batch", download,
        ), patch(
            "backend.yadisk_control._process_command", process,
        ):
            handler = AsyncMock()
            await yadisk_control._poll_commands_once(handler)

        download.assert_awaited_once_with(items)
        self.assertEqual(process.await_args_list, [
            call(items[0], handler, b"first"),
            call(items[1], handler, b"second"),
        ])

    def test_extracts_only_listed_commands_from_folder_archive(self):
        first = f"{'a' * 32}.json"
        appeared_later = f"{'b' * 32}.json"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(f"to_booth/{first}", b"first")
            archive.writestr(f"to_booth/{appeared_later}", b"later")
            archive.writestr("to_booth/manual_notes/readme.txt", b"ignore")

        bodies, invalid = yadisk_control._extract_command_archive(
            buffer.getvalue(), [{"name": first}])

        self.assertEqual(bodies, {first: b"first"})
        self.assertEqual(invalid, set())

    async def test_command_batch_download_targets_the_folder(self):
        filename = f"{'a' * 32}.json"
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr(f"to_booth/{filename}", b"command")
        download = AsyncMock(return_value=archive_bytes.getvalue())
        with patch.object(
            yadisk_control, "_root", "/control",
        ), patch(
            "backend.yadisk_control._download_bytes", download,
        ):
            bodies, invalid = await yadisk_control._download_command_batch(
                [{"name": filename}])

        self.assertEqual(bodies, {filename: b"command"})
        self.assertEqual(invalid, set())
        download.assert_awaited_once_with(
            "/control/to_booth",
            yadisk_control.MAX_COMMAND_ARCHIVE_SIZE,
        )

    async def test_oversized_listed_command_is_deleted_before_folder_download(self):
        item = {
            "name": f"{'a' * 32}.json",
            "size": yadisk_control.MAX_COMMAND_FILE_SIZE + 1,
        }
        delete = AsyncMock(return_value=True)
        download = AsyncMock()
        with patch(
            "backend.yadisk_control._list_commands",
            AsyncMock(return_value=[item]),
        ), patch(
            "backend.yadisk_control._delete_command", delete,
        ), patch(
            "backend.yadisk_control._download_command_batch", download,
        ):
            await yadisk_control._poll_commands_once(AsyncMock())

        delete.assert_awaited_once_with(item["name"])
        download.assert_not_awaited()


class ControlConnectionSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_upload_links_use_desktop_client_user_agent(self):
        api_session = MagicMock(closed=False)
        transfer_session = MagicMock(closed=False)
        with patch.object(yadisk_control, "_configured", True), \
             patch.object(yadisk_control, "_token", "secret"), \
             patch.object(yadisk_control, "_root", "/control"), \
             patch.object(yadisk_control, "_session", None), \
             patch.object(yadisk_control, "_transfer_session", None), \
             patch("backend.yadisk_control.aiohttp.ClientSession", side_effect=[
                 api_session,
                 transfer_session,
             ]) as client_session, \
             patch("backend.yadisk_control._ensure_directory", AsyncMock()) as ensure:
            self.assertTrue(await yadisk_control._connect())

        headers = client_session.call_args_list[0].kwargs["headers"]
        self.assertEqual(
            headers["User-Agent"],
            yadisk_control.YADISK_API_USER_AGENT,
        )
        self.assertEqual(headers["Authorization"], "OAuth secret")
        self.assertEqual(
            [call.args[0] for call in ensure.await_args_list],
            ["/control", "/control/to_booth", "/control/to_vps"],
        )


class PrintArtifactDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_job_folder_and_extracts_requested_image(self):
        job_id = "b" * 32
        basename = f"123_20260812T120000Z_{job_id}"
        folder_path = f"/event_by_sessions/0000_print_jobs/{basename}"
        image_path = f"{folder_path}/{basename}.jpg"
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr(f"{basename}/{basename}.jpg", b"image")
            archive.writestr(f"{basename}/{basename}.txt", b"metadata")

        download = AsyncMock(return_value=archive_bytes.getvalue())
        with patch(
            "backend.yadisk_control._connect", AsyncMock(return_value=True),
        ), patch(
            "backend.yadisk_control._download_bytes", download,
        ):
            payload = await yadisk_control.download_print_artifact(
                image_path, "event")

        self.assertEqual(payload, b"image")
        download.assert_awaited_once_with(
            folder_path,
            yadisk_control.MAX_PRINT_FOLDER_ARCHIVE_SIZE,
        )

    async def test_rejects_legacy_flat_print_artifact_path(self):
        with patch(
            "backend.yadisk_control._connect", AsyncMock(return_value=True),
        ), self.assertRaisesRegex(ValueError, "print artifact path"):
            await yadisk_control.download_print_artifact(
                "/event_by_sessions/0000_print_jobs/image.jpg",
                "event",
            )


class PrintQueueCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_reports_dnp_and_both_windows_queues(self):
        info = {
            "printer_name": "DS-RX1",
            "status": "готов к печати",
            "total_count": 1234,
            "media_remaining": 150,
            "media_capacity": 700,
        }
        records = [
            {
                "target": "grid",
                "printer_name": "DS-RX1",
                "jobs": 2,
                "error": None,
            },
            {
                "target": "strips",
                "printer_name": "DS-RX1 Strips",
                "jobs": 1,
                "error": None,
            },
        ]
        config = {
            "yadisk_folder": "event",
            "template_pack": "birthday",
        }
        with patch.object(main, "camera", None), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "CONFIG", config), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"), \
             patch("backend.main.yadisk_cloud.pending_count", return_value=0), \
             patch("backend.main.preset_names", return_value=[]), \
             patch("backend.printer.get_dnp_printer_info",
                   return_value=info) as inspect_dnp, \
             patch("backend.printer.get_windows_print_queues",
                   return_value=records) as inspect_queues:
            result = await main.handle_disk_command({
                "command_id": "a" * 32,
                "command": "status",
                "data": None,
            })

        self.assertEqual(result["status"], "ok")
        self.assertIn("• Будка: event\n\n🖼 ШАБЛОН: birthday", result["message"])
        self.assertIn("🎟 СЕССИИ", result["message"])
        self.assertIn("• Технический ивент: нет", result["message"])
        self.assertIn("• Допуск: ♾ без ограничений", result["message"])
        self.assertIn("Отпечатков: всего 1234 · остаток 150/700", result["message"])
        self.assertIn("Grid · DS-RX1 — в очереди: 2", result["message"])
        self.assertIn(
            "Strips · DS-RX1 Strips — в очереди: 1",
            result["message"],
        )
        inspect_dnp.assert_called_once_with(config)
        inspect_queues.assert_called_once_with(config)

    async def test_status_attaches_the_current_event_history(self):
        history = '{"schema_version":1,"event":"event","entries":[]}\n'
        command = {
            "command_id": "a" * 32,
            "command": "status",
            "data": None,
            "reply_target": {
                "provider": "telegram",
                "conversation_id": "123",
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch("backend.main._status_report_text",
                   AsyncMock(return_value="status")), \
             patch("backend.main._active_event_name", return_value="event"), \
             patch("backend.main._start_locked", return_value=False):
            (Path(tmpdir) / "event_history.json").write_text(
                history, encoding="utf-8")
            result = await main.handle_disk_command(command)
            response, _post_action = yadisk_control._response(command, result)

        self.assertEqual(response["document"], history)
        self.assertEqual(response["document_caption"], (
            "📊 ИТОГ ИВЕНТА: event\n"
            "• Сессии: 0 · ретейки: 0 · с несколькими копиями: 0\n"
            "• Отпечатки: 0 · Grid: 0 · Strips: 0 · Single: 0 · "
            "Print jobs: 0"
        ))

    async def test_clear_reports_partial_failure_across_both_queues(self):
        records = [
            {
                "target": "grid",
                "printer_name": "DS-RX1",
                "jobs_before": 2,
                "jobs_after": 0,
                "cleared": 2,
                "error": None,
            },
            {
                "target": "strips",
                "printer_name": "DS-RX1 Strips",
                "jobs_before": 3,
                "jobs_after": 1,
                "cleared": 2,
                "error": "после очистки осталось заданий: 1",
            },
        ]
        with patch(
            "backend.printer.clear_windows_print_queues",
            return_value=records,
        ) as clear:
            result = await main.handle_disk_command({
                "command_id": "b" * 32,
                "command": "clear_print_queue",
                "data": None,
            })

        self.assertEqual(result["status"], "error")
        self.assertIn("удалено 2, осталось 1", result["message"])
        clear.assert_called_once_with(main.CONFIG)

    async def test_rejects_any_argument_before_touching_windows(self):
        with patch(
            "backend.printer.clear_windows_print_queues",
        ) as clear:
            result = await main.handle_disk_command({
                "command_id": "c" * 32,
                "command": "clear_print_queue",
                "data": {"target": "receipts"},
            })

        self.assertEqual(result["status"], "error")
        self.assertIn("не принимает аргументы", result["message"])
        clear.assert_not_called()


class RuntimeDirectoryCleanupCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_photos_removes_only_contents_when_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photos = Path(tmpdir) / "photos"
            session = photos / "session-1"
            session.mkdir(parents=True)
            (session / "photo.jpg").write_bytes(b"photo")
            (photos / "loose.txt").write_text("data", encoding="utf-8")

            with patch.object(main, "PHOTOS_DIR", photos), \
                 patch.object(main, "_session_running", False), \
                 patch.object(main, "_background_uploads", set()), \
                 patch("backend.printer.print_queue_busy", return_value=False), \
                 patch("backend.main.yadisk_cloud.pending_count", return_value=0):
                result = await main.handle_disk_command({
                    "command_id": "a" * 32,
                    "command": "clear_photos",
                    "data": None,
                })

            self.assertEqual(result["status"], "ok")
            self.assertTrue(photos.is_dir())
            self.assertEqual(list(photos.iterdir()), [])
            self.assertIn("удалено файлов — 2, папок — 1", result["message"])

    async def test_clear_print_jobs_removes_only_contents_when_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            print_jobs = Path(tmpdir) / "photos_print_jobs"
            job = print_jobs / ("b" * 32)
            job.mkdir(parents=True)
            (job / "print_4x6.jpg").write_bytes(b"print")

            with patch.object(main, "PRINT_JOBS_DIR", print_jobs), \
                 patch.object(main, "_session_running", False), \
                 patch("backend.printer.print_queue_busy", return_value=False):
                result = await main.handle_disk_command({
                    "command_id": "a" * 32,
                    "command": "clear_print_jobs",
                    "data": None,
                })

            self.assertEqual(result["status"], "ok")
            self.assertEqual(list(print_jobs.iterdir()), [])
            self.assertIn("photos_print_jobs очищена", result["message"])

    async def test_cleanup_is_rejected_during_session_or_printing(self):
        for running, printing, expected in (
            (True, False, "идёт фотосессия"),
            (False, True, "очередь печати не пуста"),
        ):
            with self.subTest(running=running, printing=printing), \
                 patch.object(main, "_session_running", running), \
                 patch("backend.printer.print_queue_busy", return_value=printing), \
                 patch("backend.main._clear_runtime_directory") as clear:
                result = await main.handle_disk_command({
                    "command_id": "a" * 32,
                    "command": "clear_print_jobs",
                    "data": None,
                })

            self.assertEqual(result["status"], "error")
            self.assertIn(expected, result["message"])
            clear.assert_not_called()

    async def test_clear_photos_preserves_pending_upload_sources(self):
        with patch.object(main, "_session_running", False), \
             patch.object(main, "_background_uploads", set()), \
             patch("backend.printer.print_queue_busy", return_value=False), \
             patch("backend.main.yadisk_cloud.pending_count", return_value=2), \
             patch("backend.main._clear_runtime_directory") as clear:
            result = await main.handle_disk_command({
                "command_id": "a" * 32,
                "command": "clear_photos",
                "data": None,
            })

        self.assertEqual(result["status"], "error")
        self.assertIn("незавершённых загрузок — 2", result["message"])
        clear.assert_not_called()

    async def test_cleanup_commands_reject_arguments(self):
        with patch("backend.main._clear_runtime_directory") as clear:
            result = await main.handle_disk_command({
                "command_id": "a" * 32,
                "command": "clear_photos",
                "data": {"path": "../"},
            })

        self.assertEqual(result["status"], "error")
        self.assertIn("не принимает аргументы", result["message"])
        clear.assert_not_called()


class TemplatePackCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_switches_pack_and_restarts_after_response(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_template_pack",
            "data": {"name": "birthday"},
        }
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch(
                 "backend.main.update_template_pack",
                 return_value=("park_universal", "birthday", True),
             ) as update:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertIn("park_universal → birthday", result["message"])
        self.assertIs(result["_post_action"], main._do_restart)
        update.assert_called_once_with("birthday")

    async def test_does_not_switch_pack_during_session(self):
        with patch.object(main, "STATE", "countdown"), patch(
            "backend.main.update_template_pack",
        ) as update:
            result = await main.handle_disk_command({
                "command_id": "a" * 32,
                "command": "set_template_pack",
                "data": {"name": "birthday"},
            })

        self.assertEqual(result["status"], "error")
        self.assertNotIn("_post_action", result)
        update.assert_not_called()


class AppConfigCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_allowed_field_and_restarts_after_response(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_app_config",
            "data": {"field": "setting", "value": "true"},
        }
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch(
                 "backend.main.update_app_config_field",
                 return_value=("setting", False, True, True),
             ) as update:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertIn("false → true", result["message"])
        self.assertIs(result["_post_action"], main._do_restart)
        update.assert_called_once_with("setting", "true")


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
             patch("backend.main._save_event_folder") as save, \
             patch("backend.main._set_cafe_unlock_sessions") as reset:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["event_folder"], "Свадьба Ивановых 2026")
        self.assertNotIn("<b>", result["message"])
        save.assert_called_once_with("Свадьба Ивановых 2026")
        reset.assert_not_called()

    async def test_set_event_attaches_the_archived_history_and_summary(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_event",
            "data": {"name": "new-event"},
            "reply_target": {
                "provider": "telegram",
                "conversation_id": "123",
            },
        }
        old_history = {
            "schema_version": 1,
            "event": "old-event",
            "entries": [
                {"at": "2026-08-23T10:00:00+00:00",
                 "type": "photo_session", "result": "retake"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "_event_history_ready", True), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch("backend.main.yadisk_cloud.set_event_folder", AsyncMock()), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="new-event"), \
             patch("backend.main._save_event_folder"), \
             patch("backend.main.broadcast", AsyncMock()):
            main._write_event_history(old_history)
            result = await main.handle_disk_command(command)
            response, _post_action = yadisk_control._response(command, result)

        archived = json.loads(response["document"])
        self.assertEqual(archived["event"], "old-event")
        self.assertEqual(archived["entries"][-1]["type"], "event_ended")
        self.assertEqual(response["document_caption"], (
            "📊 ИТОГ ИВЕНТА: old-event\n"
            "• Сессии: 1 · ретейки: 1 · с несколькими копиями: 0\n"
            "• Отпечатки: 0 · Grid: 0 · Strips: 0 · Single: 0 · "
            "Print jobs: 0"
        ))

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

    async def test_camera_preset_change_restarts_only_after_success(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_camera_preset",
            "data": {"name": "evening"},
        }
        changes = {
            "tv": ("1/200", "1/60"),
            "iso": (100, 400),
        }
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch("backend.main.apply_camera_preset",
                   return_value=(
                       "Улица, тёмный вечер",
                       changes,
                       "Вспышка: начните с 1/32. Фон тёмный — /tv 1/50.",
                   )) as apply:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertIn("Улица, тёмный вечер", result["message"])
        self.assertIn('tv: "1/200" → "1/60"', result["message"])
        self.assertIn("iso: 100 → 400", result["message"])
        self.assertIn(
            "Подсказка: Вспышка: начните с 1/32",
            result["message"],
        )
        self.assertIs(result["_post_action"], main._do_restart)
        apply.assert_called_once_with("evening")

    async def test_camera_preset_is_rejected_without_restart_when_busy(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_camera_preset",
            "data": {"name": "sun"},
        }
        with patch.object(main, "STATE", "countdown"), \
             patch("backend.main.apply_camera_preset") as apply:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "error")
        self.assertNotIn("_post_action", result)
        apply.assert_not_called()

    async def test_invalid_camera_preset_does_not_restart(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_camera_preset",
            "data": {"name": "missing"},
        }
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "_background_uploads", set()), \
             patch("backend.main.apply_camera_preset",
                   side_effect=ValueError("неизвестный пресет")):
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "error")
        self.assertIn("неизвестный пресет", result["message"])
        self.assertNotIn("_post_action", result)

    async def test_status_lists_ready_to_copy_camera_commands(self):
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "camera", None), \
             patch.object(main, "CONFIG", {"yadisk_folder": "event"}), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"), \
             patch("backend.main.yadisk_cloud.pending_count", return_value=0), \
             patch("backend.main.preset_names",
                   return_value=["sun", "indoor_dark"]), \
             patch("backend.main.lens_max_aperture_hint",
                   return_value="lens aperture hint"), \
             patch("backend.main.camera_exposure_options", return_value={
                 "av": ["av-option"],
                 "tv": ["tv-option"],
                 "iso": ["iso-option"],
             }):
            result = await main.handle_disk_command({
                "command_id": "a" * 32,
                "command": "status",
                "data": None,
            })

        self.assertEqual(result["status"], "ok")
        self.assertIn("🎛 УПРАВЛЕНИЕ", result["message"])
        self.assertIn(
            '/light <имя>: ["sun", "indoor_dark"]',
            result["message"],
        )
        self.assertIn("• lens aperture hint", result["message"])
        self.assertIn('/av: ["av-option"]', result["message"])
        self.assertIn('/tv: ["tv-option"]', result["message"])
        self.assertIn('/iso: ["iso-option"]', result["message"])

    async def test_get_config_embeds_one_text_export_in_response(self):
        command = {
            "command_id": "a" * 32,
            "command": "get_config",
            "data": None,
        }
        with patch(
            "backend.main._build_config_export",
            return_value=b"config export",
        ):
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["document"], "config export")
        self.assertNotIn("artifact_path", result)

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

    async def test_remote_run_records_the_command_after_ack(self):
        camera = MagicMock(is_connected=True, storage_ready=None)
        command = {
            "command_id": "a" * 32,
            "command": "run",
            "data": None,
        }
        with patch.object(main, "STATE", "idle"), \
             patch.object(main, "camera", camera), \
             patch.object(main, "_background_uploads", set()), \
             patch("backend.main._start_locked", return_value=False), \
             patch("backend.main._record_event_history") as record, \
             patch("backend.main.run_session", new_callable=AsyncMock) as run:
            result = await main.handle_disk_command(command)
            await result["_post_action"]()
            await asyncio.sleep(0)

        record.assert_called_once_with({
            "type": "admin_command",
            "command": "run",
            "command_id": "a" * 32,
        })
        run.assert_awaited_once_with()

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

    async def test_websocket_skip_finishes_template_selection(self):
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=[
            json.dumps({"type": "skip_print"}),
            WebSocketDisconnect(),
        ])
        skip = MagicMock()
        with patch.object(main, "STATE", "template_select"), \
             patch.object(main, "CLIENTS", []), \
             patch.object(main.app.state, "on_skip_print", skip, create=True), \
             patch("backend.main._start_locked", return_value=False):
            await main.websocket_endpoint(ws)

        skip.assert_called_once_with()

    async def test_allowance_is_consumed_after_print_enqueue_before_done(self):
        order = []

        async def enqueue(*_args):
            order.append("print")

        def require(_generation):
            order.append("camera")

        def consume():
            order.append("consume")

        async def state(value, extra=None):
            self.assertEqual(value, "done")
            self.assertEqual(extra, {"print_sheets": 1})
            order.append("done")

        with patch.object(main, "CONFIG", {"print_enabled": True}), \
             patch("backend.printer.enqueue_print", side_effect=enqueue), \
             patch("backend.main._require_session_camera", side_effect=require), \
             patch("backend.main._consume_cafe_unlock_session",
                   side_effect=consume), \
             patch("backend.main.set_state", side_effect=state):
            await main._finish_successful_session(
                [(Path("print.jpg"), "grid")], 7, True)

        self.assertEqual(order, ["print", "camera", "consume", "done"])

    async def test_basket_queues_every_sheet_before_consuming_one_allowance(self):
        """A multi-sheet basket is one paid session, not one job per sheet."""
        queued = []

        async def enqueue(path, _config, template=""):
            queued.append((Path(path).name, template))

        consumed = []

        async def state(value, extra=None):
            self.assertEqual(value, "done")
            self.assertEqual(extra, {"print_sheets": 5})

        with patch.object(main, "CONFIG", {"print_enabled": True}), \
             patch("backend.printer.enqueue_print", side_effect=enqueue), \
             patch("backend.main._require_session_camera"), \
             patch("backend.main._consume_cafe_unlock_session",
                   side_effect=lambda: consumed.append(1)), \
             patch("backend.main.set_state", side_effect=state):
            await main._finish_successful_session(
                [
                    (Path("print_strips.jpg"), "strips"),
                    (Path("print_strips.jpg"), "strips"),
                    (Path("print_grid.jpg"), "grid"),
                    (Path("print_grid.jpg"), "grid"),
                    (Path("print_single_photo_02_frame.jpg"), "single"),
                ],
                7,
                True,
            )

        # Every sheet reaches the spooler, and strips keep their own queue name
        # so the DNP 2inch cut still applies to them alone.
        self.assertEqual(queued, [
            ("print_strips.jpg", "strips"),
            ("print_strips.jpg", "strips"),
            ("print_grid.jpg", "grid"),
            ("print_grid.jpg", "grid"),
            ("print_single_photo_02_frame.jpg", "single"),
        ])
        self.assertEqual(consumed, [1])

    async def test_print_enqueue_error_does_not_consume_allowance(self):
        with patch.object(main, "CONFIG", {"print_enabled": True}), \
             patch("backend.printer.enqueue_print", new_callable=AsyncMock,
                   side_effect=RuntimeError("printer unavailable")), \
             patch("backend.main._consume_cafe_unlock_session") as consume, \
             patch("backend.main.set_state", new_callable=AsyncMock) as state:
            with self.assertRaisesRegex(RuntimeError, "printer unavailable"):
                await main._finish_successful_session(
                    [(Path("print.jpg"), "grid")], 7, True)

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
        self.assertIn("• Технический ивент: да", result["message"])
        self.assertIn("• Допуск: 🔴 закрыт", result["message"])
        self.assertIn("сессий осталось: 0", result["message"])
        self.assertNotIn("document", result)

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
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(main, "ROOT_DIR", Path(tmpdir)), \
                 patch.object(main, "CONFIG", config), \
                 patch.object(main, "STATE", "idle"), \
                 patch.object(main, "_background_uploads", set()), \
                 patch.object(main, "_cafe_unlock_sessions_remaining", 4), \
                 patch("backend.main.yadisk_cloud.set_event_folder",
                       new_callable=AsyncMock), \
                 patch("backend.main.yadisk_cloud.current_event_folder",
                       return_value="Кафе"), \
                 patch("backend.main._save_event_folder"), \
                 patch("backend.main.broadcast",
                       new_callable=AsyncMock) as broadcast:
                result = await main.handle_disk_command(command)
                persisted = json.loads(
                    (Path(tmpdir) / "cafe_unlock_state.json").read_text(
                        encoding="utf-8"))

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["start_locked"])
        self.assertEqual(result["unlock_sessions_remaining"], 0)
        self.assertEqual(persisted, {"remaining_sessions": 0})
        broadcast.assert_awaited_once()
        self.assertTrue(broadcast.await_args.args[0]["start_locked"])
        self.assertEqual(
            broadcast.await_args.args[0]["unlock_sessions_remaining"],
            0,
        )

    async def test_cafe_event_is_not_changed_when_lock_reset_fails(self):
        command = {
            "command_id": "a" * 32,
            "command": "set_event",
            "data": {"name": "Кафе"},
        }
        with patch.object(
            main,
            "CONFIG",
            {"technical_event_name": "Кафе", "yadisk_folder": "old_event"},
        ), patch.object(main, "STATE", "idle"), patch.object(
            main,
            "_background_uploads",
            set(),
        ), patch(
            "backend.main._set_cafe_unlock_sessions",
            side_effect=OSError("disk full"),
        ), patch(
            "backend.main.yadisk_cloud.set_event_folder",
            new_callable=AsyncMock,
        ) as set_event:
            result = await main.handle_disk_command(command)

        self.assertEqual(result["status"], "error")
        self.assertIn("Кафе не заблокировано", result["message"])
        set_event.assert_not_awaited()


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


class BoothNoticeTests(unittest.IsolatedAsyncioTestCase):
    """Unsolicited administrator notices published into to_vps."""

    async def test_notice_is_typed_and_named_for_chronological_pruning(self):
        uploaded = {}

        async def upload(payload, path):
            uploaded["payload"] = json.loads(payload)
            uploaded["path"] = path

        with patch.object(yadisk_control, "_root", "/control"), \
             patch("backend.yadisk_control._connect",
                   AsyncMock(return_value=True)), \
             patch("backend.yadisk_control._prune_booth_notices",
                   AsyncMock()), \
             patch("backend.yadisk_control._upload_bytes", side_effect=upload):
            path = await yadisk_control.publish_booth_notice(
                "camera_config", "Конфигурация камеры", "ISO=100")

        self.assertTrue(path.startswith("/control/to_vps/notice_"))
        self.assertEqual(uploaded["path"], path)
        notice = uploaded["payload"]
        self.assertEqual(notice["schema_version"], yadisk_control.SCHEMA_VERSION)
        self.assertEqual(notice["message_type"], "booth_notice")
        self.assertEqual(notice["kind"], "camera_config")
        self.assertEqual(notice["text"], "ISO=100")
        # A notice answers no command, so it must not claim a reply_target.
        self.assertNotIn("reply_target", notice)
        self.assertTrue(yadisk_control.BOOTH_NOTICE_NAME_RE.fullmatch(
            path.rsplit("/", 1)[-1]))

    async def test_oversized_text_is_truncated_instead_of_rejected(self):
        uploaded = {}

        async def upload(payload, _path):
            uploaded["payload"] = json.loads(payload)

        with patch.object(yadisk_control, "_root", "/control"), \
             patch("backend.yadisk_control._connect",
                   AsyncMock(return_value=True)), \
             patch("backend.yadisk_control._prune_booth_notices",
                   AsyncMock()), \
             patch("backend.yadisk_control._upload_bytes", side_effect=upload):
            await yadisk_control.publish_booth_notice(
                "camera_config", "t", "x" * 9000)

        text = uploaded["payload"]["text"]
        self.assertEqual(len(text), yadisk_control.MAX_BOOTH_NOTICE_TEXT)
        self.assertTrue(text.endswith("..."))

    async def test_status_notice_carries_history_and_summary_together(self):
        uploaded = {}

        async def upload(payload, _path):
            uploaded["payload"] = json.loads(payload)

        with patch.object(yadisk_control, "_root", "/control"), \
             patch("backend.yadisk_control._connect",
                   AsyncMock(return_value=True)), \
             patch("backend.yadisk_control._prune_booth_notices",
                   AsyncMock()), \
             patch("backend.yadisk_control._upload_bytes", side_effect=upload):
            await yadisk_control.publish_booth_notice(
                "booth_status",
                "Статус фотобудки",
                "status",
                document="{}\n",
                document_caption="summary",
            )

        self.assertEqual(uploaded["payload"]["document"], "{}\n")
        self.assertEqual(
            uploaded["payload"]["document_caption"], "summary")

    async def test_invalid_kind_is_rejected_before_any_network_call(self):
        with patch("backend.yadisk_control._connect",
                   AsyncMock()) as connect, \
             patch("backend.yadisk_control._upload_bytes",
                   AsyncMock()) as upload:
            for kind in ("", "Camera Config", "camera-config", "_x", "x" * 41):
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    await yadisk_control.publish_booth_notice(kind, "t", "b")
        connect.assert_not_awaited()
        upload.assert_not_awaited()

    async def test_pruning_removes_only_oldest_notice_files(self):
        names = [
            f"notice_20260809T1000{index:02d}Z_{'a' * 32}.json"
            for index in range(4)
        ]
        items = [{"name": name, "type": "file"} for name in names]
        # Session manifests and command responses must never be touched.
        items.append({"name": "session_x.json", "type": "file"})
        items.append({"name": f"response_{'b' * 32}.json", "type": "file"})
        deleted = []

        class Response:
            status = 200

            async def json(self):
                return {"_embedded": {"items": items}}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        class Deleted(Response):
            status = 204

        def get(_url, params=None):
            return Response()

        def delete(_url, params=None):
            deleted.append(params["path"])
            return Deleted()

        session = MagicMock()
        session.get = get
        session.delete = delete

        with patch.object(yadisk_control, "_root", "/control"), \
             patch.object(yadisk_control, "_session", session):
            await yadisk_control._prune_booth_notices(keep=3)

        self.assertEqual(deleted, [
            f"/control/to_vps/{names[0]}",
            f"/control/to_vps/{names[1]}",
        ])


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


class TemplatePackConfigTests(unittest.TestCase):
    def test_validates_and_atomically_updates_app_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config_app.json"
            templates_dir = root / "templates"
            pack_dir = templates_dir / "summer"
            pack_dir.mkdir(parents=True)
            config_path.write_text(json.dumps({
                "template_pack": "winter",
                "default_template": "grid",
                "other": 123,
            }), encoding="utf-8")
            (pack_dir / "config.json").write_text(json.dumps({
                "templates": {"grid": {}},
            }), encoding="utf-8")

            result = backend_config.update_template_pack(
                "summer", config_path, templates_dir,
            )
            saved = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(result, ("winter", "summer", True))
            self.assertEqual(saved["template_pack"], "summer")
            self.assertEqual(saved["other"], 123)
            self.assertEqual(
                backend_config.update_template_pack(
                    "summer", config_path, templates_dir,
                ),
                ("summer", "summer", False),
            )
            with self.assertRaisesRegex(ValueError, "доступно: summer"):
                backend_config.update_template_pack(
                    "missing", config_path, templates_dir,
                )


class AppConfigFieldTests(unittest.TestCase):
    def test_allowlist_controls_typed_atomic_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config_app.json"
            path.write_text(json.dumps({
                "enabled": False,
                "mode": "first",
                "_mode_options": ["first", "second"],
                "_admin_editable_fields": ["enabled", "mode"],
            }), encoding="utf-8")

            self.assertEqual(
                backend_config.update_app_config_field("enabled", "true", path),
                ("enabled", False, True, True),
            )
            self.assertEqual(
                backend_config.update_app_config_field("mode", "SECOND", path),
                ("mode", "first", "second", True),
            )
            with self.assertRaisesRegex(ValueError, "не разрешено"):
                backend_config.update_app_config_field("other", "1", path)


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
        frontend = next(
            route.app for route in main.app.routes
            if route.name == "frontend"
        )
        scope = {"method": "GET", "path": "/", "headers": []}
        for filename in ("index.html", "style.css", "core.js", "app.js"):
            with self.subTest(filename=filename):
                response = await frontend.get_response(filename, scope)
                self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
