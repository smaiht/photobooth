import asyncio
import ctypes
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend import main
from backend.camera import edsdk
from backend.video import VideoRecorder


class CameraWorkerRecoveryTests(unittest.TestCase):
    def test_initially_missing_camera_is_found_by_automatic_backoff(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        ready = threading.Event()
        errors = []

        def stop_after_connect():
            camera._running = False

        camera.set_callbacks(
            on_error=errors.append,
            on_connected=ready.set,
        )
        with patch.object(edsdk, "RECONNECT_MIN_SECONDS", 0.01), \
             patch.object(edsdk, "RECONNECT_MAX_SECONDS", 0.02), \
             patch.object(edsdk.ctypes, "WinDLL", return_value=object(), create=True), \
             patch.object(camera, "_setup_sdk_functions"), \
             patch.object(camera, "_init_sdk"), \
             patch.object(camera, "_connect_camera", side_effect=[RuntimeError("No camera"), None]) as connect, \
             patch.object(camera, "_configure_for_photobooth"), \
             patch.object(camera, "_register_handlers"), \
             patch.object(camera, "_run_connected", side_effect=stop_after_connect), \
             patch.object(camera, "_cleanup"):
            camera.start()
            self.assertTrue(ready.wait(2), "automatic backoff did not find the camera")
            camera._thread.join(timeout=2)

        self.assertFalse(camera._thread.is_alive())
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(errors, ["No camera"])

    def test_disconnect_reconnects_automatically_on_same_thread(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        disconnected = threading.Event()
        reconnected = threading.Event()
        connected_calls = []
        errors = []

        def on_connected():
            connected_calls.append(threading.get_ident())
            if len(connected_calls) == 2:
                reconnected.set()

        def on_error(message):
            errors.append(message)
            disconnected.set()

        def run_connected():
            if len(connected_calls) == 1:
                camera._cmd_queue.put(("capture", "stale"))
                camera._mark_disconnected("USB disconnected")
            else:
                camera._running = False

        camera.set_callbacks(on_error=on_error, on_connected=on_connected)
        with patch.object(edsdk.ctypes, "WinDLL", return_value=object(), create=True), \
             patch.object(camera, "_setup_sdk_functions"), \
             patch.object(camera, "_init_sdk"), \
             patch.object(camera, "_connect_camera") as connect, \
             patch.object(camera, "_configure_for_photobooth") as configure, \
             patch.object(camera, "_register_handlers"), \
             patch.object(camera, "_run_connected", side_effect=run_connected), \
             patch.object(camera, "_cleanup"):
            camera.start()
            self.assertTrue(disconnected.wait(2), "disconnect callback was not called")
            self.assertTrue(reconnected.wait(2), "automatic reconnect did not run")
            camera._thread.join(timeout=2)

        self.assertFalse(camera._thread.is_alive())
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(configure.call_count, 2)
        self.assertEqual(errors, ["USB disconnected"])
        self.assertEqual(len(connected_calls), 2)
        self.assertEqual(connected_calls[0], connected_calls[1])
        self.assertTrue(camera._cmd_queue.empty())

    def test_cleanup_releases_camera_even_if_unlock_fails(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._sdk = MagicMock()
        camera._sdk.EdsSendStatusCommand.side_effect = RuntimeError("disconnected")

        camera._cleanup_camera()

        camera._sdk.EdsCloseSession.assert_called_once()
        camera._sdk.EdsRelease.assert_called_once()
        self.assertFalse(camera._camera)

    def test_shutdown_event_does_not_run_one_more_camera_command(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._running = True
        camera._connected = True
        camera._sdk = MagicMock()
        camera._cmd_queue.put(("capture", "stale"))

        def disconnect_during_event():
            camera._mark_disconnected("USB disconnected")
            return edsdk.EDS_ERR_OK

        camera._sdk.EdsGetEvent.side_effect = disconnect_during_event
        with patch.object(camera, "_do_capture") as capture:
            camera._run_connected()

        capture.assert_not_called()
        self.assertEqual(camera.connection_generation, 1)
        self.assertTrue(camera._cmd_queue.empty())

    def test_live_view_communication_error_is_not_hidden_as_missing_frame(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._camera = ctypes.c_void_p(123)
        camera._sdk.EdsCreateMemoryStream.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsCreateEvfImageRef.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsDownloadEvfImage.return_value = edsdk.EDS_ERR_COMM_DISCONNECTED

        with self.assertRaises(edsdk.EDSDKError) as raised:
            camera._download_evf_frame()

        self.assertEqual(raised.exception.code, edsdk.EDS_ERR_COMM_DISCONNECTED)


class SessionDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_mid_session_disconnect_is_not_printed_or_uploaded(self):
        class DisconnectingCamera:
            def __init__(self):
                self.connected = True
                self.generation = 0

            @property
            def is_connected(self):
                return self.connected

            @property
            def connection_generation(self):
                return self.generation

            def set_download_dir(self, _path):
                pass

            def start_live_view(self):
                pass

            def stop_live_view(self):
                pass

            def take_picture(self, _tag=""):
                self.connected = False
                self.generation += 1

        camera = DisconnectingCamera()
        recorder = MagicMock()
        config = dict(main.CONFIG)
        config.update({
            "num_photos": 4,
            "pre_countdown_delay": 0,
            "countdown_seconds": 0,
            "countdown_sound_seconds": 0,
            "print_enabled": True,
        })

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "camera", camera), \
             patch.object(main, "video_recorder", recorder), \
             patch.object(main, "CONFIG", config), \
             patch.object(main, "PHOTOS_DIR", Path(tmpdir)), \
             patch.object(main, "CLIENTS", []), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "SESSION_COUNT", 0), \
             patch.object(main, "_session_running", False), \
             patch.object(main, "_camera_disconnected_event", asyncio.Event()), \
             patch("backend.main.yadisk_cloud.enqueue_session", new_callable=AsyncMock) as upload, \
             patch("backend.printer.enqueue_print", new_callable=AsyncMock) as print_job:
            await main.run_session()

            self.assertEqual(main.STATE, "camera_searching")
            self.assertFalse(main._session_running)
            self.assertEqual(main.SESSION_PHOTOS, [])

        recorder.abort.assert_called_once()
        upload.assert_not_awaited()
        print_job.assert_not_awaited()


class VideoAbortTests(unittest.TestCase):
    def test_late_photo_after_abort_is_ignored(self):
        recorder = VideoRecorder()
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder.start(Path(tmpdir))
            recorder.mark_photo()
            recorder.abort()
            recorder.set_photo_path(str(Path(tmpdir) / "late.jpg"))
            self.assertIsNone(recorder.stop_and_encode())


if __name__ == "__main__":
    unittest.main()
