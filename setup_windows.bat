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

:: 2. Set custom shell for Photobooth user (PowerShell for SID lookup)
echo [2/3] Setting custom shell...
powershell -Command ^
    "$sid = (New-Object System.Security.Principal.NTAccount('Photobooth')).Translate([System.Security.Principal.SecurityIdentifier]).Value; ^
    $hivePath = \"C:\Users\Photobooth\NTUSER.DAT\"; ^
    $loaded = $false; ^
    if (!(Test-Path \"Registry::HKU\$sid\")) { ^
        if (Test-Path $hivePath) { ^
            reg load \"HKU\$sid\" $hivePath 2>$null; ^
            $loaded = $true; ^
        } else { ^
            Write-Host '[WARN] User profile not created yet. Log in as Photobooth once, then re-run setup.'; ^
            exit 1; ^
        } ^
    }; ^
    reg add \"HKU\$sid\Software\Microsoft\Windows NT\CurrentVersion\Winlogon\" /v Shell /t REG_SZ /d \"%EXE_PATH%\" /f; ^
    if ($loaded) { reg unload \"HKU\$sid\" 2>$null }; ^
    Write-Host '[OK]'"
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
echo   1. Log in as Photobooth user once (if first time)
echo   2. Log back to your admin account
echo   3. Re-run this script if step 2/3 showed WARN
echo   4. Reboot to enter kiosk mode
echo.
echo   Exit kiosk: Ctrl+Alt+Del, switch user
echo   Undo: run undo_setup.bat as admin
echo ============================================
pause
