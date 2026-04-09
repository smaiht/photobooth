#include <cstring>
#include <filesystem>
#include <iostream>
#include <iterator>
#include <list>
#include <map>
#include <memory>
#include <regex>
#include <string>
#include <vector>
#include <thread>
#include <sstream>
#include "EDSDK.h"
#include "EDSDKTypes.h"
#include "CameraModel.h"

EdsError CameraModel::UILock()
{
	EdsError err = EDS_ERR_OK;
	if (_lockCount == 0)
	{
		err = EdsSendStatusCommand(_camera, kEdsCameraStatusCommand_UILock, 1); // inParam = 0:TFT ON, 1:TFT OFF
	}
	if (err == EDS_ERR_OK)
	{
		//		std::cout << "Cam No." << _bodyID << ":" << _modelName << " UI locked" << std::endl;
		_lockCount += 1;
	}
	else
	{
		std::cout << "Cam No." << _bodyID << ":" << _modelName << " UI lock error !!" << std::endl;
	}
	return err;
}

EdsError CameraModel::UIUnLock()
{
	EdsError err = EDS_ERR_OK;
	if (_lockCount > 0)
	{
		err = EdsSendStatusCommand(_camera, kEdsCameraStatusCommand_UIUnLock, 0);
	}
	if (err == EDS_ERR_OK)
	{
		//		std::cout << "Cam No." << _bodyID << ":" << _modelName << " UI Unlocked" << std::endl;
		_lockCount -= 1;
	}
	else
	{
		std::cout << "Cam No." << _bodyID << ":" << _modelName << " UI Unlock error !!" << std::endl;
	}
	return err;
}

bool CameraModel::OpenSessionCommand()
{
	EdsError err = EDS_ERR_OK;
	bool locked = false;

	std::cout << "Cam No." << _bodyID << ":" << _modelName << " -> session openning" << std::endl;

	// enable property
	err = EdsSetPropertyData(_camera, 0x01000000, 0x51DD2696, sizeof(EdsUInt32), &PropID_UTCTime);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x00FA71F7, sizeof(EdsUInt32), &PropID_TimeZone);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x09780670, sizeof(EdsUInt32), &PropID_SummerTimeSetting);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x20DD3609, sizeof(EdsUInt32), &PropID_ManualWhiteBalanceData);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x14840DF1, sizeof(EdsUInt32), &PropID_TempStatus);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x00E13499, sizeof(EdsUInt32), &PropID_MirrorLockUpState);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x17AF25B1, sizeof(EdsUInt32), &PropID_FixedMovie);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x2A0C1274, sizeof(EdsUInt32), &PropID_MovieParam);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x3FB1718B, sizeof(EdsUInt32), &PropID_Aspect);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x517F095D, sizeof(EdsUInt32), &PropID_MirrorUpSetting);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x1C31565B, sizeof(EdsUInt32), &PropID_AutoPowerOffSetting);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x707571DF, sizeof(EdsUInt32), &PropID_FocusShiftSetting);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x44396197, sizeof(EdsUInt32), &PropID_MovieHFRSetting);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x5B960B1C, sizeof(EdsUInt32), &PropID_RegisterFocusEdge);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x5AB16AAC, sizeof(EdsUInt32), &PropID_DriveFocusToEdge);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x5F745B48, sizeof(EdsUInt32), &PropID_FocusPosition);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x1EDD16B6, sizeof(EdsUInt32), &PropID_StillMovieDivideSetting);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x4FB44E3C, sizeof(EdsUInt32), &PropID_CardExtension);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x5C6C20B2, sizeof(EdsUInt32), &PropID_MovieCardExtension);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x139E4D1D, sizeof(EdsUInt32), &PropID_StillCurrentMedia);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x00D50906, sizeof(EdsUInt32), &PropID_MovieCurrentMedia);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x7DE61188, sizeof(EdsUInt32), &PropID_ApertureLockSetting);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x2532744B, sizeof(EdsUInt32), &PropID_LensIsSetting);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x2472666C, sizeof(EdsUInt32), &PropID_ScreenDimmerTime);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x27B64F45, sizeof(EdsUInt32), &PropID_ScreenOffTime);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x18F75F17, sizeof(EdsUInt32), &PropID_ViewfinderOffTime);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x653048A9, sizeof(EdsUInt32), &PropID_Evf_ClickWBCoeffs);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x05B3740D, sizeof(EdsUInt32), &PropID_Evf_RollingPitching);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x4D2879F3, sizeof(EdsUInt32), &PropID_Evf_VisibleRect);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x7CBD2BB7, sizeof(EdsUInt32), &PropID_Evf_ViewType);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x54D820D3, sizeof(EdsUInt32), &PropID_MovieRecVolume_IntMic);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x20DD3087, sizeof(EdsUInt32), &PropID_MovieRecVolume_ExtMic);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x703F0EAA, sizeof(EdsUInt32), &PropID_MovieRecVolume_Acc);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x57E66AD7, sizeof(EdsUInt32), &PropID_MovieParamEx);
	err = EdsSetPropertyData(_camera, 0x01000000, 0x2FEF13CD, sizeof(EdsUInt32), &PropID_SlowFastMode);

	// The communication with the camera begins
	err = EdsOpenSession(_camera);

	// for powershot
	// err = EdsSendCommand(_camera, kEdsCameraCommand_SetRemoteShootingMode, kDcRemoteShootingModeStart);

	if (err == EDS_ERR_OK)
	{
		err = EdsSetPropertyData(_camera, kEdsPropID_SaveTo, 0, sizeof(_saveTo), &_saveTo);
	}

	// UI lock
	UILock();

	if (err == EDS_ERR_OK)
	{
		locked = true;
	}

	if (err == EDS_ERR_OK)
	{
		EdsCapacity capacity = {0x7FFFFFFF, 0x1000, 1};
		err = EdsSetCapacity(_camera, capacity);
	}

	// It releases it when locked
	UIUnLock();

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It retries it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "Error Cam No." << _bodyID << ":" << _modelName << "DeviceBusy" << std::endl;
		}
		std::cout << "Error Cam No." << _bodyID << ":" << _modelName << std::endl;
	}
	return true;
}

