"""Photobooth backend - FastAPI + WebSocket.

State machine:
  IDLE -> COUNTDOWN -> CAPTURE -> (repeat num_photos times) -> PROCESSING -> TEMPLATE_SELECT -> COMPOSING -> DONE -> IDLE
"""

import asyncio
import json
import logging
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from .config import (
    EDSDK_DLL,
    FRONTEND_DIR,
    PHOTOS_DIR,
    ROOT_DIR,
    TEMPLATES_DIR,
    load_event_config,
    update_camera_config_field,
)
from .composer import compose, generate_template_previews
from .log import read_log_snapshot
from .video import VideoRecorder
from . import yadisk_cloud, yadisk_control

log = logging.getLogger(__name__)

app = FastAPI()

# --- State ---
STATE = "idle"
SESSION_ID = ""
SESSION_PHOTOS: list[str] = []
SESSION_COUNT = 0
SESSION_LINK = ""
TEMPLATE_OPTIONS: list[dict] = []
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


CONFIG_EXPORT_FILENAMES = ("config_app.json", "config_camera.json")


def _build_config_export(root: Path = ROOT_DIR) -> bytes:
    """Combine both current config files into one readable text document."""
    output = bytearray()
    for filename in CONFIG_EXPORT_FILENAMES:
        payload = (root / filename).read_bytes()
        output.extend(f"===== {filename} =====\n".encode("utf-8"))
        output.extend(payload)
        if not payload.endswith(b"\n"):
            output.extend(b"\n")
        output.extend(b"\n")
    return bytes(output)

# --- Services ---
video_recorder = VideoRecorder()
_event_loop = None
_latest_frame: bytes | None = None
_live_view_active = False
_evf_accept_after: float = 0.0
_background_uploads: set[asyncio.Task] = set()
_service_tasks: set[asyncio.Task] = set()
_session_running = False
_camera_disconnected_event = asyncio.Event()
_services_stopping = False


class CameraSessionAborted(RuntimeError):
    """The camera connection changed while a session was in progress."""


def _require_session_camera(generation: int) -> None:
    if (not camera or not camera.is_connected
            or camera.connection_generation != generation
            or _camera_disconnected_event.is_set()):
        raise CameraSessionAborted("camera disconnected during session")


def _clear_live_view():
    global _latest_frame, _live_view_active
    _live_view_active = False
    _latest_frame = None


def _remove_preview_dir(preview_dir: Path) -> None:
    """Remove only a generated session directory named exactly ``previews``."""
    if preview_dir.name != "previews":
        raise ValueError(f"Refusing to remove non-preview directory: {preview_dir}")
    if preview_dir.is_symlink() or preview_dir.is_file():
        preview_dir.unlink(missing_ok=True)
    elif preview_dir.is_dir():
        shutil.rmtree(preview_dir)


def _cleanup_stale_preview_dirs() -> None:
    if not PHOTOS_DIR.is_dir():
        return
    for session_dir in PHOTOS_DIR.iterdir():
        if session_dir.is_dir() and not session_dir.is_symlink():
            preview_dir = session_dir / "previews"
            if preview_dir.exists() or preview_dir.is_symlink():
                _remove_preview_dir(preview_dir)
                log.info("Removed stale template previews: %s", preview_dir)


# --- WebSocket broadcast ---
async def broadcast(msg: dict):
    data = json.dumps(msg)
    for ws in list(CLIENTS):
        try:
            await ws.send_text(data)
        except Exception:
            try:
                CLIENTS.remove(ws)
            except ValueError:
                pass


def _state_message(new_state: str) -> dict:
    msg = {"type": "state", "state": new_state}
    if SESSION_ID:
        msg["session_id"] = SESSION_ID
    if SESSION_LINK:
        msg["session_link"] = SESSION_LINK
    if new_state == "template_select":
        msg["timeout"] = int(CONFIG["template_select_timeout"])
        msg["templates"] = [dict(option) for option in TEMPLATE_OPTIONS]
    return msg


async def set_state(new_state: str, extra: dict | None = None):
    global STATE
    STATE = new_state
    msg = _state_message(new_state)
    if extra:
        msg.update(extra)
    log.info(f"State -> {new_state}")
    await broadcast(msg)


