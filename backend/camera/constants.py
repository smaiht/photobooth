"""EDSDK constants extracted from EDSDKTypes.h and EDSDKErrors.h"""

# --- Errors ---
EDS_ERR_OK = 0x00000000
EDS_ERR_UNIMPLEMENTED = 0x00000001
EDS_ERR_INTERNAL_ERROR = 0x00000002
EDS_ERR_MEM_ALLOC_FAILED = 0x00000003
EDS_ERR_MEM_FREE_FAILED = 0x00000004
EDS_ERR_OPERATION_CANCELLED = 0x00000005
EDS_ERR_INCOMPATIBLE_VERSION = 0x00000006
EDS_ERR_NOT_SUPPORTED = 0x00000007
EDS_ERR_UNEXPECTED_EXCEPTION = 0x00000008
EDS_ERR_PROTECTION_VIOLATION = 0x00000009
EDS_ERR_MISSING_SUBCOMPONENT = 0x0000000A
EDS_ERR_SELECTION_UNAVAILABLE = 0x0000000B
EDS_ERR_FILE_IO_ERROR = 0x00000020
EDS_ERR_FILE_TOO_MANY_OPEN = 0x00000021
EDS_ERR_FILE_NOT_FOUND = 0x00000022
EDS_ERR_FILE_OPEN_ERROR = 0x00000023
EDS_ERR_FILE_CLOSE_ERROR = 0x00000024
EDS_ERR_FILE_SEEK_ERROR = 0x00000025
EDS_ERR_FILE_TELL_ERROR = 0x00000026
EDS_ERR_FILE_READ_ERROR = 0x00000027
EDS_ERR_FILE_WRITE_ERROR = 0x00000028
EDS_ERR_FILE_PERMISSION_ERROR = 0x00000029
EDS_ERR_FILE_DISK_FULL_ERROR = 0x0000002A
EDS_ERR_FILE_ALREADY_EXISTS = 0x0000002B
EDS_ERR_FILE_FORMAT_UNRECOGNIZED = 0x0000002C
EDS_ERR_FILE_DATA_CORRUPT = 0x0000002D
EDS_ERR_FILE_NAMING_NA = 0x0000002E
EDS_ERR_DIR_NOT_FOUND = 0x00000040
EDS_ERR_DIR_IO_ERROR = 0x00000041
EDS_ERR_DIR_ENTRY_NOT_FOUND = 0x00000042
EDS_ERR_DIR_ENTRY_EXISTS = 0x00000043
EDS_ERR_DIR_NOT_EMPTY = 0x00000044
EDS_ERR_PROPERTIES_UNAVAILABLE = 0x00000050
EDS_ERR_PROPERTIES_MISMATCH = 0x00000051
EDS_ERR_PROPERTIES_NOT_LOADED = 0x00000053
EDS_ERR_INVALID_PARAMETER = 0x00000060
EDS_ERR_INVALID_HANDLE = 0x00000061
EDS_ERR_INVALID_POINTER = 0x00000062
EDS_ERR_INVALID_INDEX = 0x00000063
EDS_ERR_INVALID_LENGTH = 0x00000064
EDS_ERR_INVALID_FN_POINTER = 0x00000065
EDS_ERR_INVALID_SORT_FN = 0x00000066
EDS_ERR_DEVICE_NOT_FOUND = 0x00000080
EDS_ERR_DEVICE_BUSY = 0x00000081
EDS_ERR_DEVICE_INVALID = 0x00000082
EDS_ERR_DEVICE_EMERGENCY = 0x00000083
EDS_ERR_DEVICE_MEMORY_FULL = 0x00000084
EDS_ERR_DEVICE_INTERNAL_ERROR = 0x00000085
EDS_ERR_DEVICE_INVALID_PARAMETER = 0x00000086
EDS_ERR_DEVICE_NO_DISK = 0x00000087
EDS_ERR_DEVICE_DISK_ERROR = 0x00000088
EDS_ERR_DEVICE_CF_GATE_CHANGED = 0x00000089
EDS_ERR_DEVICE_DIAL_CHANGED = 0x0000008A
EDS_ERR_DEVICE_NOT_INSTALLED = 0x0000008B
EDS_ERR_DEVICE_STAY_AWAKE = 0x0000008C
EDS_ERR_DEVICE_NOT_RELEASED = 0x0000008D
EDS_ERR_STREAM_IO_ERROR = 0x000000A0
EDS_ERR_STREAM_NOT_OPEN = 0x000000A1
EDS_ERR_STREAM_ALREADY_OPEN = 0x000000A2
EDS_ERR_STREAM_OPEN_ERROR = 0x000000A3
EDS_ERR_STREAM_CLOSE_ERROR = 0x000000A4
EDS_ERR_STREAM_SEEK_ERROR = 0x000000A5
EDS_ERR_STREAM_TELL_ERROR = 0x000000A6
EDS_ERR_STREAM_READ_ERROR = 0x000000A7
EDS_ERR_STREAM_WRITE_ERROR = 0x000000A8
EDS_ERR_STREAM_PERMISSION_ERROR = 0x000000A9
EDS_ERR_STREAM_COULDNT_BEGIN_THREAD = 0x000000AA
EDS_ERR_STREAM_BAD_OPTIONS = 0x000000AB
EDS_ERR_STREAM_END_OF_STREAM = 0x000000AC
EDS_ERR_COMM_PORT_IS_IN_USE = 0x000000C0
EDS_ERR_COMM_DISCONNECTED = 0x000000C1
EDS_ERR_COMM_DEVICE_INCOMPATIBLE = 0x000000C2
EDS_ERR_COMM_BUFFER_FULL = 0x000000C3
EDS_ERR_COMM_USB_BUS_ERR = 0x000000C4
EDS_ERR_USB_DEVICE_LOCK_ERROR = 0x000000D0
EDS_ERR_USB_DEVICE_UNLOCK_ERROR = 0x000000D1
EDS_ERR_STI_UNKNOWN_ERROR = 0x000000E0
EDS_ERR_STI_INTERNAL_ERROR = 0x000000E1
EDS_ERR_STI_DEVICE_CREATE_ERROR = 0x000000E2
EDS_ERR_STI_DEVICE_RELEASE_ERROR = 0x000000E3
EDS_ERR_DEVICE_NOT_LAUNCHED = 0x000000E4
EDS_ERR_ENUM_NA = 0x000000F0
EDS_ERR_INVALID_FN_CALL = 0x000000F1
EDS_ERR_HANDLE_NOT_FOUND = 0x000000F2
EDS_ERR_INVALID_ID = 0x000000F3
EDS_ERR_WAIT_TIMEOUT_ERROR = 0x000000F4
EDS_ERR_SESSION_NOT_OPEN = 0x00002003
EDS_ERR_INVALID_TRANSACTIONID = 0x00002004
EDS_ERR_INCOMPLETE_TRANSFER = 0x00002007
EDS_ERR_INVALID_STORAGEID = 0x00002008
EDS_ERR_DEVICEPROP_NOT_SUPPORTED = 0x0000200A
EDS_ERR_INVALID_OBJECTFORMATCODE = 0x0000200B
EDS_ERR_SELF_TEST_FAILED = 0x00002011
EDS_ERR_PARTIAL_DELETION = 0x00002012
EDS_ERR_SPECIFICATION_BY_FORMAT_UNSUPPORTED = 0x00002014
EDS_ERR_NO_VALID_OBJECTINFO = 0x00002015
EDS_ERR_INVALID_CODE_FORMAT = 0x00002016
EDS_ERR_UNKNOWN_VENDOR_CODE = 0x00002017
EDS_ERR_CAPTURE_ALREADY_TERMINATED = 0x00002018
EDS_ERR_PTP_DEVICE_BUSY = 0x00002019
EDS_ERR_INVALID_PARENT_OBJECT = 0x0000201A
EDS_ERR_INVALID_DEVICEPROP_FORMAT = 0x0000201B
EDS_ERR_INVALID_DEVICEPROP_VALUE = 0x0000201C
EDS_ERR_SESSION_ALREADY_OPEN = 0x0000201E
EDS_ERR_TRANSACTION_CANCELLED = 0x0000201F
EDS_ERR_SPECIFICATION_OF_DESTINATION_UNSUPPORTED = 0x00002020
EDS_ERR_NOT_CAMERA_SUPPORT_SDK_VERSION = 0x00002021
EDS_ERR_UNKNOWN_COMMAND = 0x0000A001
EDS_ERR_OPERATION_REFUSED = 0x0000A005
EDS_ERR_LENS_COVER_CLOSE = 0x0000A006
EDS_ERR_LOW_BATTERY = 0x0000A101
EDS_ERR_OBJECT_NOTREADY = 0x0000A102
EDS_ERR_CANNOT_MAKE_OBJECT = 0x0000A104
EDS_ERR_MEMORYSTATUS_NOTREADY = 0x0000A106
EDS_ERR_TAKE_PICTURE_AF_NG = 0x00008D01
EDS_ERR_TAKE_PICTURE_RESERVED = 0x00008D02
EDS_ERR_TAKE_PICTURE_MIRROR_UP_NG = 0x00008D03
EDS_ERR_TAKE_PICTURE_SENSOR_CLEANING_NG = 0x00008D04
EDS_ERR_TAKE_PICTURE_SILENCE_NG = 0x00008D05
EDS_ERR_TAKE_PICTURE_NO_CARD_NG = 0x00008D06
EDS_ERR_TAKE_PICTURE_CARD_NG = 0x00008D07
EDS_ERR_TAKE_PICTURE_CARD_PROTECT_NG = 0x00008D08
EDS_ERR_TAKE_PICTURE_MOVIE_CROP_NG = 0x00008D09
EDS_ERR_TAKE_PICTURE_STROBO_CHARGE_NG = 0x00008D0A
EDS_ERR_TAKE_PICTURE_NO_LENS_NG = 0x00008D0B
EDS_ERR_TAKE_PICTURE_SPECIAL_MOVIE_MODE_NG = 0x00008D0C
EDS_ERR_TAKE_PICTURE_LV_REL_PROHIBIT_MODE_NG = 0x00008D0D
EDS_ERR_TAKE_PICTURE_MOVIE_MODE_NG = 0x00008D0E
EDS_ERR_TAKE_PICTURE_RETRACTED_LENS_NG = 0x00008D0F

