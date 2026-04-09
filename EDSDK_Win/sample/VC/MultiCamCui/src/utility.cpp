#include <map>
#include <iostream>
#include <iterator>
#include <regex>
#include <string>
#include "EDSDKTypes.h"
#include "utility.h"

void clr_screen()
{
	std::cout << "\033[2J";	  // screen clr
	std::cout << "\033[0;0H"; // move low=0, column=0
}

EdsUInt32 gethex()
{
	std::string input;
	std::smatch match_results;
	std::getline(std::cin, input); // Pass if only return key is input.
	if (input != "\n")
	{
		if (std::regex_search(input, match_results, std::regex("[a-fA-F0-9]")))
		{
			//input = "f";
			EdsUInt32 ret;
			ret = stoul((input),0,16);
			return ret;
		}
	}
	return (-1);
}

EdsInt32 getvalue()
{
	std::string input;
	std::smatch match_results;
	std::getline(std::cin, input); // Pass if only return key is input.
	if (input != "\n")
	{
		if (std::regex_search(input, match_results, std::regex("[0-9]")))
		{
			return (stoi(input));
		}
	}
	return (-1);
}

EdsInt32 getIntValue()
{
	std::string input;
	std::smatch match_results;
	std::getline(std::cin, input); // Pass if only return key is input.
	if (input != "\n")
	{
		if (std::regex_search(input, match_results, std::regex("[0-9-]")))
		{
			return (stoi(input));
		}
		else
		{
			std::cout << "Error invalid parameter" << std::endl;
			return (0xff);
		}
	}
	return (0xff);
}

EdsInt32 getstrings(std::string& cstr, EdsInt32 number)
{
	std::string input;
	std::smatch match_results;
	std::getline(std::cin, input); // Pass if only return key is input.

	if (input != "\n")
	{
		cstr = input;
		if (input.size() > number - 1) // number - null
		{
			cstr = input.substr(0, number - 2);
		}
		else
		{
			cstr = input.substr(0);
		}

		if (std::regex_search(input, match_results, std::regex("^[a-zA-Z0-9!-/:-@[-`{-~ ]+")))
		{
			return 1;
		}
		else
		{
			std::cout << "Error invalid character" << std::endl;
			return (-1);
		}
	}
	return (-1);
}

void pause_return()
{
	//	system("pause");
	std::cout << "\n"
		<< "Press the RETURN key." << std::endl;
	getvalue();
}

void ListAvailValue(std::map<EdsUInt32, const char*> _table)
{
	std::cout << "available settings are...\n";
	for (auto iter = _table.begin(); iter != _table.end(); ++iter)
	{
		std::cout << iter->first << ":" << iter->second << "\n";
	}
}