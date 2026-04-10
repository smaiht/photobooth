"""Photobooth — single entry point.

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
if getattr(sys, 'frozen', False):
    _log_dir = os.path.dirname(sys.executable)
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
Загрузка...
</body>
</html>
"""


def start_server():
    import uvicorn
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


def wait_and_load(window):
    """Wait for server, then load the app. Restart if server didn't start."""
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/config", timeout=1)
            window.evaluate_js("window.location.replace('http://127.0.0.1:8000')")
            return
        except Exception:
            time.sleep(0.5)
    # Server didn't start — restart the whole app
    os.execv(sys.executable, [sys.executable] + sys.argv)


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

    # Start backend
    threading.Thread(target=start_server, daemon=True).start()

    # Show loading screen immediately, then switch to app
    import webview
    window = webview.create_window(
        title="Photobooth",
        html=LOADING_HTML,
        fullscreen=not dev,
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