bool CameraModel::CloseSessionCommand()
{
	EdsError err = EDS_ERR_OK;

	std::cout << "session closing" << std::endl;
	// The communication with the camera is ended
	err = EdsCloseSession(_camera);
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It retries it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "Error Cam No." << _bodyID << ":" << _modelName << "DeviceBusy" << std::endl;
		}
		std::cout << "Error Cam No." << _bodyID << ":" << _modelName << std::endl;
	}
	return true;
}

EdsError CameraModel::TakePicture(EdsShutterButton shuttertype)
{
	EdsError err = EDS_ERR_OK;
	std::cout << "shooting cam" << _bodyID << std::endl;
	err = PressShutter(shuttertype);
	if (err != EDS_ERR_OK)
	{
		PressShutter(kEdsCameraCommand_ShutterButton_OFF);
		err = EDS_ERR_INTERNAL_ERROR;
	}
	else
	{
		err = PressShutter(kEdsCameraCommand_ShutterButton_OFF);
	}
	return err;
}

EdsError CameraModel::PressShutter(EdsUInt32 _status)
{
	EdsError err = EDS_ERR_OK;
	err = EdsSendCommand(_camera, kEdsCameraCommand_PressShutterButton, _status);
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It retries it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "Error Cam No." << _bodyID << ":" << _modelName << "DeviceBusy" << std::endl;
		}
		std::cout << "Error Cam No." << _bodyID << ":" << _modelName << std::endl;
	}
	return err;
}

EdsError CameraModel::SendCommand(EdsUInt32 _command, EdsUInt32 _status)
{
	EdsError err = EDS_ERR_OK;
	err = EdsSendCommand(_camera, _command, _status);
	return err;
}

bool CameraModel::DoEvfAFCommand(EdsUInt32 _status)

{
	EdsError err = EDS_ERR_OK;
	// EvfAFON
	if (err == EDS_ERR_OK)
	{
		err = EdsSendCommand(_camera, kEdsCameraCommand_DoEvfAf, _status);
	}

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It retries it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "Error Cam No." << _bodyID << ":" << _modelName << "DeviceBusy" << std::endl;
		}
		std::cout << "Error Cam No." << _bodyID << ":" << _modelName << std::endl;
	}

	return true;
}

EdsError CameraModel::GetPropertyvalue(EdsPropertyID propertyID)
{
	EdsError err = EDS_ERR_OK;
	EdsDataType dataType = EdsDataType::kEdsDataType_Unknown;
	EdsUInt32 dataSize = 0;
	err = EdsGetPropertySize(_camera,
							 propertyID,
							 0,
							 &dataType,
							 &dataSize);
	if (err == EDS_ERR_OK)
	{
		if (dataType == EdsDataType::kEdsDataType_UInt32 || dataType == EdsDataType::kEdsDataType_Int32)
		{
			EdsUInt32 data = 0;

			// Acquisition of the property
			err = EdsGetPropertyData(_camera,
									 propertyID,
									 0,
									 dataSize,
									 &data);

			if (err == EDS_ERR_OK)
			{
				std::cout << "camera" << _bodyID << " : current value is " << data;
			}
		}
		else if (dataType == EdsDataType::kEdsDataType_String)
		{
			EdsChar str[EDS_MAX_NAME] = {};
			// Acquisition of the property
			err = EdsGetPropertyData(_camera,
									 propertyID,
									 0,
									 dataSize,
									 str);

			if (err == EDS_ERR_OK)
			{
				std::cout << "camera" << _bodyID << " : current value is " << str;
			}
		}
		else if (dataType == EdsDataType::kEdsDataType_ByteBlock)
		{
			if (propertyID == kEdsPropID_FocusShiftSetting)
			{
				EdsFocusShiftSet fssData;
				err = EdsGetPropertyData(_camera,
										 propertyID,
										 0,
										 dataSize,
										 &fssData);

				if (err == EDS_ERR_OK)
				{
					std::cout
						<< "Version : " << fssData.version << "\n"
						<< "FocusShiftFunction : " << fssData.focusShiftFunction << "\n"
						<< "ShootingNumber : " << fssData.shootingNumber << "\n"
						<< "StepWidth : " << fssData.stepWidth << "\n"
						<< "ExposureSmoothing : " << fssData.exposureSmoothing << std::endl;
					if (fssData.version >= 3)
					{
						std::cout
							<< "FocusStackingFunction : " << fssData.focusStackingFunction << "\n"
							<< "FocusStackingTrimming : " << fssData.focusStackingTrimming << "\n"
							<< "FlashInterval( Available only for supported models) : " << fssData.flashInterval << std::endl;
					}
				}
			}
			else if (propertyID == kEdsPropID_MovieFileNameReelNo || propertyID == kEdsPropID_MovieFileNameClipNo)
			{
				EdsMovieFileNoSet noset = {0};
				int num;

				err = EdsGetPropertyData(_camera,
					propertyID,
					0,
					dataSize,
					&noset);

				if (err == EDS_ERR_OK)
				{
					std::cout << "camera" << _bodyID << " : current value is " <<  noset.number;
				}
			}
		}
		else if (dataType == EdsDataType::kEdsDataType_PictureStyleDesc)
		{
			EdsPictureStyleDesc psdData;
			err = EdsGetPropertyData(_camera,
									 propertyID,
									 0,
									 dataSize,
									 &psdData);

			if (err == EDS_ERR_OK)
			{
				std::cout
					<< "contrast       : " << psdData.contrast << "\n"
					<< "sharpness      : " << psdData.sharpness << "\n"
					<< "saturation     : " << psdData.saturation << "\n"
					<< "colorTone      : " << psdData.colorTone << "\n"
					<< "filterEffect   : " << psdData.filterEffect << "\n"
					<< "toningEffect   : " << psdData.toningEffect << "\n"
					<< "sharpFineness  : " << psdData.sharpFineness << "\n"
					<< "sharpThreshold : " << psdData.sharpThreshold << std::endl;
			}
		}
		if (err != EDS_ERR_OK)
		{
			// Notification of error
			std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
					  << std::endl;
		}
	}
	else
	{
		// Notification of error
		std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
				  << std::endl;
	}
	return err;
}

