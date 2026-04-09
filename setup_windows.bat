@echo off
:: Run as Administrator!
echo Setting up photobooth kiosk...
echo.

:: Disable lock screen
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f
echo [OK] Lock screen disabled
echo.

:: Add startup.bat to auto-start
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
echo @echo off > "%STARTUP_DIR%\photobooth.bat"
echo cd /d "%~dp0" >> "%STARTUP_DIR%\photobooth.bat"
echo call startup.bat >> "%STARTUP_DIR%\photobooth.bat"
echo [OK] Added to startup
echo.

echo Done! Reboot to test.
pause
