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


def kill_port(port=8000):
    """Kill any process using our port."""
    import socket, subprocess
    try:
        s = socket.socket()
        s.settimeout(0.5)
        s.connect(("127.0.0.1", port))
        s.close()
        if sys.platform == "win32":
            # Find PID on port and kill it
            result = subprocess.run(
                f'netstat -ano | findstr :{port}',
                capture_output=True, text=True, shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if parts and parts[-1].isdigit():
                    subprocess.run(
                        f'taskkill /F /PID {parts[-1]}',
                        capture_output=True, shell=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
        else:
            subprocess.run(f"lsof -ti:{port} | xargs kill -9", shell=True, capture_output=True)
        time.sleep(1)
    except Exception:
        pass


def start_server():
    import uvicorn
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


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

_HASH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".update_hash")


def _should_skip(name: str) -> bool:
    """Skip files that Windows locks while Python is running."""
    n = name.replace("\\", "/")
    if n.endswith("/"):
        return True
    # Skip all exe/dll/pyd in python/ — they're locked by running process
    if n.startswith("python/") and n.rsplit(".", 1)[-1] in ("exe", "dll", "pyd"):
        return True
    top = n.split("/", 1)[0]
    # Event configuration and runtime state belong to this installation, not
    # to a release artifact built on CI.
    if top in {
        ".env", ".ENV", "config_app.json", "config_camera.json", "photos",
        "yadisk_queue.json", "upload_queue.json", "photobooth.log",
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


def _update_from_disk() -> bool:
    """Download and install the latest VPS-published Disk artifact."""
    import json
    from backend.yadisk_updates import download_artifact, read_status

    config_path = Path(__file__).resolve().parent / "config_app.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    folder = config.get("yadisk_updates_folder", "photobooth_system/updates")
    status = read_status(folder)
    if not status:
        log.info("Disk update: status.json not available")
        _ui_log("На Диске нет обновлений")
        return False

    version = status.get("version")
    kind = status.get("kind", "full")
    if not isinstance(version, str) or len(version) != 16 or kind not in ("full", "small"):
        raise ValueError("invalid update status")
    local_hash = Path(_HASH_FILE).read_text(encoding="utf-8").strip() \
        if os.path.exists(_HASH_FILE) else ""
    if version == local_hash:
        log.info(f"Disk update: already current ({version}, {kind})")
        _ui_log(f"Версия актуальна ({version})")
        return False

    _ui(f"setStatus('Обновление')")
    _ui_log(f"Новая версия на Диске: {version} ({kind})")
    app_dir = Path(__file__).resolve().parent
    temp_path = app_dir / ".update_download.zip"
    try:
        _ui_log("Скачивание с Яндекс Диска...")
        size, _ = download_artifact(status, temp_path)
        _ui_log(f"Получено {size / 1048576:.0f} МБ")
        _ui_log("Распаковка...")
        _extract_update(str(temp_path), str(app_dir))
        Path(_HASH_FILE).write_text(version, encoding="utf-8")
        log.info(f"Disk update: installed {version} ({kind})")
        _ui_log("Обновление установлено!")
        return True
    finally:
        temp_path.unlink(missing_ok=True)
def auto_update():
    """Check the Disk status pointer before starting the application."""
    import subprocess
    si = None
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        if _update_from_disk():
            log.info("Restarting with new Disk code...")
            _ui_log("Перезапуск...")
            subprocess.Popen([sys.executable] + sys.argv, startupinfo=si)
            os._exit(0)
    except Exception as e:
        log.exception("Disk update failed")
        _ui_log(f"Ошибка обновления: {e}")


def main():
    dev = "--dev" in sys.argv
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

    # Kill leftover process on our port
    kill_port()

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
        auto_update()
        _ui_log("Запуск сервера...")
        # Start backend
        start_server()

    threading.Thread(target=update_then_start, daemon=True).start()

    # Wait for server in background, then load app
    threading.Thread(target=wait_and_load, args=(window,), daemon=True).start()

    webview.start()


if __name__ == "__main__":
    main()
