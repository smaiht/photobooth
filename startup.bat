@echo off
title Photobooth
cd /d "%~dp0"

:: Browser — change to msedge if needed
set BROWSER=msedge

:: First run: create venv and install dependencies
if not exist "venv\Scripts\python.exe" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
    echo [SETUP] Installing dependencies...
    venv\Scripts\pip install -r requirements.txt
    echo [SETUP] Done!
)

:: Kill leftover processes from previous run
taskkill /f /fi "WINDOWTITLE eq PhotoboothServer" >nul 2>&1
taskkill /f /im "%BROWSER%.exe" /fi "COMMANDLINE eq *localhost:8000*" >nul 2>&1

:: Start backend in separate window
echo [START] Starting server...
start "PhotoboothServer" /min venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

:: Wait for server
echo [START] Waiting for server...
:wait_loop
timeout /t 1 /nobreak >nul
curl -s http://localhost:8000/api/config >nul 2>&1
if errorlevel 1 goto wait_loop

:: Launch kiosk — restart if closed
echo [START] Launching kiosk (%BROWSER%)...
:kiosk_loop
start /wait %BROWSER% --kiosk http://localhost:8000 --no-first-run --disable-features=TranslateUI --autoplay-policy=no-user-gesture-required
echo [WARN] Browser closed, restarting in 2s...
timeout /t 2 /nobreak >nul
goto kiosk_loop
