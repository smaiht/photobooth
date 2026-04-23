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
    <div style="display:flex; align-items:center; gap:2vw">
        {DOTS_SVG}
        <span style="font-size:3.5vw; font-weight:600; color:#FF2973">Загрузка1</span>
    </div>
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

_HASH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".update_hash")


def _should_skip(name: str) -> bool:
    """Skip files that Windows locks while Python is running."""
    n = name.replace("\\", "/")
    if n.endswith("/"):
        return True
    # Skip all exe/dll/pyd in python/ — they're locked by running process
    if n.startswith("python/") and n.rsplit(".", 1)[-1] in ("exe", "dll", "pyd"):
        return True
    return False


def _update_from_notes():
    """Download update from Yandex Notes pb_update. Returns True if updated."""
    import asyncio, base64, zipfile, io

    cookie = os.environ.get("YANOTES_SESSION_ID", "")
    if not cookie:
        log.info("Notes update: no YANOTES_SESSION_ID")
        return False

    async def _do():
        from backend.yanotes import build_session, find_or_create_notes, get_note_content, list_notes
        from backend.cloud import _decrypt_str, UPDATE_NOTE

        s = build_session(cookie)
        try:
            notes = await find_or_create_notes(s, [UPDATE_NOTE])
            note_id = notes.get(UPDATE_NOTE)
            if not note_id:
                return False

            # Get snippet (encrypted hash)
            all_notes = await list_notes(s)
            snippet = ""
            for n in all_notes:
                if n.get("title") == UPDATE_NOTE:
                    snippet = n.get("snippet", "")
                    break
            if not snippet:
                log.info("Notes update: no update available")
                return False

            remote_hash = _decrypt_str(snippet)
            log.info(f"Notes update: remote hash decrypted: {remote_hash}")
            local_hash = open(_HASH_FILE).read().strip() if os.path.exists(_HASH_FILE) else ""
            if remote_hash == local_hash:
                log.info(f"Notes update: up to date ({remote_hash})")
                return False

            # Download content
            log.info(f"Notes update: new version {remote_hash}, downloading...")
            content, _ = await get_note_content(s, note_id)
            log.info(f"Notes update: content type={type(content).__name__}, len={len(str(content)[:200])}")
            if isinstance(content, list):
                content = content[0]
            payload = None
            try:
                for attr in content["children"][0]["children"][0].get("attributes", []):
                    if attr[0] == "d" and attr[1]:
                        payload = attr[1]
                        break
            except (KeyError, IndexError):
                pass
            if not payload:
                log.info("Notes update: no payload")
                return False
            log.info(f"Notes update: payload size {len(payload)} chars")

            # Decrypt → base64 decode → ZIP
            log.info("Notes update: decrypting...")
            zip_data = base64.b64decode(_decrypt_str(payload))
            log.info(f"Notes update: ZIP {len(zip_data)/1048576:.1f} MB")

            # Extract, skip locked exe/dll files
            app_dir = os.path.dirname(os.path.abspath(__file__))
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                for member in zf.namelist():
                    if _should_skip(member):
                        continue
                    target = os.path.join(app_dir, member)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())

            open(_HASH_FILE, "w").write(remote_hash)
            log.info(f"Notes update: done ({remote_hash})")
            return True
        finally:
            await s.close()

    return asyncio.run(_do())


def auto_update():
    """Git pull + pip install if GitHub reachable. TODO: fallback to Yandex Notes."""
    import subprocess, socket
    si = None
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        # TEMP: simulate GitHub blocked — remove this line to restore
        raise OSError("SIMULATED: GitHub blocked")
        # socket.create_connection(("github.com", 443), timeout=5)
        log.info("Network: OK")
    except OSError as e:
        log.info(f"Network: no connection ({e})")
        try:
            if _update_from_notes():
                log.info("Restarting with new code...")
                subprocess.Popen([sys.executable] + sys.argv, startupinfo=si)
                os._exit(0)
        except Exception as ex:
            log.info(f"Notes update error: {ex}")
        return
    app_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        r = subprocess.run(["git", "pull"], cwd=app_dir, capture_output=True, text=True, timeout=15, startupinfo=si)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        log.info(f"git pull: {out} {err}")
        if out and "Already up to date" not in out:
            r2 = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                                cwd=app_dir, capture_output=True, text=True, timeout=60, startupinfo=si)
            log.info(f"pip install: done ({(r2.stderr or '').strip()})")
            log.info("Restarting with new code...")
            # Spawn new process, kill old (Popen + _exit is safer than execv when pywebview is running)
            subprocess.Popen([sys.executable] + sys.argv, startupinfo=si)
            os._exit(0)
            # Alternative: os.execv(sys.executable, [sys.executable] + sys.argv)
            # Works when no GUI window is open, but may fail with pywebview active
    except Exception as e:
        log.info(f"Error: {e}")


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

    def update_then_start():
        # Auto-update while Loading is shown
        auto_update()
        # Start backend
        start_server()

    threading.Thread(target=update_then_start, daemon=True).start()

    # Wait for server in background, then load app
    threading.Thread(target=wait_and_load, args=(window,), daemon=True).start()

    webview.start()


if __name__ == "__main__":
    main()
