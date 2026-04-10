"""EDSDK constants extracted from EDSDKTypes.h and EDSDKErrors.h"""

# --- Errors ---
EDS_ERR_OK = 0x00000000

# --- Property IDs ---
kEdsPropID_ProductName = 0x00000002
kEdsPropID_BatteryLevel = 0x00000008
kEdsPropID_SaveTo = 0x0000000b
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
kEdsPropID_Evf_OutputDevice = 0x00000500
kEdsPropID_Evf_Mode = 0x00000501
kEdsPropID_Evf_AFMode = 0x0000050E
kEdsPropID_ContinuousAfMode = 0x01000433
kEdsPropID_AFEyeDetect = 0x01000455

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
kEdsStateEvent_WillSoonShutDown = 0x00000303

# --- Property Events ---
kEdsPropertyEvent_All = 0x00000100

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
    "face_tracking": 0x02,   # LiveFace — face/eye detect + tracking
    "whole_area": 0x0e,      # WholeArea
    "zone": 0x04,            # LiveZone
    "large_zone_h": 0x07,    # LiveZoneLargeH
    "large_zone_v": 0x08,    # LiveZoneLargeV
    "spot": 0x0a,            # LiveSpotAF
    "single_point": 0x10,    # NoTracking_1Point
    "expand_cross": 0x05,    # LiveSingleExpandCross
    "expand_around": 0x06,   # LiveSingleExpandAround
}

# --- Color Space ---
COLOR_SPACE_MAP = {
    "srgb": 1,
    "adobe_rgb": 2,
}

# --- Drive Mode ---
kEdsDriveMode_Single = 0x00000000

# --- Av (Aperture) values — EDSDK uses hex codes ---
AV_MAP = {
    "1.0": 0x08, "1.1": 0x0B, "1.2": 0x0D, "1.4": 0x10,
    "1.6": 0x13, "1.8": 0x15, "2.0": 0x18, "2.2": 0x1B,
    "2.5": 0x1D, "2.8": 0x20, "3.2": 0x23, "3.5": 0x25,
    "4.0": 0x28, "4.5": 0x2B, "5.0": 0x2D, "5.6": 0x30,
    "6.3": 0x33, "7.1": 0x35, "8.0": 0x38, "9.0": 0x3B,
    "10": 0x3D, "11": 0x40, "13": 0x43, "14": 0x45,
    "16": 0x48, "18": 0x4B, "20": 0x4D, "22": 0x50,
}

# --- Tv (Shutter speed) values — EDSDK uses hex codes ---
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
