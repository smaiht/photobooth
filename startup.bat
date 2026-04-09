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
echo [OK] Python found
echo.

:: Create venv if needed
if not exist "venv\Scripts\python.exe" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv!
        pause
        exit /b 1
    )
    echo [OK] Venv created
    echo.

    echo [SETUP] Installing dependencies...
    venv\Scripts\pip.exe install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies!
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed
    echo.
) else (
    echo [OK] Venv exists
    echo.
)

:: Check uvicorn
echo [CHECK] Uvicorn...
venv\Scripts\python.exe -c "import uvicorn; print('uvicorn', uvicorn.__version__)" 2>nul
if errorlevel 1 (
    echo [WARN] Uvicorn not found, reinstalling...
    venv\Scripts\pip.exe install -r requirements.txt
)
echo.

:: Check app imports
echo [CHECK] App imports...
venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from backend.main import app; print('[OK] App loaded, routes:', len(app.routes))"
if errorlevel 1 (
    echo [ERROR] App failed to import! Check errors above.
    pause
    exit /b 1
)
echo.

:: Kill leftover processes
echo [CLEANUP] Killing old processes...
taskkill /f /fi "WINDOWTITLE eq PhotoboothServer*" >nul 2>&1
taskkill /f /im "msedge.exe" /fi "COMMANDLINE eq *localhost:8000*" >nul 2>&1
echo [OK] Cleanup done
echo.

:: Start server
echo [START] Starting server...
start "PhotoboothServer" cmd /k "cd /d "%~dp0" && venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 2>&1"
echo [OK] Server process launched (check PhotoboothServer window)
echo.

:: Wait for server with countdown
echo [WAIT] Waiting for server to respond...
set /a attempts=0
:wait_loop
set /a attempts+=1
if %attempts% gtr 30 (
    echo [ERROR] Server did not start after 30 seconds!
    echo         Check the PhotoboothServer window for errors.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul

:: Try connecting — use powershell if curl not available
curl -s -o nul -w "" http://localhost:8000/api/config >nul 2>&1
if errorlevel 1 (
    powershell -Command "try { Invoke-WebRequest -Uri http://localhost:8000/api/config -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
)
if errorlevel 1 (
    echo        Attempt %attempts%/30...
    goto wait_loop
)

echo [OK] Server is running!
echo.

:: Launch kiosk
echo [START] Launching Edge kiosk...
echo         (if browser closes, it will restart automatically)
echo.
echo ============================================
echo         PHOTOBOOTH IS READY
echo ============================================
echo.

:kiosk_loop
start /wait msedge --kiosk http://localhost:8000 --edge-kiosk-type=fullscreen --no-first-run --disable-features=TranslateUI --autoplay-policy=no-user-gesture-required
echo [WARN] Browser closed! Restarting in 2 seconds...
timeout /t 2 /nobreak >nul
goto kiosk_loop
