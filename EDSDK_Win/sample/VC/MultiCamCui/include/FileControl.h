#include "EDSDK.h"
#include "EDSDKTypes.h"
#include "CameraModel.h"

EdsError downloadImage(EdsDirectoryItemRef directoryItem, EdsVoid *_bodyID);
EdsError DownloadImageAll(std::vector<CameraModel *> _model);
EdsError SetMetaImageAll(std::vector<CameraModel *> _model, EdsUInt32 MetaType);
