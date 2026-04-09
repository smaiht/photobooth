#include <vector>
#include <cstring>
#include <sstream>
#include <iostream>
#include <filesystem>
#include "EDSDK.h"
#include "EDSDKTypes.h"
#include "CameraModel.h"

namespace fs = std::filesystem;

#define CONFIG_BUFSIZE               (256)

struct FileNumber
{
	EdsDirectoryItemRef DirItem;
	int dirnum;
	int* filenum;

	FileNumber(int p1)
	{
		DirItem = NULL;
		dirnum = p1;
		filenum = new int[dirnum];
	}
};

EdsError CountImages(EdsDirectoryItemRef* directoryItem, EdsUInt32* directory_count, int* fileCount, const FileNumber& fileNumber, std::vector<EdsDirectoryItemRef>& imageItems);
EdsError CountImagesByDirectory(EdsDirectoryItemRef directoryItem, int directoryNo, int* image_count, std::vector<EdsDirectoryItemRef>& imageItems);
EdsError CountDirectory(EdsDirectoryItemRef directoryItem, std::string* targetFolderName, EdsUInt32* directory_count);
void ChangeTargetFolderName(std::string& targetFolderName);
EdsError DownloadImageByDirectory(EdsUInt32 _bodyID, int volume_num);
EdsError SetMetaImageByDirectory(EdsUInt32 _bodyID, int volume_num);

static int _currentFileNum = 0;
static int _fileCount = 0;
static std::vector<EdsDirectoryItemRef> _imageItems;
static EdsGpsMetaData* GpsDataValue;

EdsError downloadImage(EdsDirectoryItemRef directoryItem, EdsVoid* _bodyID)
{
	EdsError err = EDS_ERR_OK;
	EdsStreamRef stream = NULL; // Get directory item information
	EdsDirectoryItemInfo dirItemInfo;

	err = EdsGetDirectoryItemInfo(directoryItem, &dirItemInfo);

	// create folder  ex) cam1
	EdsUInt32 camid;
	camid = (EdsUInt64)_bodyID;
	std::string directory_tree = "cam" + std::to_string(camid);
	if (fs::exists(directory_tree) == FALSE)
	{
		std::filesystem::create_directories(directory_tree);
	}

	std::string tmp;
	tmp = directory_tree + "/" + dirItemInfo.szFileName;
	char* filename = new char[tmp.size() + 1];
	strcpy(filename, tmp.c_str());

	// Create file stream for transfer destination
	if (err == EDS_ERR_OK)
	{
		err = EdsCreateFileStream(filename, kEdsFileCreateDisposition_CreateAlways, kEdsAccess_ReadWrite, &stream);
	}

	// Download image
	if (err == EDS_ERR_OK)
	{
		err = EdsDownload(directoryItem, dirItemInfo.size, stream);
	}
	// Issue notification that download is complete
	if (err == EDS_ERR_OK)
	{
		err = EdsDownloadComplete(directoryItem);
	}

	// Release stream
	if (stream != NULL)
	{
		EdsRelease(stream);
		stream = NULL;
	}

	return err;
}

EdsError CountImages(EdsDirectoryItemRef* directoryItem, EdsUInt32* directory_count, int* fileCount, const FileNumber& fileNumber, std::vector<EdsDirectoryItemRef>& imageItems)
{
	EdsError err = EDS_ERR_OK;

	// Get the number of camera volumes
	fileCount = 0;

	// Get retrieved item information

	for (EdsUInt32 i = 0; i < *directory_count; ++i)
	{
		int count = 0;
		err = CountImagesByDirectory(*directoryItem, i, &count, imageItems);
		if (err != EDS_ERR_OK)
		{
			return err;
		}
		fileCount += count;
		fileNumber.filenum[i] = count;
	}
	return EDS_ERR_OK;
}

