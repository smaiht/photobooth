"""Photobooth - single entry point.

Starts FastAPI backend + pywebview fullscreen window.
Shows loading screen instantly, switches to app when server is ready.
"""

import sys
import os
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Log to file so we can debug when console is hidden
from backend.log import setup as setup_logging
setup_logging()

DOTS_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" style="width:6vw;height:6vw">'
    '<circle fill="#FF2973" stroke="#FF2973" stroke-width="23" r="15" cx="40" cy="65">'
    '<animate attributeName="cy" calcMode="spline" dur="2" values="65;135;65;" '
    'keySplines=".5 0 .5 1;.5 0 .5 1" repeatCount="indefinite" begin="-.4"/></circle>'
    '<circle fill="#FF2973" stroke="#FF2973" stroke-width="23" r="15" cx="100" cy="65">'
    '<animate attributeName="cy" calcMode="spline" dur="2" values="65;135;65;" '
    'keySplines=".5 0 .5 1;.5 0 .5 1" repeatCount="indefinite" begin="-.2"/></circle>'
    '<circle fill="#FF2973" stroke="#FF2973" stroke-width="23" r="15" cx="160" cy="65">'
    '<animate attributeName="cy" calcMode="spline" dur="2" values="65;135;65;" '
    'keySplines=".5 0 .5 1;.5 0 .5 1" repeatCount="indefinite" begin="0"/></circle>'
    '</svg>'
)

FONT_PATH = Path(__file__).parent / "frontend" / "assets" / "fonts" / "Comfortaa-VariableFont_wght.ttf"

def _build_loading_html():
    import base64
    font_b64 = base64.b64encode(FONT_PATH.read_bytes()).decode("ascii")
    return f"""
<html>
<head><style>
@font-face {{
    font-family: 'Comfortaa';
    src: url('data:font/truetype;base64,{font_b64}') format('truetype');
}}
</style></head>
<body style="margin:0; background:#fff; display:flex; align-items:center;
             justify-content:center; height:100vh; font-family:'Comfortaa',sans-serif">
    <div style="display:flex; flex-direction:column; align-items:center; gap:2vw">
        <div style="display:flex; align-items:center; gap:2vw">
            {DOTS_SVG}
            <span id="status" style="font-size:3.5vw; font-weight:600; color:#FF2973">Загрузка</span>
        </div>
        <div id="log" style="font-size:1.2vw; color:#999; text-align:center; line-height:1.8"></div>
    </div>
    <script>
    function setStatus(text) {{ document.getElementById('status').textContent = text; }}
    function addLog(text) {{
        var el = document.getElementById('log');
        el.innerHTML += text + '<br>';
    }}
    </script>
</body>
</html>
"""


_server = None
_instance_mutex_handle = None
_INSTANCE_MUTEX_NAME = "Local\\PhotoboothApp.SingleInstance"
_ERROR_ALREADY_EXISTS = 183
_RESTART_PARENT_ENV = "PHOTOBOOTH_RESTART_PARENT_PID"


def _wait_for_restart_parent() -> None:
    """Let a deliberately spawned replacement wait for the old mutex owner."""
    raw_pid = os.environ.pop(_RESTART_PARENT_ENV, "").strip()
    if sys.platform != "win32" or not raw_pid:
        return
    try:
        parent_pid = int(raw_pid)
    except ValueError:
        return
    deadline = time.monotonic() + 30
    while (_windows_process_is_running(parent_pid)
           and time.monotonic() < deadline):
        time.sleep(0.1)


def _acquire_single_instance() -> bool:
    """Own the booth process without ever killing an existing instance."""
    global _instance_mutex_handle
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    create_mutex.restype = wintypes.HANDLE
    handle = create_mutex(None, False, _INSTANCE_MUTEX_NAME)
    if not handle:
        log.error("Photobooth single-instance mutex could not be created")
        return False
    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        log.info("Another photobooth instance is already running; exiting")
        return False
    _instance_mutex_handle = handle
    return True


def _release_single_instance() -> None:
    global _instance_mutex_handle
    if not _instance_mutex_handle or sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(_instance_mutex_handle)
    finally:
        _instance_mutex_handle = None


def start_server():
    global _server
    import uvicorn
    from backend.main import app
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=8000, log_level="warning"))
    _server = server
    try:
        server.run()
    finally:
        _server = None


