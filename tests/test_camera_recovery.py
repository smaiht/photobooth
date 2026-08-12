import asyncio
import ctypes
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from PIL import Image

from backend import main
from backend.camera import edsdk
from backend.video import VideoRecorder


class CameraWorkerRecoveryTests(unittest.TestCase):
    def test_enables_and_disables_auto_power_off_for_eos_r(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsSetPropertyData.return_value = edsdk.EDS_ERR_OK

        camera._enable_limited_properties()

        auto_power_enable = [
            call for call in camera._sdk.EdsSetPropertyData.call_args_list
            if call.args[2] == 0x1C31565B
        ]
        self.assertEqual(len(auto_power_enable), 1)
        self.assertEqual(
            auto_power_enable[0].args[4]._obj.value,
            edsdk.kEdsPropID_AutoPowerOffSetting,
        )

        with patch.object(
            camera, "_get_property_desc", return_value=[0, 60]), \
             patch.object(camera, "_set_prop_u32", return_value=edsdk.EDS_ERR_OK) as set_prop, \
             patch.object(camera, "_get_prop_u32", return_value=0):
            self.assertEqual(camera._disable_auto_power_off(), edsdk.EDS_ERR_OK)

        set_prop.assert_called_once_with(
            edsdk.kEdsPropID_AutoPowerOffSetting,
            edsdk.kEdsAutoPowerOff_Disable,
            validate=False,
        )

    def test_com_sta_is_balanced_even_when_already_initialized(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        ole32 = MagicMock()
        ole32.CoInitializeEx.return_value = edsdk.S_FALSE
        with patch.object(
            edsdk.ctypes, "windll", SimpleNamespace(ole32=ole32), create=True,
        ):
            camera._initialize_com()
            camera._uninitialize_com()

        ole32.CoInitializeEx.assert_called_once_with(
            None, edsdk.COINIT_APARTMENTTHREADED)
        ole32.CoUninitialize.assert_called_once_with()

    def test_com_changed_mode_is_reported_and_not_uninitialized(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        ole32 = MagicMock()
        ole32.CoInitializeEx.return_value = ctypes.c_int32(
            edsdk.RPC_E_CHANGED_MODE).value
        with patch.object(
            edsdk.ctypes, "windll", SimpleNamespace(ole32=ole32), create=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "another COM apartment"):
                camera._initialize_com()
            camera._uninitialize_com()

        ole32.CoUninitialize.assert_not_called()

    def test_connected_loop_does_not_send_unsolicited_shutdown_timer_commands(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._running = True
        camera._connected = True
        camera._sdk = MagicMock()
        event_calls = 0

        def get_event():
            nonlocal event_calls
            event_calls += 1
            if event_calls == 2:
                camera._connected = False
            return edsdk.EDS_ERR_OK

        camera._sdk.EdsGetEvent.side_effect = get_event
        with patch.object(edsdk.time, "sleep"):
            camera._run_connected()

        camera._sdk.EdsSendCommand.assert_not_called()

    def test_shutdown_warning_extends_timer_and_logs_timer_update(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsSetObjectEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCameraStateEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetPropertyEventHandler.return_value = edsdk.EDS_ERR_OK

        with patch.object(camera, "_extend_shutdown_timer") as extend:
            camera._register_handlers()
            camera._state_handler_ref(
                edsdk.kEdsStateEvent_WillSoonShutDown, 30, None)

        extend.assert_called_once_with("Canon warning, 30s remaining")

    def test_camera_health_values_are_human_readable(self):
        self.assertEqual(edsdk.Camera._format_battery_level(0xFFFFFFFF), "AC")
        self.assertEqual(edsdk.Camera._format_auto_power_off(0), "disabled")
        self.assertEqual(edsdk.Camera._format_temperature_status(0), "normal")
        self.assertEqual(
            edsdk.Camera._format_temperature_status(4), "capture_disabled")

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
             patch.object(camera, "_initialize_com"), \
             patch.object(camera, "_uninitialize_com"), \
             patch.object(camera, "_setup_sdk_functions"), \
             patch.object(camera, "_init_sdk") as init_sdk, \
             patch.object(camera, "_terminate_sdk") as terminate_sdk, \
             patch.object(camera, "_connect_camera", side_effect=[RuntimeError("No camera"), None]) as connect, \
             patch.object(camera, "_configure_for_photobooth"), \
             patch.object(camera, "_register_handlers"), \
             patch.object(camera, "_run_connected", side_effect=stop_after_connect), \
             patch.object(camera, "_cleanup_camera"):
            camera.start()
            self.assertTrue(ready.wait(2), "automatic backoff did not find the camera")
            camera._thread.join(timeout=2)

        self.assertFalse(camera._thread.is_alive())
        self.assertEqual(connect.call_count, 2)
        init_sdk.assert_called_once_with()
        terminate_sdk.assert_called_once_with()
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
             patch.object(camera, "_initialize_com"), \
             patch.object(camera, "_uninitialize_com"), \
             patch.object(camera, "_setup_sdk_functions"), \
             patch.object(camera, "_init_sdk") as init_sdk, \
             patch.object(camera, "_terminate_sdk") as terminate_sdk, \
             patch.object(camera, "_connect_camera") as connect, \
             patch.object(camera, "_configure_for_photobooth") as configure, \
             patch.object(camera, "_register_handlers"), \
             patch.object(camera, "_run_connected", side_effect=run_connected), \
             patch.object(camera, "_cleanup_camera"):
            camera.start()
            self.assertTrue(disconnected.wait(2), "disconnect callback was not called")
            self.assertTrue(reconnected.wait(2), "automatic reconnect did not run")
            camera._thread.join(timeout=2)

        self.assertFalse(camera._thread.is_alive())
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(configure.call_count, 2)
        init_sdk.assert_called_once_with()
        terminate_sdk.assert_called_once_with()
        self.assertEqual(errors, ["USB disconnected"])
        self.assertEqual(len(connected_calls), 2)
        self.assertEqual(connected_calls[0], connected_calls[1])
        self.assertTrue(camera._cmd_queue.empty())

    def test_cleanup_releases_camera_even_if_unlock_fails(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._session_open = True
        camera._ui_locked = True
        camera._sdk = MagicMock()
        camera._sdk.EdsSendStatusCommand.side_effect = RuntimeError("disconnected")
        camera._sdk.EdsCloseSession.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsRelease.return_value = 0

        self.assertFalse(camera._cleanup_camera())

        camera._sdk.EdsCloseSession.assert_called_once()
        camera._sdk.EdsRelease.assert_called_once()
        self.assertFalse(camera._camera)
        self.assertTrue(camera._worker_cleanup_clean)

    def test_transport_loss_cleanup_only_releases_local_camera_ref(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._session_open = True
        camera._ui_locked = True
        camera._mode_dial_locked = True
        camera._transport_lost = True
        camera._sdk = MagicMock()
        camera._sdk.EdsRelease.return_value = 0

        camera._cleanup_camera()

        camera._sdk.EdsSendStatusCommand.assert_not_called()
        camera._sdk.EdsSendCommand.assert_not_called()
        camera._sdk.EdsCloseSession.assert_not_called()
        camera._sdk.EdsRelease.assert_called_once()
        self.assertFalse(camera._transport_lost)
        self.assertFalse(camera._worker_cleanup_clean)

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

    def test_open_session_retry_uses_fresh_refs_without_restarting_sdk(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._running = True
        camera._sdk = MagicMock()
        camera._sdk.EdsOpenSession.side_effect = [
            edsdk.EDS_ERR_INTERNAL_ERROR,
            edsdk.EDS_ERR_OK,
        ]
        camera._sdk.EdsRelease.return_value = 0
        first = ctypes.c_void_p(101)
        second = ctypes.c_void_p(102)
        with patch.object(camera, "_acquire_camera", side_effect=[first, second]), \
             patch.object(camera, "_enable_limited_properties"), \
             patch.object(camera._retry_event, "wait"):
            camera._connect_camera()

        self.assertTrue(camera._session_open)
        self.assertEqual(camera._camera.value, second.value)
        camera._sdk.EdsRelease.assert_called_once_with(first)
        camera._sdk.EdsCloseSession.assert_not_called()
        camera._sdk.EdsInitializeSDK.assert_not_called()
        camera._sdk.EdsTerminateSDK.assert_not_called()

    def test_sdk_init_and_terminate_are_each_guarded(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsInitializeSDK.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsTerminateSDK.return_value = edsdk.EDS_ERR_OK

        camera._init_sdk()
        camera._init_sdk()
        camera._terminate_sdk()
        camera._terminate_sdk()

        camera._sdk.EdsInitializeSDK.assert_called_once_with()
        camera._sdk.EdsTerminateSDK.assert_called_once_with()

    def test_ptp_busy_live_view_frame_is_transient(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._camera = ctypes.c_void_p(123)

        def make_ref(_size, out_ref):
            out_ref._obj.value = 201
            return edsdk.EDS_ERR_OK

        def make_evf(_stream, out_ref):
            out_ref._obj.value = 202
            return edsdk.EDS_ERR_OK

        camera._sdk.EdsCreateMemoryStream.side_effect = make_ref
        camera._sdk.EdsCreateEvfImageRef.side_effect = make_evf
        camera._sdk.EdsDownloadEvfImage.return_value = edsdk.EDS_ERR_PTP_DEVICE_BUSY

        self.assertIsNone(camera._download_evf_frame())
        self.assertEqual(camera._sdk.EdsRelease.call_count, 2)

    def test_mode_dial_is_locked_with_zero_and_unlocked_with_one(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsSendCommand.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCapacity.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsCloseSession.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsRelease.return_value = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config_camera.json"
            config_path.write_text(json.dumps({
                "disable_auto_power_off": False,
                "lock_camera_ui": False,
                "lock_mode_dial": True,
            }), encoding="utf-8")
            with patch("backend.config.ROOT_DIR", Path(tmpdir)), \
                 patch.object(camera, "storage_ready", return_value=(True, "")), \
                 patch.object(camera, "_configure_ae_mode"), \
                 patch.object(camera, "_set_prop_u32", return_value=edsdk.EDS_ERR_OK), \
                 patch.object(camera, "_read_camera_identity"), \
                 patch.object(camera, "_log_applied_config"), \
                 patch.object(camera, "_log_camera_health"), \
                 patch.object(edsdk.shutil, "disk_usage", return_value=SimpleNamespace(
                     free=10 * 1024 ** 3)):
                camera._configure_for_photobooth()

        camera._sdk.EdsSendCommand.assert_called_with(
            camera._camera,
            edsdk.kEdsCameraCommand_SetModeDialDisable,
            0,
        )

        camera._camera = ctypes.c_void_p(123)
        camera._session_open = True
        camera._mode_dial_locked = True
        camera._cleanup_camera()
        unlock_args = camera._sdk.EdsSendCommand.call_args_list[-1].args
        self.assertEqual(unlock_args[0].value, 123)
        self.assertEqual(
            unlock_args[1:],
            (edsdk.kEdsCameraCommand_SetModeDialDisable, 1),
        )

    def test_r8_face_tracking_uses_whole_area_value(self):
        self.assertEqual(
            edsdk.EVF_AF_MODE_MAP["face_tracking"],
            edsdk.EVF_AF_MODE_MAP["whole_area"],
        )
        self.assertEqual(edsdk.EVF_AF_MODE_MAP["face_tracking"], 0x0E)
        self.assertEqual(edsdk.EVF_AF_MODE_MAP["live_face"], 0x02)
        self.assertEqual(
            edsdk.Camera._name_from_map(edsdk.EVF_AF_MODE_MAP, 0x0E),
            "whole_area",
        )

    def test_optional_camera_lock_retries_busy_then_succeeds(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsGetEvent.return_value = edsdk.EDS_ERR_OK
        operation = MagicMock(side_effect=[
            edsdk.EDS_ERR_DEVICE_BUSY,
            edsdk.EDS_ERR_OK,
        ])

        with patch.object(edsdk.time, "sleep"):
            result = camera._retry_optional_command("lock camera UI", operation)

        self.assertEqual(result, edsdk.EDS_ERR_OK)
        self.assertEqual(operation.call_count, 2)
        camera._sdk.EdsGetEvent.assert_called_once_with()

    def test_camera_ui_lock_is_the_last_configuration_operation(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsSetCapacity.return_value = edsdk.EDS_ERR_OK
        events = []
        camera._sdk.EdsSendStatusCommand.side_effect = (
            lambda *_args: events.append("UI lock") or edsdk.EDS_ERR_OK)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config_camera.json"
            config_path.write_text(json.dumps({
                "disable_auto_power_off": False,
                "lock_camera_ui": True,
                "lock_mode_dial": False,
            }), encoding="utf-8")
            with patch("backend.config.ROOT_DIR", Path(tmpdir)), \
                 patch.object(camera, "storage_ready", return_value=(True, "")), \
                 patch.object(camera, "_configure_ae_mode"), \
                 patch.object(camera, "_set_prop_u32", return_value=edsdk.EDS_ERR_OK), \
                 patch.object(camera, "_read_camera_identity",
                              side_effect=lambda: events.append("identity")), \
                 patch.object(camera, "_log_applied_config",
                              side_effect=lambda: events.append("readback")), \
                 patch.object(camera, "_log_camera_health",
                              side_effect=lambda: events.append("health")), \
                 patch.object(edsdk.shutil, "disk_usage", return_value=SimpleNamespace(
                     free=10 * 1024 ** 3)):
                camera._configure_for_photobooth()

        self.assertEqual(events, ["identity", "readback", "health", "UI lock"])
        self.assertTrue(camera._ui_locked)

    def test_cleanup_retries_busy_close_and_records_real_result(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._session_open = True
        camera._sdk = MagicMock()
        camera._sdk.EdsCloseSession.side_effect = [
            edsdk.EDS_ERR_DEVICE_BUSY,
            edsdk.EDS_ERR_OK,
        ]
        camera._sdk.EdsGetEvent.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsRelease.return_value = 0

        with patch.object(edsdk.time, "sleep"):
            self.assertTrue(camera._cleanup_camera())

        self.assertEqual(camera._sdk.EdsCloseSession.call_count, 2)
        camera._sdk.EdsGetEvent.assert_called_once_with()
        self.assertEqual(camera.status_snapshot()["last_cleanup_result"], "closed")

    def test_failed_close_marks_worker_shutdown_as_unclean(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._session_open = True
        camera._sdk = MagicMock()
        camera._sdk.EdsCloseSession.return_value = edsdk.EDS_ERR_INTERNAL_ERROR
        camera._sdk.EdsRelease.return_value = 0

        self.assertFalse(camera._cleanup_camera())

        self.assertFalse(camera._worker_cleanup_clean)
        self.assertIn(
            "close failed", camera.status_snapshot()["last_cleanup_result"])

    def test_stop_reports_a_native_worker_that_remains_stuck(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        worker = MagicMock()
        worker.is_alive.return_value = True
        camera._thread = worker

        self.assertFalse(camera.stop(0.25))

        worker.join.assert_called_once_with(timeout=0.25)

    def test_optional_mode_dial_internal_error_does_not_claim_usb_loss(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsGetEvent.return_value = edsdk.EDS_ERR_OK
        operation = MagicMock(return_value=edsdk.EDS_ERR_INTERNAL_ERROR)

        with patch.object(edsdk.time, "sleep"):
            result = camera._retry_optional_command(
                "lock camera mode dial", operation)

        self.assertEqual(result, edsdk.EDS_ERR_INTERNAL_ERROR)
        operation.assert_called_once_with()
        camera._sdk.EdsGetEvent.assert_not_called()
        self.assertFalse(camera._transport_lost)

    def test_mode_dial_internal_error_does_not_abort_camera_configuration(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._sdk = MagicMock()
        camera._sdk.EdsSendCommand.return_value = edsdk.EDS_ERR_INTERNAL_ERROR
        camera._sdk.EdsGetEvent.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCapacity.return_value = edsdk.EDS_ERR_OK

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config_camera.json"
            config_path.write_text(json.dumps({
                "disable_auto_power_off": False,
                "lock_camera_ui": False,
                "lock_mode_dial": True,
            }), encoding="utf-8")
            with patch("backend.config.ROOT_DIR", Path(tmpdir)), \
                 patch.object(camera, "storage_ready", return_value=(True, "")), \
                 patch.object(camera, "_configure_ae_mode"), \
                 patch.object(camera, "_set_prop_u32", return_value=edsdk.EDS_ERR_OK), \
                 patch.object(camera, "_read_camera_identity") as identity, \
                 patch.object(camera, "_log_applied_config"), \
                 patch.object(camera, "_log_camera_health"), \
                 patch.object(edsdk.shutil, "disk_usage", return_value=SimpleNamespace(
                     free=10 * 1024 ** 3)), \
                 patch.object(edsdk.time, "sleep"):
                camera._configure_for_photobooth()

        identity.assert_called_once_with()
        self.assertFalse(camera._transport_lost)

    def test_generic_internal_error_closes_an_open_session_normally(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._session_open = True
        camera._sdk = MagicMock()
        camera._sdk.EdsCloseSession.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsRelease.return_value = 0

        camera._mark_disconnected(
            "optional command failed",
            transport_lost=(
                edsdk.EDS_ERR_INTERNAL_ERROR in edsdk.FATAL_TRANSPORT_ERRORS),
        )
        camera._cleanup_camera()

        camera._sdk.EdsCloseSession.assert_called_once()
        camera._sdk.EdsRelease.assert_called_once()

    def test_optional_camera_lock_propagates_real_usb_loss(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        operation = MagicMock(return_value=edsdk.EDS_ERR_COMM_DISCONNECTED)

        with self.assertRaises(edsdk.EDSDKError) as raised:
            camera._retry_optional_command("lock camera UI", operation)

        self.assertEqual(raised.exception.code, edsdk.EDS_ERR_COMM_DISCONNECTED)
        camera._sdk.EdsGetEvent.assert_not_called()

    def test_property_descriptor_blocks_an_unavailable_value(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()

        def get_desc(_camera, _prop, out_desc):
            out_desc._obj.numElements = 2
            out_desc._obj.propDesc[0] = 100
            out_desc._obj.propDesc[1] = 200
            return edsdk.EDS_ERR_OK

        camera._sdk.EdsGetPropertyDesc.side_effect = get_desc
        result = camera._set_prop_u32(edsdk.kEdsPropID_ISOSpeed, 400)

        self.assertEqual(result, edsdk.EDS_ERR_INVALID_DEVICEPROP_VALUE)
        camera._sdk.EdsSetPropertyData.assert_not_called()

    def test_object_event_ref_is_released_for_success_failure_and_ignore(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsSetObjectEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCameraStateEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetPropertyEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsRelease.return_value = 0
        camera._register_handlers()

        with patch.object(camera, "_download_photo") as download:
            camera._obj_handler_ref(
                edsdk.kEdsObjectEvent_DirItemRequestTransfer, 101, None)
            download.side_effect = RuntimeError("download failed")
            camera._obj_handler_ref(
                edsdk.kEdsObjectEvent_DirItemRequestTransfer, 102, None)
            camera._obj_handler_ref(0x00000209, 103, None)

        self.assertEqual(camera._sdk.EdsRelease.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in camera._sdk.EdsRelease.call_args_list],
            [101, 102, 103],
        )

    def test_failed_download_is_cancelled_and_partial_file_removed(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsDownloadCancel.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsRelease.return_value = 0

        def get_info(_item, out_info):
            out_info._obj.size = 10
            out_info._obj.szFileName = b"IMG_9999.JPG"
            return edsdk.EDS_ERR_OK

        def create_stream(_path, _disposition, _access, out_stream):
            out_stream._obj.value = 456
            return edsdk.EDS_ERR_OK

        camera._sdk.EdsGetDirectoryItemInfo.side_effect = get_info
        camera._sdk.EdsCreateFileStreamEx.side_effect = create_stream
        camera._sdk.EdsDownload.return_value = edsdk.EDS_ERR_INCOMPLETE_TRANSFER

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(camera, "storage_ready", return_value=(True, "")):
            download_dir = Path(tmpdir) / "Фото с будки"
            download_dir.mkdir()
            camera.set_download_dir(download_dir)
            partial = download_dir / "IMG_9999.JPG"
            partial.write_bytes(b"partial")
            with self.assertRaises(edsdk.EDSDKError):
                camera._download_photo(ctypes.c_void_p(123))
            self.assertFalse(partial.exists())

        stream_path = camera._sdk.EdsCreateFileStreamEx.call_args.args[0]
        self.assertIsInstance(stream_path, str)
        self.assertIn("Фото с будки", stream_path)
        camera._sdk.EdsDownloadCancel.assert_called_once()
        self.assertEqual(
            camera._sdk.EdsDownloadCancel.call_args.args[0].value, 123)
        camera._sdk.EdsDownloadComplete.assert_not_called()

    def test_internal_error_event_forces_reconnect(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._running = True
        camera._connected = True
        camera._sdk = MagicMock()
        camera._sdk.EdsSetObjectEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCameraStateEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetPropertyEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._register_handlers()

        camera._state_handler_ref(edsdk.kEdsStateEvent_InternalError, 0, None)

        self.assertFalse(camera._connected)
        self.assertEqual(camera.connection_generation, 1)
        self.assertEqual(
            camera.status_snapshot()["last_disconnect_reason"],
            "EDSDK internal camera error",
        )

    def test_state_event_diagnostics_use_their_own_semantics(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsSetObjectEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCameraStateEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetPropertyEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._register_handlers()

        with self.assertLogs("backend.camera.edsdk", level="INFO") as logs:
            camera._state_handler_ref(edsdk.kEdsStateEvent_CaptureError, 2, None)
            camera._state_handler_ref(
                edsdk.kEdsStateEvent_ShutDownTimerUpdate, 999, None)

        output = "\n".join(logs.output)
        self.assertIn("lens_closed", output)
        self.assertIn("extension accepted", output)
        self.assertNotIn("999s", output)

    def test_capture_retries_only_transient_errors(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._cfg = {"focus_before_capture": False}
        camera._running = True
        camera._connected = True
        camera._sdk = MagicMock()
        camera._sdk.EdsSendCommand.side_effect = [
            edsdk.EDS_ERR_DEVICE_BUSY,
            edsdk.EDS_ERR_PTP_DEVICE_BUSY,
            edsdk.EDS_ERR_OK,
            edsdk.EDS_ERR_OK,
        ]
        camera._sdk.EdsGetEvent.return_value = edsdk.EDS_ERR_OK

        with patch.object(edsdk.time, "sleep"):
            camera._do_capture()

        self.assertEqual(camera._sdk.EdsSendCommand.call_count, 4)
        self.assertTrue(camera._connected)

        camera._sdk.reset_mock()
        camera._sdk.EdsSendCommand.side_effect = [
            edsdk.EDS_ERR_TAKE_PICTURE_AF_NG,
            edsdk.EDS_ERR_OK,
        ]
        camera._do_capture()
        self.assertEqual(camera._sdk.EdsSendCommand.call_count, 2)

    def test_capture_transport_error_disconnects_without_retry(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._camera = ctypes.c_void_p(123)
        camera._cfg = {"focus_before_capture": False}
        camera._running = True
        camera._connected = True
        camera._sdk = MagicMock()
        camera._sdk.EdsSendCommand.return_value = edsdk.EDS_ERR_COMM_DISCONNECTED

        camera._do_capture()

        self.assertFalse(camera._connected)
        camera._sdk.EdsSendCommand.assert_called_once()

    def test_temperature_status_decodes_still_and_movie_words(self):
        self.assertEqual(
            edsdk.Camera._format_temperature_status(0x00020001),
            "warning+movie_restricted",
        )

    def test_storage_guard_uses_configured_threshold(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._cfg = {"min_free_disk_gib": 2}
        with patch.object(
            edsdk.shutil, "disk_usage",
            return_value=SimpleNamespace(free=1024 ** 3),
        ):
            ready, reason = camera.storage_ready()
        self.assertFalse(ready)
        self.assertIn("disk space is low", reason)

    def test_temperature_property_event_is_reported_immediately(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsSetObjectEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCameraStateEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetPropertyEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._register_handlers()

        camera._prop_handler_ref(
            edsdk.kEdsPropertyEvent_PropertyChanged,
            edsdk.kEdsPropID_TempStatus,
            0,
            None,
        )
        with patch.object(camera, "_get_prop_u32", return_value=0x00020001), \
             patch.object(camera, "_log_camera_health"), \
             self.assertLogs("backend.camera.edsdk", level="WARNING") as logs:
            camera._process_property_updates()

        self.assertIn("warning+movie_restricted", "\n".join(logs.output))
        self.assertFalse(camera._pending_property_updates)

    def test_capture_property_flood_is_not_queued_for_health_reads(self):
        camera = edsdk.Camera("fake-edSDK.dll")
        camera._sdk = MagicMock()
        camera._sdk.EdsSetObjectEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetCameraStateEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._sdk.EdsSetPropertyEventHandler.return_value = edsdk.EDS_ERR_OK
        camera._register_handlers()

        for prop_id in (
            edsdk.kEdsPropID_AvailableShots,
            edsdk.kEdsPropID_AEMode,
            edsdk.kEdsPropID_Tv,
            edsdk.kEdsPropID_Av,
        ):
            camera._prop_handler_ref(
                edsdk.kEdsPropertyEvent_PropertyChanged,
                prop_id,
                0,
                None,
            )

        self.assertFalse(camera._pending_property_updates)


class ManualCameraRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_resets_usb_between_stopping_and_starting_edsdk(self):
        camera = MagicMock()
        camera.stop.side_effect = [False, True]
        recovery_lock = asyncio.Lock()

        with patch.object(main, "camera", camera), \
             patch.object(main, "STATE", "camera_searching"), \
             patch.object(main, "_services_stopping", False), \
             patch.object(main, "_camera_recovery_lock", recovery_lock), \
             patch("backend.main.set_state", new_callable=AsyncMock) as set_state, \
             patch("backend.main._request_camera_usb_restart",
                   return_value=(True, "USB reset")) as usb_reset, \
             patch.object(main, "CAMERA_USB_RESET_WAIT_SECONDS", 0):
            result = await main._recover_camera()

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["usb_reset"])
        self.assertEqual(camera.stop.call_args_list, [call(3.0), call(10.0)])
        usb_reset.assert_called_once_with()
        camera.start.assert_called_once_with()
        set_state.assert_awaited_once_with("camera_searching")

    async def test_recovery_still_cycles_edsdk_when_system_task_is_missing(self):
        camera = MagicMock()
        camera.stop.return_value = True

        with patch.object(main, "camera", camera), \
             patch.object(main, "STATE", "no_camera"), \
             patch.object(main, "_services_stopping", False), \
             patch.object(main, "_camera_recovery_lock", asyncio.Lock()), \
             patch("backend.main.set_state", new_callable=AsyncMock), \
             patch("backend.main._request_camera_usb_restart",
                   return_value=(False, "task missing")):
            result = await main._recover_camera()

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["usb_reset"])
        self.assertIn("EDSDK перезапущен", result["message"])
        camera.stop.assert_called_once_with(3.0)
        camera.start.assert_called_once_with()

    async def test_recovery_never_starts_a_second_worker_over_a_stuck_one(self):
        camera = MagicMock()
        camera.stop.return_value = False

        with patch.object(main, "camera", camera), \
             patch.object(main, "STATE", "camera_searching"), \
             patch.object(main, "_services_stopping", False), \
             patch.object(main, "_camera_recovery_lock", asyncio.Lock()), \
             patch("backend.main.set_state", new_callable=AsyncMock), \
             patch("backend.main._request_camera_usb_restart",
                   return_value=(True, "USB reset")), \
             patch.object(main, "CAMERA_USB_RESET_WAIT_SECONDS", 0):
            result = await main._recover_camera()

        self.assertEqual(result["status"], "error")
        self.assertEqual(camera.stop.call_count, 2)
        camera.start.assert_not_called()

    def test_windows_usb_reset_uses_only_the_fixed_scheduled_task(self):
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        with patch.object(main.sys, "platform", "win32"), \
             patch("backend.main.subprocess.run", return_value=completed) as run:
            requested, _detail = main._request_camera_usb_restart()

        self.assertTrue(requested)
        command = run.call_args.args[0]
        self.assertEqual(command, [
            "schtasks.exe", "/Run", "/TN", "PhotoboothResetCanonR8",
        ])
        self.assertNotIn("pnputil", " ".join(command).lower())

    def test_setup_task_is_immutable_and_scoped_to_canon_r8(self):
        root = Path(__file__).resolve().parents[1]
        setup = (root / "_setup_camera_reset.ps1").read_text(encoding="utf-8")

        self.assertIn("VID_04A9&PID_330C", setup)
        self.assertIn("-EncodedCommand", setup)
        self.assertIn("(A;;GRGX;;;$kioskSid)", setup)
        self.assertNotIn("-File $", setup)


class CameraStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_status_contains_camera_health_and_last_disconnect(self):
        camera = MagicMock()
        camera.is_connected = True
        camera.status_snapshot.return_value = {
            "product_name": "Canon EOS R8",
            "battery": "AC",
            "temperature": "normal",
            "ae_mode": "manual",
            "auto_power_off": "disabled",
            "disk_free_bytes": 10 * 1024 ** 3,
            "last_shutdown_timer_extension_result": "ok",
            "last_shutdown_timer_extension_at": "2026-07-24T12:00:00+00:00",
            "last_disconnect_reason": "Camera shutdown/disconnected",
            "last_disconnect_at": "2026-07-24T11:00:00+00:00",
        }
        command = {
            "command_id": "a" * 32,
            "command": "status",
            "data": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "camera", camera), \
             patch.object(main, "ROOT_DIR", Path(tmpdir)), \
             patch.object(main, "STATE", "idle"), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="test_event"), \
             patch("backend.main.yadisk_cloud.pending_count", return_value=0):
            result = await main.handle_disk_command(command)

        self.assertIn("Camera model: Canon EOS R8", result["message"])
        self.assertIn("power=AC", result["message"])
        self.assertIn("Photo disk free: 10.00 GiB", result["message"])
        self.assertIn("Last camera disconnect", result["message"])


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
             patch("backend.main._start_locked", return_value=False), \
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
    def test_first_live_frame_logs_canon_evf_resolution(self):
        recorder = VideoRecorder()
        frame = io.BytesIO()
        Image.new("RGB", (960, 640), "black").save(frame, "JPEG")

        with tempfile.TemporaryDirectory() as tmpdir:
            recorder.start(Path(tmpdir))
            with self.assertLogs("backend.video", level="INFO") as captured:
                recorder.add_frame(frame.getvalue())
            recorder.abort()

        self.assertTrue(any(
            "Canon EVF JPEG: 960x640" in message
            for message in captured.output
        ))

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
