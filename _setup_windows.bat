@echo off
:: Run as Administrator!
echo ============================================
echo   PHOTOBOOTH KIOSK SETUP (run as Admin!)
echo ============================================
echo.

set EXE_PATH=C:\photobooth\dist\Photobooth.exe
if not exist "%EXE_PATH%" (
    echo [ERROR] %EXE_PATH% not found!
    echo         Run build.bat first.
    pause
    exit /b 1
)

:: 1. Create kiosk user
echo [1/3] Creating Photobooth user...
net user Photobooth /add /passwordreq:no >nul 2>&1
net user Photobooth "" >nul 2>&1
echo [OK]

:: 2. Set custom shell
echo [2/3] Setting custom shell...
powershell -ExecutionPolicy Bypass -File "%~dp0_set_shell.ps1" "%EXE_PATH%"
echo.

:: 3. Auto-login
echo [3/3] Setting auto-login...
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f >nul
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d Photobooth /f >nul
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultPassword /t REG_SZ /d "" /f >nul
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f >nul
echo [OK]
echo.

echo ============================================
echo   DONE!
echo   1. Log in as Photobooth user once (if WARN above)
echo   2. Log back to admin, re-run this script
echo   3. Reboot to enter kiosk mode
echo.
echo   Exit kiosk: Ctrl+Alt+Del, switch user
echo   Undo: run undo_setup.bat as admin
echo ============================================
pause
