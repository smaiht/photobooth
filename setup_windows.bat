@echo off
:: Run as Administrator!
:: Sets up Windows for photobooth kiosk:
::   1. Auto-login without password
::   2. Auto-start photobooth on boot
::   3. Disable lock screen

echo ============================================
echo   PHOTOBOOTH WINDOWS SETUP (run as Admin!)
echo ============================================
echo.

:: 1. Auto-login
echo [1/3] Setting up auto-login...
set /p USERNAME="Windows username (e.g. jack): "
set /p PASSWORD="Windows password (leave empty if none): "

reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d "%USERNAME%" /f
if not "%PASSWORD%"=="" (
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultPassword /t REG_SZ /d "%PASSWORD%" /f
)
echo [OK] Auto-login configured
echo.

:: 2. Add startup.bat to auto-start
echo [2/3] Adding to startup...
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SCRIPT_DIR=%~dp0
echo @echo off > "%STARTUP_DIR%\photobooth.bat"
echo cd /d "%SCRIPT_DIR%" >> "%STARTUP_DIR%\photobooth.bat"
echo call startup.bat >> "%STARTUP_DIR%\photobooth.bat"
echo [OK] Added to startup folder
echo.

:: 3. Disable lock screen
echo [3/3] Disabling lock screen...
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f
echo [OK] Lock screen disabled
echo.

echo ============================================
echo   DONE! Reboot to test auto-start.
echo ============================================
pause
