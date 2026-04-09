#include "EDSDK.h"
#include "EDSDKTypes.h"

EdsError EDSCALLBACK handleObjectEvent(EdsObjectEvent event, EdsBaseRef object, EdsVoid *context);
EdsError EDSCALLBACK handlePropertyEvent(
	EdsUInt32 inEvent,
	EdsUInt32 inPropertyID,
	EdsUInt32 inParam,
	EdsVoid *inContext);
EdsError EDSCALLBACK handleSateEvent(EdsStateEvent event, EdsUInt32 parameter, EdsVoid *context);
