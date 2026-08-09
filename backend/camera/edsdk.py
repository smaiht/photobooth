"""Canon EDSDK wrapper via ctypes - Windows only.

Uses EdsGetEvent() polling (no Windows message pump needed).
All EDSDK calls must happen from the same thread that called EdsInitializeSDK().
"""

import ctypes
import ctypes.wintypes
import threading
import time
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue, Empty

from .constants import *

log = logging.getLogger(__name__)

# ctypes type aliases matching EDSDK types
EdsError = ctypes.c_uint32
EdsBaseRef = ctypes.c_void_p
EdsUInt32 = ctypes.c_uint32
EdsInt32 = ctypes.c_int32
EdsUInt64 = ctypes.c_uint64
EdsBool = ctypes.c_int32

COINIT_APARTMENTTHREADED = 0x2
S_OK = 0x00000000
S_FALSE = 0x00000001
RPC_E_CHANGED_MODE = 0x80010106


class EdsCapacity(ctypes.Structure):
    _fields_ = [
        ("numberOfFreeClusters", EdsInt32),
        ("bytesPerSector", EdsInt32),
        ("reset", EdsBool),
    ]


class EdsDeviceInfo(ctypes.Structure):
    _fields_ = [
        ("szPortName", ctypes.c_char * 256),
        ("szDeviceDescription", ctypes.c_char * 256),
        ("deviceSubType", EdsUInt32),
        ("reserved", EdsUInt32),
    ]


class EdsDirectoryItemInfo(ctypes.Structure):
    _fields_ = [
        ("size", EdsUInt64),
        ("isFolder", EdsBool),
        ("groupID", EdsUInt32),
        ("option", EdsUInt32),
        ("szFileName", ctypes.c_char * 256),
        ("format", EdsUInt32),
        ("dateTime", EdsUInt32),
    ]


class EdsPropertyDesc(ctypes.Structure):
    _fields_ = [
        ("form", EdsInt32),
        ("access", EdsInt32),
        ("numElements", EdsInt32),
        ("propDesc", EdsInt32 * 128),
    ]