def _track_background(task: asyncio.Task, label: str) -> None:
    _background_uploads.add(task)

    def finished(done: asyncio.Task) -> None:
        _background_uploads.discard(done)
        try:
            done.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Background %s failed", label)

    task.add_done_callback(finished)


async def _on_session_link(session_id: str, public_url: str) -> None:
    """Show a link only while its session is still the booth's latest one."""
    global SESSION_LINK
    if SESSION_ID != session_id:
        log.info("YaDisk: ignoring QR for an older session %s", session_id)
        return
    SESSION_LINK = public_url
    await broadcast({
        "type": "session_link",
        "session_id": session_id,
        "url": public_url,
    })


async def _prepare_session_link(session_id: str, created_at: datetime,
                                event_folder: str,
                                session_folder: str) -> None:
    """Prepare the URL early; frontend decides when it may become visible."""
    delay = 1
    for attempt in range(4):
        if await yadisk_cloud.prepare_session_share(
            session_id,
            created_at,
            event_folder=event_folder,
            session_folder=session_folder,
        ):
            return
        if attempt < 3:
            await asyncio.sleep(delay)
            delay *= 2
    log.warning("YaDisk: early QR preparation failed for session %s", session_id)


# --- Callbacks from EDSDK thread ---
def on_evf_frame(jpeg_bytes: bytes):
    """Called from EDSDK thread - store latest frame, record video."""
    global _latest_frame
    if not _live_view_active or time.monotonic() < _evf_accept_after:
        return
    _latest_frame = jpeg_bytes
    video_recorder.add_frame(jpeg_bytes)


def on_photo_downloaded(file_path: str):
    SESSION_PHOTOS.append(file_path)
    idx = len(SESSION_PHOTOS)
    tag = f"[P{idx}]"
    log.info(f"{tag} downloaded: {file_path}")
    video_recorder.set_photo_path(file_path)
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            broadcast({"type": "photo_taken", "index": idx - 1}),
            _event_loop)


def on_camera_error(error: str):
    log.warning(f"Camera error: {error}")
    _clear_live_view()
    if _event_loop and _event_loop.is_running():
        async def show_disconnected():
            _camera_disconnected_event.set()
            await set_state("camera_searching")

        asyncio.run_coroutine_threadsafe(show_disconnected(), _event_loop)


def on_camera_connected():
    log.info("Camera connected")
    if _event_loop and _event_loop.is_running():
        async def show_ready():
            if not _session_running:
                await set_state("idle")

        asyncio.run_coroutine_threadsafe(show_ready(), _event_loop)


def _countdown_timing() -> tuple[float, int, int]:
    pre_countdown_delay = max(0.0, float(CONFIG["pre_countdown_delay"]))
    countdown_seconds = max(0, int(CONFIG["countdown_seconds"]))
    countdown_sound_seconds = int(CONFIG["countdown_sound_seconds"])
    countdown_sound_seconds = max(0, min(countdown_sound_seconds, countdown_seconds))
    return pre_countdown_delay, countdown_seconds, countdown_sound_seconds


# --- Session flow ---
async def run_session():
    global _session_running, TEMPLATE_OPTIONS
    if _session_running:
        log.warning("Duplicate session start ignored")
        return
    _session_running = True
    try:
        await _run_session()
    except CameraSessionAborted as exc:
        log.warning("Session aborted: %s", exc)
        _clear_live_view()
        SESSION_PHOTOS.clear()
        video_recorder.abort()
        await set_state(
            "idle" if camera and camera.is_connected else "camera_searching")
    except Exception:
        log.exception("Session error")
        _clear_live_view()
        video_recorder.abort()
        if camera and camera.is_connected:
            camera.stop_live_view()
        await set_state(
            "idle" if camera and camera.is_connected else "camera_searching")
    finally:
        _session_running = False
        app.state.on_template_choice = None
        TEMPLATE_OPTIONS = []
        if SESSION_ID:
            try:
                _remove_preview_dir(PHOTOS_DIR / SESSION_ID / "previews")
            except OSError:
                log.exception("Could not remove session template previews")
        if (camera and camera.is_connected
                and STATE in ("no_camera", "camera_searching")):
            await set_state("idle")


