@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Photobooth - create strips printer queue

echo ============================================
echo   PHOTOBOOTH STRIPS PRINTER QUEUE SETUP
echo ============================================
echo.

:: Adding a local Windows printer queue requires elevation. Re-run this same
:: file through UAC when it was started normally.
fltmc >nul 2>&1
if errorlevel 1 (
    echo Administrator permission is required. Opening the UAC prompt...
    set "PHOTOBOOTH_STRIPS_SETUP=%~f0"
    set "PHOTOBOOTH_STRIPS_DIR=%~dp0"
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:PHOTOBOOTH_STRIPS_SETUP -WorkingDirectory $env:PHOTOBOOTH_STRIPS_DIR -Verb RunAs"
    if errorlevel 1 (
        echo ERROR: Could not request Administrator permission.
        pause
        exit /b 1
    )
    exit /b 0
)

if not exist "%~dp0config_app.json" (
    echo ERROR: config_app.json was not found next to this script.
    pause
    exit /b 1
)

echo Reading printer queue names from config_app.json...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $configPath=Join-Path (Get-Location) 'config_app.json'; $config=Get-Content -Raw -Encoding UTF8 -LiteralPath $configPath | ConvertFrom-Json; $sourceName=([string]$config.printer_name).Trim(); $targetName=([string]$config.printer_name_strips).Trim(); if ([string]::IsNullOrWhiteSpace($sourceName)) { throw 'printer_name is empty in config_app.json' }; if ([string]::IsNullOrWhiteSpace($targetName)) { throw 'printer_name_strips is empty in config_app.json' }; if ($sourceName -eq $targetName) { throw 'printer_name and printer_name_strips must be different' }; $source=Get-Printer -Name $sourceName -ErrorAction Stop; Write-Host ('Source queue : ' + $source.Name); Write-Host ('Driver       : ' + $source.DriverName); Write-Host ('Port         : ' + $source.PortName); Write-Host ('Strips queue : ' + $targetName); Write-Host ''; $target=Get-Printer -Name $targetName -ErrorAction SilentlyContinue; if ($null -ne $target) { if ($target.DriverName -ne $source.DriverName -or $target.PortName -ne $source.PortName) { throw ('Queue ' + $targetName + ' already exists but uses another driver or port. Nothing was changed.') }; Write-Host '[OK] Matching strips queue already exists; creation skipped.' -ForegroundColor Green } else { Add-Printer -Name $targetName -DriverName $source.DriverName -PortName $source.PortName -ErrorAction Stop; $target=Get-Printer -Name $targetName -ErrorAction Stop; Write-Host '[OK] Strips queue created from the source driver and port.' -ForegroundColor Green }; Write-Host ''; Write-Host 'The DNP 2inch cut option is proprietary and cannot be set by Add-Printer.' -ForegroundColor Yellow; Write-Host 'Printer Properties will open now.'; Write-Host 'Open Advanced - Printing Defaults, enable 2inch cut, then Apply and OK.' -ForegroundColor Yellow; Write-Host ''; & (Join-Path $env:SystemRoot 'System32\rundll32.exe') 'printui.dll,PrintUIEntry' '/p' '/n' $targetName"

if errorlevel 1 (
    echo.
    echo ERROR: The strips printer queue was not created.
    echo Check the message above and verify that the main DNP queue is installed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   QUEUE READY
echo ============================================
echo The main queue was not modified.
echo Make sure DNP 2inch cut was enabled only for the strips queue.
echo.
pause
exit /b 0