# Canon's public header keeps these historical misspellings. Retain aliases so
# copied SDK error names can be searched verbatim in our Python wrapper/logs.
EDS_ERR_INVALID_STRAGEID = EDS_ERR_INVALID_STORAGEID
EDS_ERR_INVALID_PARENTOBJECT = EDS_ERR_INVALID_PARENT_OBJECT
EDS_ERR_TAKE_PICTURE_RETRUCTED_LENS_NG = EDS_ERR_TAKE_PICTURE_RETRACTED_LENS_NG

# Keep the map derived from the constants above so logs always include the
# official symbolic EDSDK name instead of an opaque hexadecimal value.
EDSDK_ERROR_NAMES = {
    value: name for name, value in list(globals().items())
    if name.startswith("EDS_ERR_") and name != "EDS_ERR_OK" and isinstance(value, int)
}


def edsdk_error_name(code: int) -> str:
    return EDSDK_ERROR_NAMES.get(code, "UNKNOWN")

# --- Property IDs ---
kEdsPropID_ProductName = 0x00000002
kEdsPropID_FirmwareVersion = 0x00000007
kEdsPropID_BatteryLevel = 0x00000008
kEdsPropID_SaveTo = 0x0000000b
kEdsPropID_BatteryQuality = 0x00000010
kEdsPropID_BodyIDEx = 0x00000015
kEdsPropID_ImageQuality = 0x00000100
kEdsPropID_WhiteBalance = 0x00000106
kEdsPropID_ColorTemperature = 0x00000107
kEdsPropID_ColorSpace = 0x0000010d
kEdsPropID_PictureStyle = 0x00000114
kEdsPropID_AEMode = 0x00000400
kEdsPropID_DriveMode = 0x00000401
kEdsPropID_ISOSpeed = 0x00000402
kEdsPropID_MeteringMode = 0x00000403
kEdsPropID_AFMode = 0x00000404
kEdsPropID_Av = 0x00000405
kEdsPropID_Tv = 0x00000406
kEdsPropID_ExposureCompensation = 0x00000407
kEdsPropID_AvailableShots = 0x0000040A
kEdsPropID_LensName = 0x0000040D
kEdsPropID_AEModeSelect = 0x00000436
kEdsPropID_Evf_OutputDevice = 0x00000500
kEdsPropID_Evf_Mode = 0x00000501
kEdsPropID_Evf_AFMode = 0x0000050E
kEdsPropID_EnableProperty = 0x01000000
kEdsPropID_ContinuousAfMode = 0x01000433
kEdsPropID_TempStatus = 0x01000415
kEdsPropID_AutoPowerOffSetting = 0x0100045e
kEdsPropID_AFEyeDetect = 0x01000455
kEdsPropID_ShutterType = 0x01000461
kEdsPropID_AFTrackingObject = 0x01000468
kEdsPropID_Evf_ViewType = 0x01000513