async def _run_session():
    global SESSION_ID, SESSION_PHOTOS, SESSION_COUNT, SESSION_LINK
    global TEMPLATE_OPTIONS
    global _live_view_active, _evf_accept_after

    if not camera or not camera.is_connected:
        await set_state("camera_searching" if camera else "no_camera")
        return
    storage_check = getattr(camera, "storage_ready", None)
    if storage_check:
        storage_ok, storage_error = storage_check()
        if not storage_ok:
            raise RuntimeError(storage_error)
    camera_generation = camera.connection_generation
    _camera_disconnected_event.clear()
    _require_session_camera(camera_generation)

    num_photos = int(CONFIG["num_photos"])
    if num_photos <= 0:
        raise ValueError("num_photos must be positive")
    template_dir = TEMPLATES_DIR / CONFIG.get("template_pack", "default")
    tpl_config = json.loads((template_dir / "config.json").read_text(encoding="utf-8"))
    available_templates = tpl_config.get("templates", {})
    if not isinstance(available_templates, dict) or not available_templates:
        raise ValueError(f"No templates configured in {template_dir}")
    for template_name, template in available_templates.items():
        slots = template.get("photos") if isinstance(template, dict) else None
        if not isinstance(slots, list) or len(slots) != num_photos:
            raise ValueError(
                f"Template {template_name!r} must contain {num_photos} photo slots"
            )
        background = template.get("background")
        if not isinstance(background, str) or not (template_dir / background).is_file():
            raise ValueError(f"Template background is missing: {template_name!r}")
    if CONFIG["default_template"] not in available_templates:
        raise ValueError(f"Unknown default template: {CONFIG['default_template']}")

    SESSION_COUNT += 1
    SESSION_ID = uuid.uuid4().hex[:8] + hex(int(time.time() * 1000000))[2:]
    SESSION_LINK = ""
    TEMPLATE_OPTIONS = []
    session_created_at = datetime.now(timezone.utc)
    event_folder = (
        yadisk_cloud.current_event_folder()
        or str(CONFIG.get("yadisk_folder") or "").strip().strip("/")
    )
    session_folder = yadisk_cloud.session_folder_name(
        SESSION_ID, session_created_at)
    SESSION_PHOTOS = []
    session_dir = PHOTOS_DIR / SESSION_ID
    session_dir.mkdir(exist_ok=True)
    log.info(f"=== Session {SESSION_ID} started ===")

    pre_countdown_delay, countdown_seconds, countdown_sound_seconds = _countdown_timing()

    # Drop the previous session frame before the frontend reconnects to /live.
    _clear_live_view()

    video_recorder.start(session_dir)
    if camera and camera.is_connected:
        camera.set_download_dir(session_dir)
        camera.start_live_view()
        _evf_accept_after = time.monotonic() + float(CONFIG.get("live_view_warmup", 0.3))
        _live_view_active = True
        log.info("Live view started")

    # Countdown -> capture loop (live view continues throughout)
    for photo_idx in range(num_photos):
        _require_session_camera(camera_generation)

        tag = f"[P{photo_idx+1}]"
        log.info(
            f"{tag} pre_countdown={pre_countdown_delay}s, "
            f"countdown={countdown_seconds}s, sound={countdown_sound_seconds}s")
        await set_state("countdown", {
            "photo_index": photo_idx,
            "total": num_photos,
            "countdown_seconds": countdown_seconds,
            "countdown_sound_seconds": countdown_sound_seconds,
        })
        if pre_countdown_delay > 0:
            await asyncio.sleep(pre_countdown_delay)
        _require_session_camera(camera_generation)

        for sec in range(countdown_seconds, 0, -1):
            _require_session_camera(camera_generation)
            beep = sec <= countdown_sound_seconds
            await broadcast({
                "type": "countdown",
                "value": sec,
                "beep": beep,
                "beep_index": countdown_sound_seconds - sec if beep else 0,
            })
            await asyncio.sleep(1)

        _require_session_camera(camera_generation)

        log.info(f"{tag} take_picture + mark_photo")
        camera.take_picture(tag)
        video_recorder.mark_photo()
        await broadcast({"type": "flash"})

    # Wait for all photos to download
    log.info(f"Waiting for {num_photos} photos to download...")
    for _ in range(300):
        _require_session_camera(camera_generation)
        if len(SESSION_PHOTOS) >= num_photos:
            break
        await asyncio.sleep(0.1)
    _require_session_camera(camera_generation)
    _clear_live_view()
    camera.stop_live_view()
    log.info("Live view stopped")

    if len(SESSION_PHOTOS) < num_photos:
        video_recorder.abort()
        await broadcast({"type": "error", "message": "Photo download error. Try again."})
        await asyncio.sleep(3)
        await set_state("idle")
        return

    # Start video encoding in background (all frames + photos ready)
    photos_copy = SESSION_PHOTOS[:]
    video_future = asyncio.get_event_loop().run_in_executor(
        None, video_recorder.stop_and_encode
    )

    link_task = asyncio.create_task(_prepare_session_link(
        SESSION_ID,
        session_created_at,
        event_folder,
        session_folder,
    ))
    _track_background(link_task, f"QR preparation for {SESSION_ID}")

    # Build real, session-specific options before showing template selection.
    await set_state("processing")
    preview_dir = session_dir / "previews"
    log.info("Generating previews for %d templates...", len(available_templates))
    preview_started = time.monotonic()
    preview_paths = await asyncio.get_running_loop().run_in_executor(
        None,
        generate_template_previews,
        template_dir,
        photos_copy,
        tpl_config,
        preview_dir,
    )
    _require_session_camera(camera_generation)
    for template_name, preview_path in preview_paths.items():
        template = available_templates[template_name]
        label = template.get("label")
        if not isinstance(label, str) or not label.strip():
            label = template_name
        TEMPLATE_OPTIONS.append({
            "name": template_name,
            "label": label,
            "preview_url": (
                f"/photos/{SESSION_ID}/previews/{preview_path.name}"
            ),
        })
    selectable_templates = set(preview_paths)
    selected_template = CONFIG["default_template"]
    if selected_template not in selectable_templates:
        selected_template = TEMPLATE_OPTIONS[0]["name"]
        log.warning(
            "Default template preview unavailable; falling back to %s",
            selected_template,
        )
    log.info(
        "Template previews ready in %.2fs: %s",
        time.monotonic() - preview_started,
        ", ".join(preview_paths),
    )

    template_event = asyncio.Event()
    chosen = {"template": selected_template}

    def on_template_choice(t):
        if t not in selectable_templates:
            log.warning(f"Ignoring unknown template: {t}")
            return
        log.info(f"Template chosen: {t}")
        chosen["template"] = t
        template_event.set()

    app.state.on_template_choice = on_template_choice
    await set_state("template_select")
    log.info("Waiting for template choice...")
    choice_task = asyncio.create_task(template_event.wait())
    disconnect_task = asyncio.create_task(_camera_disconnected_event.wait())
    try:
        done, _ = await asyncio.wait(
            (choice_task, disconnect_task),
            timeout=CONFIG["template_select_timeout"],
            return_when=asyncio.FIRST_COMPLETED,
        )
        _require_session_camera(camera_generation)
        if choice_task not in done:
            log.info(f"Template timeout, using default: {selected_template}")
    finally:
        for task in (choice_task, disconnect_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(choice_task, disconnect_task, return_exceptions=True)
    selected_template = chosen["template"]
    log.info(f"Selected template: {selected_template}")

    # Compose the local print file. It never enters the cloud outbox.
    await set_state("composing")
    TEMPLATE_OPTIONS = []
    try:
        _remove_preview_dir(preview_dir)
    except OSError:
        log.exception("Could not remove session template previews: %s", preview_dir)
    log.info(f"SESSION_PHOTOS: {SESSION_PHOTOS}")
    output_path = None
    if SESSION_PHOTOS:
        def _compose():
            log.info(f"Composing {selected_template}...")
            result = compose(template_dir, selected_template, SESSION_PHOTOS, tpl_config)
            path = session_dir / f"print_{selected_template}.jpg"
            try:
                dpi = int(CONFIG.get("print_dpi", 600))
                result.save(str(path), "JPEG", quality=95, subsampling=0, dpi=(dpi, dpi))
            finally:
                result.close()
            return path

        output_path = await asyncio.get_event_loop().run_in_executor(None, _compose)
        _require_session_camera(camera_generation)
        log.info(f"Composed: {output_path}")
    else:
        log.warning("No photos to compose!")

    _require_session_camera(camera_generation)
    await set_state("done")

    # Print in background
    if CONFIG["print_enabled"] and output_path:
        from .printer import enqueue_print
        await enqueue_print(str(output_path), CONFIG, selected_template)
        _require_session_camera(camera_generation)

    # Upload in background
    session_id = SESSION_ID
    async def _bg_upload():
        try:
            video_file = await video_future
        except Exception:
            log.exception(
                "Video encoding failed for session %s; uploading photos only",
                session_id,
            )
            video_file = None
        await yadisk_cloud.enqueue_session(
            session_id,
            photos_copy,
            video_file,
            created_at=session_created_at,
            event_folder=event_folder,
            session_folder=session_folder,
        )
    upload_task = asyncio.create_task(_bg_upload())
    _track_background(upload_task, f"outbox preparation for {session_id}")

    # Show done/QR screen before allowing the next session
    await asyncio.sleep(max(0, float(CONFIG.get("done_screen_seconds", 8))))
    if (camera and camera.is_connected
            and camera.connection_generation == camera_generation
            and not _camera_disconnected_event.is_set()):
        await set_state("idle")


# --- MJPEG live view stream ---
async def _mjpeg_generator():
    while True:
        frame = _latest_frame if _live_view_active else None
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                b"\r\n" + frame + b"\r\n"
            )
        await asyncio.sleep(0.033)


