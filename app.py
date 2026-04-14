"""Photobooth - single entry point.

Starts FastAPI backend + pywebview fullscreen window.
Shows loading screen instantly, switches to app when server is ready.
"""

import sys
import os
import threading
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Log to file so we can debug when console is hidden
_log_dir = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_log_dir, "photobooth.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

LOADING_HTML = """
<html>
<body style="margin:0;background:#fff;color:#000;display:flex;align-items:center;
justify-content:center;height:100vh;font-family:system-ui;font-size:4vw">
<div style="text-align:center">
<div style="width:60px;height:60px;border:4px solid #ddd;border-top:4px solid #000;
border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 30px"></div>
Загрузка...
</div>
<style>@keyframes spin{to{transform:rotate(360deg)}}</style>
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


_UPDATE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".update_log")

def auto_update():
    """Git pull + pip install before starting. Restart if code changed."""
    lines = []
    import subprocess, socket
    si = None
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        socket.create_connection(("github.com", 443), timeout=5)
        lines.append("Network: OK")
    except OSError as e:
        lines.append(f"Network: no connection ({e})")
        open(_UPDATE_LOG, "w").write("\n".join(lines))
        return
    app_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        r = subprocess.run(["git", "pull"], cwd=app_dir, capture_output=True, text=True, timeout=15, startupinfo=si)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        lines.append(f"git pull: {out} {err}")
        if out and "Already up to date" not in out:
            r2 = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                                cwd=app_dir, capture_output=True, text=True, timeout=60, startupinfo=si)
            lines.append(f"pip install: done ({(r2.stderr or '').strip()})")
            lines.append("Restarting with new code...")
            open(_UPDATE_LOG, "w").write("\n".join(lines))
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        lines.append(f"Error: {e}")
    open(_UPDATE_LOG, "w").write("\n".join(lines))


def main():
    auto_update()
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

    # Start backend
    threading.Thread(target=start_server, daemon=True).start()

    # Show loading screen immediately, then switch to app
    import webview
    window = webview.create_window(
        title="Photobooth",
        html=LOADING_HTML,
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

    # Wait for server in background, then load app
    threading.Thread(target=wait_and_load, args=(window,), daemon=True).start()

    webview.start()


if __name__ == "__main__":
    main()