# --- Save To ---
kEdsSaveTo_Camera = 1
kEdsSaveTo_Host = 2
kEdsSaveTo_Both = 3

# --- EVF Output Device ---
kEdsEvfOutputDevice_TFT = 1
kEdsEvfOutputDevice_PC = 2
kEdsEvfOutputDevice_PC_Small = 8

# --- Camera Commands ---
kEdsCameraCommand_TakePicture = 0x00000000
kEdsCameraCommand_ExtendShutDownTimer = 0x00000001
kEdsCameraCommand_PressShutterButton = 0x00000004
kEdsCameraCommand_DoEvfAf = 0x00000102
kEdsCameraCommand_SetModeDialDisable = 0x00000113

# --- EVF AF command status ---
kEdsCameraCommand_EvfAf_OFF = 0
kEdsCameraCommand_EvfAf_ON = 1

# --- Camera Status Commands ---
kEdsCameraStatusCommand_UILock = 0x00000000
kEdsCameraStatusCommand_UIUnLock = 0x00000001

# --- Shutter Button ---
kEdsCameraCommand_ShutterButton_OFF = 0x00000000
kEdsCameraCommand_ShutterButton_Halfway = 0x00000001
kEdsCameraCommand_ShutterButton_Completely = 0x00000003
kEdsCameraCommand_ShutterButton_Halfway_NonAF = 0x00010001
kEdsCameraCommand_ShutterButton_Completely_NonAF = 0x00010003