@app.get("/live")
async def live_view():
    return StreamingResponse(_mjpeg_generator(),
                             media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={
                                 "Cache-Control": "no-store, no-cache, must-revalidate",
                                 "Pragma": "no-cache",
                             })


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


@app.get("/api/state")
async def get_state(frontend: str = ""):
    if frontend and frontend != STATE:
        log.warning(f"State desync: frontend={frontend} backend={STATE}")
    response = _state_message(STATE)
    response.pop("type", None)
    return response


@app.post("/api/shutdown")
async def shutdown():
    """Full stop."""
    await _shutdown_services()
    os._exit(0)


async def _do_restart():
    log.info("Restart requested!")
    await _shutdown_services()
    import subprocess
    si = None
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    log.info(f"Spawning: {sys.executable} {sys.argv}")
    child_env = os.environ.copy()
    child_env["PHOTOBOOTH_RESTART_PARENT_PID"] = str(os.getpid())
    subprocess.Popen(
        [sys.executable] + sys.argv,
        startupinfo=si,
        env=child_env,
    )
    await asyncio.sleep(0.1)
    os._exit(0)


def _save_event_folder(name: str) -> None:
    config_path = ROOT_DIR / "config_app.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["yadisk_folder"] = name
    temporary = config_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    temporary.replace(config_path)
    CONFIG["yadisk_folder"] = name


