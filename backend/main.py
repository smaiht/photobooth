"""Photobooth backend — FastAPI + WebSocket.

State machine:
  IDLE → COUNTDOWN → CAPTURE → FREEZE → (repeat num_photos times) → TEMPLATE_SELECT → COMPOSING → PRINTING → IDLE
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import load_event_config, PHOTOS_DIR, FRONTEND_DIR, EDSDK_DLL
from .composer import compose_strip, compose_grid
from .uploader import Uploader
from .video import VideoRecorder
from .bot import start_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI()

# --- State ---
STATE = "idle"
SESSION_ID = ""
SESSION_PHOTOS: list[str] = []
SESSION_COUNT = 0
CONFIG = load_event_config()
CLIENTS: list[WebSocket] = []

# --- Camera (Windows only) ---
camera = None
if sys.platform == "win32":
    try:
        from .camera.edsdk import Camera
        camera = Camera(EDSDK_DLL)
        camera.set_download_dir(PHOTOS_DIR)
    except Exception as e:
        log.warning(f"EDSDK not available: {e}")

# --- Services ---
uploader = Uploader({
    "tg_bot_token": os.environ.get("TG_BOT_TOKEN", ""),
    "tg_chat_id": os.environ.get("TG_CHAT_ID", ""),
})
video_recorder = VideoRecorder()
_event_loop = None


# --- WebSocket broadcast ---
async def broadcast(msg: dict):
    data = json.dumps(msg)
    for ws in list(CLIENTS):
        try:
            await ws.send_text(data)
        except Exception:
            CLIENTS.remove(ws)


async def broadcast_binary(data: bytes):
    for ws in list(CLIENTS):
        try:
            await ws.send_bytes(data)
        except Exception:
            CLIENTS.remove(ws)


async def set_state(new_state: str, extra: dict | None = None):
    global STATE
    STATE = new_state
    msg = {"type": "state", "state": new_state}
    if extra:
        msg.update(extra)
    log.info(f"State → {new_state}")
    await broadcast(msg)


# --- Callbacks from EDSDK thread ---
def on_evf_frame(jpeg_bytes: bytes):
    """Called from EDSDK thread — forward to clients + record video."""
    video_recorder.add_frame(jpeg_bytes)
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast_binary(jpeg_bytes), _event_loop)


def on_photo_downloaded(file_path: str):
    SESSION_PHOTOS.append(file_path)
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            broadcast({"type": "photo_taken", "index": len(SESSION_PHOTOS) - 1}),
            _event_loop)


def on_camera_error(error: str):
    log.warning(f"Camera error: {error}")
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            broadcast({"type": "state", "state": "no_camera"}),
            _event_loop)


def on_camera_connected():
    log.info("Camera connected")
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            set_state("idle"),
            _event_loop)


# --- Session flow ---
async def run_session():
    global SESSION_ID, SESSION_PHOTOS, SESSION_COUNT

    SESSION_COUNT += 1
    SESSION_ID = uuid.uuid4().hex[:8]
    SESSION_PHOTOS = []
    session_dir = PHOTOS_DIR / SESSION_ID
    session_dir.mkdir(exist_ok=True)
    log.info(f"=== Session {SESSION_ID} started ===")

    num_photos = CONFIG["num_photos"]
    countdown_sec = CONFIG["countdown_seconds"]

    # Start live view + video recording
    if camera:
        camera.set_download_dir(session_dir)
        camera.start_live_view()
        log.info("Live view started")
    video_recorder.start(session_dir)

    # Countdown → capture loop (live view continues throughout)
    for photo_idx in range(num_photos):
        n = photo_idx + 1
        log.info(f"Countdown {n}/{num_photos} started ({countdown_sec}s)")
        await set_state("countdown", {"photo_index": photo_idx, "total": num_photos})
        for sec in range(countdown_sec, 0, -1):
            await broadcast({"type": "countdown", "value": sec})
            await asyncio.sleep(1)
        log.info(f"Countdown {n}/{num_photos} finished, sending capture command")
        if camera:
            camera.take_picture()
        await broadcast({"type": "flash"})
        video_recorder.mark_capture()

    # Wait for all photos to download (live view still running)
    if camera:
        log.info(f"Waiting for {num_photos} photos to download...")
        for _ in range(300):
            if len(SESSION_PHOTOS) >= num_photos:
                break
            await asyncio.sleep(0.1)
        camera.stop_live_view()
        log.info("Live view stopped")

        if len(SESSION_PHOTOS) < num_photos:
            await broadcast({"type": "error", "message": "Ошибка загрузки фото. Попробуйте снова."})
            await asyncio.sleep(3)
            await set_state("idle")
            return

    # Start video encoding in background (all frames + photos ready)
    photos_copy = SESSION_PHOTOS[:]
    video_path = session_dir / "session.mp4"
    video_future = asyncio.get_event_loop().run_in_executor(
        None, video_recorder.stop_and_encode, video_path, photos_copy, 30
    )

    # Template selection
    await set_state("template_select")
    selected_template = CONFIG["default_template"]
    template_event = asyncio.Event()
    chosen = {"template": selected_template}

    def on_template_choice(t):
        chosen["template"] = t
        template_event.set()

    app.state.on_template_choice = on_template_choice
    try:
        await asyncio.wait_for(template_event.wait(), timeout=CONFIG["template_select_timeout"])
    except asyncio.TimeoutError:
        pass
    selected_template = chosen["template"]

    # Compose collage
    await set_state("composing")
    output_path = None
    if SESSION_PHOTOS:
        from .config import TEMPLATES_DIR
        template_dir = TEMPLATES_DIR / "default"
        overlay = template_dir / f"{selected_template}.png"
        overlay_path = str(overlay) if overlay.exists() else None

        if selected_template == "strip":
            result = compose_strip(SESSION_PHOTOS[:4], overlay_path)
        else:
            result = compose_grid(SESSION_PHOTOS[:4], overlay_path)

        output_path = session_dir / f"print_{selected_template}.jpg"
        result.save(str(output_path), "JPEG", quality=95, dpi=(300, 300))
        log.info(f"Composed: {output_path}")

    # Print
    if CONFIG["print_enabled"] and output_path:
        await set_state("printing")
        from .printer import enqueue_print
        await enqueue_print(str(output_path), CONFIG)

    # Upload in background (wait for video, then send)
    async def _bg_upload():
        video_file = await video_future
        await uploader.upload_session(
            session_id=SESSION_ID,
            photos=photos_copy,
            collage=str(output_path) if output_path else None,
            video=video_file,
        )
    asyncio.create_task(_bg_upload())

    await set_state("idle")


# --- Routes ---
app.mount("/photos", StaticFiles(directory=str(PHOTOS_DIR)), name="photos")
app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/style.css")
async def style():
    return FileResponse(str(FRONTEND_DIR / "style.css"))


@app.get("/app.js")
async def script():
    return FileResponse(str(FRONTEND_DIR / "app.js"))


@app.get("/api/config")
async def get_config():
    return CONFIG


@app.post("/api/shutdown")
async def shutdown():
    """Full stop. Used by Telegram bot /stop."""
    os._exit(0)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    CLIENTS.append(ws)
    await ws.send_text(json.dumps({"type": "state", "state": STATE}))

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg["type"] == "start_session" and STATE == "idle":
                if camera and camera._connected:
                    asyncio.create_task(run_session())
                else:
                    await broadcast({"type": "state", "state": "no_camera"})

            elif msg["type"] == "select_template" and STATE == "template_select":
                cb = getattr(app.state, "on_template_choice", None)
                if cb:
                    cb(msg.get("template", "strip"))

    except WebSocketDisconnect:
        CLIENTS.remove(ws)


@app.on_event("startup")
async def startup():
    global _event_loop
    _event_loop = asyncio.get_event_loop()

    if camera:
        camera.set_callbacks(
            on_evf_frame=on_evf_frame,
            on_photo=on_photo_downloaded,
            on_error=on_camera_error,
            on_connected=on_camera_connected,
        )
        camera.start()
        log.info("Camera started")
    else:
        log.info("Running without camera (not Windows or EDSDK not found)")

    # Periodic retry of failed Telegram uploads
    async def retry_loop():
        while True:
            await asyncio.sleep(30)
            await uploader.retry_pending()

    asyncio.create_task(retry_loop())

    # Status callback for bot
    def get_status():
        return {
            "state": STATE,
            "session_count": SESSION_COUNT,
            "print_enabled": CONFIG.get("print_enabled", False),
            "tg_enabled": bool(uploader.tg_bot_token and uploader.tg_chat_id),
            "reset_to_idle": lambda: asyncio.create_task(set_state("idle")),
        }

    # Start Telegram admin bot
    token = os.environ.get("TG_BOT_TOKEN", "")
    admin_id = int(os.environ.get("TG_ADMIN_ID", "0") or "0")
    asyncio.create_task(start_bot(token, admin_id, get_status))
