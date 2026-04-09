"""EDSDK constants extracted from EDSDKTypes.h and EDSDKErrors.h"""

# --- Errors ---
EDS_ERR_OK = 0x00000000

# --- Property IDs ---
kEdsPropID_ProductName = 0x00000002
kEdsPropID_BatteryLevel = 0x00000008
kEdsPropID_SaveTo = 0x0000000b
kEdsPropID_ImageQuality = 0x00000100
kEdsPropID_ISOSpeed = 0x00000402
kEdsPropID_Av = 0x00000405
kEdsPropID_Tv = 0x00000406
kEdsPropID_Evf_OutputDevice = 0x00000500
kEdsPropID_Evf_Mode = 0x00000501
kEdsPropID_Evf_Zoom = 0x00000507
kEdsPropID_Evf_AFMode = 0x0000050E

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

# --- Shutter Button ---
kEdsCameraCommand_ShutterButton_OFF = 0x00000000
kEdsCameraCommand_ShutterButton_Halfway = 0x00000001
kEdsCameraCommand_ShutterButton_Completely = 0x00000003
kEdsCameraCommand_ShutterButton_Halfway_NonAF = 0x00010001
kEdsCameraCommand_ShutterButton_Completely_NonAF = 0x00010003

# --- Object Events ---
kEdsObjectEvent_All = 0x00000200
kEdsObjectEvent_DirItemRequestTransfer = 0x00000208
kEdsObjectEvent_DirItemCreated = 0x00000203

# --- State Events ---
kEdsStateEvent_All = 0x00000300
kEdsStateEvent_Shutdown = 0x00000301
kEdsStateEvent_WillSoonShutDown = 0x00000303
kEdsStateEvent_CaptureError = 0x00000305

# --- Property Events ---
kEdsPropertyEvent_All = 0x00000100
kEdsPropertyEvent_PropertyChanged = 0x00000101

# --- File Create Disposition ---
kEdsFileCreateDisposition_CreateNew = 0
kEdsFileCreateDisposition_CreateAlways = 1
kEdsFileCreateDisposition_OpenExisting = 2
kEdsFileCreateDisposition_OpenAlways = 3

# --- Access ---
kEdsAccess_Read = 0
kEdsAccess_Write = 1
kEdsAccess_ReadWrite = 2

# --- Data Types ---
kEdsDataType_UInt32 = 9
kEdsDataType_String = 2

# --- Image Quality ---
EdsImageQuality_LJF = 0x0013ff0f   # JPEG Large Fine (~8-15MB, best for print)
EdsImageQuality_LJN = 0x0012ff0f   # JPEG Large Normal (~5-8MB, good enough)
EdsImageQuality_MJF = 0x0113ff0f   # JPEG Middle Fine
EdsImageQuality_SJF = 0x0213ff0f   # JPEG Small Fine

# --- Drive Mode ---
kEdsDriveMode_Single = 0x00000000

# --- AF Mode ---
kEdsAFMode_OneShot = 0
kEdsAFMode_AIServo = 1
kEdsAFMode_AIFocus = 2
kEdsAFMode_Manual = 3