# Callback function types (EDSCALLBACK = __stdcall on Windows).  CFUNCTYPE is
# only a test/import fallback for non-Windows development machines.
_CALLBACK = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
OBJECT_EVENT_HANDLER = _CALLBACK(EdsError, ctypes.c_uint32, EdsBaseRef, ctypes.c_void_p)
STATE_EVENT_HANDLER = _CALLBACK(EdsError, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
PROPERTY_EVENT_HANDLER = _CALLBACK(EdsError, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)

RECONNECT_MIN_SECONDS = 2
RECONNECT_MAX_SECONDS = 10
CAMERA_HEALTH_LOG_SECONDS = 10 * 60.0
MIN_FREE_DISK_GIB = 2.0

TRANSIENT_CAPTURE_ERRORS = {
    EDS_ERR_DEVICE_BUSY,
    EDS_ERR_PTP_DEVICE_BUSY,
    EDS_ERR_OBJECT_NOTREADY,
    EDS_ERR_TAKE_PICTURE_STROBO_CHARGE_NG,
}
FATAL_TRANSPORT_ERRORS = {
    # Keep this set limited to errors which explicitly say that the current
    # device/session transport is unusable.  EDS_ERR_INTERNAL_ERROR is a
    # generic per-operation failure: EOS R8 may return it for optional body
    # commands (notably SetModeDialDisable) while the open session remains
    # perfectly usable.  Treating it as a USB loss makes cleanup skip
    # EdsCloseSession and can leave the body rejecting every later open.
    EDS_ERR_DEVICE_NOT_FOUND,
    EDS_ERR_DEVICE_INVALID,
    EDS_ERR_DEVICE_EMERGENCY,
    EDS_ERR_DEVICE_INTERNAL_ERROR,
    EDS_ERR_COMM_DISCONNECTED,
    EDS_ERR_COMM_USB_BUS_ERR,
    EDS_ERR_SESSION_NOT_OPEN,
}
OPTIONAL_PROPERTY_ERRORS = {
    EDS_ERR_NOT_SUPPORTED,
    EDS_ERR_PROPERTIES_UNAVAILABLE,
    EDS_ERR_DEVICEPROP_NOT_SUPPORTED,
    EDS_ERR_INVALID_ID,
}


class EDSDKError(Exception):
    def __init__(self, func_name: str, code: int):
        self.code = code
        super().__init__(f"EDSDK {func_name} failed: 0x{code:08X} {edsdk_error_name(code)}")


def _check(func_name: str, err: int):
    if err != EDS_ERR_OK:
        raise EDSDKError(func_name, err)


class Camera:
    """Manages a single Canon camera via EDSDK."""

    def __init__(self, dll_path: str | Path):
        self._dll_path = str(dll_path)
        self._sdk = None
        self._sdk_initialized = False
        self._ole32 = None
        self._com_initialized = False
        self._camera = EdsBaseRef()
        self._session_open = False
        self._transport_lost = False
        self._ui_locked = False
        self._mode_dial_locked = False
        self._evf_original_output: int | None = None
        self._running = False
        self._connected = False
        self._connection_generation = 0
        self._failure_notified = False
        self._photo_tag = ""
        self._cfg = {}
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._retry_event = threading.Event()
        self._cmd_queue: Queue = Queue()
        self._evf_frame_cb = None  # callback(jpeg_bytes)
        self._photo_cb = None  # callback(file_path)
        self._error_cb = None  # callback(error_str)
        self._connected_cb = None  # callback()
        self._download_dir = Path("photos")
        self._health_lock = threading.Lock()
        self._health = {
            "connected": False,
            "last_disconnect_reason": None,
            "last_disconnect_at": None,
            "last_shutdown_timer_extension_at": None,
            "last_shutdown_timer_extension_result": None,
        }
        self._pending_property_updates: set[int] = set()

        # Must keep references to prevent GC of ctypes callbacks
        self._obj_handler_ref = None
        self._state_handler_ref = None
        self._prop_handler_ref = None

    def set_callbacks(self, on_evf_frame=None, on_photo=None, on_error=None, on_connected=None):
        self._evf_frame_cb = on_evf_frame
        self._photo_cb = on_photo
        self._error_cb = on_error
        self._connected_cb = on_connected

    def set_download_dir(self, path: Path):
        self._download_dir = path
        self._download_dir.mkdir(parents=True, exist_ok=True)

    def start(self):
        """Start the persistent EDSDK thread and wake its automatic search."""
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                self._retry_event.set()
                return
            self._running = True
            self._retry_event.set()
            self._thread = threading.Thread(
                target=self._run, name="edsdk-camera", daemon=True)
            self._thread.start()

    def stop(self):
        self._running = False
        self._retry_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                log.error("EDSDK thread did not stop within 10 seconds")

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and self._running and self._thread and self._thread.is_alive())

    @property
    def connection_generation(self) -> int:
        """Changes on every disconnect so an old session cannot resume after reconnect."""
        return self._connection_generation

    def status_snapshot(self) -> dict:
        """Return a thread-safe camera/host health snapshot for remote status."""
        with self._health_lock:
            snapshot = dict(self._health)
        snapshot["connected"] = self.is_connected
        return snapshot

    def storage_ready(self) -> tuple[bool, str]:
        """Refuse a new session before host storage becomes dangerously full."""
        try:
            free_bytes = shutil.disk_usage(self._download_dir).free
        except OSError as exc:
            return False, f"cannot read photo disk free space: {exc}"
        minimum = self._minimum_free_disk_bytes()
        self._update_health(
            disk_free_bytes=free_bytes,
            disk_minimum_bytes=minimum,
        )
        if free_bytes < minimum:
            return False, (
                f"photo disk space is low: {self._format_gib(free_bytes)} free, "
                f"minimum {self._format_gib(minimum)}"
            )
        return True, ""

    def take_picture(self, tag: str = ""):
        """Queue a capture command."""
        if self.is_connected:
            self._cmd_queue.put(("capture", tag))

    def start_live_view(self):
        if self.is_connected:
            self._cmd_queue.put(("start_evf",))

    def stop_live_view(self):
        if self.is_connected:
            self._cmd_queue.put(("stop_evf",))

    # --- Internal: runs on dedicated EDSDK thread ---

    def _run(self):
        """Own COM and one EDSDK lifetime while reconnecting camera sessions."""
        retry_delay = 0
        try:
            self._initialize_com()
            self._sdk = ctypes.WinDLL(self._dll_path)
            self._setup_sdk_functions()
            self._init_sdk()

            while self._running:
                if retry_delay:
                    log.info("Camera: next automatic search in %ds", retry_delay)
                    self._retry_event.wait(timeout=retry_delay)
                self._retry_event.clear()
                if not self._running:
                    break

                self._discard_commands()
                log.info("Camera: search started")
                reached_ready = False
                try:
                    self._connect_camera()
                    self._configure_for_photobooth()
                    self._register_handlers()
                    self._connected = True
                    self._failure_notified = False
                    self._update_health(connected=True)
                    reached_ready = True
                    log.info("Camera ready")
                    if self._connected_cb:
                        self._connected_cb()
                    self._run_connected()
                except EDSDKError as exc:
                    if self._running:
                        log.warning("Camera EDSDK operation failed: %s", exc)
                        self._mark_disconnected(
                            str(exc),
                            transport_lost=exc.code in FATAL_TRANSPORT_ERRORS,
                        )
                except RuntimeError as exc:
                    if self._running:
                        log.warning("Camera search failed: %s", exc)
                        self._mark_disconnected(str(exc))
                except Exception as exc:
                    if self._running:
                        log.exception("Camera connection failed")
                        # ctypes access violations and other unexpected errors
                        # while a session is active make further remote cleanup
                        # unsafe. EdsRelease is still required for our ref.
                        self._mark_disconnected(
                            str(exc), transport_lost=self._session_open)
                finally:
                    self._connected = False
                    self._update_health(connected=False)
                    self._cleanup_camera()

                if reached_ready:
                    # A runtime USB disconnect gets one immediate retry.
                    retry_delay = 0
                elif retry_delay:
                    retry_delay = min(retry_delay * 2, RECONNECT_MAX_SECONDS)
                else:
                    retry_delay = RECONNECT_MIN_SECONDS
        except Exception as exc:
            if self._running:
                log.exception("EDSDK worker initialization failed")
                self._mark_disconnected(str(exc))
        finally:
            self._connected = False
            self._update_health(connected=False)
            self._cleanup_camera()
            self._terminate_sdk()
            self._sdk = None
            self._uninitialize_com()
            self._discard_commands()
            log.info("EDSDK thread stopped")

    def _initialize_com(self):
        """Initialize the dedicated EDSDK thread as a COM STA."""
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx.restype = ctypes.c_long
        result = int(ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED))
        code = result & 0xFFFFFFFF
        if code not in (S_OK, S_FALSE):
            detail = " (thread already uses another COM apartment)" \
                if code == RPC_E_CHANGED_MODE else ""
            raise RuntimeError(f"CoInitializeEx failed: 0x{code:08X}{detail}")
        self._ole32 = ole32
        self._com_initialized = True
        log.info("Camera COM apartment initialized")

    def _uninitialize_com(self):
        if not self._com_initialized or not self._ole32:
            return
        try:
            self._ole32.CoUninitialize()
        finally:
            self._com_initialized = False
            self._ole32 = None
        log.info("Camera COM apartment uninitialized")

    def _run_connected(self):
        evf_active = False
        now = time.monotonic()
        next_health_log = now + CAMERA_HEALTH_LOG_SECONDS
        log.info(
            "Camera auto-off protection active: Auto Power Off disabled; "
            "shutdown timer is extended only after a Canon warning")
        while self._running and self._connected:
            _check("EdsGetEvent", self._sdk.EdsGetEvent())
            # The shutdown callback runs synchronously inside EdsGetEvent().
            # Do not execute one final queued command against a camera that the
            # callback has just marked as disconnected.
            if not self._connected:
                break

            try:
                cmd = self._cmd_queue.get_nowait()
                log.info(f"CMD: {cmd[0]}")
                if cmd[0] == "capture":
                    self._photo_tag = cmd[1] if len(cmd) > 1 else ""
                    try:
                        self._do_capture()
                    except EDSDKError as exc:
                        if exc.code in FATAL_TRANSPORT_ERRORS:
                            self._mark_disconnected(
                                str(exc), transport_lost=True)
                        else:
                            log.exception("Capture exception")
                    except Exception:
                        log.exception("Capture exception")
                elif cmd[0] == "start_evf":
                    self._do_start_evf()
                    evf_active = True
                elif cmd[0] == "stop_evf":
                    self._do_stop_evf()
                    evf_active = False
            except Empty:
                pass

            self._process_property_updates()

            if evf_active and self._evf_frame_cb:
                frame = self._download_evf_frame()
                if frame:
                    self._evf_frame_cb(frame)

            now = time.monotonic()
            if now >= next_health_log:
                self._log_camera_health()
                next_health_log = now + CAMERA_HEALTH_LOG_SECONDS

            time.sleep(0.03)

    def _extend_shutdown_timer(self, reason: str) -> int:
        err = self._sdk.EdsSendCommand(
            self._camera, kEdsCameraCommand_ExtendShutDownTimer, 0)
        self._update_health(
            last_shutdown_timer_extension_at=self._utc_now(),
            last_shutdown_timer_extension_result=(
                "ok" if err == EDS_ERR_OK
                else f"0x{err:08X} {edsdk_error_name(err)}"
            ),
        )
        if err == EDS_ERR_OK:
            log.info("Camera shutdown timer extended: %s", reason)
        else:
            log.warning(
                "Camera shutdown timer extension failed (%s): 0x%08X %s",
                reason, err, edsdk_error_name(err),
            )
            if err in FATAL_TRANSPORT_ERRORS:
                self._mark_disconnected(
                    f"Shutdown timer transport failure: "
                    f"0x{err:08X} {edsdk_error_name(err)}",
                    transport_lost=True,
                )
        return err

    def _discard_commands(self):
        discarded = 0
        while True:
            try:
                self._cmd_queue.get_nowait()
                discarded += 1
            except Empty:
                break
        if discarded:
            log.info("Camera: discarded %d stale commands", discarded)

    def _mark_disconnected(self, reason: str, *, transport_lost: bool = False):
        if transport_lost:
            self._transport_lost = True
        was_connected = self._connected
        self._connected = False
        if was_connected:
            self._connection_generation += 1
        self._discard_commands()
        self._update_health(
            connected=False,
            last_disconnect_reason=reason,
            last_disconnect_at=self._utc_now(),
        )
        if not self._failure_notified:
            self._failure_notified = True
            log.warning("Camera disconnected: %s", reason)
            if self._error_cb:
                self._error_cb(reason)

    def _setup_sdk_functions(self):
        """Declare return/arg types for the SDK functions we use."""
        sdk = self._sdk

        for name, restype, argtypes in [
            ("EdsInitializeSDK", EdsError, []),
            ("EdsTerminateSDK", EdsError, []),
            ("EdsGetCameraList", EdsError, [ctypes.POINTER(EdsBaseRef)]),
            ("EdsGetChildCount", EdsError, [EdsBaseRef, ctypes.POINTER(EdsUInt32)]),
            ("EdsGetChildAtIndex", EdsError, [EdsBaseRef, EdsInt32, ctypes.POINTER(EdsBaseRef)]),
            ("EdsGetDeviceInfo", EdsError, [EdsBaseRef, ctypes.POINTER(EdsDeviceInfo)]),
            ("EdsOpenSession", EdsError, [EdsBaseRef]),
            ("EdsCloseSession", EdsError, [EdsBaseRef]),
            ("EdsSendCommand", EdsError, [EdsBaseRef, EdsUInt32, EdsInt32]),
            ("EdsSendStatusCommand", EdsError, [EdsBaseRef, EdsUInt32, EdsInt32]),
            ("EdsGetPropertySize", EdsError, [EdsBaseRef, EdsUInt32, EdsInt32, ctypes.POINTER(EdsUInt32), ctypes.POINTER(EdsUInt32)]),
            ("EdsSetPropertyData", EdsError, [EdsBaseRef, EdsUInt32, EdsInt32, EdsUInt32, ctypes.c_void_p]),
            ("EdsGetPropertyData", EdsError, [EdsBaseRef, EdsUInt32, EdsInt32, EdsUInt32, ctypes.c_void_p]),
            ("EdsGetPropertyDesc", EdsError, [EdsBaseRef, EdsUInt32, ctypes.POINTER(EdsPropertyDesc)]),
            ("EdsSetCapacity", EdsError, [EdsBaseRef, EdsCapacity]),
            ("EdsCreateMemoryStream", EdsError, [EdsUInt64, ctypes.POINTER(EdsBaseRef)]),
            # The non-Ex API accepts an ANSI EdsChar path.  The Windows Ex API
            # accepts WCHAR and therefore also works when the install or user
            # profile path contains Cyrillic characters.
            ("EdsCreateFileStreamEx", EdsError, [
                ctypes.c_wchar_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(EdsBaseRef),
            ]),
            ("EdsCreateEvfImageRef", EdsError, [EdsBaseRef, ctypes.POINTER(EdsBaseRef)]),
            ("EdsDownloadEvfImage", EdsError, [EdsBaseRef, EdsBaseRef]),
            ("EdsGetPointer", EdsError, [EdsBaseRef, ctypes.POINTER(ctypes.c_void_p)]),
            ("EdsGetLength", EdsError, [EdsBaseRef, ctypes.POINTER(EdsUInt64)]),
            ("EdsGetDirectoryItemInfo", EdsError, [EdsBaseRef, ctypes.POINTER(EdsDirectoryItemInfo)]),
            ("EdsDownload", EdsError, [EdsBaseRef, EdsUInt64, EdsBaseRef]),
            ("EdsDownloadComplete", EdsError, [EdsBaseRef]),
            ("EdsDownloadCancel", EdsError, [EdsBaseRef]),
            ("EdsRelease", EdsUInt32, [EdsBaseRef]),
            ("EdsGetEvent", EdsError, []),
            ("EdsSetObjectEventHandler", EdsError, [EdsBaseRef, EdsUInt32, OBJECT_EVENT_HANDLER, ctypes.c_void_p]),
            ("EdsSetCameraStateEventHandler", EdsError, [EdsBaseRef, EdsUInt32, STATE_EVENT_HANDLER, ctypes.c_void_p]),
            ("EdsSetPropertyEventHandler", EdsError, [EdsBaseRef, EdsUInt32, PROPERTY_EVENT_HANDLER, ctypes.c_void_p]),
        ]:
            fn = getattr(sdk, name)
            fn.restype = restype
            fn.argtypes = argtypes

    def _init_sdk(self):
        if self._sdk_initialized:
            return
        _check("EdsInitializeSDK", self._sdk.EdsInitializeSDK())
        self._sdk_initialized = True
        log.info("EDSDK initialized")

    def _terminate_sdk(self):
        if not self._sdk_initialized or not self._sdk:
            return
        try:
            err = self._sdk.EdsTerminateSDK()
            if err != EDS_ERR_OK:
                log.warning(
                    "EdsTerminateSDK failed: 0x%08X %s",
                    err, edsdk_error_name(err),
                )
        except Exception:
            log.exception("EdsTerminateSDK raised during worker shutdown")
        finally:
            self._sdk_initialized = False
        log.info("EDSDK terminated")

    def _connect_camera(self):
        """Open a session using fresh camera refs without restarting EDSDK."""
        self._transport_lost = False
        last_error = None
        for attempt in range(1, 6):
            self._camera = self._acquire_camera()
            try:
                self._enable_limited_properties()
                err = self._sdk.EdsOpenSession(self._camera)
                if err == EDS_ERR_OK:
                    self._session_open = True
                    log.info("Session opened")
                    return
                last_error = err
                log.warning(
                    "OpenSession attempt %d/5 failed: 0x%08X %s",
                    attempt, err, edsdk_error_name(err),
                )
            finally:
                if not self._session_open:
                    camera = self._camera
                    self._camera = EdsBaseRef()
                    if camera:
                        self._sdk.EdsRelease(camera)
            if attempt < 5:
                # Make OpenSession backoff interruptible so application
                # shutdown never waits through all five attempts.
                self._retry_event.wait(timeout=2)
                self._retry_event.clear()
                if not self._running:
                    raise RuntimeError("Camera worker is stopping")

        raise RuntimeError(
            "Failed to open camera session after 5 attempts"
            + (f": 0x{last_error:08X} {edsdk_error_name(last_error)}"
               if last_error is not None else "")
        )

    def _acquire_camera(self) -> EdsBaseRef:
        camera_list = EdsBaseRef()
        _check("EdsGetCameraList", self._sdk.EdsGetCameraList(ctypes.byref(camera_list)))

        try:
            count = EdsUInt32()
            _check("EdsGetChildCount", self._sdk.EdsGetChildCount(camera_list, ctypes.byref(count)))
            if count.value == 0:
                raise RuntimeError("No camera found")

            camera = EdsBaseRef()
            _check("EdsGetChildAtIndex", self._sdk.EdsGetChildAtIndex(
                camera_list, 0, ctypes.byref(camera)))
        finally:
            if camera_list:
                self._sdk.EdsRelease(camera_list)

        info = EdsDeviceInfo()
        try:
            _check("EdsGetDeviceInfo", self._sdk.EdsGetDeviceInfo(
                camera, ctypes.byref(info)))
        except Exception:
            self._sdk.EdsRelease(camera)
            raise
        model = self._decode_c_string(info.szDeviceDescription)
        port = self._decode_c_string(info.szPortName)
        self._update_health(model=model, port=port)
        log.info("Camera: %s (port=%s)", model or "unknown", port or "unknown")
        return camera

    def _enable_limited_properties(self):
        """Enable EOS R limited properties that Canon requires before OpenSession."""
        for prop_id, key in [
            (kEdsPropID_TempStatus, 0x14840DF1),
            (kEdsPropID_ContinuousAfMode, 0x32F87FF6),
            (kEdsPropID_AutoPowerOffSetting, 0x1C31565B),
            (kEdsPropID_AFEyeDetect, 0x7C89405C),
            (kEdsPropID_Evf_ViewType, 0x7CBD2BB7),
            (kEdsPropID_ShutterType, 0x4C157D57),
            (kEdsPropID_AFTrackingObject, 0x0C78510D),
        ]:
            val = EdsUInt32(prop_id)
            err = self._sdk.EdsSetPropertyData(
                self._camera, kEdsPropID_EnableProperty, key,
                ctypes.sizeof(val), ctypes.byref(val))
            if err != EDS_ERR_OK:
                log.warning(f"EnableProp(0x{prop_id:08X}) failed: 0x{err:08X} (skipping)")

    def _configure_for_photobooth(self):
        # Load camera config
        import json
        from ..config import ROOT_DIR
        config_path = ROOT_DIR / "config_camera.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        else:
            cfg = {}
            log.warning("config_camera.json not found, using defaults")
        self._cfg = cfg

        storage_ok, storage_error = self.storage_ready()
        if not storage_ok:
            raise RuntimeError(storage_error)

        # Canon section 6.19: 0 disables/locks the physical mode dial and 1
        # cancels that state. Lock it before using AEModeSelect.
        if cfg.get("lock_mode_dial", True):
            err = self._retry_optional_command(
                "lock camera mode dial",
                lambda: self._sdk.EdsSendCommand(
                    self._camera, kEdsCameraCommand_SetModeDialDisable, 0),
            )
            if err == EDS_ERR_OK:
                self._mode_dial_locked = True
                log.info("Camera mode dial locked")

        # This is the primary protection for an unattended booth. The
        # If Canon still emits WillSoonShutDown, its event handler extends the
        # timer once in direct response to that warning.
        if cfg.get("disable_auto_power_off", True):
            err = self._disable_auto_power_off()
            if err == EDS_ERR_OK:
                log.info("Camera auto power-off disabled")
            else:
                log.warning(
                    "Camera auto power-off could not be disabled; "
                    "Canon shutdown warnings will still be handled")
        else:
            log.warning("Camera auto power-off protection disabled by config")

        # Save photos to host PC
        self._set_prop_u32(kEdsPropID_SaveTo, kEdsSaveTo_Host)
        free_bytes = shutil.disk_usage(self._download_dir).free
        bytes_per_sector = 0x1000
        free_clusters = min(free_bytes // bytes_per_sector, 0x7FFFFFFF)
        capacity = EdsCapacity(
            numberOfFreeClusters=max(1, free_clusters),
            bytesPerSector=bytes_per_sector,
            reset=1,
        )
        _check("EdsSetCapacity", self._sdk.EdsSetCapacity(self._camera, capacity))
        log.info("Camera host capacity set from disk free=%s", self._format_gib(free_bytes))

        self._configure_ae_mode(cfg)

        # Shutter type - required for flash sync on EOS R8. Avoid electronic/silent shutter.
        shutter_type = self._mapped_config_value(
            cfg, "shutter_type", SHUTTER_TYPE_MAP, "electronic_first_curtain")
        if shutter_type is not None:
            self._set_prop_u32(kEdsPropID_ShutterType, shutter_type)

        # Image quality
        q = self._mapped_config_value(
            cfg, "image_quality", IMAGE_QUALITY_MAP, "jpeg_large_fine")
        if q is not None:
            self._set_prop_u32(kEdsPropID_ImageQuality, q)

        # AE Mode - set on camera dial manually (SDK can't override the physical dial)
        # ae = AE_MODE_MAP.get(cfg.get("ae_mode", "manual"), 0x03)
        # self._set_prop_u32(kEdsPropID_AEMode, ae)

        # Aperture / shutter speed / ISO. config_camera.json keeps the human
        # readable value; an unsupported value is logged instead of silently
        # leaving the camera on whatever the body had before.
        for label, prop_id, resolver, default in (
            ("av", kEdsPropID_Av, resolve_av, "5.6"),
            ("tv", kEdsPropID_Tv, resolve_tv, "1/125"),
            ("iso", kEdsPropID_ISOSpeed, resolve_iso, 400),
        ):
            raw = cfg.get(label, default)
            resolved = resolver(raw)
            if resolved is None:
                log.error(
                    "Unsupported %s=%r in config_camera.json; camera keeps its "
                    "current value", label, raw,
                )
                continue
            self._set_prop_u32(prop_id, resolved[1])

        # White balance
        wb = self._mapped_config_value(
            cfg, "white_balance", WHITE_BALANCE_MAP, "auto")
        if wb is not None:
            self._set_prop_u32(kEdsPropID_WhiteBalance, wb)

        # Color temperature (only if white_balance = color_temp)
        if cfg.get("white_balance") == "color_temp":
            self._set_prop_u32(
                kEdsPropID_ColorTemperature,
                int(self._numeric_config_value(cfg, "color_temperature", 5200)),
            )

        # Picture style
        ps = self._mapped_config_value(
            cfg, "picture_style", PICTURE_STYLE_MAP, "standard")
        if ps is not None:
            self._set_prop_u32(kEdsPropID_PictureStyle, ps)

        # Color space
        cs = self._mapped_config_value(cfg, "color_space", COLOR_SPACE_MAP, "srgb")
        if cs is not None:
            self._set_prop_u32(kEdsPropID_ColorSpace, cs)

        # Drive mode
        self._set_prop_u32(kEdsPropID_DriveMode, kEdsDriveMode_Single)

        # AF operation mode
        af_mode = self._mapped_config_value(cfg, "af_mode", AF_MODE_MAP, "servo")
        if af_mode is not None:
            self._set_prop_u32(kEdsPropID_AFMode, af_mode)

        # EVF AF mode (face tracking, zone, etc.)
        evf_af_mode = self._mapped_config_value(
            cfg, "evf_af_mode", EVF_AF_MODE_MAP, "face_tracking")
        if evf_af_mode is not None:
            self._set_prop_u32(kEdsPropID_Evf_AFMode, evf_af_mode)

        # Subject detection
        subject = self._mapped_config_value(
            cfg, "subject_tracking", AF_TRACKING_OBJECT_MAP, "people")
        if subject is not None:
            self._set_prop_u32(kEdsPropID_AFTrackingObject, subject)

        # Live view exposure simulation. "disable" keeps preview usable in dark flash setups.
        evf_view_type = self._mapped_config_value(
            cfg, "evf_view_type", EVF_VIEW_TYPE_MAP, "disable")
        if evf_view_type is not None:
            self._set_prop_u32(kEdsPropID_Evf_ViewType, evf_view_type)

        # Continuous preview AF keeps tracking the selected person/eye during
        # live view, including while the countdown is running.
        self._set_prop_u32(
            kEdsPropID_ContinuousAfMode,
            1 if cfg.get("continuous_af", True) else 0,
        )

        # Eye detection is independent from the AF area on current EOS R
        # bodies. WholeArea + People + EyeDetect is the R8 tracking setup.
        self._set_prop_u32(
            kEdsPropID_AFEyeDetect,
            1 if cfg.get("eye_detection_af", True) else 0,
        )

        # Lock camera UI
        if cfg.get("lock_camera_ui", True):
            err = self._retry_optional_command(
                "lock camera UI",
                lambda: self._sdk.EdsSendStatusCommand(
                    self._camera, kEdsCameraStatusCommand_UILock, 0),
            )
            if err == EDS_ERR_OK:
                self._ui_locked = True

        self._read_camera_identity()
        log.info("Camera configured from config_camera.json")
        self._log_applied_config()
        self._log_camera_health()

    def _retry_optional_command(self, label: str, operation, attempts: int = 3) -> int:
        """Retry optional body locks while Canon finishes property updates."""
        retryable = {
            EDS_ERR_DEVICE_BUSY,
            EDS_ERR_PTP_DEVICE_BUSY,
            EDS_ERR_OBJECT_NOTREADY,
        }
        err = EDS_ERR_OK
        for attempt in range(1, attempts + 1):
            err = operation()
            if err == EDS_ERR_OK:
                return err
            if err in FATAL_TRANSPORT_ERRORS:
                raise EDSDKError(label, err)
            if err not in retryable or attempt == attempts:
                break
            event_err = self._sdk.EdsGetEvent()
            if event_err in FATAL_TRANSPORT_ERRORS:
                raise EDSDKError(f"{label}/EdsGetEvent", event_err)
            if event_err != EDS_ERR_OK:
                # An event-pump failure is not the optional lock command's
                # result.  Abort this setup attempt, but allow normal session
                # cleanup unless the code explicitly denotes transport loss.
                raise EDSDKError(f"{label}/EdsGetEvent", event_err)
            time.sleep(0.15 * attempt)
        log.warning(
            "Could not %s after %d attempt(s): 0x%08X %s",
            label, attempt, err, edsdk_error_name(err),
        )
        return err

    def _disable_auto_power_off(self) -> int:
        offered = self._get_property_desc(kEdsPropID_AutoPowerOffSetting)
        if offered is not None and kEdsAutoPowerOff_Disable not in offered:
            log.warning(
                "Camera does not offer AutoPowerOff=Off; available=%s", offered)
            return EDS_ERR_INVALID_DEVICEPROP_VALUE
        err = self._set_prop_u32(
            kEdsPropID_AutoPowerOffSetting,
            kEdsAutoPowerOff_Disable,
            validate=False,
        )
        if err == EDS_ERR_OK:
            actual = self._get_prop_u32(kEdsPropID_AutoPowerOffSetting)
            if actual != kEdsAutoPowerOff_Disable:
                log.warning(
                    "Camera AutoPowerOff readback mismatch: requested=off actual=%s",
                    self._format_auto_power_off(actual),
                )
                return EDS_ERR_PROPERTIES_MISMATCH
        return err

    def _configure_ae_mode(self, cfg: dict) -> None:
        requested_name = str(cfg.get("ae_mode", "manual"))
        requested = AE_MODE_MAP.get(requested_name)
        actual = self._get_prop_u32(kEdsPropID_AEMode)
        if requested is None:
            log.warning("Unknown ae_mode=%r; camera reports 0x%X", requested_name, actual or 0)
            return
        if actual != requested and self._mode_dial_locked:
            offered = self._get_property_desc(kEdsPropID_AEModeSelect)
            if offered is not None and requested in offered:
                self._set_prop_u32(
                    kEdsPropID_AEModeSelect, requested, validate=False)
                actual = self._get_prop_u32(kEdsPropID_AEMode)
        self._update_health(ae_mode=(
            self._name_from_map(AE_MODE_MAP, actual) if actual is not None
            else "unavailable"
        ))
        if actual != requested:
            log.error(
                "Camera AE mode mismatch: requested=%s actual=%s. "
                "Set the physical dial to %s before the event.",
                requested_name,
                self._name_from_map(AE_MODE_MAP, actual) if actual is not None else "unavailable",
                requested_name.upper(),
            )

    def _get_property_desc(self, prop_id: int) -> list[int] | None:
        desc = EdsPropertyDesc()
        err = self._sdk.EdsGetPropertyDesc(
            self._camera, prop_id, ctypes.byref(desc))
        if err != EDS_ERR_OK:
            if err not in OPTIONAL_PROPERTY_ERRORS:
                log.warning(
                    "GetPropertyDesc(0x%08X) failed: 0x%08X %s",
                    prop_id, err, edsdk_error_name(err),
                )
            return None
        count = min(max(desc.numElements, 0), len(desc.propDesc))
        return [ctypes.c_uint32(desc.propDesc[index]).value
                for index in range(count)]

    def _set_prop_u32(self, prop_id: int, value: int, *, validate: bool = True):
        if validate:
            offered = self._get_property_desc(prop_id)
            if offered is not None and offered and value not in offered:
                log.warning(
                    "SetProp(0x%08X) skipped: requested=0x%X available=%s",
                    prop_id, value, [f"0x{item:X}" for item in offered],
                )
                return EDS_ERR_INVALID_DEVICEPROP_VALUE
        val = EdsUInt32(value)
        err = self._sdk.EdsSetPropertyData(
            self._camera, prop_id, 0, ctypes.sizeof(val), ctypes.byref(val))
        if err != EDS_ERR_OK:
            log.warning(
                "SetProp(0x%08X)=0x%X failed: 0x%08X %s (skipping)",
                prop_id, value, err, edsdk_error_name(err),
            )
        return err

    def _get_prop_u32(self, prop_id: int) -> int | None:
        val = EdsUInt32()
        err = self._sdk.EdsGetPropertyData(
            self._camera, prop_id, 0, ctypes.sizeof(val), ctypes.byref(val))
        if err != EDS_ERR_OK:
            if err not in OPTIONAL_PROPERTY_ERRORS:
                log.warning(
                    "GetProp(0x%08X) failed: 0x%08X %s",
                    prop_id, err, edsdk_error_name(err),
                )
            return None
        return val.value

    def _get_prop_string(self, prop_id: int) -> str | None:
        data_type = EdsUInt32()
        size = EdsUInt32()
        err = self._sdk.EdsGetPropertySize(
            self._camera, prop_id, 0,
            ctypes.byref(data_type), ctypes.byref(size),
        )
        if err != EDS_ERR_OK or not 0 < size.value <= 4096:
            return None
        value = ctypes.create_string_buffer(size.value)
        err = self._sdk.EdsGetPropertyData(
            self._camera, prop_id, 0, size.value, ctypes.byref(value))
        if err != EDS_ERR_OK:
            return None
        return self._decode_c_string(value.raw)

    def _read_camera_identity(self) -> None:
        identity = {
            "product_name": self._get_prop_string(kEdsPropID_ProductName),
            "serial": self._get_prop_string(kEdsPropID_BodyIDEx),
            "firmware": self._get_prop_string(kEdsPropID_FirmwareVersion),
            "lens": self._get_prop_string(kEdsPropID_LensName),
        }
        self._update_health(**{
            key: value for key, value in identity.items() if value
        })
        log.info(
            "Camera identity: product=%s serial=%s firmware=%s lens=%s",
            identity["product_name"] or "unavailable",
            identity["serial"] or "unavailable",
            identity["firmware"] or "unavailable",
            identity["lens"] or "unavailable",
        )

    @staticmethod
    def _name_from_map(mapping: dict, value: int) -> str:
        for name, mapped in mapping.items():
            if mapped == value:
                return str(name)
        return f"0x{value:X}"

    @staticmethod
    def _mapped_config_value(cfg: dict, field: str, mapping: dict, default):
        """EDSDK code for a named config value.

        A value the map does not know is reported and skipped. Silently
        substituting the default would make the camera disagree with
        config_camera.json without any trace in the log.
        """
        raw = cfg.get(field, default)
        code = mapping.get(raw)
        if code is None and isinstance(raw, str):
            code = mapping.get(raw.strip().casefold())
        if code is None:
            log.error(
                "Unsupported %s=%r in config_camera.json; camera keeps its "
                "current value", field, raw,
            )
        return code

    @staticmethod
    def _numeric_config_value(cfg: dict, field: str, default: float) -> float:
        """Numeric config value checked against its documented range.

        Telegram updates are validated before they are stored, but a manually
        edited or older config file can still hold an out-of-range number.
        """
        raw = cfg.get(field, default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            log.error(
                "Invalid %s=%r in config_camera.json; using %r",
                field, raw, default)
            return float(default)
        if numeric_range_error(field, value) is not None:
            minimum, maximum, _ = CAMERA_NUMERIC_RANGES[field]
            clamped = min(max(value, minimum), maximum)
            log.error(
                "Out-of-range %s=%r in config_camera.json; using %r "
                "(allowed %s..%s)", field, raw, clamped, minimum, maximum)
            return clamped
        return value

    # Every camera-side field that can be read back, in log/report order.
    _CONFIG_READBACK = (
        ("AE", kEdsPropID_AEMode, "ae_mode", "manual", AE_MODE_MAP),
        ("ShutterType", kEdsPropID_ShutterType, "shutter_type",
         "electronic_first_curtain", SHUTTER_TYPE_MAP),
        ("ImageQuality", kEdsPropID_ImageQuality, "image_quality",
         "jpeg_large_fine", IMAGE_QUALITY_MAP),
        ("Av", kEdsPropID_Av, "av", "5.6", AV_MAP),
        ("Tv", kEdsPropID_Tv, "tv", "1/125", TV_MAP),
        ("ISO", kEdsPropID_ISOSpeed, "iso", 400, ISO_MAP),
        ("WhiteBalance", kEdsPropID_WhiteBalance, "white_balance",
         "auto", WHITE_BALANCE_MAP),
        ("ColorTemperature", kEdsPropID_ColorTemperature, "color_temperature",
         5200, None),
        ("PictureStyle", kEdsPropID_PictureStyle, "picture_style",
         "standard", PICTURE_STYLE_MAP),
        ("ColorSpace", kEdsPropID_ColorSpace, "color_space", "srgb",
         COLOR_SPACE_MAP),
        ("DriveMode", kEdsPropID_DriveMode, "drive_mode", "single",
         DRIVE_MODE_MAP),
        ("AFMode", kEdsPropID_AFMode, "af_mode", "servo", AF_MODE_MAP),
        ("EvfAFMode", kEdsPropID_Evf_AFMode, "evf_af_mode", "face_tracking",
         EVF_AF_MODE_MAP),
        ("Subject", kEdsPropID_AFTrackingObject, "subject_tracking", "people",
         AF_TRACKING_OBJECT_MAP),
        ("EyeDetect", kEdsPropID_AFEyeDetect, "eye_detection_af", True,
         ENABLE_DISABLE_MAP),
        ("ContinuousAF", kEdsPropID_ContinuousAfMode, "continuous_af", True,
         ENABLE_DISABLE_MAP),
        ("EvfViewType", kEdsPropID_Evf_ViewType, "evf_view_type", "disable",
         EVF_VIEW_TYPE_MAP),
        ("AutoPowerOff", kEdsPropID_AutoPowerOffSetting,
         "disable_auto_power_off", True, None),
    )

    # These never reach EDSDK, so they are reported straight from the config.
    _HOST_ONLY_FIELDS = (
        ("FocusBeforeCapture", "focus_before_capture", False),
        ("FocusDelay", "focus_delay", 0.4),
        ("MinFreeDisk", "min_free_disk_gib", MIN_FREE_DISK_GIB),
        ("KeepCameraScreen", "evf_keep_camera_screen", False),
        ("LockCameraUI", "lock_camera_ui", True),
        ("LockModeDial", "lock_mode_dial", True),
    )

    def _requested_code(self, field: str, default, mapping: dict | None):
        """EDSDK code the config asks for, or None when it cannot be mapped."""
        resolver = CAMERA_VALUE_RESOLVERS.get(field)
        raw = self._cfg.get(field, default)
        if resolver is not None:
            return resolved_code(resolver, raw)
        if field == "disable_auto_power_off":
            return kEdsAutoPowerOff_Disable if bool(raw) else None
        if field in CAMERA_NUMERIC_RANGES:
            return int(self._numeric_config_value(self._cfg, field, default))
        if mapping is ENABLE_DISABLE_MAP:
            return 1 if bool(raw) else 0
        if mapping is None:
            return None
        code = mapping.get(raw)
        if code is None and isinstance(raw, str):
            code = mapping.get(raw.strip().casefold())
        return code

    def _format_readback(self, label: str, value: int | None,
                         mapping: dict | None) -> str:
        if value is None:
            return "unavailable"
        if label == "AutoPowerOff":
            return self._format_auto_power_off(value)
        if mapping is None:
            return str(value)
        return self._name_from_map(mapping, value)

    def build_config_report(self) -> dict:
        """Camera-side settings read back from the body plus host-only fields.

        The startup log, the remote status command and the report pushed to the
        administrator all use this, so the three can never disagree.
        """
        entries: list[dict] = []
        for label, prop_id, field, default, mapping in self._CONFIG_READBACK:
            if (field == "color_temperature"
                    and self._cfg.get("white_balance") != "color_temp"):
                continue
            actual = self._get_prop_u32(prop_id)
            requested = self._requested_code(field, default, mapping)
            entries.append({
                "label": label,
                "field": field,
                "requested": self._cfg.get(field, default),
                "actual": self._format_readback(label, actual, mapping),
                "available": actual is not None,
                "verifiable": requested is not None,
                "matches": (actual is not None and requested is not None
                            and actual == requested),
            })
        host = [
            {"label": label, "field": field,
             "value": self._cfg.get(field, default)}
            for label, field, default in self._HOST_ONLY_FIELDS
        ]
        return {
            "camera": entries,
            "host": host,
            "mismatched": [entry["label"] for entry in entries
                           if entry["verifiable"] and entry["available"]
                           and not entry["matches"]],
            "unavailable": [entry["label"] for entry in entries
                            if not entry["available"]],
        }

    def _log_applied_config(self):
        """Read back every camera value so config/apply issues reach the log."""
        report = self.build_config_report()
        for entry in report["camera"]:
            if not entry["available"]:
                log.warning(
                    "Camera config unavailable %s: requested=%r; "
                    "camera did not report this property",
                    entry["label"], entry["requested"])
            elif entry["verifiable"] and not entry["matches"]:
                log.warning(
                    "Camera config mismatch %s: requested=%r actual=%s",
                    entry["label"], entry["requested"], entry["actual"])
        log.info("Camera applied config: " + ", ".join(
            f"{entry['label']}={entry['actual']}"
            for entry in report["camera"]))
        log.info("Camera host config: " + ", ".join(
            f"{entry['label']}={entry['value']!r}" for entry in report["host"]))
        self._update_health(
            config_report=report,
            config_report_at=self._utc_now(),
        )

    @staticmethod
    def _format_battery_level(value: int | None) -> str:
        if value is None:
            return "unavailable"
        if value == 0xFFFFFFFF:
            return "AC"
        if value == 0xFFFFFFFE:
            return "unknown"
        return str(value)

    @staticmethod
    def _format_auto_power_off(value: int | None) -> str:
        if value is None:
            return "unavailable"
        if value == kEdsAutoPowerOff_Disable:
            return "disabled"
        if value == 0xFFFFFFFF:
            return "shutdown"
        return f"{value}s"

    @staticmethod
    def _format_temperature_status(value: int | None) -> str:
        if value is None:
            return "unavailable"
        names = {
            0: "normal",
            1: "warning",
            2: "framerate_down",
            3: "liveview_disabled",
            4: "capture_disabled",
            5: "still_quality_warning",
        }
        still_status = value & 0xFFFF
        movie_status = (value >> 16) & 0xFFFF
        still_name = names.get(still_status, f"unknown_0x{still_status:04X}")
        if movie_status == 0:
            return still_name
        movie_name = "movie_restricted" if movie_status == 2 \
            else f"movie_unknown_0x{movie_status:04X}"
        return f"{still_name}+{movie_name}"

    @staticmethod
    def _decode_c_string(value) -> str:
        raw = bytes(value).split(b"\0", 1)[0]
        for encoding in ("utf-8", "mbcs", "latin-1"):
            try:
                return raw.decode(encoding).strip()
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _format_gib(value: int) -> str:
        return f"{value / (1024 ** 3):.2f} GiB"

    def _minimum_free_disk_bytes(self) -> int:
        minimum_gib = self._numeric_config_value(
            self._cfg, "min_free_disk_gib", MIN_FREE_DISK_GIB)
        return int(minimum_gib * (1024 ** 3))

    def _update_health(self, **values) -> None:
        with self._health_lock:
            self._health.update(values)

    def _log_camera_health(self):
        battery = self._get_prop_u32(kEdsPropID_BatteryLevel)
        battery_quality = self._get_prop_u32(kEdsPropID_BatteryQuality)
        auto_power_off = self._get_prop_u32(kEdsPropID_AutoPowerOffSetting)
        temperature = self._get_prop_u32(kEdsPropID_TempStatus)
        available_shots = self._get_prop_u32(kEdsPropID_AvailableShots)
        ae_mode = self._get_prop_u32(kEdsPropID_AEMode)
        try:
            disk_free = shutil.disk_usage(self._download_dir).free
        except OSError:
            disk_free = None
        self._update_health(
            battery=self._format_battery_level(battery),
            battery_quality=battery_quality,
            auto_power_off=self._format_auto_power_off(auto_power_off),
            temperature=self._format_temperature_status(temperature),
            available_shots=available_shots,
            ae_mode=(self._name_from_map(AE_MODE_MAP, ae_mode)
                     if ae_mode is not None else "unavailable"),
            disk_free_bytes=disk_free,
            last_health_at=self._utc_now(),
        )
        log.info(
            "Camera health: power=%s, quality=%s, auto_power_off=%s, "
            "temperature=%s, AE=%s, available_shots=%s, disk_free=%s",
            self._format_battery_level(battery),
            battery_quality if battery_quality is not None else "unavailable",
            self._format_auto_power_off(auto_power_off),
            self._format_temperature_status(temperature),
            self._name_from_map(AE_MODE_MAP, ae_mode)
            if ae_mode is not None else "unavailable",
            available_shots if available_shots is not None else "unavailable",
            self._format_gib(disk_free) if disk_free is not None else "unavailable",
        )

    def _process_property_updates(self) -> None:
        if not self._pending_property_updates:
            return
        changed = set(self._pending_property_updates)
        self._pending_property_updates.clear()
        if changed & {
            kEdsPropID_BatteryLevel,
            kEdsPropID_BatteryQuality,
            kEdsPropID_TempStatus,
            kEdsPropID_AutoPowerOffSetting,
        }:
            temperature = None
            if kEdsPropID_TempStatus in changed:
                temperature = self._get_prop_u32(kEdsPropID_TempStatus)
                formatted = self._format_temperature_status(temperature)
                if formatted != "normal":
                    log.warning("Camera temperature restriction changed: %s", formatted)
                else:
                    log.info("Camera temperature status returned to normal")
            self._log_camera_health()
        if changed & {
            kEdsPropID_ProductName,
            kEdsPropID_BodyIDEx,
            kEdsPropID_FirmwareVersion,
            kEdsPropID_LensName,
        }:
            self._read_camera_identity()

    def _register_handlers(self):
        def on_object_event(event, ref, context):
            log.info(f"ObjectEvent: 0x{event:08X}")
            try:
                if event == kEdsObjectEvent_DirItemRequestTransfer:
                    self._download_photo(ref)
            except EDSDKError as exc:
                if exc.code in FATAL_TRANSPORT_ERRORS:
                    self._mark_disconnected(
                        f"Photo transfer transport failure: {exc}",
                        transport_lost=True,
                    )
                log.exception("Download failed")
            except Exception:
                log.exception("Download failed")
            finally:
                if ref:
                    self._sdk.EdsRelease(ref)
            return 0

        def on_state_event(event, data, context):
            if event == kEdsStateEvent_WillSoonShutDown:
                log.warning("Camera will soon shut down: %ss remaining", data)
                self._extend_shutdown_timer(
                    f"Canon warning, {data}s remaining")
            elif event == kEdsStateEvent_ShutDownTimerUpdate:
                log.info("Camera shutdown timer extension accepted")
            elif event == kEdsStateEvent_CaptureError:
                log.warning("CaptureError: %d %s", data, capture_error_name(data))
            elif event == kEdsStateEvent_JobStatusChanged:
                log.info(
                    "Camera transfer jobs: %s",
                    "pending" if data == 1 else "none" if data == 0 else f"unknown({data})",
                )
            elif event == kEdsStateEvent_InternalError:
                log.critical("Camera reported EDSDK internal error; reconnecting")
                self._mark_disconnected(
                    "EDSDK internal camera error", transport_lost=True)
            elif event == kEdsStateEvent_Shutdown:
                self._mark_disconnected(
                    "Camera shutdown/disconnected", transport_lost=True)
            else:
                log.info("StateEvent: 0x%08X data=%d", event, data)
            return 0

        def on_property_event(event, prop_id, param, context):
            log.debug(
                "PropertyEvent: 0x%08X prop=0x%08X param=%d",
                event, prop_id, param,
            )
            if event in (
                kEdsPropertyEvent_PropertyChanged,
                kEdsPropertyEvent_PropertyDescChanged,
            ) and prop_id in {
                kEdsPropID_BatteryLevel,
                kEdsPropID_BatteryQuality,
                kEdsPropID_TempStatus,
                kEdsPropID_AutoPowerOffSetting,
                kEdsPropID_ProductName,
                kEdsPropID_BodyIDEx,
                kEdsPropID_FirmwareVersion,
                kEdsPropID_LensName,
            }:
                self._pending_property_updates.add(prop_id)
            return 0

        self._obj_handler_ref = OBJECT_EVENT_HANDLER(on_object_event)
        self._state_handler_ref = STATE_EVENT_HANDLER(on_state_event)
        self._prop_handler_ref = PROPERTY_EVENT_HANDLER(on_property_event)

        _check("SetObjectEventHandler", self._sdk.EdsSetObjectEventHandler(
            self._camera, kEdsObjectEvent_All, self._obj_handler_ref, None))
        _check("SetStateEventHandler", self._sdk.EdsSetCameraStateEventHandler(
            self._camera, kEdsStateEvent_All, self._state_handler_ref, None))
        _check("SetPropertyEventHandler", self._sdk.EdsSetPropertyEventHandler(
            self._camera, kEdsPropertyEvent_All, self._prop_handler_ref, None))

    def _do_start_evf(self):
        # Enable EVF mode
        evf_mode = EdsUInt32(1)
        _check("SetEvfMode", self._sdk.EdsSetPropertyData(
            self._camera, kEdsPropID_Evf_Mode, 0,
            ctypes.sizeof(evf_mode), ctypes.byref(evf_mode)))

        original = self._get_prop_u32(kEdsPropID_Evf_OutputDevice)
        self._evf_original_output = original if original is not None else 0
        keep_camera_screen = bool(self._cfg.get("evf_keep_camera_screen", False))
        output = kEdsEvfOutputDevice_PC
        if keep_camera_screen:
            output |= self._evf_original_output
        device = EdsUInt32(output)
        _check("SetEvfOutput", self._sdk.EdsSetPropertyData(
            self._camera, kEdsPropID_Evf_OutputDevice, 0,
            ctypes.sizeof(device), ctypes.byref(device)))
        log.info("Live view started")

    def _do_stop_evf(self):
        device = EdsUInt32(self._evf_original_output or 0)
        err = self._sdk.EdsSetPropertyData(
            self._camera, kEdsPropID_Evf_OutputDevice, 0,
            ctypes.sizeof(device), ctypes.byref(device))
        self._evf_original_output = None
        if err != EDS_ERR_OK:
            log.warning(
                "Stop live view output restore failed: 0x%08X %s",
                err, edsdk_error_name(err),
            )
        log.info("Live view stopped")

    def _download_evf_frame(self) -> bytes | None:
        """Download one live view JPEG frame. Returns None if not ready."""
        stream = EdsBaseRef()
        evf_image = EdsBaseRef()
        try:
            _check("CreateMemStream", self._sdk.EdsCreateMemoryStream(0, ctypes.byref(stream)))
            _check("CreateEvfRef", self._sdk.EdsCreateEvfImageRef(stream, ctypes.byref(evf_image)))

            err = self._sdk.EdsDownloadEvfImage(self._camera, evf_image)
            if err in (
                EDS_ERR_OBJECT_NOTREADY,
                EDS_ERR_DEVICE_BUSY,
                EDS_ERR_PTP_DEVICE_BUSY,
            ):
                return None  # Normal while the next frame is not ready yet.
            _check("DownloadEvfImage", err)

            length = EdsUInt64()
            _check("GetLength", self._sdk.EdsGetLength(stream, ctypes.byref(length)))

            ptr = ctypes.c_void_p()
            _check("GetPointer", self._sdk.EdsGetPointer(stream, ctypes.byref(ptr)))

            buf = (ctypes.c_ubyte * length.value)()
            ctypes.memmove(buf, ptr.value, length.value)
            return bytes(buf)
        finally:
            if evf_image:
                self._sdk.EdsRelease(evf_image)
            if stream:
                self._sdk.EdsRelease(stream)

    def _do_capture(self):
        t = self._photo_tag
        focus_before = bool(self._cfg.get("focus_before_capture", False))
        focus_delay = self._numeric_config_value(self._cfg, "focus_delay", 0.4)

        if focus_before:
            log.info(f"{t} Capture: half-press AF for {focus_delay:.1f}s")
            err = self._sdk.EdsSendCommand(
                self._camera, kEdsCameraCommand_PressShutterButton,
                kEdsCameraCommand_ShutterButton_Halfway)
            if err != EDS_ERR_OK:
                log.warning(
                    f"{t} Capture: half-press err=0x{err:08X} "
                    f"{edsdk_error_name(err)}")
                if err in FATAL_TRANSPORT_ERRORS:
                    self._mark_disconnected(
                        f"Capture transport failure: {edsdk_error_name(err)}",
                        transport_lost=True,
                    )
                    return
            end = time.monotonic() + focus_delay
            while time.monotonic() < end:
                event_err = self._sdk.EdsGetEvent()
                if event_err in FATAL_TRANSPORT_ERRORS:
                    self._mark_disconnected(
                        f"AF event transport failure: "
                        f"0x{event_err:08X} {edsdk_error_name(event_err)}",
                        transport_lost=True,
                    )
                    return
                if not self._connected:
                    return
                time.sleep(0.05)
            shutter_button = kEdsCameraCommand_ShutterButton_Completely
            log.info(f"{t} Capture: sending ShutterButton_Completely")
        else:
            shutter_button = kEdsCameraCommand_ShutterButton_Completely_NonAF
            log.info(f"{t} Capture: sending ShutterButton_Completely_NonAF")

        capture_succeeded = False
        for attempt in range(1, 4):
            if not self._connected:
                return
            err = self._sdk.EdsSendCommand(
                self._camera, kEdsCameraCommand_PressShutterButton,
                shutter_button)
            if err == EDS_ERR_OK:
                log.info(f"{t} Capture: shutter OK")
                capture_succeeded = True
                break
            log.warning(
                f"{t} Capture: attempt {attempt}/3 "
                f"err=0x{err:08X} {edsdk_error_name(err)}")
            if err in FATAL_TRANSPORT_ERRORS:
                self._mark_disconnected(
                    f"Capture transport failure: 0x{err:08X} {edsdk_error_name(err)}",
                    transport_lost=True,
                )
                return
            if err not in TRANSIENT_CAPTURE_ERRORS:
                log.error(
                    "%s Capture: permanent shooting/configuration error; not retrying",
                    t,
                )
                break
            if attempt == 3:
                break
            for _ in range(10):
                event_err = self._sdk.EdsGetEvent()
                if event_err in FATAL_TRANSPORT_ERRORS:
                    self._mark_disconnected(
                        f"Capture event transport failure: "
                        f"0x{event_err:08X} {edsdk_error_name(event_err)}",
                        transport_lost=True,
                    )
                    return
                if not self._connected:
                    return
                time.sleep(0.1)
        if not capture_succeeded:
            log.error(f"{t} Capture: FAILED")
        if not self._connected:
            return
        log.info(f"{t} Capture: sending ShutterButton_OFF")
        off_err = self._sdk.EdsSendCommand(
            self._camera, kEdsCameraCommand_PressShutterButton,
            kEdsCameraCommand_ShutterButton_OFF)
        if off_err != EDS_ERR_OK:
            log.warning(
                "%s Capture: ShutterButton_OFF failed: 0x%08X %s",
                t, off_err, edsdk_error_name(off_err),
            )
            if off_err in FATAL_TRANSPORT_ERRORS:
                self._mark_disconnected(
                    f"Shutter release transport failure: "
                    f"0x{off_err:08X} {edsdk_error_name(off_err)}",
                    transport_lost=True,
                )

    def _download_photo(self, dir_item):
        stream = EdsBaseRef()
        file_path = None
        completed = False
        try:
            storage_ok, storage_error = self.storage_ready()
            if not storage_ok:
                raise RuntimeError(storage_error)
            info = EdsDirectoryItemInfo()
            _check("GetDirItemInfo", self._sdk.EdsGetDirectoryItemInfo(
                dir_item, ctypes.byref(info)))

            file_name = Path(self._decode_c_string(info.szFileName)).name
            if not file_name:
                raise RuntimeError("camera supplied an empty photo filename")
            file_path = self._download_dir / file_name
            t = self._photo_tag
            log.info(f"{t} Photo download: {file_name} ({info.size} bytes)")

            _check("CreateFileStreamEx", self._sdk.EdsCreateFileStreamEx(
                str(file_path), kEdsFileCreateDisposition_CreateAlways,
                kEdsAccess_ReadWrite, ctypes.byref(stream)))
            _check("EdsDownload", self._sdk.EdsDownload(dir_item, info.size, stream))
            _check("EdsDownloadComplete", self._sdk.EdsDownloadComplete(dir_item))
            completed = True
            log.info(f"{t} Photo saved: {file_path}")
            if self._photo_cb:
                self._photo_cb(str(file_path))
        except Exception:
            if not completed:
                try:
                    cancel_err = self._sdk.EdsDownloadCancel(dir_item)
                    if cancel_err != EDS_ERR_OK:
                        log.warning(
                            "EdsDownloadCancel failed: 0x%08X %s",
                            cancel_err, edsdk_error_name(cancel_err),
                        )
                except Exception:
                    log.exception("EdsDownloadCancel raised")
                # Windows cannot remove an EDSDK-backed file while the stream
                # still owns its handle. Release it before deleting a partial.
                if stream:
                    self._sdk.EdsRelease(stream)
                    stream = EdsBaseRef()
                if file_path is not None:
                    try:
                        file_path.unlink(missing_ok=True)
                    except OSError:
                        log.exception("Could not remove partial photo: %s", file_path)
            raise
        finally:
            if stream:
                self._sdk.EdsRelease(stream)

    def _cleanup_camera(self):
        camera = self._camera
        self._camera = EdsBaseRef()
        session_open = self._session_open
        self._session_open = False
        transport_lost = self._transport_lost
        self._transport_lost = False
        if not camera or not self._sdk:
            return

        calls = []
        if session_open and self._ui_locked and not transport_lost:
            calls.append(("UI unlock", True, lambda: self._sdk.EdsSendStatusCommand(
                camera, kEdsCameraStatusCommand_UIUnLock, 0)))
        if session_open and self._mode_dial_locked and not transport_lost:
            # Canon section 6.19: 1 cancels the disabled/locked mode dial.
            calls.append(("mode dial unlock", True, lambda: self._sdk.EdsSendCommand(
                camera, kEdsCameraCommand_SetModeDialDisable, 1)))
        if session_open and not transport_lost:
            calls.append(("close session", True, lambda: self._sdk.EdsCloseSession(camera)))
        if session_open and transport_lost:
            log.info(
                "Camera transport is gone; skipping remote unlock/close calls")
        # EdsRelease returns a reference count, not EdsError.
        calls.append(("release camera", False, lambda: self._sdk.EdsRelease(camera)))

        for label, returns_error, cleanup_call in calls:
            try:
                err = cleanup_call()
                if returns_error and isinstance(err, int) and err != EDS_ERR_OK:
                    log.debug(
                        "Camera cleanup %s failed: 0x%08X %s",
                        label, err, edsdk_error_name(err),
                    )
            except Exception:
                log.debug("Camera cleanup %s raised", label, exc_info=True)
        self._ui_locked = False
        self._mode_dial_locked = False
        self._evf_original_output = None
        self._pending_property_updates.clear()
        self._obj_handler_ref = None
        self._state_handler_ref = None
        self._prop_handler_ref = None
        log.info("Camera session cleaned up")

    def _cleanup(self):
        """Backward-compatible per-camera cleanup; SDK lifetime is worker-wide."""
        self._cleanup_camera()
