@echo off
echo Stopping Photobooth...
taskkill /f /fi "WINDOWTITLE eq PhotoboothServer*" >nul 2>&1
taskkill /f /im "python.exe" /fi "COMMANDLINE eq *uvicorn*backend.main*" >nul 2>&1
taskkill /f /im "msedge.exe" /fi "COMMANDLINE eq *localhost:8000*" >nul 2>&1
echo Done.
pause
