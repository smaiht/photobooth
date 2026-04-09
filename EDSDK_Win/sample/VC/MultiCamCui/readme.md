*****

# for Windows
## Operating environment
 We recommend using this sample with "windows terminal" because it uses ESC character (\033) for screen control.

## Install build tools
 Visual Studio 2019 version 16.5 or later
 Build it as a cmake project.

## Build Method
 1.Unzip MultiCamCui.zip.

 2.Start Visual Studio.

 3.Click "Open a local folder,"
   Select the folder created by unzipping MultiCamCui.zip.

 4.Choose between x64-Debug or x64-Release
   If you want to run the sample app on another PC rather than a build machine, you must build it with x64-Release.

 5.Build -> Build All


*****

# for Linux
## Operating environment
 We recommend using this sample with
  "Raspberry Pi 4/Raspberry Pi OS 32bit"
  "Jetson nano/ubuntu18.04 64bit."
  "Intel 64bit PC ubuntu20.04 64bit(AMD64)"

## Install build tools

 1.Install toolchain
  sudo apt install cmake build-essential

  ### for jetson nano:
    sudo apt install software-properties-common
    sudo add-apt-repository ppa:ubuntu-toolchain-r/test
    sudo apt-get update
    sudo apt install gcc-9 g++-9
    sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-9 10
    sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-9 10


## Build Method
 1.Unzip MultiCamCui.zip.

 2.Change the folder created by unzipping MultiCamCui.zip.
   cd MultiCamCui

 3.Edit CMakeLists.txt
  Depending on your build architecture, change line 58 of "CMakeLists.txt" to the following:
   arm64 : set(EDSDK_LDIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../EDSDK/Library/ARM64)
   arm32 : set(EDSDK_LDIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../EDSDK/Library/ARM32)
   intel : set(EDSDK_LDIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../EDSDK/Library/x86_64)

 4.Configure
   cmake CMakeLists.txt

 5.Build
   make


*****