def _request_server_stop() -> None:
    if _server is not None:
        _server.should_exit = True


def wait_and_load(window):
    """Wait for server, then load the app."""
    import urllib.request
    while True:
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/config", timeout=1)
            window.evaluate_js("window.location.replace('http://127.0.0.1:8000')")
            return
        except Exception:
            time.sleep(0.5)


import logging
log = logging.getLogger("update")

_window = None

def _ui(js):
    """Execute JS on loading screen (safe to call before window is ready)."""
    try:
        if _window:
            _window.evaluate_js(js)
    except Exception:
        pass

def _ui_log(text):
    _ui(f"addLog('{text}')")

_APP_DIR = Path(__file__).resolve().parent
_HASH_FILE = str(_APP_DIR / ".update_hash")
_UPDATE_MARKER = _APP_DIR / ".update_in_progress.json"

_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002
_ES_CONTINUOUS = 0x80000000


def _prevent_windows_sleep() -> bool:
    """Keep an active booth and its display awake until this process exits."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        set_execution_state = ctypes.windll.kernel32.SetThreadExecutionState
        set_execution_state.argtypes = (wintypes.DWORD,)
        set_execution_state.restype = wintypes.DWORD
        flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        if not set_execution_state(flags):
            log.warning("Windows sleep prevention could not be enabled")
            return False
        log.info("Windows system sleep and display timeout prevention enabled")
        return True
    except Exception:
        log.exception("Windows sleep prevention failed")
        return False


def _restore_windows_sleep(enabled: bool) -> None:
    """Release the process-scoped execution-state request on a normal exit."""
    if not enabled or sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        set_execution_state = ctypes.windll.kernel32.SetThreadExecutionState
        set_execution_state.argtypes = (wintypes.DWORD,)
        set_execution_state.restype = wintypes.DWORD
        set_execution_state(_ES_CONTINUOUS)
        log.info("Windows sleep prevention released")
    except Exception:
        log.exception("Windows sleep prevention release failed")


def _windows_process_is_running(pid: int) -> bool:
    """Return whether a Windows process still exists without opening a shell."""
    if sys.platform != "win32" or pid <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        wait_for_single_object = kernel32.WaitForSingleObject
        wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        wait_for_single_object.restype = wintypes.DWORD
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        # HANDLE is pointer-sized. Without the explicit ctypes signatures it
        # is truncated to a 32-bit int on 64-bit Windows, making a live
        # installer look dead and allowing a second update to start over it.
        handle = open_process(synchronize, False, pid)
        if not handle:
            return False
        try:
            return wait_for_single_object(handle, 0) == wait_timeout
        finally:
            close_handle(handle)
    except Exception:
        return False


def _external_update_active(marker_path: Path = _UPDATE_MARKER) -> bool:
    """Detect the one-shot installer, tolerating its atomic marker rewrite."""
    if not marker_path.is_file():
        return False
    try:
        import json
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        installer_pid = int(marker.get("installer_pid") or 0)
        owner_pid = int(marker.get("owner_pid") or 0)
        started_at = float(marker.get("started_at") or 0)
    except Exception:
        installer_pid = 0
        owner_pid = 0
        try:
            started_at = marker_path.stat().st_mtime
        except OSError:
            return False

    age = time.time() - started_at
    active_pid = installer_pid or owner_pid
    if active_pid and 0 <= age < 2 * 60 * 60 \
            and _windows_process_is_running(active_pid):
        return True
    # There is a very short interval between creating the marker and receiving
    # the PowerShell PID. Treat it as active, but recover from a crashed launch.
    if not installer_pid and 0 <= age < 30:
        return True
    try:
        marker_path.unlink(missing_ok=True)
    except OSError:
        pass
    log.warning("Disk update: removed stale installer marker")
    return False


def _claim_update_marker(marker_path: Path = _UPDATE_MARKER) -> bool:
    """Atomically own the Windows update check before doing any network work."""
    import json

    marker = {
        "started_at": time.time(),
        "owner_pid": os.getpid(),
        "installer_pid": 0,
    }
    try:
        marker_fd = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return False
    try:
        with os.fdopen(marker_fd, "w", encoding="utf-8") as marker_file:
            json.dump(marker, marker_file)
    except Exception:
        try:
            marker_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return True


def _release_update_marker(marker_path: Path = _UPDATE_MARKER) -> None:
    """Release only a check marker still owned by this Python process."""
    try:
        import json
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if (int(marker.get("owner_pid") or 0) != os.getpid()
                or int(marker.get("installer_pid") or 0)):
            return
        marker_path.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("Disk update: could not release update marker: %s", exc)


def _cleanup_stale_update_artifacts(app_dir: Path = _APP_DIR) -> None:
    """Best-effort cleanup after an interrupted current installer."""
    import shutil

    file_patterns = (
        ".update_download.*.zip",
        ".update_apply.*.ps1",
        ".update_in_progress.json.*.tmp",
        ".update_hash.tmp",
    )
    for pattern in file_patterns:
        for path in app_dir.glob(pattern):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Disk update: stale file is still busy %s: %s", path, exc)
    for pattern in (".update_stage.*",):
        for path in app_dir.glob(pattern):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
            except OSError as exc:
                log.warning("Disk update: stale stage is still busy %s: %s", path, exc)


def _should_skip(name: str) -> bool:
    """Skip files that Windows locks while Python is running."""
    n = name.replace("\\", "/")
    if n.endswith("/"):
        return True
    # Skip all exe/dll/pyd in python/ — they're locked by running process
    if n.startswith("python/") and n.rsplit(".", 1)[-1] in ("exe", "dll", "pyd"):
        return True
    top = n.split("/", 1)[0]
    # Runtime state belongs to this installation. config_app.json and
    # config_camera.json intentionally come from the release for now.
    if top in {
        ".git", ".env", ".ENV", "photos", "photos_print_jobs",
        "yadisk_queue.json", "photobooth.log",
    } or top.startswith("photobooth.log."):
        return True
    return False


def _extract_update(zip_path: str, app_dir: str) -> None:
    import zipfile

    root = os.path.realpath(app_dir)
    with zipfile.ZipFile(zip_path) as zf:
        bad_member = zf.testzip()
        if bad_member:
            raise ValueError(f"ZIP CRC failed: {bad_member}")
        for info in zf.infolist():
            member = info.filename.replace("\\", "/")
            if _should_skip(member):
                continue
            target = os.path.realpath(os.path.join(app_dir, member))
            if os.path.commonpath((root, target)) != root:
                raise ValueError(f"ZIP path escapes application directory: {member}")
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())


def _prepare_update_stage(zip_path: Path, stage_path: Path) -> int:
    """Extract a full release before the visible application is closed."""
    import shutil
    import zipfile

    stage_path = stage_path.resolve()
    if stage_path.exists():
        shutil.rmtree(stage_path)
    stage_path.mkdir(parents=True)
    stage_root = os.path.realpath(stage_path)
    extracted_files = 0
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                member = info.filename.replace("\\", "/")
                target = os.path.realpath(os.path.join(stage_path, member))
                if os.path.commonpath((stage_root, target)) != stage_root:
                    raise ValueError(
                        f"ZIP path escapes update stage: {info.filename}")
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                extracted_files += 1
        if not (stage_path / "app.py").is_file():
            raise ValueError("full update does not contain app.py at ZIP root")
        return extracted_files
    except Exception:
        shutil.rmtree(stage_path, ignore_errors=True)
        raise


def _schedule_full_update(stage_path: Path, app_dir: Path, version: str) -> bool:
    """Start the one external installer; return False if one already owns it."""
    import json
    import subprocess

    app_dir = app_dir.resolve()
    stage_path = stage_path.resolve()
    suffix = str(os.getpid())
    script_path = app_dir / f".update_apply.{suffix}.ps1"
    marker_path = app_dir / ".update_in_progress.json"
    marker_temp_path = app_dir / f".update_in_progress.json.{suffix}.tmp"

    marker = {
        "started_at": time.time(),
        "owner_pid": os.getpid(),
        "installer_pid": 0,
    }
    try:
        marker_fd = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        try:
            existing = json.loads(marker_path.read_text(encoding="utf-8"))
            owns_marker = (
                int(existing.get("owner_pid") or 0) == os.getpid()
                and not int(existing.get("installer_pid") or 0)
            )
        except Exception:
            owns_marker = False
        if not owns_marker:
            log.info("Disk update: another process already owns the update marker")
            return False
        marker_fd = None

    process = None
    try:
        if marker_fd is not None:
            with os.fdopen(marker_fd, "w", encoding="utf-8") as marker_file:
                json.dump(marker, marker_file)
        script_path.write_text(r'''param(
    [int]$ParentPid,
    [string]$AppDir,
    [string]$StagePath,
    [string]$Version,
    [string]$PythonExe,
    [ValidateSet("kiosk", "dev")]
    [string]$Mode,
    [string]$MarkerPath
)
$ErrorActionPreference = "Stop"
$stage = $StagePath
$logPath = Join-Path $AppDir "photobooth.log"
$installed = $false

function Write-UpdateLog([string]$Message, [string]$Level = "INFO") {
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss,fff"
        Add-Content -LiteralPath $logPath -Encoding UTF8 -ErrorAction Stop `
            -Value ($timestamp + " update " + $Level + " " + $Message)
    } catch {
        # Logging must never make an otherwise valid update fail.
    }
}

function Get-PhotoboothProcesses {
    return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.ProcessId -ne $ParentPid -and $_.ExecutablePath -and
        [string]::Equals(
            [string]$_.ExecutablePath,
            $PythonExe,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    })
}

try {
    Write-UpdateLog ("Full installer started for " + $Version.Substring(0, 16))
    Wait-Process -Id $ParentPid -ErrorAction SilentlyContinue
    Write-UpdateLog "Parent application stopped"

    $deadline = (Get-Date).AddSeconds(60)
    $otherProcesses = @(Get-PhotoboothProcesses)
    while ($otherProcesses.Count -gt 0 -and (Get-Date) -lt $deadline) {
        Write-UpdateLog ("Waiting for another photobooth process: " + `
            (($otherProcesses | ForEach-Object { $_.ProcessId }) -join ", "))
        Start-Sleep -Milliseconds 1000
        $otherProcesses = @(Get-PhotoboothProcesses)
    }
    if ($otherProcesses.Count -gt 0) {
        throw ("Another photobooth process is still running: " + `
            (($otherProcesses | ForEach-Object { $_.ProcessId }) -join ", "))
    }

    if (-not (Test-Path -LiteralPath (Join-Path $stage "app.py") -PathType Leaf)) {
        throw "Prepared update stage does not contain app.py"
    }
    Write-UpdateLog "Prepared full release found"
    $preserve = @(
        ".git", ".env", ".ENV", "photos", "photos_print_jobs", "yadisk_queue.json",
        "photobooth.log", ".update_hash"
    )
    foreach ($name in $preserve) {
        Remove-Item -LiteralPath (Join-Path $stage $name) -Recurse -Force `
            -ErrorAction SilentlyContinue
    }
    Get-ChildItem -LiteralPath $stage -Filter "photobooth.log*" -Force `
        -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $stage -Force -ErrorAction SilentlyContinue | `
        Where-Object { $_.Name -like ".update*" } | `
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    Write-UpdateLog "Copying release files"
    & robocopy.exe $stage $AppDir /E /COPY:DAT /DCOPY:DAT /R:20 /W:1 `
        /NFL /NDL /NJH /NJS /NP | Out-Null
    $copyExitCode = $LASTEXITCODE
    if ($copyExitCode -ge 8) {
        throw ("robocopy failed with exit code " + $copyExitCode)
    }
    Write-UpdateLog ("Release files copied, robocopy exit code " + $copyExitCode)

    $hashPath = Join-Path $AppDir ".update_hash"
    $hashTempPath = Join-Path $AppDir ".update_hash.tmp"
    Set-Content -LiteralPath $hashTempPath -Value $Version -NoNewline -Encoding ascii
    Move-Item -LiteralPath $hashTempPath -Destination $hashPath -Force
    $installed = $true
    Write-UpdateLog ("Full update installed " + $Version.Substring(0, 16))
} catch {
    Write-UpdateLog ("Full update failed: " + $_.Exception.Message) "ERROR"
} finally {
    Remove-Item -LiteralPath (Join-Path $AppDir ".update_hash.tmp") `
        -Force -ErrorAction SilentlyContinue
}

$appScript = Join-Path $AppDir "app.py"
$relaunchArgumentLine = '"' + $appScript + '"'
if ($Mode -eq "dev") {
    $relaunchArgumentLine += " --dev"
}

# The next process is an ordinary application launch. Remove installer
# ownership first so it performs the normal status.json version check.
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue

try {
    $launched = Start-Process -FilePath $PythonExe `
        -ArgumentList $relaunchArgumentLine -WorkingDirectory $AppDir -PassThru
    if ($installed) {
        Write-UpdateLog ("Updated application restarted, PID " + $launched.Id)
    } else {
        Write-UpdateLog ("Application restarted after failed update, PID " + `
            $launched.Id) "ERROR"
    }
    Start-Sleep -Seconds 2
    if ($launched.HasExited) {
        Write-UpdateLog ("Relaunched application exited immediately with code " + `
            $launched.ExitCode) "ERROR"
    }
} catch {
    Write-UpdateLog ("Application relaunch failed: " + $_.Exception.Message) "ERROR"
}
''', encoding="utf-8")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script_path),
                "-ParentPid", str(os.getpid()),
                "-AppDir", str(app_dir),
                "-StagePath", str(stage_path),
                "-Version", version,
                "-PythonExe", sys.executable,
                "-Mode", "dev" if "--dev" in sys.argv else "kiosk",
                "-MarkerPath", str(marker_path),
            ],
            cwd=str(app_dir),
            creationflags=creation_flags,
        )
        marker["installer_pid"] = process.pid
        marker_temp_path.write_text(json.dumps(marker), encoding="utf-8")
        os.replace(marker_temp_path, marker_path)
        return True
    except Exception:
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass
        for path in (marker_temp_path, marker_path, script_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _full_update(status: dict) -> dict:
    if not isinstance(status, dict) or status.get("schema_version") != 1:
        raise ValueError("invalid update status")
    if status.get("active") != "full":
        raise ValueError("update status does not point to the full artifact")
    artifacts = status.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("invalid update status")
    artifact = artifacts.get("full")
    if not isinstance(artifact, dict):
        raise ValueError("full update artifact is missing")
    return artifact


def _update_from_disk() -> str | None:
    """Download and install the latest VPS-published Disk artifact."""
    import json
    from backend.yadisk_updates import download_artifact, read_status

    config_path = Path(__file__).resolve().parent / "config_app.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    folder = config.get("yadisk_updates_folder", "photobooth_system/updates")
    log.info("Disk update: checking %s/status.json", folder.rstrip("/"))
    status = read_status(folder)
    if not status:
        log.info("Disk update: status.json not available")
        _ui_log("На Диске нет обновлений")
        return None

    artifact = _full_update(status)
    version = artifact.get("sha256")
    if not isinstance(version, str) or len(version) != 64:
        raise ValueError("invalid update sha256")
    local_hash = Path(_HASH_FILE).read_text(encoding="utf-8").strip() \
        if os.path.exists(_HASH_FILE) else ""
    if version == local_hash:
        log.info(f"Disk update: already current ({version[:16]}, full)")
        _ui_log(f"Версия актуальна ({version[:16]})")
        return None

    _ui(f"setStatus('Обновление')")
    _ui_log(f"Новая полная версия на Диске: {version[:16]}")
    app_dir = Path(__file__).resolve().parent
    temp_path = app_dir / f".update_download.{os.getpid()}.zip"
    stage_path = app_dir / f".update_stage.{os.getpid()}"
    external_owns_stage = False
    try:
        _ui_log("Скачивание с Яндекс Диска...")
        expected_size = int(artifact.get("size") or 0)
        log.info("Disk update: downloading full %s (%.1f MiB)",
                 version[:16], expected_size / 1048576)
        download_started = time.monotonic()
        size, _ = download_artifact(artifact, temp_path)
        elapsed = max(time.monotonic() - download_started, 0.001)
        log.info("Disk update: download complete, %.1f MiB in %.1fs (%.1f MiB/s)",
                 size / 1048576, elapsed, size / 1048576 / elapsed)
        _ui_log(f"Получено {size / 1048576:.0f} МБ")
        if sys.platform == "win32":
            _ui_log("Проверка архива...")
            log.info("Disk update: validating ZIP CRC and paths")
            # Validate paths and CRC before handing the archive to PowerShell.
            import zipfile
            root = os.path.realpath(app_dir)
            with zipfile.ZipFile(temp_path) as archive:
                bad_member = archive.testzip()
                if bad_member:
                    raise ValueError(f"ZIP CRC failed: {bad_member}")
                for info in archive.infolist():
                    member = info.filename.replace("\\", "/")
                    target = os.path.realpath(os.path.join(app_dir, member))
                    if os.path.commonpath((root, target)) != root:
                        raise ValueError(
                            f"ZIP path escapes application directory: {info.filename}")
                log.info("Disk update: ZIP valid, %d entries", len(archive.infolist()))
            _ui_log("Подготовка файлов обновления...")
            log.info("Disk update: preparing full release before application exit")
            prepare_started = time.monotonic()
            extracted_files = _prepare_update_stage(temp_path, stage_path)
            log.info(
                "Disk update: full release prepared, %d files in %.1fs",
                extracted_files, time.monotonic() - prepare_started,
            )
            if _schedule_full_update(stage_path, app_dir, version):
                external_owns_stage = True
                log.info(f"Disk update: scheduled full {version[:16]}")
                _ui_log("Приложение сейчас закроется и откроется автоматически")
            else:
                log.info("Disk update: yielding to the installer already in progress")
                _ui_log("Установка уже выполняется другим процессом")
            return "external"

        _ui_log("Распаковка...")
        _extract_update(str(temp_path), str(app_dir))
        Path(_HASH_FILE).write_text(version, encoding="utf-8")
        log.info(f"Disk update: installed full {version[:16]}")
        _ui_log("Обновление установлено!")
        return "restart"
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Disk update: could not remove temporary download %s: %s",
                        temp_path, exc)
        if not external_owns_stage:
            import shutil
            try:
                shutil.rmtree(stage_path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("Disk update: could not remove prepared stage %s: %s",
                            stage_path, exc)


def auto_update():
    """Check the Disk status pointer before starting the application."""
    import subprocess
    si = None
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        update_action = _update_from_disk()
        if update_action == "external":
            log.info("Exiting for external full update...")
            _ui_log("Завершение полной установки...")
            os._exit(0)
        if update_action == "restart":
            log.info("Restarting with new Disk code...")
            _ui_log("Перезапуск...")
            subprocess.Popen([sys.executable] + sys.argv, startupinfo=si)
            os._exit(0)
    except Exception as e:
        log.exception("Disk update failed")
        _ui_log(f"Ошибка обновления: {e}")


def _run_application():
    installer_active = _external_update_active()
    if installer_active:
        # Do not load FastAPI or EDSDK while PowerShell is replacing files. The
        # installer waits for this short-lived Python process before copying.
        log.info("Disk update: installer is active; this extra launch will exit")
        return
    update_marker_owned = False
    if sys.platform == "win32":
        update_marker_owned = _claim_update_marker()
        if not update_marker_owned:
            log.info("Disk update: another launch won the update check; exiting")
            return
    _cleanup_stale_update_artifacts()

    dev = "--dev" in sys.argv
    sleep_prevention_enabled = _prevent_windows_sleep()
    # Load .env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    if key.strip() and val.strip():
                        os.environ[key.strip()] = val.strip()

    # Show loading screen immediately
    import webview
    window = webview.create_window(
        title="Photobooth",
        html=_build_loading_html(),
        fullscreen=not dev,
        width=1200,
        height=900,
        easy_drag=False,
        text_select=False,
        zoomable=False,
    )

    def on_loaded():
        window.evaluate_js("document.addEventListener('contextmenu', e => e.preventDefault())")

    window.events.loaded += on_loaded
    global _window
    _window = window

    def update_then_start():
        # Auto-update while Loading is shown
        try:
            auto_update()
        finally:
            if update_marker_owned:
                _release_update_marker()
        _ui_log("Запуск сервера...")
        # Start backend
        start_server()

    server_thread = threading.Thread(target=update_then_start, daemon=True)
    server_thread.start()

    # Wait for server in background, then load app
    threading.Thread(target=wait_and_load, args=(window,), daemon=True).start()

    try:
        webview.start()
    finally:
        _request_server_stop()
        server_thread.join(timeout=15)
        if server_thread.is_alive():
            log.warning("Backend did not stop within 15 seconds")
        _restore_windows_sleep(sleep_prevention_enabled)


def main():
    _wait_for_restart_parent()
    if not _acquire_single_instance():
        return
    try:
        _run_application()
    finally:
        _release_single_instance()


if __name__ == "__main__":
    main()