EdsError CountImagesByDirectory(EdsDirectoryItemRef directoryItem, int directoryNo, int* image_count, std::vector<EdsDirectoryItemRef>& imageItems)
{
	EdsUInt32 item_count = 0;

	EdsDirectoryItemRef directoryfiles;
	EdsDirectoryItemRef fileitem;
	EdsDirectoryItemInfo dirItemInfo;

	EdsError err = EdsGetChildAtIndex(directoryItem, directoryNo, &directoryfiles);
	if (err != EDS_ERR_OK)
	{
		return err;
	}

	// Get retrieved item information
	// Get item name
	err = EdsGetDirectoryItemInfo(directoryfiles, &dirItemInfo);
	if (err != EDS_ERR_OK)
	{
		return err;
	}

	EdsUInt32 index = 0, filecount = 0;
	err = EdsGetChildCount(directoryfiles, &item_count);
	if (err != EDS_ERR_OK)
	{
		return err;
	}
	for (index = 0; index < item_count; ++index)
	{
		err = EdsGetChildAtIndex(directoryfiles, index, &fileitem);
		if (err != EDS_ERR_OK)
		{
			return err;
		}

		// Get retrieved item information
		err = EdsGetDirectoryItemInfo(fileitem, &dirItemInfo);
		if (err != EDS_ERR_OK)
		{
			return err;
		}
		if (dirItemInfo.isFolder == 0)
		{
			imageItems.push_back(fileitem);
			filecount += 1;
		}
	}
	*image_count = filecount;

	return EDS_ERR_OK;
}

EdsError CountDirectory(EdsBaseRef _volume, std::string* targetFolderName, EdsDirectoryItemRef* directoryItem, EdsUInt32* directory_count)
{
	EdsError err = EDS_ERR_OK;
	EdsUInt32 item_count = 0;
	*directory_count = 0;

	// Get DCIM or XFVC folder
	EdsDirectoryItemRef dirItem;
	EdsDirectoryItemInfo dirItemInfo;
	dirItemInfo.szFileName[EDS_MAX_NAME - 1] = {};
	dirItemInfo.size = 0;

	err = EdsGetChildCount(_volume, &item_count);
	if (err != EDS_ERR_OK)
	{
		return err;
	}
	for (EdsUInt32 i = 0; i < item_count; ++i)
	{
		// Get the ith item under the specifed volume
		err = EdsGetChildAtIndex(_volume, i, &dirItem);
		if (err != EDS_ERR_OK)
		{
			continue;
		}

		// Get retrieved item information
		err = EdsGetDirectoryItemInfo(dirItem, &dirItemInfo);
		if (err != EDS_ERR_OK)
		{
			return err;
		}

		std::string filename;
		filename = dirItemInfo.szFileName;

		// Indicates whether or not the retrieved item is DCIM or XFVC folder.
		if (filename == *targetFolderName && dirItemInfo.isFolder == 1)
		{
			*directoryItem = dirItem;
			break;
		}

		// Release retrieved item
		if (dirItem != NULL)
		{
			EdsRelease(dirItem);
		}
	}

	// Get number of directory in DCIM or XFVC.
	return err = EdsGetChildCount(*directoryItem, directory_count);
}

// Due to the addition of XFVC specifications, a function is provided to change the target folder.
void ChangeTargetFolderName(std::string* targetFolderName)
{
	if (*targetFolderName == "DCIM")
	{
		*targetFolderName = "XFVC";
	}
	else if (*targetFolderName == "XFVC")
	{
		*targetFolderName = "";
	}
}

EdsError DownloadImageAll(std::vector<CameraModel*> _model)
{
	int cam_no;
	EdsUInt32 volume_count = 0;
	EdsBaseRef volumes[2] = {};
	EdsError err = EDS_ERR_OK;
	EdsVolumeInfo outVolumeInfo;
	EdsDirectoryItemRef directoryItem = nullptr;
	std::string targetFolderName;


	for (cam_no = 0; cam_no < _model.size(); cam_no++)
	{
		std::cout << std::endl;
		std::cout << "Cam No." << cam_no+1 << std::endl;

		err = EdsGetChildCount(_model[cam_no]->getCameraObject(), &volume_count);
		if (volume_count > 0)
		{
			for (EdsUInt32 j = 0; j < volume_count; j++)
			{
				err = EdsGetChildAtIndex(_model[cam_no]->getCameraObject(), j, &volumes[j]);
				err = EdsGetVolumeInfo(volumes[j], &outVolumeInfo);
				if (outVolumeInfo.storageType != kEdsStorageType_Non)
				{
					std::cout << "Memory Card " << j + 1 << " (" << outVolumeInfo.szVolumeLabel << ")" << std::endl;
				}

				targetFolderName = "DCIM";
				while (targetFolderName == "DCIM" || targetFolderName == "XFVC") {
					directoryItem = nullptr;

					if (outVolumeInfo.storageType != kEdsStorageType_Non)
					{
						std::cout << "[ " << targetFolderName << " ]" << std::endl;
					}

					// download all
					_currentFileNum = 0;

					EdsUInt32 directoryCount;
					err = CountDirectory(volumes[j], &targetFolderName, &directoryItem, &directoryCount);

					// If there is no target folder, directoryItem will be returned as nullptr.
					if (directoryItem != nullptr)
					{

						FileNumber _fileNumber(directoryCount);
						_fileNumber.DirItem = directoryItem;
						err = CountImages(&directoryItem, &directoryCount, &_fileCount, _fileNumber, _imageItems);
						if (err != EDS_ERR_OK)
						{
							return false;
						}

						// Download file.
						err = DownloadImageByDirectory(_model[cam_no]->getbodyID(), j);
						if (err != EDS_ERR_OK)
						{
							return false;
						}
					}
					ChangeTargetFolderName(&targetFolderName);
				}
			}
		}
	}
	return true;
}

