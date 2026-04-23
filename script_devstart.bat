@echo off
cd /d "%~dp0"
git pull
call _ensure_python.bat
start "" python\pythonw.exe app.py --dev
