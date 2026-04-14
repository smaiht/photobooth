@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Creating venv...
    python -m venv venv
    venv\Scripts\pip.exe install -q -r requirements.txt
)

start "" venv\Scripts\pythonw.exe app.py --dev
