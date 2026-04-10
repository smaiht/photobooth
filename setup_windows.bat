@echo off
:: Run as Administrator!
echo ============================================
echo   PHOTOBOOTH KIOSK SETUP (run as Admin!)
echo ============================================
echo.

:: Get path to Photobooth.exe
set /p EXE_PATH="Full path to Photobooth.exe (e.g. C:\photobooth\dist\Photobooth.exe): "
if not exist "%EXE_PATH%" (
    echo [ERROR] File not found: %EXE_PATH%
    pause
    exit /b 1
)
echo.

:: 1. Create kiosk user
echo [1/4] Creating Photobooth user...
net user Photobooth /add /passwordreq:no >nul 2>&1
net user Photobooth "" >nul 2>&1
echo [OK] User created
echo.

:: 2. Replace shell for kiosk user
echo [2/4] Setting custom shell...
for /f "tokens=2" %%i in ('wmic useraccount where name^="Photobooth" get sid /value ^| find "="') do set KIOSK_SID=%%i
reg add "HKU\%KIOSK_SID%\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "%EXE_PATH%" /f >nul
echo [OK] Shell set to %EXE_PATH%
echo.

:: 3. Auto-login as Photobooth user
echo [3/4] Setting auto-login...
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f >nul
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d Photobooth /f >nul
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultPassword /t REG_SZ /d "" /f >nul
echo [OK] Auto-login configured
echo.

:: 4. Disable lock screen and gestures
echo [4/4] Disabling lock screen and gestures...
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\EdgeUI" /v AllowEdgeSwipe /t REG_DWORD /d 0 /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Explorer" /v DisableNotificationCenter /t REG_DWORD /d 1 /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Dsh" /v AllowNewsAndInterests /t REG_DWORD /d 0 /f >nul
echo [OK] Lock screen and gestures disabled
echo.

echo ============================================
echo   DONE! Reboot to enter kiosk mode.
echo   To exit kiosk: Ctrl+Alt+Del, switch user,
echo   login to your admin account.
echo ============================================
echo.
echo To undo: run undo_setup.bat
pause