EdsError CameraModel::GetProperty(EdsPropertyID propertyID, std::map<EdsUInt32, const char *> table)
{
	EdsError err = EDS_ERR_OK;
	EdsDataType dataType = EdsDataType::kEdsDataType_Unknown;
	EdsUInt32 dataSize = 0;
	err = EdsGetPropertySize(_camera,
							 propertyID,
							 0,
							 &dataType,
							 &dataSize);
	if (err == EDS_ERR_OK)
	{
		if (dataType == EdsDataType::kEdsDataType_UInt32 || dataType == EdsDataType::kEdsDataType_Int32)
		{
			EdsUInt32 data = 0;

			// Acquisition of the property
			err = EdsGetPropertyData(_camera,
									 propertyID,
									 0,
									 dataSize,
									 &data);

			std::map<EdsUInt32, const char *>::iterator itr = table.find(data);
			if (itr != table.end())
			{
				// Set String combo box
				std::cout << "camera" << _bodyID << " : current setting is ";
				std::cout << itr->second << "\n"
						  << std::endl;
				//					std::cout << "distance=" << std::distance(table.begin(), itr) << std::endl;
			}
		}

		if (dataType == EdsDataType::kEdsDataType_ByteBlock)
		{
			EdsUInt64 data = 0;

			// Acquisition of the property
			err = EdsGetPropertyData(_camera,
				propertyID,
				0,
				dataSize,
				&data);

			std::map<EdsUInt32, const char*>::iterator itr = table.find(data);
			if (itr != table.end())
			{
				// Set String combo box
				std::cout << "camera" << _bodyID << " : current setting is ";
				std::cout << itr->second << "\n"
					<< std::endl;
			}
		}

		if (dataType == EdsDataType::kEdsDataType_String)
		{
			EdsChar str[EDS_MAX_NAME] = {};
			// Acquisition of the property
			err = EdsGetPropertyData(_camera,
									 propertyID,
									 0,
									 dataSize,
									 str);

			// Acquired property value is set
			if (err == EDS_ERR_OK)
			{
				std::cout << "camera" << _bodyID << " : current setting is ";
				std::cout << str << "\n"
						  << std::endl;
			}
		}
	}
	else
	{
		std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
				  << std::endl;
	}
	return err;
}

EdsError CameraModel::GetPropertyEx(EdsPropertyID propertyID, std::map<EdsUInt64, const char*> table)
{
	EdsError err = EDS_ERR_OK;
	EdsDataType dataType = EdsDataType::kEdsDataType_Unknown;
	EdsUInt32 dataSize = 0;
	err = EdsGetPropertySize(_camera,
		propertyID,
		0,
		&dataType,
		&dataSize);
	if (err == EDS_ERR_OK)
	{
		if (dataType == EdsDataType::kEdsDataType_ByteBlock)
		{
			EdsUInt64 data = 0;

			// Acquisition of the property
			err = EdsGetPropertyData(_camera,
				propertyID,
				0,
				dataSize,
				&data);

			std::map<EdsUInt64, const char*>::iterator itr = table.find(data);
			if (itr != table.end())
			{
				// Set String combo box
				std::cout << "camera" << _bodyID << " : current setting is ";
				std::cout << itr->second << "\n"
					<< std::endl;
			}
		}

	}
	else
	{
		std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
			<< std::endl;
	}
	return err;
}


EdsError CameraModel::GetPropertyDesc(EdsPropertyID propertyID, std::map<EdsUInt32, const char *> prop_table)
{
	EdsError err = EDS_ERR_OK;
	EdsPropertyDesc propertyDesc = {0};
	std::vector<EdsInt32> duplicate_check;
	// Get property
	if (err == EDS_ERR_OK)
	{
		err = EdsGetPropertyDesc(_camera,
								 propertyID,
								 &propertyDesc);
	}
	if (err == EDS_ERR_OK)
	{
		std::cout << "camera" << _bodyID << "'s \t available settings are...";
		for (int propDescNum = 0; propDescNum < propertyDesc.numElements; propDescNum++)
		{
			if ((propDescNum % 4) == 0)
			{
				std::cout << std::endl;
			}
			EdsInt32 key = propertyDesc.propDesc[propDescNum];
			auto insert = std::find(duplicate_check.begin(), duplicate_check.end(), key);
			if (insert == duplicate_check.end()) // check for dupulicate
			{
				duplicate_check.insert(insert, key);
				std::map<EdsUInt32, const char *>::iterator itr = prop_table.find(propertyDesc.propDesc[propDescNum]);
				if (itr != prop_table.end())
				{
					std::cout << std::setw(4) << std::right << std::distance(prop_table.begin(), itr) << ":";
					std::cout << std::setw(7) << std::right << itr->second << "      ";
					std::cout << std::left;
				}
			}
		}
		std::cout << "\n"
				  << std::endl;
	}
	return err;
}


EdsError CameraModel::GetPropertyDescEx(EdsPropertyID propertyID, std::map<EdsUInt64, const char*> prop_table)
{
	EdsError err = EDS_ERR_OK;
	EdsPropertyDescEx propertyDesc = { 0 };
	std::vector<EdsInt32> duplicate_check;
	// Get property
	if (err == EDS_ERR_OK)
	{
		err = EdsGetPropertyDescEx(_camera,
			propertyID,
			&propertyDesc);
	}
	if (err == EDS_ERR_OK)
	{
		std::cout << "camera" << _bodyID << "'s \t available settings are...";
		for (int propDescNum = 0; propDescNum < propertyDesc.numElements; propDescNum++)
		{
			if ((propDescNum % 4) == 0)
			{
				std::cout << std::endl;
			}
			EdsInt32 key = propertyDesc.propDesc[propDescNum];
			auto insert = std::find(duplicate_check.begin(), duplicate_check.end(), key);
			if (insert == duplicate_check.end()) // check for dupulicate
			{
				duplicate_check.insert(insert, key);
				std::map<EdsUInt64, const char*>::iterator itr = prop_table.find(propertyDesc.propDesc[propDescNum]);
				if (itr != prop_table.end())
				{
					std::cout << std::setw(4) << std::right << std::distance(prop_table.begin(), itr) << ":";
					std::cout << std::setw(7) << std::right << itr->second << "      ";
					std::cout << std::left;
				}
			}
		}
		std::cout << "\n"
			<< std::endl;
	}
	return err;
}

