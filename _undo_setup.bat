@echo off
:: Run as Administrator!
echo Undoing kiosk setup...

:: Remove auto-login
reg delete "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultPassword /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /f >nul 2>&1
echo [OK] Auto-login and lock screen restored

:: Delete kiosk user
net user Photobooth /delete >nul 2>&1
echo [OK] Photobooth user deleted

echo.
echo Done! Reboot to return to normal.
pause
