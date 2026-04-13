"""Canon EDSDK wrapper via ctypes - Windows only.

Uses EdsGetEvent() polling (no Windows message pump needed).
All EDSDK calls must happen from the same thread that called EdsInitializeSDK().
"""

import ctypes
import ctypes.wintypes
import threading
import time
import logging
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


# Callback function types (EDSCALLBACK = __stdcall on Windows)
OBJECT_EVENT_HANDLER = ctypes.WINFUNCTYPE(EdsError, ctypes.c_uint32, EdsBaseRef, ctypes.c_void_p)
STATE_EVENT_HANDLER = ctypes.WINFUNCTYPE(EdsError, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
PROPERTY_EVENT_HANDLER = ctypes.WINFUNCTYPE(EdsError, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)


class EDSDKError(Exception):
    def __init__(self, func_name: str, code: int):
        self.code = code
        super().__init__(f"EDSDK {func_name} failed: 0x{code:08X}")


def _check(func_name: str, err: int):
    if err != EDS_ERR_OK:
        raise EDSDKError(func_name, err)


class Camera:
    """Manages a single Canon camera via EDSDK."""

    def __init__(self, dll_path: str | Path):
        self._dll_path = str(dll_path)
        self._sdk = None
        self._camera = EdsBaseRef()
        self._running = False
        self._connected = False
        self._thread: threading.Thread | None = None
        self._cmd_queue: Queue = Queue()
        self._evf_frame_cb = None  # callback(jpeg_bytes)
        self._photo_cb = None  # callback(file_path)
        self._error_cb = None  # callback(error_str)
        self._connected_cb = None  # callback()
        self._download_dir = Path("photos")

        # Must keep references to prevent GC of ctypes callbacks
        self._obj_handler_ref = None
        self._state_handler_ref = None

    def set_callbacks(self, on_evf_frame=None, on_photo=None, on_error=None, on_connected=None):
        self._evf_frame_cb = on_evf_frame
        self._photo_cb = on_photo
        self._error_cb = on_error
        self._connected_cb = on_connected

    def set_download_dir(self, path: Path):
        self._download_dir = path
        self._download_dir.mkdir(parents=True, exist_ok=True)

    def start(self):
        """Start the EDSDK thread. All SDK calls happen on this thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def take_picture(self):
        """Queue a capture command."""
        self._cmd_queue.put(("capture",))

    def start_live_view(self):
        self._cmd_queue.put(("start_evf",))

    def stop_live_view(self):
        self._cmd_queue.put(("stop_evf",))

    # --- Internal: runs on dedicated EDSDK thread ---

    def _run(self):
        try:
            self._sdk = ctypes.WinDLL(self._dll_path)
            self._setup_sdk_functions()
            self._init_sdk()

            # Retry camera connection until found
            while self._running and not self._connected:
                try:
                    self._connect_camera()
                    self._configure_for_photobooth()
                    self._register_handlers()
                    self._connected = True
                    log.info("Camera ready")
                    if self._connected_cb:
                        self._connected_cb()
                except RuntimeError:
                    log.info("Waiting for camera...")
                    time.sleep(3)

            evf_active = False
            while self._running:
                # Poll EDSDK events
                self._sdk.EdsGetEvent()

                # Process commands from main thread
                try:
                    cmd = self._cmd_queue.get_nowait()
                    if cmd[0] == "capture":
                        try:
                            self._do_capture()
                        except EDSDKError as e:
                            log.warning(f"Capture failed: {e}")
                    elif cmd[0] == "start_evf":
                        self._do_start_evf()
                        evf_active = True
                    elif cmd[0] == "stop_evf":
                        self._do_stop_evf()
                        evf_active = False
                except Empty:
                    pass

                # Download live view frame if active
                if evf_active and self._evf_frame_cb:
                    frame = self._download_evf_frame()
                    if frame:
                        self._evf_frame_cb(frame)

                time.sleep(0.03)  # ~30fps

        except Exception as e:
            log.exception("EDSDK thread error")
            if self._error_cb:
                self._error_cb(str(e))
        finally:
            self._cleanup()

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
            ("EdsSetPropertyData", EdsError, [EdsBaseRef, EdsUInt32, EdsInt32, EdsUInt32, ctypes.c_void_p]),
            ("EdsGetPropertyData", EdsError, [EdsBaseRef, EdsUInt32, EdsInt32, EdsUInt32, ctypes.c_void_p]),
            ("EdsSetCapacity", EdsError, [EdsBaseRef, EdsCapacity]),
            ("EdsCreateMemoryStream", EdsError, [EdsUInt64, ctypes.POINTER(EdsBaseRef)]),
            ("EdsCreateFileStream", EdsError, [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(EdsBaseRef)]),
            ("EdsCreateEvfImageRef", EdsError, [EdsBaseRef, ctypes.POINTER(EdsBaseRef)]),
            ("EdsDownloadEvfImage", EdsError, [EdsBaseRef, EdsBaseRef]),
            ("EdsGetPointer", EdsError, [EdsBaseRef, ctypes.POINTER(ctypes.c_void_p)]),
            ("EdsGetLength", EdsError, [EdsBaseRef, ctypes.POINTER(EdsUInt64)]),
            ("EdsGetDirectoryItemInfo", EdsError, [EdsBaseRef, ctypes.POINTER(EdsDirectoryItemInfo)]),
            ("EdsDownload", EdsError, [EdsBaseRef, EdsUInt64, EdsBaseRef]),
            ("EdsDownloadComplete", EdsError, [EdsBaseRef]),
            ("EdsRelease", EdsUInt32, [EdsBaseRef]),
            ("EdsGetEvent", EdsError, []),
            ("EdsSetObjectEventHandler", EdsError, [EdsBaseRef, EdsUInt32, OBJECT_EVENT_HANDLER, ctypes.c_void_p]),
            ("EdsSetCameraStateEventHandler", EdsError, [EdsBaseRef, EdsUInt32, STATE_EVENT_HANDLER, ctypes.c_void_p]),
        ]:
            fn = getattr(sdk, name)
            fn.restype = restype
            fn.argtypes = argtypes

    def _init_sdk(self):
        _check("EdsInitializeSDK", self._sdk.EdsInitializeSDK())
        log.info("EDSDK initialized")

    def _connect_camera(self):
        camera_list = EdsBaseRef()
        _check("EdsGetCameraList", self._sdk.EdsGetCameraList(ctypes.byref(camera_list)))

        count = EdsUInt32()
        _check("EdsGetChildCount", self._sdk.EdsGetChildCount(camera_list, ctypes.byref(count)))
        if count.value == 0:
            raise RuntimeError("No camera found")

        _check("EdsGetChildAtIndex", self._sdk.EdsGetChildAtIndex(camera_list, 0, ctypes.byref(self._camera)))
        self._sdk.EdsRelease(camera_list)

        info = EdsDeviceInfo()
        _check("EdsGetDeviceInfo", self._sdk.EdsGetDeviceInfo(self._camera, ctypes.byref(info)))
        log.info(f"Camera: {info.szDeviceDescription.decode()}")

        # Retry OpenSession - camera may need time after USB connect
        for attempt in range(5):
            err = self._sdk.EdsOpenSession(self._camera)
            if err == EDS_ERR_OK:
                log.info("Session opened")
                return
            log.warning(f"OpenSession attempt {attempt+1}/5 failed: 0x{err:08X}")
            time.sleep(2)
        raise RuntimeError(f"Failed to open camera session after 5 attempts")

    def _configure_for_photobooth(self):
        # Load camera config
        import json
        from ..config import BUNDLE_DIR
        config_path = BUNDLE_DIR / "camera_config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text())
        else:
            cfg = {}
            log.warning("camera_config.json not found, using defaults")

        # Save photos to host PC
        self._set_prop_u32(kEdsPropID_SaveTo, kEdsSaveTo_Host)
        capacity = EdsCapacity(numberOfFreeClusters=0x7FFFFFFF, bytesPerSector=0x1000, reset=1)
        _check("EdsSetCapacity", self._sdk.EdsSetCapacity(self._camera, capacity))

        # Image quality
        q = IMAGE_QUALITY_MAP.get(cfg.get("image_quality", "jpeg_large_fine"), EdsImageQuality_LJF)
        self._set_prop_u32(kEdsPropID_ImageQuality, q)

        # AE Mode - set on camera dial manually (SDK can't override the physical dial)
        # ae = AE_MODE_MAP.get(cfg.get("ae_mode", "manual"), 0x03)
        # self._set_prop_u32(kEdsPropID_AEMode, ae)

        # Aperture
        av_val = AV_MAP.get(str(cfg.get("av", "5.6")))
        if av_val is not None:
            self._set_prop_u32(kEdsPropID_Av, av_val)

        # Shutter speed
        tv_val = TV_MAP.get(str(cfg.get("tv", "1/125")))
        if tv_val is not None:
            self._set_prop_u32(kEdsPropID_Tv, tv_val)

        # ISO
        iso_raw = cfg.get("iso", 400)
        iso_val = ISO_MAP.get(iso_raw if isinstance(iso_raw, str) else int(iso_raw))
        if iso_val is not None:
            self._set_prop_u32(kEdsPropID_ISOSpeed, iso_val)

        # White balance
        wb = WHITE_BALANCE_MAP.get(cfg.get("white_balance", "auto"), 0)
        self._set_prop_u32(kEdsPropID_WhiteBalance, wb)

        # Color temperature (only if white_balance = color_temp)
        if cfg.get("white_balance") == "color_temp":
            self._set_prop_u32(kEdsPropID_ColorTemperature, cfg.get("color_temperature", 5200))

        # Picture style
        ps = PICTURE_STYLE_MAP.get(cfg.get("picture_style", "standard"), 0x0081)
        self._set_prop_u32(kEdsPropID_PictureStyle, ps)

        # Color space
        cs = COLOR_SPACE_MAP.get(cfg.get("color_space", "srgb"), 1)
        self._set_prop_u32(kEdsPropID_ColorSpace, cs)

        # Drive mode
        self._set_prop_u32(kEdsPropID_DriveMode, kEdsDriveMode_Single)

        # EVF AF mode (face tracking, zone, etc.)
        af_mode = EVF_AF_MODE_MAP.get(cfg.get("evf_af_mode", "face_tracking"), 0x02)
        self._set_prop_u32(kEdsPropID_Evf_AFMode, af_mode)

        # Continuous AF (Servo) - keeps focus during live view, instant capture
        if cfg.get("continuous_af", True):
            self._set_prop_u32(kEdsPropID_ContinuousAfMode, 1)  # 1 = enable

        # Eye detection AF
        if cfg.get("eye_detection_af", True):
            self._set_prop_u32(kEdsPropID_AFEyeDetect, 1)  # 1 = enable

        # Lock camera UI
        if cfg.get("lock_camera_ui", True):
            self._sdk.EdsSendStatusCommand(self._camera, kEdsCameraStatusCommand_UILock, 0)

        # Lock mode dial
        if cfg.get("lock_mode_dial", True):
            self._sdk.EdsSendCommand(self._camera, kEdsCameraCommand_SetModeDialDisable, 1)

        log.info("Camera configured from camera_config.json")

    def _set_prop_u32(self, prop_id: int, value: int):
        val = EdsUInt32(value)
        err = self._sdk.EdsSetPropertyData(
            self._camera, prop_id, 0, ctypes.sizeof(val), ctypes.byref(val))
        if err != EDS_ERR_OK:
            log.warning(f"SetProp(0x{prop_id:04X})=0x{value:X} failed: 0x{err:08X} (skipping)")
        return err

    def _register_handlers(self):
        def on_object_event(event, ref, context):
            if event == kEdsObjectEvent_DirItemRequestTransfer:
                try:
                    self._download_photo(ref)
                except Exception as e:
                    log.exception("Download failed")
            return 0

        def on_state_event(event, data, context):
            if event == kEdsStateEvent_WillSoonShutDown:
                # Keep camera awake
                self._sdk.EdsSendCommand(
                    self._camera, kEdsCameraCommand_ExtendShutDownTimer, 0)
            return 0

        self._obj_handler_ref = OBJECT_EVENT_HANDLER(on_object_event)
        self._state_handler_ref = STATE_EVENT_HANDLER(on_state_event)

        _check("SetObjectEventHandler", self._sdk.EdsSetObjectEventHandler(
            self._camera, kEdsObjectEvent_All, self._obj_handler_ref, None))
        _check("SetStateEventHandler", self._sdk.EdsSetCameraStateEventHandler(
            self._camera, kEdsStateEvent_All, self._state_handler_ref, None))

    def _do_start_evf(self):
        # Enable EVF mode
        evf_mode = EdsUInt32(1)
        self._sdk.EdsSetPropertyData(
            self._camera, kEdsPropID_Evf_Mode, 0,
            ctypes.sizeof(evf_mode), ctypes.byref(evf_mode))

        # Output to PC
        device = EdsUInt32(kEdsEvfOutputDevice_PC)
        _check("SetEvfOutput", self._sdk.EdsSetPropertyData(
            self._camera, kEdsPropID_Evf_OutputDevice, 0,
            ctypes.sizeof(device), ctypes.byref(device)))
        log.info("Live view started")

    def _do_stop_evf(self):
        device = EdsUInt32(0)
        self._sdk.EdsSetPropertyData(
            self._camera, kEdsPropID_Evf_OutputDevice, 0,
            ctypes.sizeof(device), ctypes.byref(device))
        log.info("Live view stopped")

    def _download_evf_frame(self) -> bytes | None:
        """Download one live view JPEG frame. Returns None if not ready."""
        stream = EdsBaseRef()
        evf_image = EdsBaseRef()
        try:
            _check("CreateMemStream", self._sdk.EdsCreateMemoryStream(0, ctypes.byref(stream)))
            _check("CreateEvfRef", self._sdk.EdsCreateEvfImageRef(stream, ctypes.byref(evf_image)))

            err = self._sdk.EdsDownloadEvfImage(self._camera, evf_image)
            if err != EDS_ERR_OK:
                return None  # Frame not ready yet

            length = EdsUInt64()
            _check("GetLength", self._sdk.EdsGetLength(stream, ctypes.byref(length)))

            ptr = ctypes.c_void_p()
            _check("GetPointer", self._sdk.EdsGetPointer(stream, ctypes.byref(ptr)))

            buf = (ctypes.c_ubyte * length.value)()
            ctypes.memmove(buf, ptr.value, length.value)
            return bytes(buf)
        except EDSDKError:
            return None
        finally:
            if evf_image:
                self._sdk.EdsRelease(evf_image)
            if stream:
                self._sdk.EdsRelease(stream)

    def _do_capture(self):
        # TakePicture includes AF + capture. Retry if AF fails.
        for attempt in range(3):
            err = self._sdk.EdsSendCommand(
                self._camera, kEdsCameraCommand_TakePicture, 0)
            if err == EDS_ERR_OK:
                log.info("Capture triggered")
                return
            log.warning(f"Capture attempt {attempt+1}/3 failed: 0x{err:08X}")
            time.sleep(0.5)
        log.error("Capture failed after 3 attempts")

    def _download_photo(self, dir_item):
        """Download captured photo from camera to disk."""
        info = EdsDirectoryItemInfo()
        _check("GetDirItemInfo", self._sdk.EdsGetDirectoryItemInfo(dir_item, ctypes.byref(info)))

        file_name = info.szFileName.decode()
        file_path = self._download_dir / file_name

        stream = EdsBaseRef()
        _check("CreateFileStream", self._sdk.EdsCreateFileStream(
            str(file_path).encode(), kEdsFileCreateDisposition_CreateAlways,
            kEdsAccess_ReadWrite, ctypes.byref(stream)))

        try:
            _check("EdsDownload", self._sdk.EdsDownload(dir_item, info.size, stream))
            _check("EdsDownloadComplete", self._sdk.EdsDownloadComplete(dir_item))
            log.info(f"Photo saved: {file_path}")
            if self._photo_cb:
                self._photo_cb(str(file_path))
        finally:
            self._sdk.EdsRelease(stream)

    def _cleanup(self):
        try:
            if self._camera:
                self._sdk.EdsSendStatusCommand(self._camera, kEdsCameraStatusCommand_UIUnLock, 0)
                self._sdk.EdsSendCommand(self._camera, kEdsCameraCommand_SetModeDialDisable, 0)
                self._sdk.EdsCloseSession(self._camera)
                self._sdk.EdsRelease(self._camera)
            self._sdk.EdsTerminateSDK()
        except Exception:
            pass
        log.info("EDSDK cleaned up")