EdsError CameraModel::SetPropertyValue(EdsPropertyID propertyID, std::string data)
{
	EdsError err = EDS_ERR_OK;
	EdsDataType dataType = EdsDataType::kEdsDataType_Unknown;
	EdsUInt32 dataSize = 0;
	err = EdsGetPropertySize(_camera,
							 propertyID,
							 0,
							 &dataType,
							 &dataSize);
	if (err == EDS_ERR_OK)
	{
		if (dataType == EdsDataType::kEdsDataType_UInt32 || dataType == EdsDataType::kEdsDataType_Int32)
		{
			// Acquisition of the property
			err = EdsSetPropertyData(_camera,
									 propertyID,
									 0,
									 dataSize,
									 &data);

			if (err == EDS_ERR_OK)
			{
				std::cout << "camera" << _bodyID << " : property changed "
						  << "\n"
						  << std::endl;
			}
			else
			{
				std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
						  << std::endl;
			}
		}

		if (dataType == EdsDataType::kEdsDataType_String)
		{
			EdsUInt32 size = (EdsUInt32)data.size();
			// std::cout << cstr << std::endl;
			// Acquisition of the property

			//In the case of kEdsPropID_StillFileName setting, null characters are not needed, so distinguish between the cases.
			if (propertyID == kEdsPropID_StillFileNameUserSet1 || propertyID == kEdsPropID_StillFileNameUserSet2
				|| propertyID == kEdsPropID_MovieFileNameIndex || propertyID == kEdsPropID_MovieFileNameUserDef
				|| propertyID == kEdsPropID_StillFolderName)
			{
				EdsChar* cstr = new char[size];
				data.copy(cstr, size);
				cstr[size] = '\0';
				err = EdsSetPropertyData(_camera,
					propertyID,
					0,
					size,
					cstr);
			}
			else
			{
				EdsChar* cstr = new char[size + 1];
				data.copy(cstr, size);
				cstr[size] = '\0';
				err = EdsSetPropertyData(_camera,
					propertyID,
					0,
					size + 1,
					cstr);
			}			

			if (err == EDS_ERR_OK)
			{
				std::cout << "camera" << _bodyID << " : property changed "
						  << "\n"
						  << std::endl;
				;
			}
			else
			{
				std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
						  << std::endl;
			}
		}
	}
	return err;
}

EdsError CameraModel::SetPropertyValue(EdsPropertyID propertyID, const EdsVoid *data)
{
	EdsError err = EDS_ERR_OK;
	EdsUInt32 dataSize = 0;
	EdsDataType dataType = EdsDataType::kEdsDataType_Unknown;

	err = EdsGetPropertySize(_camera,
							 propertyID,
							 0,
							 &dataType,
							 &dataSize);

	if (err == EDS_ERR_OK)
	{
		// Acquisition of the property
		err = EdsSetPropertyData(_camera,
								 propertyID,
								 0,
								 dataSize,
								 (EdsVoid *)data);

		if (err == EDS_ERR_OK)
		{
			std::cout << "camera" << _bodyID << " : property changed "
					  << "\n"
					  << std::endl;
		}
		else
		{
			std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
					  << std::endl;
		}
	}
	return err;
}

EdsError CameraModel::SetPropertyEx(EdsPropertyID propertyID, EdsInt32 data, std::map<EdsUInt64, const char*> prop_table)
{
	EdsError err = EDS_ERR_OK;
	EdsDataType dataType = EdsDataType::kEdsDataType_Unknown;
	EdsUInt32 dataSize = 0; // Set property

	EdsPropertyDescEx propertyDesc = { 0 };
	// Get property
	err = EdsGetPropertyDescEx(_camera,
		propertyID,
		&propertyDesc);

	EdsUInt64 input_prop;
	if (err == EDS_ERR_OK)
	{
		//auto iter = prop_table.begin();
		auto iter = prop_table.begin();
		std::advance(iter, (EdsUInt64)data); // Advance the iterator to the datath map
		input_prop = iter->first;
		bool exists = std::find(propertyDesc.propDesc, propertyDesc.propDesc + propertyDesc.numElements, input_prop) != propertyDesc.propDesc + propertyDesc.numElements;
		if (exists)
		{
			err = EdsGetPropertySize(_camera,
				propertyID,
				0,
				&dataType,
				&dataSize);
			if (err == EDS_ERR_OK)
			{
				err = EdsSetPropertyData(_camera,
					propertyID,
					0,
					dataSize,
					&input_prop);
			}
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
		}
		else
		{
			std::cout << "error invalid setting." << std::endl;
		}
	}

	return err;
}

EdsError CameraModel::SetProperty(EdsPropertyID propertyID, EdsInt32 data, std::map<EdsUInt32, const char *> prop_table)
{
	EdsError err = EDS_ERR_OK;
	EdsDataType dataType = EdsDataType::kEdsDataType_Unknown;
	EdsUInt32 dataSize = 0; // Set property
	EdsPropertyDesc propertyDesc = {0};
	// Get property
	err = EdsGetPropertyDesc(_camera,
							 propertyID,
							 &propertyDesc);
	EdsInt32 input_prop;
	if (err == EDS_ERR_OK)
	{
		auto iter = prop_table.begin();
		std::advance(iter, (EdsInt32)data); // Advance the iterator to the datath map
		input_prop = iter->first;
		bool exists = std::find(propertyDesc.propDesc, propertyDesc.propDesc + propertyDesc.numElements, input_prop) != propertyDesc.propDesc + propertyDesc.numElements;
		if (exists)
		{
			err = EdsGetPropertySize(_camera,
									 propertyID,
									 0,
									 &dataType,
									 &dataSize);
			if (err == EDS_ERR_OK)
			{
				err = EdsSetPropertyData(_camera,
										 propertyID,
										 0,
										 dataSize,
										 &input_prop);
			}
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
		}
		else
		{
			std::cout << "error invalid setting." << std::endl;
		}
	}

	return err;
}

