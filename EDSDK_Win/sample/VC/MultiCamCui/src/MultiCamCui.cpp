#include <iostream>
#include <iterator>
#include <list>
#include <regex>
#include <string>
#include <vector>
#include <thread>
#include <memory>
#include "EDSDK.h"
#include "EDSDKTypes.h"
#include "FileControl.h"
#include "PreSetting.h"
#include "Property.h"
#include "CameraModel.h"
#include "utility.h"

static std::string control_number = "";
static bool keyflag;

using namespace std::chrono_literals;

void CheckKey() // After key is entered, _ endthread is automatically called.
{
	std::cin >> control_number;
	std::cin.ignore(); // ignore "\n"
	keyflag = true;
}

int main()
{
	EdsError err = EDS_ERR_OK;
	EdsCameraListRef cameraList = NULL;
	EdsCameraRef camera;
	EdsFlashRef flash;
	std::vector<CameraModel *> _detectedCameraArray;
	std::vector<CameraModel *> _openedCamerasArray;
	EdsUInt32 min = 0, max = 0, i = 0;
	EdsUInt32 count = 0;
	EdsUInt32 data;
	bool isSDKLoaded = false;
	std::smatch match_results;
	std::shared_ptr<std::thread> th = std::shared_ptr<std::thread>();

	// Initialization of SDK
	err = EdsInitializeSDK();
	if (err == EDS_ERR_OK)
	{
		isSDKLoaded = true;
		std::this_thread::sleep_for(1000ms);
	}

	while (true)
	{
		bool loop = true;

		while (true)
		{
			if (loop)
			{
				// Acquisition of camera list
				if (err == EDS_ERR_OK)
				{
					err = EdsGetCameraList(&cameraList);
				}

				// Acquisition of number of Cameras
				if (err == EDS_ERR_OK)
				{
					err = EdsGetChildCount(cameraList, &count);
					if (count == 0)
					{
						std::cout << "Cannot detect any camera" << std::endl;
						pause_return();
						exit(EXIT_FAILURE);
					}
					else if (count > 30)
					{
						std::cout << "Too many cameras detected" << std::endl;
						pause_return();
						exit(EXIT_FAILURE);
					}
					std::cout << count << "cameras detected." << std::endl;
				}

				std::cout << "number\t"
					<< "Device Description" << std::endl;
				std::cout << "------+-------------------------" << std::endl;

				// Acquisition of camera at the head of the list
				for (i = 0; i < count; i++)
				{
					if (err == EDS_ERR_OK)
					{
						err = EdsGetChildAtIndex(cameraList, i, &camera);
						EdsDeviceInfo deviceInfo;
						err = EdsGetDeviceInfo(camera, &deviceInfo);
						if (err == EDS_ERR_OK && camera == NULL)
						{
							std::cout << "Camera is not found." << std::endl;
							pause_return();
							exit(EXIT_FAILURE);
						}
						std::cout << "[" << i + 1 << "]\t" << deviceInfo.szDeviceDescription << std::endl;
						_detectedCameraArray.push_back(new CameraModel(camera, i + 1, kEdsSaveTo_Host)); // select direction : kEdsSaveTo_Camera / kEdsSaveTo_Host / kEdsSaveTo_Both
						_detectedCameraArray[i]->setModelName(deviceInfo.szDeviceDescription);
					}
				}
				std::cout << "--------------------------------" << std::endl;
				std::cout << "Enter the number of the camera to connect [1-" << count << "]" << std::endl;
				std::cout << "\tor 'a' (=All)" << std::endl;
				std::cout << "\tor 'x' (=eXit)" << std::endl;
				std::cout << "> ";

				// Wait for input on another thread to send the command "getevent" periodically.
				th = std::make_shared<std::thread>(CheckKey);

				loop = false;
				keyflag = false; // initialize keyflag
			}
			if (keyflag == true) // Within this scope, the CheckKey thread is terminated
			{
				th->join();
				// min～max
				if (std::regex_match(control_number, match_results, std::regex(R"((\d+)-(\d+))")))
				{

					min = stoi(match_results[1].str());
					max = stoi(match_results[2].str());
					std::cout << "connecting to [" << min << "-" << max << "] ..." << std::endl;
					if (min > count || max > count)
					{
						std::cout << "invalid number" << std::endl;
						pause_return();
						exit(EXIT_FAILURE);
					}
					for (i = (min - 1); i < max; i++)
						_openedCamerasArray.push_back(_detectedCameraArray[i]);
					break;
				}

				// single camera
				else if (std::regex_search(control_number, match_results, std::regex("[0-9]")))
				{
					i = stoi(control_number) - 1;
					if (i > count - 1)
					{
						std::cout << "invalid number" << std::endl;
						pause_return();
						exit(EXIT_FAILURE);
					}
					std::cout << "connecting to [" << control_number << "] ..." << std::endl;
					_openedCamerasArray.push_back(_detectedCameraArray[i]);
					break;
				}

				// all
				else if (std::regex_search(control_number, match_results, std::regex("a", std::regex_constants::icase)))
				{
					std::cout << "connecting to all cameras..." << std::endl;
					for (i = 0; i < count; i++)
						_openedCamerasArray.push_back(_detectedCameraArray[i]);
					break;
				}

				// exit
				else if (std::regex_search(control_number, match_results, std::regex("x", std::regex_constants::icase)))
				{
					std::cout << "closing app..." << std::endl;
					pause_return();
					exit(EXIT_SUCCESS);
				}

				// retry
				else
				{
					keyflag = false;
					loop = true;
					pause_return();
					clr_screen();

					continue;
				}
			}
			// send getevent periodically
			EdsGetEvent();
			std::this_thread::sleep_for(200ms);
		}

		PreSetting(_detectedCameraArray);

		clr_screen();

		loop = true;

		for (i = 0; i < _openedCamerasArray.size(); i++)
			_openedCamerasArray[i]->OpenSessionCommand();

		while (true)
		{
			// control menu
			if (loop)
			{
				keyflag = false; // initialize keyflag
								 //				_beginthread(CheckKey, 0, NULL); // Start waiting for keystrokes
				th = std::make_shared<std::thread>(CheckKey);

				std::cout << "--------------------------------" << std::endl;
				std::cout
					<< "[ 1] Set Save To \n"
					<< "[ 2] Set Image Quality \n"
					<< "[ 3] Take Picture and download \n"
					<< "[ 4] Press Halfway \n"
					<< "[ 5] Press Completely \n"
					<< "[ 6] Press Off \n"
					<< "[ 7] TV \n"
					<< "[ 8] AV \n"
					<< "[ 9] ISO \n"
					<< "[10] White Balance \n"
					<< "[11] Drive Mode \n"
					<< "[12] Exposure Compensation \n"
					<< "[13] AE Mode (read only) \n"
					<< "[14] AF Mode (read only)  \n"
					<< "[15] Aspect setting (read only)  \n"
					<< "[16] Get Available shots (read only)  \n"
					<< "[17] Get Battery Level (read only)  \n"
					<< "[18] Edit Copyright \n"
					<< "[19] Display simulation"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[20] Get Live View Image\n"
					<< "[21] Start Live View\n"
					<< "[22] Stop Live View\n"
					<< "[23] Get Focal Length"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[30] All File Download\n"
					<< "[31] Format Volume\n"
					<< "[32] Set Meta Data(EXIF) to All Image files\n"
					<< "[33] Set Meta Data(XMP) to All Image files\n"
					<< "[34] current storage\n"
					<< "[35] current folder\n"
					<< "[36] Filename Setting\n"
					<< "[37] Create Still Folder Setting"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[40] Rec mode on\n"
					<< "[41] Rec Start\n"
					<< "[42] Rec Stop\n"
					<< "[43] Rec mode off\n"
					<< "[44] MovieRecVolume\n"
					<< "[45] MovieParamEx"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[50] Select Picture Style\n"
					<< "[51] Picture Style edit"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[60] Get Lens Name\n"
					<< "[61] Lens IS Setting\n"
					<< "[62] Aperture Lock Setting \n"
					<< "[63] Focus Shift Setting \n"
					<< "[64] [FPM]Drive Focus To Edge \n"
					<< "[65] [FPM]Register Edge Focus Position \n"
					<< "[66] [FPM]Get Current Focus Position \n"
					<< "[67] [FPM]Moving the Focus Position"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[70] Auto power off\n"
					<< "[71] Screen Off Time\n"
					<< "[72] Viewfinder Off Time\n"
					<< "[73] Screen dimmer Time"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[80] Digital Zoom Setting \n"
					<< "[81] Color Filter (V10 only) \n"
					<< "[82] AfLock State (V10 only) \n"
					<< "[83] Brightness Setting (V10 only)"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout << "Please start Live View with [21] before performing any of the following Power Zoom functions." << std::endl;
				std::cout
					<< "[84] Power zoom Spped Setting \n"
					<< "[85] Power zoom Move to Tele \n"
					<< "[86] Power zoom Move to Wide \n"
					<< "[87] Power zoom Stop \n"
					<< "[88] Power zoom Get Position "
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[90] Target Flash Setting \n"
					<< "[91] Flash Firing \n"
					<< "[98] IBIS_HighResoShot (EOS R5 only)\n"
					<< "[99] WhiteBalanceShift "
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;
				std::cout
					<< "[100] Take Picture time interval(Deprecated for evaluation) \n"
					<< std::endl;
				std::cout << "-------------------------------" << std::endl;

				std::cout << "Enter the number of the control.\n"
					<< "\tor 'r' (=Return)" << std::endl;
				std::cout << "> ";
				loop = false;
			}

			if (keyflag == true) // Within this scope, the CheckKey thread is terminated
			{

				th->join();

				if (std::regex_search(control_number, match_results, std::regex("[0-9]")))
				{
					// set save to
					if (control_number == "1")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_SaveTo, SaveTo_table);

						ListAvailValue(SaveTo_table);

						std::cout << "input no." << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= SaveTo_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								if (data & kEdsSaveTo_Camera) // Check media
								{
									EdsUInt32 volume_count;
									volume_count = _openedCamerasArray[i]->GetVolume();
									if (volume_count == 0)
									{
										std::cout << " no card" << std::endl;
									}
								}
								_openedCamerasArray[i]->SetPropertyValue(kEdsPropID_SaveTo, &data);
								_openedCamerasArray[i]->setsaveTo(data);

								if (data & kEdsSaveTo_Both || data & kEdsSaveTo_Host) // When the Host or the Both is selected, it is recommended to execute the SetCapacity command.
								{
									EdsCapacity capacity = { 0x7FFFFFFF, 0x1000, 1 };
									_openedCamerasArray[i]->SetCapacity(capacity);
								}
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// set image quality
					if (control_number == "2")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_ImageQuality, ImageQuality_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_ImageQuality, ImageQuality_table);

						std::cout << "input no." << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= ImageQuality_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_ImageQuality, data, ImageQuality_table);
								_openedCamerasArray[i]->setImageQuality(data);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// Take Picture
					else if (control_number == "3")
					{
						/* select with AF or without AF
						 *   kEdsCameraCommand_ShutterButton_Completely
						 *   kEdsCameraCommand_ShutterButton_Completely_NonAF
						 */
						EdsBool pause_flg = 0;
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							err = _openedCamerasArray[i]->TakePicture(kEdsCameraCommand_ShutterButton_Completely_NonAF);
							pause_flg = pause_flg | (err != EDS_ERR_OK);
						}
						if (pause_flg)
							pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Press halfway
					else if (control_number == "4")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->PressShutter(kEdsCameraCommand_ShutterButton_Halfway);
						clr_screen();
						loop = true;
						continue;
					}
					// Press Completely
					else if (control_number == "5")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->PressShutter(kEdsCameraCommand_ShutterButton_Completely);
						clr_screen();
						loop = true;
						continue;
					}
					// Press Off
					else if (control_number == "6")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->PressShutter(kEdsCameraCommand_ShutterButton_OFF);
						clr_screen();
						loop = true;
						continue;
					}
					// TV
					else if (control_number == "7")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_Tv, tv_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_Tv, tv_table);

						std::cout << "input no. (ex. 54 = 1/250)" << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= tv_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_Tv, data, tv_table);
								_openedCamerasArray[i]->setTv(data);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// Av
					else if (control_number == "8")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_Av, av_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_Av, av_table);

						std::cout << "input Av (ex. 21 = 5.6)" << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= av_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_Av, data, av_table);
								_openedCamerasArray[i]->setAv(data);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// ISO
					else if (control_number == "9")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_ISOSpeed, iso_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_ISOSpeed, iso_table);

						std::cout << "input ISOSpeed (ex. 8 = ISO 200)" << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= iso_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_ISOSpeed, data, iso_table);
								_openedCamerasArray[i]->setIso(data);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// White Balanse
					else if (control_number == "10")

					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_WhiteBalance, whitebalance_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_WhiteBalance, whitebalance_table);

						std::cout << "input WhiteBalance (ex. 0 = Auto)" << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= whitebalance_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_WhiteBalance, data, whitebalance_table);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// Drive Mode
					else if (control_number == "11")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_DriveMode, drivemode_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_DriveMode, drivemode_table);

						std::cout << "input Drive Mode (ex. 0 = Single shooting)" << std::endl;
						std::cout << ">";
						data = getvalue();

						if (data != -1 || data <= drivemode_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->SetProperty(kEdsPropID_DriveMode, data, drivemode_table);
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// Exposure Compensation
					else if (control_number == "12")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_ExposureCompensation, ExposureComp_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_ExposureCompensation, ExposureComp_table);

						std::cout << "!!! Exposure compensation is not available if the camera is in Manual exposure mode. !!!" << std::endl;
						std::cout << "input no. (ex. 0 = 0)" << std::endl;

						std::cout << ">";
						data = getvalue();

						if (data != -1 || data <= ExposureComp_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->SetProperty(kEdsPropID_ExposureCompensation, data, ExposureComp_table);
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// AE Mode (read only)
					else if (control_number == "13")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_AEMode, AEmode_table);
						// for (i = 0; i < _openedCamerasArray.size(); i++) _openedCamerasArray[i]->SendCommand(kEdsCameraCommand_SetModeDialDisable, 0); // Disables the mode dial.
						// for (i = 0; i < _openedCamerasArray.size(); i++) _openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_AEModeSelect, AEmode_table);
						// for (i = 0; i < _openedCamerasArray.size(); i++) _openedCamerasArray[i]->SendCommand(kEdsCameraCommand_SetModeDialDisable, 1); // Cancels the disabled mode dial.

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// AF Mode (read only)
					else if (control_number == "14")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_AFMode, AFmode_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_AFMode, AFmode_table);

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Aspect (read only)
					else if (control_number == "15")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_Aspect, Aspect_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_Aspect, Aspect_table);

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// AvailableShots (read only)
					else if (control_number == "16")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_AvailableShots);
							std::cout << " shots" << std::endl;
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// BatteryLevel (read only)
					else if (control_number == "17")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_BatteryLevel);
							std::cout << " %" << std::endl;
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Edit Copyright
					else if (control_number == "18")
					{
						std::string str(64, 0);
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_Copyright);
							std::cout << " \n"
								<< std::endl;
						}
						std::cout << "What do you want?\n"
							<< std::endl;
						std::cout << "[E]dit? or [D]elete?\n"
							<< std::endl;
						std::cout << ">";
						err = getstrings(str, 64);
						if (std::regex_search(str, match_results, std::regex("e", std::regex_constants::icase)))
						{
							std::cout << "enter Copyright. (MAX 64 ASCII characters)\n"
								<< std::endl;
							std::cout << ">";
							err = getstrings(str, 64);
							if (err == 1)
							{
								for (i = 0; i < _openedCamerasArray.size(); i++)
								{
									_openedCamerasArray[i]->UILock();
									_openedCamerasArray[i]->SetPropertyValue(kEdsPropID_Copyright, str);
									_openedCamerasArray[i]->UIUnLock();
								}
							}
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}
						else if (std::regex_search(str, match_results, std::regex("d", std::regex_constants::icase)))
						{
							str = "";
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->UILock();
								_openedCamerasArray[i]->SetPropertyValue(kEdsPropID_Copyright, str);
								_openedCamerasArray[i]->UIUnLock();
							}
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}
						else
						{
							clr_screen();
							loop = true;
							continue;
						}
					}
					// Display simulation"
					else if (control_number == "19")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_Evf_ViewType, EVF_ViewType_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_Evf_ViewType, EVF_ViewType_table);

						std::cout << "input Display simulation (ex. 3 = Disable)" << std::endl;
						std::cout << ">";
						data = getvalue();

						if (data != -1 || data <= EVF_ViewType_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->SetProperty(kEdsPropID_Evf_ViewType, data, EVF_ViewType_table);
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// ---------------------------------------------------------------------------------------------
					// Download EVF image
					else if (control_number == "20")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->DownloadEvfCommand();
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Start Live View
					else if (control_number == "21")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_Evf_OutputDevice, EvfOutputDevice_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_Evf_OutputDevice, EvfOutputDevice_table);

						std::cout << "Select Live View Output Device" << std::endl;
						std::cout << ">";
						data = getvalue();

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->StartEvfCommand();
						}

						if (data != -1 || data <= EvfOutputDevice_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->SetProperty(kEdsPropID_Evf_OutputDevice, data, EvfOutputDevice_table);
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					// Stop Live View
					else if (control_number == "22")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->EndEvfCommand();
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Get Focal Length
					else if (control_number == "23")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetFocalLength();
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// ---------------------------------------------------------------------------------------------
					// Download All Image
					else if (control_number == "30")
					{
						DownloadImageAll(_openedCamerasArray);
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Format Volume
					else if (control_number == "31")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							std::cout << "cam" << i + 1 << std::endl;
							EdsUInt32 volume_count;
							volume_count = _openedCamerasArray[i]->GetVolume();
							if (volume_count == 0)
							{
								std::cout << "no card" << std::endl;
							}
							else
							{
								std::cout << "enter the card number to Format" << std::endl;
								std::cout << ">";
								data = getvalue();
								_openedCamerasArray[i]->FormatVolume(data);
							}
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Set Meta Data(EXIF) and Download All Image
					else if (control_number == "32")
					{
						SetMetaImageAll(_openedCamerasArray, 0);
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Set Meta Data(XMP) and Download All Image
					else if (control_number == "33")
					{
						SetMetaImageAll(_openedCamerasArray, 1);
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// current storage
					else if (control_number == "34")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_CurrentStorage);
							std::cout << " \n"
								<< std::endl;
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// current folder
					else if (control_number == "35")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_CurrentFolder);
							std::cout << " \n"
								<< std::endl;
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					//Filename Setting
					else if (control_number == "36")
					{
						std::string str(64, 0);
						int PropID = 0;

						//select filetype
						std::cout << "select FileType \n 1 : Still, 2 : Movie " << std::endl;
						std::cout << ">";

						int filetype = getvalue();
						//StillSetting
						if (filetype == 1)
						{
							//select settingtype
							std::cout << "select SettingType \n 1 : select FileNameSetting, 2 : change FileNameUserSet1, 3 : change FileNameUserSet2 " << std::endl;
							std::cout << ">";

							int settingtype = getvalue();
							switch (settingtype)
							{
							case 1:
								PropID = kEdsPropID_StillFileNameSetting;
								break;
							case 2:
								PropID = kEdsPropID_StillFileNameUserSet1;
								break;
							case 3:
								PropID = kEdsPropID_StillFileNameUserSet2;
								break;
							default:
								clr_screen();
								loop = true;
								continue;
							}

							if (PropID == kEdsPropID_StillFileNameSetting)
							{
								for (i = 0; i < _openedCamerasArray.size(); i++)
								{
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetProperty(PropID, StillFileNameSetting_table);
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetPropertyDesc(PropID, StillFileNameSetting_table);
								}
								std::cout << "sellect Setting (0～2)" << std::endl;
								std::cout << ">";

								data = getvalue();
								if (data != -1 && data < StillFileNameSetting_table.size())
								{
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->SetProperty(PropID, data, StillFileNameSetting_table);
									pause_return();
								}
							}
							else
							{
								int cnum = 0;
								if (PropID == kEdsPropID_StillFileNameUserSet1)
								{
									cnum = 4;
								}
								else
								{
									cnum = 3;
								}

								for (i = 0; i < _openedCamerasArray.size(); i++)
								{
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetPropertyvalue(PropID);

									std::cout << "\n";
									std::cout << "input String(" << cnum << "-character)" << std::endl;
									std::cout << ">";

									err = getstrings(str, 64);
									if (str.size() == cnum)
									{
										for (i = 0; i < _openedCamerasArray.size(); i++)
											_openedCamerasArray[i]->SetPropertyValue(PropID, str);
										pause_return();
									}
								}
							}
							clr_screen();
							loop = true;
							continue;
						}
						//MovieSetting
						else if(filetype == 2)
						{
							//select settingtype
							std::cout << "select SettingType \n 1 : FileNameIndex, 2 : FileNameReelNo, 3 : FileNameClipNo, 4 : FileNameUserDef " << std::endl;
							std::cout << ">";

							int settingtype = getvalue();
							switch (settingtype)
							{
							case 1:
								PropID = kEdsPropID_MovieFileNameIndex;
								break;
							case 2:
								PropID = kEdsPropID_MovieFileNameReelNo;
								break;
							case 3:
								PropID = kEdsPropID_MovieFileNameClipNo;
								break;
							case 4:
								PropID = kEdsPropID_MovieFileNameUserDef;
								break;
							default:
								clr_screen();
								loop = true;
								continue;
							}

							if (PropID == kEdsPropID_MovieFileNameIndex || PropID == kEdsPropID_MovieFileNameUserDef)
							{
								int cnum = 0;
								if (PropID == kEdsPropID_MovieFileNameIndex)
								{
									cnum = 2;
								}
								else
								{
									cnum = 5;
								}

								for (i = 0; i < _openedCamerasArray.size(); i++)
								{
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetPropertyvalue(PropID);

									std::cout << "\n";
									std::cout << "input String(" << cnum << "-character)" << std::endl;
									std::cout << ">";

									err = getstrings(str, 64);
									if (str.size() == cnum)
									{
										for (i = 0; i < _openedCamerasArray.size(); i++)
											_openedCamerasArray[i]->SetPropertyValue(PropID, str);
										pause_return();
									}
								}
							}
							else
							{
								int cnum = 0;
								std::string zero_str(64, 0);
								if (PropID == kEdsPropID_MovieFileNameReelNo)
								{
									cnum = 4;
									zero_str = "0000";
								}
								else
								{
									cnum = 3;
									zero_str = "000";
								}

								for (i = 0; i < _openedCamerasArray.size(); i++)
								{
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetPropertyvalue(PropID);

									std::cout << "\n";
									std::cout << "input Number(" << cnum << " digits other than " << zero_str << ")" << std::endl;
									std::cout << ">";

									err = getstrings(str, 64);
									if (str.size() == cnum && str != zero_str)
									{
										for (i = 0; i < _openedCamerasArray.size(); i++)
											_openedCamerasArray[i]->SetMovieFileName(PropID, str);
										pause_return();
									}
								}
							}
						}
						clr_screen();
						loop = true;
						continue;

					}

					//Create Folder Setting
					else if (control_number == "37")
					{
						std::string str(64, 0);

						//select command
						std::cout << "select Command \n 1 : ChangeFolderName , 2 : CreateFolder " << std::endl;
						std::cout << ">";

						int cmdType = getvalue();
						// ChangeFolderName
						if (cmdType == 1)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								for (i = 0; i < _openedCamerasArray.size(); i++)
									_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_StillFolderName);

								std::cout << "\n";
								std::cout << "input String(" << 5 << "-character)" << std::endl;
								std::cout << ">";

								err = getstrings(str, 64);
								if (str.size() == 5)
								{
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->SetPropertyValue(kEdsPropID_StillFolderName, str);
									pause_return();
								}
							}
							
							clr_screen();
							loop = true;
							continue;
						}

						// CreateFolder
						else if (cmdType == 2)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{

								std::cout << "Create Folder?\n"
									<< std::endl;
								std::cout << "[Y]es? or [N]o?\n"
									<< std::endl;
								std::cout << ">";
								err = getstrings(str, 64);
								if (std::regex_search(str, match_results, std::regex("y", std::regex_constants::icase)))
								{
									_openedCamerasArray[i]->CreateFolder();
									pause_return();
								}
							}
							
							clr_screen();
							loop = true;
							continue;
						}
						clr_screen();
						loop = true;
						continue;

					}
					// rec mode on
					else if (control_number == "40")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->RecModeOn();

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Rec Start
					else if (control_number == "41")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->RecStart();
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// Rec End
					else if (control_number == "42")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->RecEnd();
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// rec mode off
					else if (control_number == "43")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->RecModeOff();

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// MovieRecVolume
					else if (control_number == "44")
					{
						EdsUInt32 getdata;
						EdsDataType dataType = EdsDataType::kEdsDataType_Unknown;
						EdsUInt32 dataSize = 0;
						int PropID = 0;

						//selectMicType
						std::cout << "select MicType \n 1 : IntMic, 2 : ExtMic, 3 : Acc " << std::endl;
						std::cout << ">";

						int mictype = getvalue();
						if (0 < mictype && mictype < 4)
						{
							switch (mictype)
							{
							case 1:
								PropID = kEdsPropID_MovieRecVolume_IntMic;
								break;
							case 2:
								PropID = kEdsPropID_MovieRecVolume_ExtMic;
								break;
							case 3:
								PropID = kEdsPropID_MovieRecVolume_Acc;
								break;
							}
						}
						else
						{
							clr_screen();
							loop = true;
							continue;
						}

						//view current setting
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(PropID, MovieRecVolume_table);

						std::cout << "input MovieRecVolume (0～63)" << std::endl;
						std::cout << ">";

						//set MicVolume
						data = getvalue();
						if (data != -1 && data < MovieRecVolume_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								EdsUInt32 _bodyID = _openedCamerasArray[i]->getbodyID();
								err = EdsGetPropertySize(_openedCamerasArray[i]->getCameraObject(),
									PropID,
									0,
									&dataType,
									&dataSize);

								err = EdsSetPropertyData(_openedCamerasArray[i]->getCameraObject(),
									PropID,
									0,
									dataSize,
									&data);

								// Notification of error
								if (err == EDS_ERR_OK)
								{
									std::cout << "camera" << _bodyID << " : property changed." << std::endl;
								}
								else
								{
									// It retries it at device busy
									if (err == EDS_ERR_DEVICE_BUSY)
									{
										std::cout << "DeviceBusy";
									}
									else
									{
										std::cout << "error invalid setting." << std::endl;
									}
								}
								pause_return();
							}
						}
						clr_screen();
						loop = true;
						continue;
					}
					// MovieParamEx
					else if (control_number == "45")
					{
						EdsUInt32 sfFlag;
						EdsUInt32 _bodyID;

						for (i = 0; i < _openedCamerasArray.size(); i++) {
							_bodyID = _openedCamerasArray[i]->getbodyID();
							// Acquisition of the property
							err = EdsGetPropertyData(_openedCamerasArray[i]->getCameraObject(),
								kEdsPropID_SlowFastMode,0,sizeof(EdsUInt32),&sfFlag);

							if (err == EDS_ERR_OK)
							{
								if (sfFlag == 0) {
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetPropertyEx(kEdsPropID_MovieParamEx, MovieQualityEx_table);
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetPropertyDescEx(kEdsPropID_MovieParamEx, MovieQualityEx_table);

									std::cout << "input no." << std::endl;
									std::cout << ">";

									data = getvalue();
									if (data != -1 || data <= MovieQualityEx_table.size())
									{
										for (i = 0; i < _openedCamerasArray.size(); i++)
										{
											_openedCamerasArray[i]->SetPropertyEx(kEdsPropID_MovieParamEx, data, MovieQualityEx_table);
										}
									}
								}
								else { // sfFlag :1
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetPropertyEx(kEdsPropID_MovieParamEx, MovieQualitySF_table);
									for (i = 0; i < _openedCamerasArray.size(); i++)
										_openedCamerasArray[i]->GetPropertyDescEx(kEdsPropID_MovieParamEx, MovieQualitySF_table);

									std::cout << "input no." << std::endl;
									std::cout << ">";

									data = getvalue();
									if (data != -1 || data <= MovieQualitySF_table.size())
									{
										for (i = 0; i < _openedCamerasArray.size(); i++)
										{
											_openedCamerasArray[i]->SetPropertyEx(kEdsPropID_MovieParamEx, data, MovieQualitySF_table);
										}
									}
								}
							}
							else
							{
								std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
									<< std::endl;
							}
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// select Picture Style
					else if (control_number == "50")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetProperty(kEdsPropID_PictureStyle, PictureStyle_table);
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_PictureStyle, PictureStyle_table);
						}
						std::cout << "Select " << std::endl;
						std::cout << ">";
						data = getvalue();

						if (data != -1 || data <= PictureStyle_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->SetProperty(kEdsPropID_PictureStyle, data, PictureStyle_table);
							pause_return();
						}

						clr_screen();
						loop = true;
						continue;
					}
					// Picture Style edit
					else if (control_number == "51")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_PictureStyleDesc);
						}

						EdsError err = EDS_ERR_OK;

						EdsPictureStyleDesc psdData{};

						std::cout << "--------------------------------" << std::endl;

						std::cout << "contrast [-4 - 4]" << std::endl;
						std::cout << ">";
						data = getIntValue();
						if (data == 0xff)
						{ // TODO Value Check incomplete
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}
						else
						{
							psdData.contrast = data;
						}

						std::cout << "sharpness [0 - 7]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 <= data < 8)
						{
							psdData.sharpness = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "saturation [-4 - 4]" << std::endl;
						std::cout << ">";
						data = getIntValue();
						if (data == 0xff)
						{ // TODO Value Check incomplete
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}
						else
						{
							psdData.saturation = data;
						}

						std::cout << "colorTone [-4 - 4]" << std::endl;
						std::cout << ">";
						data = getIntValue();
						if (data == 0xff)
						{ // TODO Value Check incomplete
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}
						else
						{
							psdData.colorTone = data;
						}

						std::cout << "filterEffect [0 - 4]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 <= data < 5)
						{
							psdData.filterEffect = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "toningEffect [0 - 4]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 <= data < 5)
						{
							psdData.toningEffect = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "sharpFineness [1 - 5]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 < data < 6)
						{
							psdData.sharpFineness = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "sharpThreshold [1 - 5]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 < data < 6)
						{
							psdData.sharpThreshold = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->SetPropertyValue(kEdsPropID_PictureStyleDesc, (EdsVoid*)&psdData);
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// get lens name
					else if (control_number == "60")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_LensName);
							std::cout << " \n"
								<< std::endl;
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// Lens IS Setting
					else if (control_number == "61")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_LensIsSetting);

						std::cout << "--------------------------------" << std::endl;
						std::cout << "Select setting Normal(0) or Force Off(1) ?" << std::endl;
						std::cout << ">";

						data = getvalue();
						
						if (data == 0 || data == 1)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetPropertyValue(kEdsPropID_LensIsSetting, (EdsVoid*)&data);
							}
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// ApertureLockSetting
					else if (control_number == "62")
					{
						EdsApertureLockSetting apldata{0};

						std::cout << "--------------------------------" << std::endl;
						std::cout << "ApertureLock on(1) or off(0) ?" << std::endl;
						std::cout << ">";
						apldata.apertureLockStatus = getvalue();

						if (apldata.apertureLockStatus == 0 || apldata.apertureLockStatus == 1)
						{
							if (apldata.apertureLockStatus == 1)
							{
								std::cout << "--------------------------------" << std::endl;
								std::cout << "Input Av (ex. 21 = 5.6)" << std::endl;

								for (i = 0; i < _openedCamerasArray.size(); i++)
									_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_Av, av_table);
								std::cout << ">";
								apldata.avValue = getvalue();
							}
							if (apldata.avValue != 0xffffffff) // 0xffffffff -> no input value(return key only)
							{
								for (i = 0; i < _openedCamerasArray.size(); i++)
								{
									_openedCamerasArray[i]->SetApertureLock((EdsApertureLockSetting*)&apldata, av_table);
								}
							}
							else
							{
								std::cout << "error invalid parameter." << std::endl;
							}
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// FocusShiftSetting
					else if (control_number == "63")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_FocusShiftSetting);
						}

						EdsError err = EDS_ERR_OK;

						EdsFocusShiftSet fssData;

						std::cout << "--------------------------------" << std::endl;
						std::cout << "input Version [1 - 3]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 < data < 3)
						{
							fssData.version = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "input FocusShiftFunction [0 - 1]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (data == 0 || data == 1)
						{
							fssData.focusShiftFunction = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "input ShootingNumber [2 - 999]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (1 < data < 1000)
						{
							fssData.shootingNumber = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "input StepWidth [1 - 10]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 < data < 11)
						{
							fssData.stepWidth = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "input ExposureSmoothing [0 - 1]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (data == 0 || data == 1)
						{
							fssData.exposureSmoothing = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "input FocusStackingFunction [0 - 1]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (data == 0 || data == 1)
						{
							fssData.focusStackingFunction = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "input FocusStackingTrimming [0 - 1]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (data == 0 || data == 1)
						{
							fssData.focusStackingTrimming = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						std::cout << "input FlashInterval [0 - 9]" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 <= data < 10)
						{
							fssData.flashInterval = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->SetPropertyValue(kEdsPropID_FocusShiftSetting, (EdsVoid*)&fssData);
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}




					// DriveFocusToEdge
					else if (control_number == "64")
					{
						EdsUInt32 NearOrFar;
						std::cout << "Move the focus position to near edge or far edge" << std::endl;
						std::cout << "input number 1(near edge) or 2(far edge)" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 <= data < 3)
						{
							NearOrFar = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						EdsError err = EDS_ERR_OK;

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->SetPropertyValue_NoSizeChk(kEdsPropID_DriveFocusToEdge, (EdsVoid*)NearOrFar);
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// RegisterFocusEdge
					else if (control_number == "65")
					{
						EdsUInt32 NearOrFar;
						std::cout << "Register the current focus position as near edge or far edge to the camera memory" << std::endl;
						std::cout << "input number 1(near edge) or 2(far edge)" << std::endl;
						std::cout << ">";
						data = getvalue();
						if (0 <= data < 3)
						{
							NearOrFar = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}

						EdsError err = EDS_ERR_OK;

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->SetPropertyValue_NoSizeChk(kEdsPropID_RegisterFocusEdge, (EdsVoid*)NearOrFar);
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// Get Current Focus Position
					else if (control_number == "66")
					{
						std::cout << "Get Current Focus Position" << std::endl;
						EdsError err = EDS_ERR_OK;

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_FocusPosition);
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// Move the Focus Position 
					else if (control_number == "67")
					{
						EdsUInt32 Position;
						std::cout << "Move the Focus Position" << std::endl;
						std::cout << "Before this operation, the near end and far end must be registered as all zero and all F, respectively." << std::endl;
						std::cout << "input focus position [ 0 to ffffffff ]" << std::endl;
						std::cout << ">";
						data = gethex();
						if (0 <= data <= 0xffffffff)
						{
							Position = data;
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}
						EdsError err = EDS_ERR_OK;

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->SetPropertyValue_NoSizeChk(kEdsPropID_FocusPosition, (EdsVoid*)Position);
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// auto power off
					else if (control_number == "70")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_AutoPowerOffSetting, AutoPowerOffSetting_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_AutoPowerOffSetting, AutoPowerOffSetting_table);

						std::cout << "input no. (ex. 1 = 15 sec)" << std::endl;
						std::cout << ">";
						
						data = getvalue();

						if (data != -1 && data <= AutoPowerOffSetting_table.size()-1) //Since the setting table contains a special setting (OFF), it is set to "AutoPowerOffSetting_table.size()-1".
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_AutoPowerOffSetting, data, AutoPowerOffSetting_table);
							}
							pause_return();
						}
						else if (data != -1)
						{
							std::cout << "error invalid setting." << std::endl;
							pause_return();
						}						
						clr_screen();
						loop = true;
						continue;
					}

					// Display Off Time
					else if (control_number == "71")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_ScreenOffTime);
							std::cout << " \n"
								<< std::endl;
						}

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_ScreenOffTime, ScreenOffTime_table);
							std::cout << " \n"
								<< std::endl;
						}

						std::cout << "input no." << std::endl;

						std::cout << ">";
						data = getvalue();

						if (data != -1 || data <= ScreenOffTime_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->SetProperty(kEdsPropID_ScreenOffTime, data, ScreenOffTime_table);
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}

					// View Finder Off Time
					else if (control_number == "72")
					{

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_ViewfinderOffTime);
							std::cout << " \n"
								<< std::endl;
						}

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_ViewfinderOffTime, ViewfinderOffTime_table);
							std::cout << " \n"
								<< std::endl;
						}

						std::cout << "input no." << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= ViewfinderOffTime_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_ViewfinderOffTime, data, ViewfinderOffTime_table);
								pause_return();
							}
						}
						clr_screen();
						loop = true;
						continue;
					}

					// Screen Dimmer Time
					else if (control_number == "73")
					{

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyvalue(kEdsPropID_ScreenDimmerTime);
							std::cout << " \n"
								<< std::endl;
						}

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_ScreenDimmerTime, ScreenDimmerTime_table);
							std::cout << " \n"
								<< std::endl;
						}

						std::cout << "input no." << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= ScreenDimmerTime_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_ScreenDimmerTime, data, ScreenDimmerTime_table);
								pause_return();
							}
						}
						clr_screen();
						loop = true;
						continue;
					}
						
					// DigitalZoomSetting
					else if (control_number == "80")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetProperty(kEdsPropID_DigitalZoomSetting, DigitalZoom_table);
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_DigitalZoomSetting, DigitalZoom_table);
						}
						std::cout << "Select " << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= DigitalZoom_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_DigitalZoomSetting, data, DigitalZoom_table);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
						}

					// ColorFilter(V10 only)
					else if (control_number == "81")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetProperty(kEdsPropID_ColorFilter, ColorFilter_table);
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_ColorFilter, ColorFilter_table);
						}
						std::cout << "Select " << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= ColorFilter_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_ColorFilter, data, ColorFilter_table);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}

					// AfLockState(V10 only)
					else if (control_number == "82")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetProperty(kEdsPropID_AfLockState, AfLockState_table);
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_AfLockState, AfLockState_table);
						}
						std::cout << "Select " << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= AfLockState_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_AfLockState, data, AfLockState_table);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}

					// BrightnessSetting(V10 only)
					else if (control_number == "83")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetProperty(kEdsPropID_BrightnessSetting, BrightnessSetting_table);
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_BrightnessSetting, BrightnessSetting_table);
						}
						std::cout << "Select " << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= BrightnessSetting_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_BrightnessSetting, data, BrightnessSetting_table);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}

					// Power zoom speed setting
					else if (control_number == "84")
					{
					for (i = 0; i < _openedCamerasArray.size(); i++)
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetProperty(kEdsPropID_PowerZoom_Speed, Powerzoom_table);
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_PowerZoom_Speed, Powerzoom_table);
					}
					std::cout << "Select " << std::endl;
					std::cout << ">";

					data = getvalue();
					if (data != -1 || data <= BrightnessSetting_table.size())
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->SetProperty(kEdsPropID_PowerZoom_Speed, data, Powerzoom_table);
						}
						pause_return();
					}
					clr_screen();
					loop = true;
					continue;
					}

					// Power zoom move to tele
					else if (control_number == "85")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->ZoomToTele();
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// Power zoom move to wide
					else if (control_number == "86")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->ZoomToWide();
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// Power zoom move to stop
					else if (control_number == "87")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->ZoomStop();
						}
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// Power zoom get zoom position
					else if (control_number == "88")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
							_openedCamerasArray[i]->GetZoomPosition();
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					
					// Target Flash Settings
					else if (control_number == "90")
					{

						EdsUInt32 dataSize = sizeof(EdsUInt32);

						EdsUInt32 _bodyID = 0;
						//view current setting
						for (i = 0; i < _openedCamerasArray.size(); i++) {
							_bodyID = _openedCamerasArray[i]->getbodyID();
							// Acquisition of the property
							err = EdsGetPropertyData(_openedCamerasArray[i]->getFlashObject(),
								kEdsPropID_Flash_Target,
								0,
								dataSize,
								&data);

							if (err == EDS_ERR_OK)
							{
								std::cout << "camera" << _bodyID << " : current setting is ";
								std::cout << data << "\n";
							}
							else if (err == EDS_ERR_PROPERTIES_UNAVAILABLE)
							{
								std::cout << "camera" << _bodyID << " : property value is not available. Please enter the property value using EdsSetPropertyData first. \n";

							}
							else
							{
								std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
									<< std::endl;
							}
						}

						std::cout << "--------------------------------" << std::endl;
						std::cout << "Select Unspecified(0) or External flash(1) ?" << std::endl;
						std::cout << ">";

						data = getvalue();

						if (data == 0 || data == 1)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{

								_bodyID = _openedCamerasArray[i]->getbodyID();
								_openedCamerasArray[i]->UILock();

								err = EdsSetPropertyData(_openedCamerasArray[i]->getFlashObject(),
									kEdsPropID_Flash_Target,
									0,
									dataSize,
									&data);

								std::this_thread::sleep_for(200ms);
								_openedCamerasArray[i]->UIUnLock();


								// Notification of error
								if (err == EDS_ERR_OK)
								{
									std::cout << "camera" << _bodyID << " : property changing." << std::endl;
								}
								else
								{
									// It retries it at device busy
									if (err == EDS_ERR_DEVICE_BUSY)
									{
										std::cout << "DeviceBusy";
									}
									else
									{
										std::cout << "error invalid setting." << std::endl;
									}
								}
							}
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
						}
						std::this_thread::sleep_for(200ms);
						pause_return();
						clr_screen();
						loop = true;
						continue;

					}
					// Flash Firing on/off
					else if (control_number == "91")
					{

						EdsUInt32 dataSize = sizeof(EdsUInt32);

						EdsUInt32 _bodyID = 0;
						//view current setting
						for (i = 0; i < _openedCamerasArray.size(); i++) {
							_bodyID = _openedCamerasArray[i]->getbodyID();
							// Acquisition of the property
							err = EdsGetPropertyData(_openedCamerasArray[i]->getFlashObject(),
								kEdsPropID_Flash_Firing,
								0,
								dataSize,
								&data);

							if (err == EDS_ERR_OK)
							{
								std::cout << "camera" << _bodyID << " : current setting is ";
								std::cout << data << "\n";
							}
							else if(err == EDS_ERR_PROPERTIES_UNAVAILABLE)
							{
								std::cout << "camera" << _bodyID << " : property value is not available. Please enter the property value using EdsSetPropertyData first. \n";
								
							}
							else
							{
								std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
								<< std::endl;
							}
						}

						std::cout << "--------------------------------" << std::endl;
						std::cout << "Select Off(0) or Fire(1) ?" << std::endl;
						std::cout << ">";

						data = getvalue();

						if (data == 0 || data == 1)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{

								_bodyID = _openedCamerasArray[i]->getbodyID();
								_openedCamerasArray[i]->UILock();
								
								err = EdsSetPropertyData(_openedCamerasArray[i]->getFlashObject(),
									kEdsPropID_Flash_Firing,
									0,
									dataSize,
									&data);

								std::this_thread::sleep_for(200ms);
								_openedCamerasArray[i]->UIUnLock();


								// Notification of error
								if (err == EDS_ERR_OK)
								{
									std::cout << "camera" << _bodyID << " : property changing." << std::endl;
								}
								else
								{
									// It retries it at device busy
									if (err == EDS_ERR_DEVICE_BUSY)
									{
										std::cout << "DeviceBusy";
									}
									else
									{
										std::cout << "error invalid setting." << std::endl;
									}
								}
							}
						}
						else
						{
							std::cout << "error invalid parameter." << std::endl;
						}
						std::this_thread::sleep_for(200ms);
						pause_return();
						clr_screen();
						loop = true;
						continue;
					}

					// IBIS 
					else if (control_number == "98")
					{
						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetProperty(kEdsPropID_IBIS_HighResoShot, IBIS_HighResoShot_table);
							for (i = 0; i < _openedCamerasArray.size(); i++)
								_openedCamerasArray[i]->GetPropertyDesc(kEdsPropID_IBIS_HighResoShot, IBIS_HighResoShot_table);
						}
						std::cout << "Select " << std::endl;
						std::cout << ">";

						data = getvalue();
						if (data != -1 || data <= IBIS_HighResoShot_table.size())
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								_openedCamerasArray[i]->SetProperty(kEdsPropID_IBIS_HighResoShot, data, IBIS_HighResoShot_table);
							}
							pause_return();
						}
						clr_screen();
						loop = true;
						continue;
					}
					
					// WhiteBalanceShift
					else if (control_number == "99")
					{
						EdsInt32 wbShiftValue[2];

						std::cout << "--------------------------------" << std::endl;
						std::cout << "input ValueAB [-9 ~ +9]" << std::endl;
						std::cout << ">";
						data = getIntValue();
						if (data == 0xff)
						{ // TODO Value Check incomplete
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}
						else
						{
							wbShiftValue[0] = data;
						}

						std::cout << "input ValueGM [-9 ~ +9]" << std::endl;
						std::cout << ">";
						data = getIntValue();
						if (data == 0xff)
						{ // TODO Value Check incomplete
							pause_return();
							clr_screen();
							loop = true;
							continue;
						}
						else
						{
							wbShiftValue[1] = data;
						}
						EdsError err = EDS_ERR_OK;

						for (i = 0; i < _openedCamerasArray.size(); i++)
						{
							_openedCamerasArray[i]->SetPropertyValue(kEdsPropID_WhiteBalanceShift, (EdsVoid *)wbShiftValue);
						}

						pause_return();
						clr_screen();
						loop = true;
						continue;
					}
					// TakePicturetimeinterval
					else if (control_number == "100")
					{
						EdsUInt32 times, interval;

						std::cout << "input number of picture times" << std::endl;
						std::cout << ">";
						data = getvalue();
						times = data;

						std::cout << "input number of interval[second]" << std::endl;
						std::cout << ">";
						data = getvalue();
						interval = data;

						EdsError err = EDS_ERR_OK;
						int i, count;
						for (count = 0; count < times; count++)
						{
							for (i = 0; i < _openedCamerasArray.size(); i++)
							{
								err = _openedCamerasArray[i]->TakePicture(kEdsCameraCommand_ShutterButton_Completely_NonAF);
								EdsGetEvent();
							}
							std::this_thread::sleep_for(std::chrono::seconds(interval));
						}
						clr_screen();
						loop = true;
						continue;
					}

					// other
					else
					{
						clr_screen();
						loop = true;
						continue;
					}
				}
				// Return
				else if (std::regex_search(control_number, match_results, std::regex("r", std::regex_constants::icase)))
				{
					clr_screen();
					keyflag = false;
					break;
				}
				else
				{
					clr_screen();
					loop = true;
					continue;
				}
			}
			// send getevent periodically
			EdsGetEvent();
			std::this_thread::sleep_for(200ms);
		}

		EdsUInt32 refcount = 0;
		bool berr = true;
		// Release camera list
		if (cameraList != NULL)
		{
			refcount = EdsRelease(cameraList);
		}

		// Release Camera

		for (i = 0; i < _openedCamerasArray.size(); i++)
		{
			if (_openedCamerasArray[i] != NULL)
			{
				berr = _openedCamerasArray[i]->CloseSessionCommand();
				refcount = EdsRelease(_openedCamerasArray[i]->getCameraObject());
				_openedCamerasArray[i] = NULL;
			}
		}
		// Remove elements before looping. Memory is automatically freed at the destructor of the vector when it leaves the scope.
		_openedCamerasArray.clear();
		clr_screen();
	}

	// Termination of SDK
	if (isSDKLoaded)
	{
		EdsTerminateSDK();
	}

	return FALSE;
}