EdsError DownloadImageByDirectory(EdsUInt32 _bodyID, int volume_num)
{
	EdsDirectoryItemRef fileitem;
	EdsDirectoryItemInfo dirItemInfo;
	dirItemInfo.szFileName[EDS_MAX_NAME - 1] = {};
	dirItemInfo.size = 0;

	EdsUInt64 index = 0, filenum = _imageItems.size();

	for (index = 0; index < filenum; ++index)
	{

		fileitem = _imageItems[index];
		EdsError err = EdsGetDirectoryItemInfo(fileitem, &dirItemInfo);
		if (err != EDS_ERR_OK)
		{
			return err;
		}

		// create folder  ex) cam1
		EdsUInt32 camid;
		camid = _bodyID;
		std::string directory_tree = "cam" + std::to_string(camid) + "/card" + std::to_string(volume_num + 1);
		if (fs::exists(directory_tree) == FALSE)
		{
			std::filesystem::create_directories(directory_tree);
		}

		std::string tmp;
		tmp = directory_tree + "/" + dirItemInfo.szFileName;
		char* szDstFileName = new char[tmp.size() + 1];
		strcpy(szDstFileName, tmp.c_str());

		// Create file stream for transfer destination
		EdsStreamRef stream;

		err = EdsCreateFileStream(szDstFileName,
			kEdsFileCreateDisposition_CreateAlways,
			kEdsAccess_ReadWrite, &stream);
		if (err != EDS_ERR_OK)
		{
			return err;
		}

		// Set Progress
		// err = EdsSetProgressCallback(stream, ProgressFunc, EDSDKLib.EDSDK.kEdsProgressOption_Periodically, this);
		//  Download image
		err = EdsDownload(fileitem, dirItemInfo.size, stream);
		if (err != EDS_ERR_OK)
		{
			return err;
		}

		// Issue notification that download is complete
		err = EdsDownloadComplete(fileitem);
		if (err != EDS_ERR_OK)
		{
			return err;
		}

		// Release Item
		if (fileitem != NULL)
		{
			err = EdsRelease(fileitem);
			fileitem = NULL;
		}

		// Release stream
		if (stream != NULL)
		{
			err = EdsRelease(stream);
			stream = NULL;
		}

		_currentFileNum += 1;
		std::cout << "Downloading files " << _currentFileNum << "/" << filenum << std::endl;
		std::cout << "\033[1A";
	}

	std::cout << "\n";
	_currentFileNum = 0;
	_imageItems.clear();
	return EDS_ERR_OK;
}

static EdsError Config_strToInt(uint8_t* str, int32_t base, int32_t* val)
{
	uint8_t* failStr = NULL;
	int32_t tmp = 0U;

	tmp = (int32_t)strtol((const char*)str, (char**)&failStr, base);
	if (0U < strlen((const char*)failStr))
	{
		std::cout << "strtol error\n" << std::endl;
		return EDS_ERR_INTERNAL_ERROR;
	}

	*val = tmp;
	return EDS_ERR_OK;
}