EdsError CameraModel::SetPropertyValue_NoSizeChk(EdsPropertyID propertyID, const EdsVoid* data)
{
	EdsError err = EDS_ERR_OK;
	uintptr_t Uint32_data = (uintptr_t)data;
	// Acquisition of the property
	err = EdsSetPropertyData(_camera,
		propertyID,
		0,
		sizeof(EdsUInt32),
		&Uint32_data);

	if (err == EDS_ERR_OK)
	{
		std::cout << "camera" << _bodyID << " : property changed "
			<< "\n"
			<< std::endl;
	}
	else
	{
		std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
			<< std::endl;
	}
	return err;
}

EdsError CameraModel::SetApertureLock(const EdsApertureLockSetting* data, std::map<EdsUInt32, const char*> prop_table)
{
	EdsError err = EDS_ERR_OK;
	// Acquisition of the property
	EdsUInt32 datasize = sizeof(EdsApertureLockSetting);
	EdsUInt32 current_aperture;
	EdsApertureLockSetting apldata = { 0 };
	EdsPropertyDesc propertyDesc = { 0 };

	// Get property
	err = EdsGetPropertyData(_camera,
		kEdsPropID_Av,
		0,
		sizeof(EdsUInt32),
		&current_aperture);

	apldata.apertureLockStatus = data->apertureLockStatus;

	if (apldata.apertureLockStatus == 0 )
	{
		apldata.avValue = current_aperture;
	}
	else
	{
		apldata.avValue = data->avValue;
	}

	if (apldata.apertureLockStatus == 1)
	{
		auto iter = prop_table.begin();
		std::advance(iter, data->avValue); // Advance the iterator to the datath map
		apldata.avValue = iter->first;

		err = EdsGetPropertyDesc(_camera,
			kEdsPropID_Av,
			&propertyDesc);
		bool exists = std::find(propertyDesc.propDesc, propertyDesc.propDesc + propertyDesc.numElements, apldata.avValue) != propertyDesc.propDesc + propertyDesc.numElements;

		if (!exists)
		{
			std::cout << "error invalid setting." << std::endl;
			return err = EDS_ERR_INTERNAL_ERROR;
		}
	}

	err = EdsSetPropertyData(_camera,
		kEdsPropID_ApertureLockSetting,
		0,
		datasize,
		&apldata);

	if (err == EDS_ERR_OK)
	{
		std::cout << "camera" << _bodyID << " : property changed "
			<< "\n"
			<< std::endl;
	}
	else
	{
		std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
			<< std::endl;
	}
	return err;
}

EdsError CameraModel::SetMovieFileName(EdsPropertyID propertyID, std::string data)
{
	EdsError err = EDS_ERR_OK;
	EdsUInt32 strsize = (EdsUInt32)data.size();
	EdsUInt32 datasize = sizeof(EdsMovieFileNoSet);
	EdsUInt32 intdata = 0;
	EdsMovieFileNoSet noset = {0};

	std::stringstream(data) >> intdata;
	std::stringstream ss; 
	ss << std::hex ; 
	ss << intdata;
	std::string hexString = ss.str();
	noset.number = static_cast<EdsUInt16>(std::stoul(hexString, nullptr, 16));

	err = EdsSetPropertyData(_camera,
		propertyID,
		0,
		datasize,
		&noset);

	if (err == EDS_ERR_OK)
	{
		std::cout << "camera" << _bodyID << " : property changed "
			<< "\n"
			<< std::endl;
	}
	else
	{
		std::cout << "camera" << _bodyID << " : err " << std::hex << err << "\n"
			<< std::endl;
	}
	return err;

}


EdsError CameraModel::RecModeOn()
{
	EdsError err = EDS_ERR_OK;
	EdsUInt32 saveTo = kEdsSaveTo_Camera;
	err = EdsSetPropertyData(_camera, kEdsPropID_SaveTo, 0, sizeof(saveTo), &saveTo);
	// movieMode 0 : Disable , 1 : Enable
	EdsUInt32 movieMode;
	// Get movie mode.
	err = EdsGetPropertyData(_camera, kEdsPropID_FixedMovie, 0, sizeof(movieMode), &movieMode);
	if (movieMode == 0)
	{ // movieMode 0 : Disable , 1 : Enable
		// Set movie mode ON.
		err = EdsSendCommand(_camera, kEdsCameraCommand_MovieSelectSwON, 0);
	}
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}
	return true;
}

EdsError CameraModel::RecModeOff()
{
	EdsError err = EDS_ERR_OK;
	// movieMode 0 : Disable , 1 : Enable
	EdsUInt32 movieMode;
	// Get movie mode.
	err = EdsGetPropertyData(_camera, kEdsPropID_FixedMovie, 0, sizeof(movieMode), &movieMode);
	if (movieMode == 1)
	{ // movieMode 0 : Disable , 1 : Enable
		// Set movie mode ON.
		err = EdsSendCommand(_camera, kEdsCameraCommand_MovieSelectSwOFF, 0);
	}
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}
	return true;
}

EdsError CameraModel::RecStart()
{
	EdsError err = EDS_ERR_OK;
	EdsUInt32 saveto;

	saveto = kEdsSaveTo_Camera;

	// Set kEdsPropID_SaveTo property to kEdsSaveTo_Camera before changing Movie mode to ON
	err = EdsSetPropertyData(_camera, kEdsPropID_SaveTo, 0, sizeof(EdsUInt32), &saveto);
	EdsUInt32 record_start = 4; // Begin movie shooting
	err = EdsSetPropertyData(_camera, kEdsPropID_Record, 0, sizeof(record_start), &record_start);
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}
	return true;
}

EdsError CameraModel::RecEnd()
{
	EdsError err = EDS_ERR_OK;
	EdsUInt32 saveto;

	saveto = kEdsSaveTo_Camera;

	EdsUInt32 record_stop = 0; // End movie shooting
	err = EdsSetPropertyData(_camera, kEdsPropID_Record, 0, sizeof(record_stop), &record_stop);
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}
	return true;
}

