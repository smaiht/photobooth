@echo off
cd /d "%~dp0"
call "%~dp0_sync_from_git.bat"
if errorlevel 1 (
    echo Git synchronization failed.
    pause
    exit /b 1
)
pause