static EdsError Config_GpsConfig(uint8_t* tagStr, uint8_t tagLen, uint8_t* valStr)
{
	int32_t tmp = 0U;
	if (0 == strncmp((const char*)tagStr, "latitudeRef", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 16, &tmp))
		{
			GpsDataValue->latitudeRef = (EdsUInt8)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "longitudeRef", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 16, &tmp))
		{
			GpsDataValue->longitudeRef = (EdsUInt8)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "altitudeRef", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 16, &tmp))
		{
			GpsDataValue->altitudeRef = (EdsUInt8)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "status", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 16, &tmp))
		{
			GpsDataValue->status = (EdsUInt8)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "latitudeDegNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->latitude[0].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "latitudeDegDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->latitude[0].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "latitudeMinNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->latitude[1].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "latitudeMinDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->latitude[1].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "latitudeSecNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->latitude[2].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "latitudeSecDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->latitude[2].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "longitudeDegNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->longitude[0].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "longitudeDegDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->longitude[0].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "longitudeMinNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->longitude[1].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "longitudeMinDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->longitude[1].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "longitudeSecNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->longitude[2].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "longitudeSecDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->longitude[2].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "altitudeNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->altitude.numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "altitudeDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->altitude.denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "timeHourNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->timeStamp[0].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "timeHourDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->timeStamp[0].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "timeMinNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->timeStamp[1].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "timeMinDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->timeStamp[1].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "timeSecNum", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->timeStamp[2].numerator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "timeSecDen", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 10, &tmp))
		{
			GpsDataValue->timeStamp[2].denominator = (EdsUInt32)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "dateStampYear", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 16, &tmp))
		{
			GpsDataValue->dateStampYear = (EdsUInt16)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "dateStampMonth", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 16, &tmp))
		{
			GpsDataValue->dateStampMonth = (EdsUInt8)tmp;
			return EDS_ERR_OK;
		}
	}
	else if (0 == strncmp((const char*)tagStr, "dateStampDay", tagLen))
	{
		if (EDS_ERR_OK == Config_strToInt(valStr, 16, &tmp))
		{
			GpsDataValue->dateStampDay = (EdsUInt8)tmp;
			return EDS_ERR_OK;
		}
	}
	else
	{

	}
	return EDS_ERR_INTERNAL_ERROR;
}

EdsError Config_readConfFile(FILE* fp,
	EdsError(*readConfLineFunc)(uint8_t* tagStr, uint8_t tagLen, uint8_t* valStr))
{
	uint8_t buff[CONFIG_BUFSIZE] = { 0 };
	uint8_t* valPtr = NULL;
	uint8_t* ptr = NULL;
	uint8_t tagLen = 0U;
	EdsError result = EDS_ERR_OK;

	// file reading loop
	while (NULL != fgets((char*)buff, CONFIG_BUFSIZE - 1, fp))
	{
		// ignore top of "#"
		if ('#' == buff[0])
		{
			continue;
		}

		// check <tag>=<value>
		valPtr = (uint8_t*)strchr((const char*)buff, '=');
		if (NULL == valPtr || '\0' == (*(valPtr + 1)) ||
			'\r' == (*(valPtr + 1)) || '\n' == (*(valPtr + 1)))
		{
			continue;
		}

		tagLen = valPtr - buff;
		valPtr++;
		ptr = valPtr;

		//find terminator
		while (('\n' != *ptr) && ('\r' != *ptr) && ('\0' != *ptr))
		{
			//ignore "TAB" and "#"" after <value>
			if (('\t' == *ptr) || ('#' == *ptr))
			{
				break;
			}
			ptr++;
		}
		*ptr = '\0'; //?I?[

		//config line check
		if (EDS_ERR_OK != readConfLineFunc(buff, tagLen, valPtr))
		{
			result = EDS_ERR_INTERNAL_ERROR;
		}
	}
	return result;
}