# --- Object Events ---
kEdsObjectEvent_All = 0x00000200
kEdsObjectEvent_DirItemRequestTransfer = 0x00000208

# --- State Events ---
kEdsStateEvent_All = 0x00000300
kEdsStateEvent_Shutdown = 0x00000301
kEdsStateEvent_JobStatusChanged = 0x00000302
kEdsStateEvent_WillSoonShutDown = 0x00000303
kEdsStateEvent_ShutDownTimerUpdate = 0x00000304
kEdsStateEvent_CaptureError = 0x00000305
kEdsStateEvent_InternalError = 0x00000306

kEdsAutoPowerOff_Disable = 0x00000000

# --- Property Events ---
kEdsPropertyEvent_All = 0x00000100
kEdsPropertyEvent_PropertyChanged = 0x00000101
kEdsPropertyEvent_PropertyDescChanged = 0x00000102

CAPTURE_ERROR_NAMES = {
    1: "shooting_failure",
    2: "lens_closed",
    3: "shooting_mode_bulb_or_mirror_error",
    4: "sensor_cleaning",
    5: "silent_operation",
    6: "no_card",
    7: "card_error_or_full",
    8: "card_write_protected",
}


def capture_error_name(code: int) -> str:
    return CAPTURE_ERROR_NAMES.get(code, f"unknown({code})")

