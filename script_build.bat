@echo off
cd /d "%~dp0"
echo ============================================
echo        BUILDING PHOTOBOOTH.EXE
echo ============================================
echo.

echo [UPDATE] Git pull...
git pull 2>nul
echo.

if not exist "venv\Scripts\python.exe" (
    echo [SETUP] Creating venv...
    python -m venv venv
)
echo [SETUP] Installing dependencies...
venv\Scripts\pip.exe install -q -r requirements.txt
echo.

echo [BUILD] Running PyInstaller...
venv\Scripts\pyinstaller.exe --onefile --console --name Photobooth ^
    --add-data "frontend;frontend" ^
    --add-data "templates;templates" ^
    --add-data "bin;bin" ^
    --add-data "EDSDK_Win\EDSDK_64\Dll;EDSDK_Win\EDSDK_64\Dll" ^
    app.py
echo.
echo [DONE] dist\Photobooth.exe
pause