EdsError CameraModel::StartEvfCommand()
{
	EdsError err = EDS_ERR_OK;
	/// Change settings because live view cannot be started
	/// when camera settings are set to do not perform live view.
	EdsUInt32 evfMode = 0;

	// Acquisition of the property
	err = EdsGetPropertyData(_camera,
							 kEdsPropID_Evf_Mode,
							 0,
							 sizeof(evfMode),
							 &evfMode);

	if (evfMode == 0)
	{
		evfMode = 1;

		// Set to the camera.
		err = EdsSetPropertyData(_camera, kEdsPropID_Evf_Mode, 0, sizeof(evfMode), &evfMode);
	}

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}
	return true;
}

EdsError CameraModel::DownloadEvfCommand()
{

	EdsError err = EDS_ERR_OK;

	EdsEvfImageRef evfImage = NULL;
	EdsStreamRef stream = NULL;
	EdsUInt32 orgdevice = 0, device = 0;
	EdsUInt32 retry = 0;

	err = StartEvfCommand();

	err = EdsGetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(orgdevice), &orgdevice);
	device = orgdevice;
	device |= kEdsEvfOutputDevice_PC;

	// Set to the Host.
	if (err == EDS_ERR_OK)
	{
		err = EdsSetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(device), &device);
	}

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}

	// create folder  ex) cam1
	EdsUInt32 camid;
	camid = (EdsUInt32)_bodyID;
	std::string directory_tree = "cam" + std::to_string(camid);
	if (fs::exists(directory_tree) == FALSE)
	{
		std::filesystem::create_directories(directory_tree);
	}

	std::string tmp;
	tmp = directory_tree + "/evf.jpg";
	char *filename = new char[tmp.size() + 1];
	strcpy(filename, tmp.c_str());

	// When creating to a file.
	err = EdsCreateFileStream(filename, kEdsFileCreateDisposition_CreateAlways, kEdsAccess_ReadWrite, &stream);

	// Create EvfImageRef.
	if (err == EDS_ERR_OK)
	{
		err = EdsCreateEvfImageRef(stream, &evfImage);
	}

	std::this_thread::sleep_for(1500ms);
	for (retry = 0; retry < 3; retry++)
	{
		// Download live view image data.
		if (err == EDS_ERR_OK)
		{
			std::this_thread::sleep_for(500ms);
			err = EdsDownloadEvfImage(_camera, evfImage);
		}

		// Get meta data for live view image data.
		if (err == EDS_ERR_OK)
		{
			_EVF_DATASET dataSet = {0};

			dataSet.stream = stream;

			// Get magnification ratio (x1, x5, or x10).
			EdsGetPropertyData(evfImage, kEdsPropID_Evf_Zoom, 0, sizeof(dataSet.zoom), &dataSet.zoom);

			// Get position of image data. (when enlarging)
			// Upper left coordinate using JPEG Large size as a reference.
			EdsGetPropertyData(evfImage, kEdsPropID_Evf_ImagePosition, 0, sizeof(dataSet.imagePosition), &dataSet.imagePosition);

			// Get histogram (RGBY).
			EdsGetPropertyData(evfImage, kEdsPropID_Evf_Histogram, 0, sizeof(dataSet.histogram), dataSet.histogram);

			// Get rectangle of the focus border.
			EdsGetPropertyData(evfImage, kEdsPropID_Evf_ZoomRect, 0, sizeof(dataSet.zoomRect), &dataSet.zoomRect);

			// Get the size as a reference of the coordinates of rectangle of the focus border.
			EdsGetPropertyData(evfImage, kEdsPropID_Evf_CoordinateSystem, 0, sizeof(dataSet.sizeJpegLarge), &dataSet.sizeJpegLarge);

			/*
						// Live view image transfer complete notification.
						if (err == EDS_ERR_OK)
						{
							CameraEvent e("EvfDataChanged", &dataSet);
							_model->notifyObservers(&e);
						}
			*/
		}
		// Notification of error
		if (err != EDS_ERR_OK)
		{
			// Retry getting image data if EDS_ERR_OBJECT_NOTREADY is returned
			// when the image data is not ready yet.
			if (err == EDS_ERR_OBJECT_NOTREADY)
			{
				std::cout << "Object not ready" << std::endl;
				std::this_thread::sleep_for(500ms);
				continue;
			}
			// It doesn't retry it at device busy
			if (err == EDS_ERR_DEVICE_BUSY)
			{
				std::cout << "DeviceBusy" << std::endl;
				break;
			}
		}
		else
		{
			break;
		}
	}

	if (stream != NULL)
	{
		EdsRelease(stream);
		stream = NULL;
	}

	if (evfImage != NULL)
	{
		EdsRelease(evfImage);
		evfImage = NULL;
	}

	// Restore the previous setting .
	device = orgdevice;
	EdsSetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(device), &device);

	EndEvfCommand();

	return true;
}

EdsError CameraModel::EndEvfCommand()
{
	EdsError err = EDS_ERR_OK;

	// Get the current output device.
	EdsUInt32 device = 0;
	err = EdsGetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(device), &device);

	// Do nothing if the remote live view has already ended.
	if ((device & kEdsEvfOutputDevice_PC) == 0)
	{
		return true;
	}

	// Get depth of field status.
	EdsUInt32 depthOfFieldPreview = 0;
	err = EdsGetPropertyData(_camera, kEdsPropID_Evf_DepthOfFieldPreview, 0, sizeof(depthOfFieldPreview), &depthOfFieldPreview);

	// Release depth of field in case of depth of field status.
	if (depthOfFieldPreview != 0)
	{
		depthOfFieldPreview = 0;
		err = EdsSetPropertyData(_camera, kEdsPropID_Evf_DepthOfFieldPreview, 0, sizeof(depthOfFieldPreview), &depthOfFieldPreview);

		// Standby because commands are not accepted for awhile when the depth of field has been released.
		if (err == EDS_ERR_OK)
		{
			std::this_thread::sleep_for(500ms);
		}
	}

	// Change the output device.
	if (err == EDS_ERR_OK)
	{
		device &= ~kEdsEvfOutputDevice_PC;
		err = EdsSetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(device), &device);
	}

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It retries it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "Error Cam No." << _bodyID << ":" << _modelName << "DeviceBusy" << std::endl;
		}
		std::cout << "Error Cam No." << _bodyID << ":" << _modelName << std::endl;
	}

	EdsUInt32 evfMode = 0;
	err = EdsGetPropertyData(_camera,
							 kEdsPropID_Evf_Mode,
							 0,
							 sizeof(evfMode),
							 &evfMode);

	if (evfMode == 1)
	{
		evfMode = 0;

		// Set to the camera.
		err = EdsSetPropertyData(_camera, kEdsPropID_Evf_Mode, 0, sizeof(evfMode), &evfMode);
	}

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}
	return true;
}

