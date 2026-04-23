@echo off
:: Run as Administrator!
echo ============================================
echo   PHOTOBOOTH KIOSK SETUP (run as Admin!)
echo ============================================
echo.

set SHELL_PATH=C:\photobooth\python\pythonw.exe C:\photobooth\app.py

:: 0. Ensure embedded Python
echo [0/3] Setting up Python...
call "%~dp0_ensure_python.bat"
if not exist "C:\photobooth\python\pythonw.exe" (
    echo ERROR: Python setup failed.
    pause
    exit /b 1
)
echo [OK]
echo.

:: 1. Create kiosk user
echo [1/3] Creating Photobooth user...
net user Photobooth /add /passwordreq:no >nul 2>&1
net user Photobooth "" >nul 2>&1
echo [OK]

:: 2. Set custom shell
echo [2/3] Setting custom shell...
powershell -ExecutionPolicy Bypass -File "%~dp0_set_shell.ps1" "%SHELL_PATH%"
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
echo   DONE! Reboot to enter kiosk mode.
echo   Exit kiosk: Ctrl+Alt+Del, switch user
echo   Undo: run _undo_setup.bat as admin
echo ============================================
pause
