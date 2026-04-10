"""Photobooth — single entry point.

Starts FastAPI backend + pywebview fullscreen window.
No browser, no Edge, no kiosk mode needed.
"""

import sys
import os
import threading
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def start_server():
    import uvicorn
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


def main():
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

    # Start backend in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/config", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    # Start fullscreen window
    import webview
    window = webview.create_window(
        title="Photobooth",
        url="http://127.0.0.1:8000",
        fullscreen=True,
        easy_drag=False,
        text_select=False,
        zoomable=False,
    )

    # Disable right-click context menu via JS after page loads
    def on_loaded():
        window.evaluate_js("document.addEventListener('contextmenu', e => e.preventDefault())")

    window.events.loaded += on_loaded
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
