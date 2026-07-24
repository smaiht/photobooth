@echo off
setlocal
cd /d "%~dp0"

echo Fetching origin/main...
git fetch --prune origin main
if errorlevel 1 (
    echo ERROR: git fetch failed. Local files were not changed.
    exit /b 1
)

if exist ".update_in_progress.json" (
    echo ERROR: Yandex.Disk update is still running.
    echo Wait for the application to reopen, then try again.
    exit /b 1
)

:: Stop only this installation's app before replacing its tracked files.
set "PHOTOBOOTH_SYNC_PYTHONW=%~dp0python\pythonw.exe"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $target=[IO.Path]::GetFullPath($env:PHOTOBOOTH_SYNC_PYTHONW); $processes=@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and [IO.Path]::GetFullPath([string]$_.ExecutablePath) -ieq $target }); foreach ($process in $processes) { Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop }; foreach ($process in $processes) { Wait-Process -Id $process.ProcessId -Timeout 10 -ErrorAction SilentlyContinue }; if ($processes.Count -gt 0) { Start-Sleep -Seconds 2 }"
if errorlevel 1 (
    echo ERROR: could not stop the running Photobooth application.
    exit /b 1
)

echo Aligning tracked files with origin/main...
git reset --hard origin/main
if errorlevel 1 (
    echo ERROR: git reset failed.
    exit /b 1
)

echo [OK] Code is synchronized with origin/main.
exit /b 0
