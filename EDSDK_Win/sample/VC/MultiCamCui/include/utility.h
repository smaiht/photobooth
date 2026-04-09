#pragma once

#include <map>
#include "EDSDKTypes.h"

void clr_screen();
EdsUInt32 gethex();
EdsInt32 getvalue();
EdsInt32 getIntValue();
EdsInt32 getstrings(std::string& cstr, EdsInt32 number);
void pause_return();
void ListAvailValue(std::map<EdsUInt32, const char*>);