# How to use the sample app
 1.Connect the camera to your PC with a USB cable.

 2.Run MultiCamCui.exe.
   The top menu lists the detected cameras.

 3.Select the camera you want to connect.
   ex.
   - Select camera No.2 to No.5
     Enter "2-5"

   - Select camera No.3
     Enter "3"

   - Select all listed cameras
     Enter "a"

   - Quit the app
     Enter "x"

   * The camera number changes in the order you connect the camera to your PC.

 4.Control menu
   The control menu is the following:
		[ 1] Set Save To
		[ 2] Set Image Quality
		[ 3] Take Picture and download
		[ 4] Press Halfway
		[ 5] Press Completely
		[ 6] Press Off
		[ 7] TV
		[ 8] AV
		[ 9] ISO
		[10] White Balance
		[11] Drive Mode
		[12] Exposure Compensation
		[13] AE Mode (read only)
		[14] AF Mode (read only)
		[15] Aspect setting (read only)
		[16] Get Available shots (read only)
		[17] Get Battery Level (read only)
		[18] Edit Copyright
		[20] Get Live View Image
    [21] Start Live View
    [22] Stop Live View
		[30] All File Download
		[31] Format Volume
		[32] Set Meta Data(EXIF) to All Image files
		[33] Set Meta Data(XMP) to All Image files
		[34] current storage
		[35] current folder
		[40] Rec mode on
		[41] Rec Start
		[42] Rec Stop
		[43] Rec mode off
		[50] Select Picture Style
		[51] Picture Style edit
		[60] Get Lens Name
		[61] Lens IS Setting
		[62] Aperture Lock Setting
		[63] Focus Shift Setting
		[64] [FPM]Drive Focus To Edge
		[65] [FPM]Register Edge Focus Position
		[66] [FPM]Get Current Focus Position
		[67] [FPM]Moving the Focus Position
		[70] Auto power off
		[71] Screen Off Time
		[72] Viewfinder Off Time
		[73] Screen dimmer Time
		[80] Digital Zoom Setting
		[81] Color Filter (V10 only)
		[82] AfLock State (V10 only)
		[83] Brightness Setting (V10 only)

   Select the item number you want to control.
   The following is a description of the operation for each input number.
   *Enter "r" key to move to "Top Menu"


		[ 1] Set Save To
    Set the destination for saving images.

		[ 2] Set Image Quality
    Set the image Quality.

		[ 3] Take Picture and download
    Press and release the shutter button without AF action,
    create a "cam + number" folder in the folder where MultiCamCui.exe is located
    and save the pictures taken with each camera.

    * If you can't shoot, change the mode dial to "M" and then try again.
    * The camera number changes in the order you connect the camera to your PC.

		[ 4] Press Halfway
    Press the shutter button halfway.

		[ 5] Press Completely
    Press the shutter button completely.
    When Drive mode is set to continuous shooting,
    Continuous shooting is performed.

		[ 6] Press Off
    Release the shutter button.

		[ 7] TV
    Set the Tv settings.

		[ 8] AV
    Set the Av settings.

		[ 9] ISO
    Set the ISO settings.

		[10] White Balance
    Set the White Balance settings.

		[11] Drive Mode
    Set the Drive mode settings.

		[12] Exposure Compensation
    Set the exposure compensation settings.

		[13] AE Mode (read only)
    Indicates the AE mode settings. (not configurable)

		[14] AF Mode (read only)
    Indicates the AF mode settings. (not configurable)

	  [15] Aspect setting (read only)
    Indicates the aspect settings. (not configurable)

	  [16] Get Available shots (read only)
    Indicates the number of shots available on a camera. (not configurable)

	  [17] Get Battery Level (read only)
    Indicates the camera battery level. (not configurable)

	  [18] Edit Copyright
    Indicates/Set a string identifying the copyright information on the camera.

		[20] Get Live View Image
    Get one live view image.
    In the folder where MultiCamCui.exe is located
    Automatically create a "cam number" folder and save each camera's image.

    [21] Start Live View
    Enables the Live View function settings.

    [22] Stop Live View
    Disables the Live View function settings.

		[30] All File Download
    Download all picture File in the camera's card to PC.
    In the folder where MultiCamCui.exe is located
    automatically create a "cam number" folder and save each camera's image.

		[31] Format Volume
    Formats volumes of memory cards in a camera.

		[32] Set Meta Data(EXIF) to All Image files
    Writes information to the Exif GPS Tags of all of the image (Jpeg only) in the camera.

		[33] Set Meta Data(XMP) to All Image files
    Writes information to the XMP area of all of the image (Jpeg only) in the camera.

		[34] current storage
    Gets the current storage media for the camera.

		[35] current folder
    Gets the current folder for the camera.

		[40] Rec mode on
    Change to Movie Mode.

		[41] Rec Start
    Begin movie shooting.

		[42] Rec Stop
    End movie shooting.

		[43] Rec mode off
    Change to Still Image Mode.

		[50] Select Picture Style
    Displays a list of available picture styles from which you can choose.

		[51] Picture Style edit
    The settings for each picture style can be changed.

		[60] Get Lens Name
    Displays the lens name as an ASCII string.

		[61] Lens IS Setting
    Enable/Disables the Lens IS (IMAGE STABILIZER) Settings.

		[62] Aperture Lock Setting
    Enable/Disables the Aperture Lock Settings.

		[63] Focus Shift Setting
    Indicates the Focus bracteting settings.

		[64] [FPM]Drive Focus To Edge
    Move the focus position to near edge or far edge.(Part of the Focus Position Memory function)

		[65] [FPM]Register Edge Focus Position
    Register the current focus position as near edge or far edge to the camera memory.

		[66] [FPM]Get Current Focus Position
    Getting the Current Focus Position.

		[67] [FPM]Moving the Focus Positio
    Moving the Focus Position.

		[70] Auto power off
    Set the number of seconds before auto power off.

		[71] Screen Off Time
    Set the number of seconds before screeen off.

		[72] Viewfinder Off Time
    Set the number of seconds before viewfinder off.

		[73] Screen dimmer Time
    Set the number of seconds before screen dimmer.

		[80] Digital Zoom Setting
    Enable/Disables the Digital Zoom funtion.

		[81] Color Filter (V10 only)
    Indicates the Color filter settings.

		[82] AfLock State (V10 only)
    Indicates the AF Lock state.

		[83] Brightness Setting (V10 only)
    Indicates the Brightness settings.


   * Some settings may not be available depending on the mode dial of the camera.
     If you can't set, change the mode dial to "M" and then try again.
