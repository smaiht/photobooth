@echo off
cd /d "%~dp0"
call "%~dp0_sync_from_git.bat"
if errorlevel 1 (
    echo.
    echo Development start cancelled.
    pause
    exit /b 1
)
call _ensure_python.bat
if errorlevel 1 (
    echo.
    echo Python setup failed.
    pause
    exit /b 1
)
start "" python\pythonw.exe app.py --dev
