@echo off
:: Run as Administrator!
echo ============================================
echo   PHOTOBOOTH KIOSK SETUP (run as Admin!)
echo ============================================
echo.

set SHELL_PATH=C:\photobooth\python\pythonw.exe C:\photobooth\app.py

:: 0. Ensure embedded Python
echo [0/4] Setting up Python...
call "%~dp0_ensure_python.bat"
if not exist "C:\photobooth\python\pythonw.exe" (
    echo ERROR: Python setup failed.
    pause
    exit /b 1
)
echo [OK]
echo.

:: 1. Create kiosk user
echo [1/4] Creating Photobooth user...
net user Photobooth /add /passwordreq:no >nul 2>&1
net user Photobooth "" /active:yes /expires:never /passwordreq:no >nul 2>&1
if errorlevel 1 (
    echo ERROR: Could not create or update the Photobooth user.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Set-LocalUser -Name 'Photobooth' -PasswordNeverExpires $true"
if errorlevel 1 (
    echo ERROR: Could not set PasswordNeverExpires for the Photobooth user.
    pause
    exit /b 1
)
echo [OK]

:: 2. Install the narrow elevated adapter action
echo [2/4] Setting up network adapter control...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $source=Get-Content -Raw -Encoding UTF8 -LiteralPath '%~dp0_network_task.ps1'; $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($source)); $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand ' + $encoded); $principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest; $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden; Register-ScheduledTask -TaskName 'Photobooth Network Adapter' -Description 'Enable or disable one adapter requested by the Photobooth kiosk' -Action $action -Principal $principal -Settings $settings -Force | Out-Null; $userSid=(New-Object System.Security.Principal.NTAccount('Photobooth')).Translate([System.Security.Principal.SecurityIdentifier]).Value; $scheduler=New-Object -ComObject Schedule.Service; $scheduler.Connect(); $task=$scheduler.GetFolder('\').GetTask('Photobooth Network Adapter'); $sddl=$task.GetSecurityDescriptor(4); if ($sddl -notmatch [regex]::Escape($userSid)) { $task.SetSecurityDescriptor($sddl + '(A;;FRFX;;;' + $userSid + ')', 0) }"
if errorlevel 1 (
    echo ERROR: Could not install network adapter control.
    pause
    exit /b 1
)
echo [OK]

:: 3. Set custom shell
echo [3/4] Setting custom shell...
powershell -ExecutionPolicy Bypass -File "%~dp0_set_shell.ps1" "%SHELL_PATH%"
echo.

:: 4. Auto-login
echo [4/4] Setting auto-login...
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