EdsError SetMetaImageExif(EdsDirectoryItemRef fileitem)
{
	FILE* fp;
	uint8_t buff[10240];
	uint32_t size = 0u;
	EdsUInt32 dataSize; // metaData size
	EdsError result = EDS_ERR_OK;

	dataSize = sizeof(EdsGpsMetaData);
	GpsDataValue = (EdsGpsMetaData*) ::malloc(dataSize);

	char* filename = "./resources/gpsexifdata.txt";
	fp = fopen(filename, "rb");
	if (fp == NULL)
	{
		std::cout << "fopen() is failed.\n" << std::endl;
		return EDS_ERR_INTERNAL_ERROR;
	}
	else
	{
		std::cout << "gpsexifdata.txt read.\n" << std::endl;
		if (EDS_ERR_OK != Config_readConfFile(fp, Config_GpsConfig))
		{
			result = EDS_ERR_INTERNAL_ERROR;
		}
		fclose(fp);
	}

	EdsError err = EdsSetMetaImage(fileitem, 0, dataSize, GpsDataValue);

	std::cout << "writing metadata(EXIF) to image file" << std::endl;

	return err;
}

EdsError SetMetaImageXmp(EdsDirectoryItemRef fileitem)
{
	FILE* fp;
	uint8_t buff[10240];
	uint32_t size = 0u;

	char* filename = "./resources/metadata_xmp.txt";
	fp = fopen(filename, "rb");
	if (fp == NULL)
	{
		std::cout << "fopen() is failed.\n" << std::endl;
		return -1;
	}

	size = fread(buff, 1u, sizeof(buff), fp);
	fclose(fp);

	std::cout << "writing metadata(XMP) from resources/metadata_xmp.txt to image file" << std::endl;
	EdsError err = EdsSetMetaImage(fileitem, 1, size, buff);

	return err;
}


EdsError SetMetaImageByDirectory(EdsUInt32 _bodyID, int volume_num, EdsUInt32 MetaType)
{
	EdsDirectoryItemRef fileitem;
	EdsDirectoryItemInfo dirItemInfo;
	EdsError err;
	EdsUInt64 index = 0, filenum = _imageItems.size();

	for (index = 0; index < filenum; ++index)
	{

		fileitem = _imageItems[index];

		if (MetaType == 0)
		{
			err = SetMetaImageExif(fileitem);
		}
		else
		{
			err = SetMetaImageXmp(fileitem);
		}


		if (err != EDS_ERR_OK)
		{
			return err;
		}

		// Release Item
		if (fileitem != NULL)
		{
			err = EdsRelease(fileitem);
			fileitem = NULL;
		}


		_currentFileNum += 1;
		std::cout << "Update files " << _currentFileNum << "/" << filenum << std::endl;
	}

	std::cout << "\n";
	_currentFileNum = 0;
	_imageItems.clear();
	return EDS_ERR_OK;
}

EdsError SetMetaImageAll(std::vector<CameraModel*> _model, EdsUInt32 MetaType)
{
	int i;
	EdsUInt32 volume_count = 0;
	EdsBaseRef volumes[2] = {};
	EdsError err = EDS_ERR_OK;
	EdsVolumeInfo outVolumeInfo;
	EdsDirectoryItemRef directoryItem = nullptr;
	std::string targetFolderName = "DCIM";

	for (i = 0; i < _model.size(); i++)
	{
		err = EdsGetChildCount(_model[i]->getCameraObject(), &volume_count);
		if (volume_count > 0)
		{
			directoryItem = nullptr;

			for (EdsUInt32 j = 0; j < volume_count; j++)
			{
				err = EdsGetChildAtIndex(_model[i]->getCameraObject(), j, &volumes[j]);
				err = EdsGetVolumeInfo(volumes[j], &outVolumeInfo);

				_currentFileNum = 0;

				EdsUInt32 directoryCount;
				err = CountDirectory(volumes[j], &targetFolderName, &directoryItem, &directoryCount);

				// If there is no target folder, directoryItem will be returned as nullptr.
				if (directoryItem == nullptr) {
					continue;
				}

				if (outVolumeInfo.storageType != kEdsStorageType_Non)
				{
					std::cout << "Memory Card " << j + 1 << " (" << outVolumeInfo.szVolumeLabel << ")" << std::endl;
				}

				FileNumber _fileNumber(directoryCount);
				_fileNumber.DirItem = directoryItem;
				err = CountImages(&directoryItem, &directoryCount, &_fileCount, _fileNumber, _imageItems);
				if (err != EDS_ERR_OK)
				{
					return false;
				}

				// SetMeta file.
				err = SetMetaImageByDirectory(_model[i]->getbodyID(), j, MetaType);
				if (err != EDS_ERR_OK)
				{
					return false;
				}
			}
		}
	}
	return EDS_ERR_OK;
}