# --- File Create Disposition ---
kEdsFileCreateDisposition_CreateAlways = 1

# --- Access ---
kEdsAccess_ReadWrite = 2

# --- Image Quality ---
EdsImageQuality_LJF = 0x0013ff0f   # JPEG Large Fine
EdsImageQuality_LJN = 0x0012ff0f   # JPEG Large Normal
EdsImageQuality_MJF = 0x0113ff0f   # JPEG Middle Fine
EdsImageQuality_MJN = 0x0112ff0f   # JPEG Middle Normal
EdsImageQuality_SJF = 0x0213ff0f   # JPEG Small Fine
EdsImageQuality_SJN = 0x0212ff0f   # JPEG Small Normal
EdsImageQuality_LR = 0x0064ff0f    # RAW
EdsImageQuality_LRLJF = 0x00640013 # RAW + JPEG Large Fine

IMAGE_QUALITY_MAP = {
    "jpeg_large_fine": EdsImageQuality_LJF,
    "jpeg_large_normal": EdsImageQuality_LJN,
    "jpeg_middle_fine": EdsImageQuality_MJF,
    "jpeg_middle_normal": EdsImageQuality_MJN,
    "jpeg_small_fine": EdsImageQuality_SJF,
    "jpeg_small_normal": EdsImageQuality_SJN,
    "raw": EdsImageQuality_LR,
    "raw_jpeg_large_fine": EdsImageQuality_LRLJF,
}

# --- AE Mode ---
AE_MODE_MAP = {
    "program": 0x00,
    "tv": 0x01,
    "av": 0x02,
    "manual": 0x03,
}

# --- AF Mode ---
AF_MODE_MAP = {
    "one_shot": 0,
    "oneshot": 0,
    "servo": 1,
    "ai_servo": 1,
    "ai_focus": 2,
    "manual": 3,
}

# --- White Balance ---
WHITE_BALANCE_MAP = {
    "auto": 0,
    "daylight": 1,
    "cloudy": 2,
    "tungsten": 3,
    "fluorescent": 4,
    "strobe": 5,
    "shade": 8,
    "color_temp": 9,
}

# --- Picture Style ---
PICTURE_STYLE_MAP = {
    "standard": 0x0081,
    "portrait": 0x0082,
    "landscape": 0x0083,
    "neutral": 0x0084,
    "faithful": 0x0085,
    "monochrome": 0x0086,
    "auto": 0x0087,
    "fine_detail": 0x0088,
}

# --- EVF AF Mode ---
EVF_AF_MODE_MAP = {
    # Current EOS R bodies (including R8) expose face/eye tracking through
    # WholeArea. LiveFace is retained under an explicit legacy name.
    "face_tracking": 0x0e,   # WholeArea + subject/eye tracking
    "whole_area": 0x0e,      # WholeArea
    "live_face": 0x02,       # Legacy LiveFace
    "zone": 0x04,            # LiveZone
    "large_zone_h": 0x07,    # LiveZoneLargeH
    "large_zone_v": 0x08,    # LiveZoneLargeV
    "spot": 0x0a,            # LiveSpotAF
    "single_point": 0x10,    # NoTracking_1Point
    "expand_cross": 0x05,    # LiveSingleExpandCross
    "expand_around": 0x06,   # LiveSingleExpandAround
}

# --- AF tracking object / subject to detect ---
AF_TRACKING_OBJECT_MAP = {
    "none": 0,
    "people": 1,
    "animals": 2,
    "vehicles": 3,
    "auto": 4,
}