EdsUInt32 CameraModel::GetVolume()
{
	EdsUInt32 slot_count = 0, volume_count = 0;
	EdsBaseRef volumes[2] = {};
	EdsError err = EDS_ERR_OK;
	EdsVolumeInfo outVolumeInfo;
	err = EdsGetChildCount(_camera, &slot_count);
	if (slot_count > 0)
	{
		for (EdsUInt32 j = 0; j < slot_count; j++)
		{
			err = EdsGetChildAtIndex(_camera, j, &volumes[j]);
			err = EdsGetVolumeInfo(volumes[j], &outVolumeInfo);
			if (outVolumeInfo.storageType != kEdsStorageType_Non)
			{
				std::cout << "slot " << j + 1 << " " << outVolumeInfo.szVolumeLabel << " card" << std::endl;
				volume_count++;
			}
			else
			{
				std::cout << "slot " << j + 1 << " is empty" << std::endl;
			}
		}
	}
	return volume_count;
}

EdsError CameraModel::FormatVolume(EdsUInt32 volume_number)
{
	EdsUInt32 volume_count;
	EdsBaseRef volume;
	EdsError err = EDS_ERR_OK;
	UILock();
	err = EdsGetChildCount(_camera, &volume_count);

	if (volume_number <= volume_count)
	{
		err = EdsGetChildAtIndex(_camera, volume_number - 1, &volume);
		err = EdsFormatVolume(volume);
		UIUnLock();
		if (err == EDS_ERR_OK)
		{
			std::cout << "Format Card " << volume_number << " : succeeded" << std::endl;
		}
		else
		{
			std::cout << "Format Card " << volume_number << " : failed" << std::endl;
		}
	}
	else
	{
		std::cout << "failed number" << std::endl;
	}
	return err;
}


EdsError CameraModel::CreateFolder()
{
	EdsError err = EDS_ERR_OK;
	UILock();
	err = EdsCreateFolder(_camera);

	UIUnLock();
	if (err == EDS_ERR_OK)
	{
		std::cout << "Create Folder : succeeded" << std::endl;
	}
	else
	{
		std::cout << "Create Folder : failed" << std::endl;
	}

	return err;
}


EdsError CameraModel::SetCapacity(EdsCapacity _capacity)
{
	// It is a function only of the model since 30D.
	EdsError err = EDS_ERR_OK;

	// Acquisition of the number of sheets that can be taken a picture
	err = EdsSetCapacity(_camera, _capacity);

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		std::cout << "failed" << std::endl;
	}

	return err;
}

EdsError CameraModel::ZoomToTele()
{
	EdsError err = EDS_ERR_OK;
	err = EdsSendCommand(_camera, kEdsCameraCommand_DrivePowerZoom, kEdsDrivePowerZoom_LimitOff_Tele);
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It retries it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "Error Cam No." << _bodyID << ":" << _modelName << "DeviceBusy" << std::endl;
		}
		std::cout << "Error Cam No." << _bodyID << ":" << _modelName << std::endl;
	}
	return err;
}

EdsError CameraModel::ZoomToWide()
{
	EdsError err = EDS_ERR_OK;
	err = EdsSendCommand(_camera, kEdsCameraCommand_DrivePowerZoom, kEdsDrivePowerZoom_LimitOff_Wide);
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It retries it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "Error Cam No." << _bodyID << ":" << _modelName << "DeviceBusy" << std::endl;
		}
		std::cout << "Error Cam No." << _bodyID << ":" << _modelName << std::endl;
	}
	return err;
}

EdsError CameraModel::ZoomStop()
{
	EdsError err = EDS_ERR_OK;
	err = EdsSendCommand(_camera, kEdsCameraCommand_DrivePowerZoom, kEdsDrivePowerZoom_Stop);
	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It retries it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "Error Cam No." << _bodyID << ":" << _modelName << "DeviceBusy" << std::endl;
		}
		std::cout << "Error Cam No." << _bodyID << ":" << _modelName << std::endl;
	}
	return err;
}

