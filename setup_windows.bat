@echo off
:: Run as Administrator!
echo ============================================
echo   PHOTOBOOTH WINDOWS SETUP (run as Admin!)
echo ============================================
echo.

:: Disable lock screen
echo [1/3] Disabling lock screen...
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f >nul
echo [OK]

:: Disable touch edge swipes and gestures
echo [2/3] Disabling touch gestures...
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\EdgeUI" /v AllowEdgeSwipe /t REG_DWORD /d 0 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\PrecisionTouchPad" /v ThreeFingerSlideEnabled /t REG_DWORD /d 0 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\PrecisionTouchPad" /v FourFingerSlideEnabled /t REG_DWORD /d 0 /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Explorer" /v DisableNotificationCenter /t REG_DWORD /d 1 /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Dsh" /v AllowNewsAndInterests /t REG_DWORD /d 0 /f >nul
echo [OK]

:: Add to startup
echo [3/3] Adding to startup...
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
echo @echo off > "%STARTUP_DIR%\photobooth.bat"
echo cd /d "%~dp0" >> "%STARTUP_DIR%\photobooth.bat"
echo call startup.bat >> "%STARTUP_DIR%\photobooth.bat"
echo [OK]

echo.
echo Done! Reboot to test.
pause
