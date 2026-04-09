@echo off
chcp 65001 >nul
title Photobooth
cd /d "%~dp0"

echo ============================================
echo           PHOTOBOOTH STARTUP
echo ============================================
echo.

:: Check Python
echo [CHECK] Python...
python --version 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found! Install from python.org and check "Add to PATH"
    pause
    exit /b 1
)
echo.

:: Create venv if needed
if not exist "venv\Scripts\python.exe" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
)

:: Sync dependencies
echo [SETUP] Checking dependencies...
venv\Scripts\pip.exe install -q -r requirements.txt
echo [OK] Ready
echo.

:: Launch app with auto-restart on crash
:run_loop
echo [START] Launching Photobooth...
venv\Scripts\python.exe app.py
if exist ".stop" (
    del ".stop"
    echo [STOP] Photobooth stopped by admin.
    pause
    exit /b 0
)
echo.
echo [WARN] App crashed. Restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto run_loop