def _clear_local_logs() -> None:
    from logging.handlers import RotatingFileHandler

    log_path = ROOT_DIR / "photobooth.log"
    handler = next((
        candidate
        for candidate in logging.getLogger().handlers
        if (isinstance(candidate, RotatingFileHandler)
            and Path(candidate.baseFilename).resolve() == log_path.resolve())
    ), None)

    # On Windows the active log cannot be replaced while its handler keeps the
    # file open.  Truncate that same stream under the handler lock so concurrent
    # log records cannot slip across the clear boundary or trigger a rollover.
    if handler:
        handler.acquire()
    try:
        if handler and handler.stream:
            handler.flush()
            handler.stream.seek(0)
            handler.stream.truncate(0)
            handler.stream.flush()
        else:
            log_path.write_text("", encoding="utf-8")

        for rotated in ROOT_DIR.glob("photobooth.log.*"):
            if rotated.is_file():
                rotated.unlink(missing_ok=True)
    finally:
        if handler:
            handler.release()


async def handle_disk_command(command: dict) -> dict:
    """Execute one validated Disk command and return its response payload."""
    cmd = command["command"]
    data = command.get("data")
    command_id = command["command_id"]

    if cmd == "restart":
        if STATE not in ("idle", "no_camera", "camera_searching"):
            return {"status": "error", "message": f"Перезапуск отложен: state={STATE}"}
        if _background_uploads:
            return {
                "status": "error",
                "message": "Перезапуск отложен: завершается подготовка загрузки",
            }
        return {
            "status": "ok",
            "message": "Перезапуск подтверждён",
            "_post_action": _do_restart,
        }

    if cmd == "set_camera_config":
        if STATE not in ("idle", "no_camera", "camera_searching"):
            return {
                "status": "error",
                "message": f"Настройка камеры не изменена: state={STATE}",
            }
        if _background_uploads:
            return {
                "status": "error",
                "message": "Настройка камеры не изменена: завершается подготовка загрузки",
            }
        if not isinstance(data, dict):
            return {
                "status": "error",
                "message": "Настройка камеры не изменена: отсутствуют field/value",
            }
        try:
            field, old_value, new_value, changed = update_camera_config_field(
                data.get("field", ""), data.get("value"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "status": "error",
                "message": f"Настройка камеры не изменена: {exc}",
            }
        old_text = json.dumps(old_value, ensure_ascii=False)
        new_text = json.dumps(new_value, ensure_ascii=False)
        if not changed:
            return {
                "status": "ok",
                "message": (
                    f"Параметр камеры {field} уже равен {new_text}. "
                    "Перезапуск подтверждён"
                ),
                "_post_action": _do_restart,
            }
        return {
            "status": "ok",
            "message": (
                f"Параметр камеры {field}: {old_text} → {new_text}. "
                "Перезапуск подтверждён"
            ),
            "_post_action": _do_restart,
        }

    if cmd in ("run", "start_session"):
        if STATE != "idle":
            return {"status": "error", "message": f"Будка занята: state={STATE}"}
        if not camera or not camera.is_connected:
            await set_state("camera_searching" if camera else "no_camera")
            return {"status": "error", "message": "Камера не подключена"}
        storage_check = getattr(camera, "storage_ready", None)
        if storage_check:
            storage_ok, storage_error = storage_check()
            if not storage_ok:
                return {"status": "error", "message": storage_error}

        async def start_session_after_ack() -> None:
            asyncio.create_task(run_session())

        return {
            "status": "ok",
            "message": "Сессия запущена",
            "_post_action": start_session_after_ack,
        }

    if cmd == "status":
        hash_path = ROOT_DIR / ".update_hash"
        version = hash_path.read_text(encoding="utf-8").strip() if hash_path.exists() else "unknown"
        connected = bool(camera and camera.is_connected)
        event = yadisk_cloud.current_event_folder() or str(CONFIG.get("yadisk_folder", ""))
        status_lines = [
            f"State: {STATE}",
            f"Camera: {'online' if connected else 'offline'}",
        ]
        snapshot_method = getattr(camera, "status_snapshot", None) if camera else None
        if snapshot_method:
            snapshot = snapshot_method()
            identity = snapshot.get("product_name") or snapshot.get("model")
            if identity:
                status_lines.append(f"Camera model: {identity}")
            health = []
            for label, key in (
                ("power", "battery"),
                ("temp", "temperature"),
                ("AE", "ae_mode"),
                ("auto-off", "auto_power_off"),
            ):
                if snapshot.get(key) is not None:
                    health.append(f"{label}={snapshot[key]}")
            if health:
                status_lines.append("Camera health: " + ", ".join(health))
            disk_free = snapshot.get("disk_free_bytes")
            if isinstance(disk_free, int):
                status_lines.append(
                    f"Photo disk free: {disk_free / (1024 ** 3):.2f} GiB")
            if snapshot.get("last_shutdown_timer_extension_result"):
                status_lines.append(
                    "Camera shutdown timer extension: "
                    f"{snapshot['last_shutdown_timer_extension_result']} at "
                    f"{snapshot.get('last_shutdown_timer_extension_at') or 'unknown'}")
            if snapshot.get("last_disconnect_reason"):
                status_lines.append(
                    "Last camera disconnect: "
                    f"{snapshot['last_disconnect_reason']} at "
                    f"{snapshot.get('last_disconnect_at') or 'unknown'}")
        status_lines.extend([
            f"Event: {event}",
            f"Upload queue: {yadisk_cloud.pending_count()}",
            f"Version: {version}",
        ])
        return {
            "status": "ok",
            "message": "\n".join(status_lines),
            "event_folder": event,
        }

    if cmd == "set_event":
        name = data.get("name", "") if isinstance(data, dict) else ""
        if STATE not in ("idle", "no_camera", "camera_searching"):
            return {"status": "error", "message": f"Event не изменён: state={STATE}"}
        if _background_uploads:
            return {"status": "error", "message": "Event не изменён: завершается текущая загрузка"}
        try:
            await yadisk_cloud.set_event_folder(name)
            _save_event_folder(name)
        except Exception as exc:
            return {"status": "error", "message": f"Event не изменён: {exc}"}
        return {
            "status": "ok",
            "message": f"Event активирован на будке: {name}",
            "event_folder": name,
        }

    if cmd == "send_logs":
        log_path = ROOT_DIR / "photobooth.log"
        if not log_path.is_file():
            return {"status": "error", "message": "photobooth.log не найден"}
        payload = await asyncio.to_thread(read_log_snapshot, log_path)
        artifact_path = await yadisk_control.upload_log(command_id, payload)
        return {
            "status": "ok",
            "message": "Лог загружен",
            "artifact_path": artifact_path,
        }

    if cmd == "get_config":
        try:
            payload = await asyncio.to_thread(_build_config_export)
        except OSError as exc:
            return {
                "status": "error",
                "message": f"Конфиги не отправлены: {exc}",
            }
        artifact_path = await yadisk_control.upload_config_export(
            command_id, payload)
        return {
            "status": "ok",
            "message": "Конфиги фотобудки готовы",
            "artifact_path": artifact_path,
        }

    if cmd == "clear_logs":
        await asyncio.to_thread(_clear_local_logs)
        return {"status": "ok", "message": "Логи очищены"}

    return {"status": "error", "message": f"Неизвестная команда: {cmd}"}


async def _yadisk_service():
    await yadisk_cloud.yadisk_init()
    await yadisk_cloud.yadisk_upload_queue_loop()


async def _control_service():
    folder = CONFIG.get("yadisk_control_folder", "photobooth_system/control")
    await yadisk_control.control_init(folder)
    await yadisk_control.control_poll_loop(handle_disk_command)


async def _shutdown_services() -> None:
    """Stop EDSDK and all aiohttp owners before the process exits."""
    global _services_stopping
    if _services_stopping:
        return
    _services_stopping = True
    log.info("Stopping backend services...")

    for task in list(_service_tasks):
        task.cancel()
    if _service_tasks:
        await asyncio.gather(*list(_service_tasks), return_exceptions=True)
    _service_tasks.clear()

    if _background_uploads:
        _, pending = await asyncio.wait(
            list(_background_uploads), timeout=5)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    await asyncio.gather(
        yadisk_control.control_close(),
        yadisk_cloud.yadisk_close(),
        return_exceptions=True,
    )
    video_recorder.abort()
    if camera:
        log.info("Stopping camera...")
        await asyncio.to_thread(camera.stop)
        log.info("Camera stopped")
    log.info("Backend services stopped")


@app.post("/api/restart")
async def restart():
    await _do_restart()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    if ws not in CLIENTS:
        CLIENTS.append(ws)
    initial_state = _state_message(STATE)
    await ws.send_text(json.dumps(initial_state))

    # Show update log on first client connect
    update_log = getattr(app.state, "update_log_path", None)
    if update_log and os.path.exists(update_log):
        for line in open(update_log).read().strip().splitlines():
            log.info(f"[update] {line}")
        app.state.update_log_path = None

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg["type"] == "start_session" and STATE == "idle":
                if camera and camera.is_connected:
                    asyncio.create_task(run_session())
                else:
                    await set_state("camera_searching" if camera else "no_camera")

            elif msg["type"] == "select_template" and STATE == "template_select":
                cb = getattr(app.state, "on_template_choice", None)
                if cb:
                    cb(msg.get("template", ""))

    except WebSocketDisconnect:
        try:
            CLIENTS.remove(ws)
        except ValueError:
            pass


@app.on_event("startup")
async def startup():
    global _event_loop, _services_stopping
    _services_stopping = False
    _event_loop = asyncio.get_event_loop()
    yadisk_cloud.set_session_link_handler(_on_session_link)
    await asyncio.to_thread(_cleanup_stale_preview_dirs)

    # Log auto-update results (deferred - will show after WS connects)
    update_log = os.path.join(ROOT_DIR, ".update_log")
    app.state.update_log_path = update_log

    if camera:
        camera.set_callbacks(
            on_evf_frame=on_evf_frame,
            on_photo=on_photo_downloaded,
            on_error=on_camera_error,
            on_connected=on_camera_connected,
        )
        await set_state("camera_searching")
        camera.start()
        log.info("Camera started")
    else:
        log.info("Running without camera (not Windows or EDSDK not found)")

    _service_tasks.add(asyncio.create_task(_control_service()))
    _service_tasks.add(asyncio.create_task(_yadisk_service()))


@app.on_event("shutdown")
async def app_shutdown():
    await _shutdown_services()