EdsError CameraModel::GetZoomPosition()
{
	EdsError err = EDS_ERR_OK;

	EdsEvfImageRef evfImage = NULL;
	EdsStreamRef stream = NULL;
	EdsUInt32 orgdevice = 0, device = 0, data;
	EdsUInt32 retry = 0;

	err = StartEvfCommand();

	err = EdsGetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(orgdevice), &orgdevice);
	device = orgdevice;
	device |= kEdsEvfOutputDevice_PC;

	// Set to the Host.
	if (err == EDS_ERR_OK)
	{
		err = EdsSetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(device), &device);
	}

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}

	// create folder  ex) cam1
	EdsUInt32 camid;
	camid = (EdsUInt32)_bodyID;
	std::string directory_tree = "cam" + std::to_string(camid);
	if (fs::exists(directory_tree) == FALSE)
	{
		std::filesystem::create_directories(directory_tree);
	}

	std::string tmp;
	tmp = directory_tree + "/evf.jpg";
	char* filename = new char[tmp.size() + 1];
	strcpy(filename, tmp.c_str());

	// When creating to a file.
	err = EdsCreateFileStream(filename, kEdsFileCreateDisposition_CreateAlways, kEdsAccess_ReadWrite, &stream);

	// Create EvfImageRef.
	if (err == EDS_ERR_OK)
	{
		err = EdsCreateEvfImageRef(stream, &evfImage);
	}

	std::this_thread::sleep_for(1500ms);
	for (retry = 0; retry < 3; retry++)
	{
		// Download live view image data.
		if (err == EDS_ERR_OK)
		{
			std::this_thread::sleep_for(500ms);
			err = EdsDownloadEvfImage(_camera, evfImage);
		}

		// Get meta data for live view image data.
		if (err == EDS_ERR_OK)
		{
			err = EdsGetPropertyData(evfImage, kEdsPropID_Evf_PowerZoom_CurPosition, 0, sizeof(data), &data);

		}
		if (err == EDS_ERR_OK)
		{
			std::cout << "camera" << _bodyID << " : Current Position is " << data << "\n";
		}
		else
		{
			return err;
		}

		if (err == EDS_ERR_OK)
		{
			err = EdsGetPropertyData(evfImage, kEdsPropID_Evf_PowerZoom_MaxPosition, 0, sizeof(data), &data);

		}
		if (err == EDS_ERR_OK)
		{
			std::cout << "camera" << _bodyID << " : Max Positio is " << data << "\n";
		}
		else
		{
			return err;
		}

		if (err == EDS_ERR_OK)
		{
			err = EdsGetPropertyData(evfImage, kEdsPropID_Evf_PowerZoom_MinPosition, 0, sizeof(data), &data);

		}
		if (err == EDS_ERR_OK)
		{
			std::cout << "camera" << _bodyID << " : Min Positio is " << data << "\n";
		}
		else
		{
			return err;
		}

		// Notification of error
		if (err != EDS_ERR_OK)
		{
			// Retry getting image data if EDS_ERR_OBJECT_NOTREADY is returned
			// when the image data is not ready yet.
			if (err == EDS_ERR_OBJECT_NOTREADY)
			{
				std::cout << "Object not ready" << std::endl;
				std::this_thread::sleep_for(500ms);
				continue;
			}
			// It doesn't retry it at device busy
			if (err == EDS_ERR_DEVICE_BUSY)
			{
				std::cout << "DeviceBusy" << std::endl;
				break;
			}
		}
		else
		{
			break;
		}
	}

	if (stream != NULL)
	{
		EdsRelease(stream);
		stream = NULL;
	}

	if (evfImage != NULL)
	{
		EdsRelease(evfImage);
		evfImage = NULL;
	}

	// Restore the previous setting .
	device = orgdevice;
	EdsSetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(device), &device);

	EndEvfCommand();

	return true;
}


EdsError CameraModel::GetFocalLength()
{
	EdsError err = EDS_ERR_OK;

	EdsEvfImageRef evfImage = NULL;
	EdsStreamRef stream = NULL;
	EdsUInt32 orgdevice = 0, device = 0, data;
	EdsUInt32 retry = 0;

	err = StartEvfCommand();

	err = EdsGetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(orgdevice), &orgdevice);
	device = orgdevice;
	device |= kEdsEvfOutputDevice_PC;

	// Set to the Host.
	if (err == EDS_ERR_OK)
	{
		err = EdsSetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(device), &device);
	}

	// Notification of error
	if (err != EDS_ERR_OK)
	{
		// It doesn't retry it at device busy
		if (err == EDS_ERR_DEVICE_BUSY)
		{
			std::cout << "DeviceBusy" << std::endl;
		}
		return false;
	}

	// create folder  ex) cam1
	EdsUInt32 camid;
	camid = (EdsUInt32)_bodyID;
	std::string directory_tree = "cam" + std::to_string(camid);
	if (fs::exists(directory_tree) == FALSE)
	{
		std::filesystem::create_directories(directory_tree);
	}

	std::string tmp;
	tmp = directory_tree + "/evf.jpg";
	char* filename = new char[tmp.size() + 1];
	strcpy(filename, tmp.c_str());

	// When creating to a file.
	err = EdsCreateFileStream(filename, kEdsFileCreateDisposition_CreateAlways, kEdsAccess_ReadWrite, &stream);

	// Create EvfImageRef.
	if (err == EDS_ERR_OK)
	{
		err = EdsCreateEvfImageRef(stream, &evfImage);
	}

	std::this_thread::sleep_for(1500ms);
	for (retry = 0; retry < 3; retry++)
	{
		// Download live view image data.
		if (err == EDS_ERR_OK)
		{
			std::this_thread::sleep_for(500ms);
			err = EdsDownloadEvfImage(_camera, evfImage);
		}

		// Get meta data for live view image data.
		if (err == EDS_ERR_OK)
		{
			_EVF_DATASET dataSet = { 0 };

			dataSet.stream = stream;


			// Get the size as a reference of the coordinates of rectangle of the focus border.
			err = EdsGetPropertyData(evfImage, kEdsPropID_Evf_FocalLength, 0, sizeof(dataSet.focalLength), &dataSet.focalLength);

			if (err == EDS_ERR_OK)
			{
				std::cout << "camera" << _bodyID << " : focal length is " << dataSet.focalLength << " mm. \n"
					<< std::endl;

			}
			else {
				std::cout << "camera" << _bodyID << " : Failed to get the focal length.\n"
					<< std::endl;
			}

		}

		// Notification of error
		if (err != EDS_ERR_OK)
		{
			// Retry getting image data if EDS_ERR_OBJECT_NOTREADY is returned
			// when the image data is not ready yet.
			if (err == EDS_ERR_OBJECT_NOTREADY)
			{
				std::cout << "Object not ready" << std::endl;
				std::this_thread::sleep_for(500ms);
				continue;
			}
			// It doesn't retry it at device busy
			if (err == EDS_ERR_DEVICE_BUSY)
			{
				std::cout << "DeviceBusy" << std::endl;
				break;
			}
		}
		else
		{
			break;
		}
	}

	if (stream != NULL)
	{
		EdsRelease(stream);
		stream = NULL;
	}

	if (evfImage != NULL)
	{
		EdsRelease(evfImage);
		evfImage = NULL;
	}

	// Restore the previous setting .
	device = orgdevice;
	EdsSetPropertyData(_camera, kEdsPropID_Evf_OutputDevice, 0, sizeof(device), &device);

	EndEvfCommand();

	return true;
}
