@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [UPDATE] Git pull...
git pull 2>nul

:: Check Python
python --version 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found!
    pause
    exit /b 1
)

:: Create venv if needed
if not exist "venv\Scripts\python.exe" (
    python -m venv venv
)

:: Sync dependencies
venv\Scripts\pip.exe install -q -r requirements.txt

:: Launch app (no console)
start "" venv\Scripts\pythonw.exe app.py --dev