# --- EVF View Type / exposure simulation ---
# Canon EDSDK 13.20.10: kEdsPropID_Evf_ViewType.
# "disable" keeps live view bright for framing when flash is the main light.
EVF_VIEW_TYPE_MAP = {
    "during_dof_preview": 0x00000000,
    "enable": 0x00000001,
    "enabled": 0x00000001,
    "disable": 0x00000003,
    "disabled": 0x00000003,
    "exposure_dof": 0x00000004,
    "exposure_plus_dof": 0x00000004,
}

# --- Shutter Type ---
# Canon EDSDK 13.20.10: kEdsPropID_ShutterType.
SHUTTER_TYPE_MAP = {
    "electronic_first_curtain": 0x00000000,
    "elec_first_curtain": 0x00000000,
    "efc": 0x00000000,
    "mechanical": 0x00000002,
    "electronic": 0x00000003,
}

# --- Color Space ---
COLOR_SPACE_MAP = {
    "srgb": 1,
    "adobe_rgb": 2,
}

# --- Drive Mode ---
kEdsDriveMode_Single = 0x00000000

# --- Av (Aperture) values - EDSDK uses hex codes ---
AV_MAP = {
    "1.0": 0x08, "1.1": 0x0B, "1.2": 0x0D, "1.4": 0x10,
    "1.6": 0x13, "1.8": 0x15, "2.0": 0x18, "2.2": 0x1B,
    "2.5": 0x1D, "2.8": 0x20, "3.2": 0x23, "3.5": 0x25,
    "4.0": 0x28, "4.5": 0x2B, "5.0": 0x2D, "5.6": 0x30,
    "6.3": 0x33, "7.1": 0x35, "8.0": 0x38, "9.0": 0x3B,
    "10": 0x3D, "11": 0x40, "13": 0x43, "14": 0x45,
    "16": 0x48, "18": 0x4B, "20": 0x4D, "22": 0x50,
}

# --- Tv (Shutter speed) values - EDSDK uses hex codes ---
TV_MAP = {
    "30": 0x10, "25": 0x13, "20": 0x15, "15": 0x18,
    "13": 0x1B, "10": 0x1D, "8": 0x20, "6": 0x23,
    "5": 0x25, "4": 0x28, "3.2": 0x2B, "2.5": 0x2D,
    "2": 0x30, "1.6": 0x33, "1.3": 0x35, "1": 0x38,
    "0.8": 0x3B, "0.6": 0x3D, "0.5": 0x40, "0.4": 0x43,
    "1/3": 0x45, "1/4": 0x48, "1/5": 0x4B, "1/6": 0x4D,
    "1/8": 0x50, "1/10": 0x53, "1/13": 0x55, "1/15": 0x58,
    "1/20": 0x5B, "1/25": 0x5D, "1/30": 0x60, "1/40": 0x63,
    "1/50": 0x65, "1/60": 0x68, "1/80": 0x6B, "1/100": 0x6D,
    "1/125": 0x70, "1/160": 0x73, "1/200": 0x75, "1/250": 0x78,
    "1/320": 0x7B, "1/400": 0x7D, "1/500": 0x80, "1/640": 0x83,
    "1/800": 0x85, "1/1000": 0x88, "1/1250": 0x8B, "1/1600": 0x8D,
    "1/2000": 0x90, "1/2500": 0x93, "1/3200": 0x95, "1/4000": 0x98,
}

# --- ISO ---
ISO_MAP = {
    100: 0x48, 125: 0x4B, 160: 0x4D, 200: 0x50,
    250: 0x53, 320: 0x55, 400: 0x58, 500: 0x5B,
    640: 0x5D, 800: 0x60, 1000: 0x63, 1250: 0x65,
    1600: 0x68, 2000: 0x6B, 2500: 0x6D, 3200: 0x70,
    4000: 0x73, 5000: 0x75, 6400: 0x78,
    "auto": 0x00,
}
