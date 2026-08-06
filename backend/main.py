"""Photobooth backend - FastAPI + WebSocket.

State machine:
  IDLE -> COUNTDOWN -> CAPTURE -> (repeat num_photos times) -> PROCESSING
  -> TEMPLATE_SELECT -> (COMPOSING -> DONE -> IDLE | IDLE when printing is skipped)
"""

import asyncio
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse

from .config import (
    EDSDK_DLL,
    FRONTEND_DIR,
    PHOTOS_DIR,
    PRINT_JOBS_DIR,
    ROOT_DIR,
    SERVER_PORT,
    TEMPLATES_DIR,
    load_event_config,
    update_camera_config_field,
)
from .composer import (
    compose,
    compose_unframed_photo,
    generate_template_previews,
    template_photo_count,
)
from .log import read_log_snapshot
from .video import VideoRecorder
from . import yadisk_cloud, yadisk_control

log = logging.getLogger(__name__)

app = FastAPI()

REMOTE_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOCAL_LIVE_VIEW_FPS = 30
REMOTE_LIVE_VIEW_FPS = 2


def _is_loopback_host(host: str | None) -> bool:
    """Return whether a direct HTTP/WebSocket peer is the local booth UI."""
    if not isinstance(host, str) or not host:
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback


@app.middleware("http")
async def remote_read_only(request: Request, call_next):
    """LAN viewers may read the app but cannot call mutating HTTP routes."""
    client_host = request.client.host if request.client else None
    if (request.method not in REMOTE_READ_ONLY_METHODS
            and not _is_loopback_host(client_host)):
        log.warning(
            "Blocked remote %s %s from %s",
            request.method,
            request.url.path,
            client_host or "unknown",
        )
        return Response(status_code=403)
    return await call_next(request)

# --- State ---
STATE = "idle"
STATE_EXTRA: dict = {}
SESSION_ID = ""
SESSION_PHOTOS: list[str] = []
SESSION_COUNT = 0
SESSION_LINK = ""
TEMPLATE_OPTIONS: list[dict] = []
CONFIG = load_event_config()

CAFE_UNLOCK_STATE_FILENAME = "cafe_unlock_state.json"
MAX_UNLOCK_SESSIONS = 1000


def _technical_event_name() -> str:
    """Return the exact event name whose start button needs an allowance."""
    configured = CONFIG.get("technical_event_name")
    return configured if isinstance(configured, str) and configured else "Кафе"


def _active_event_name() -> str:
    active = yadisk_cloud.current_event_folder()
    if active is None or active == "":
        active = CONFIG.get("yadisk_folder", "")
    return active if isinstance(active, str) else ""


def _is_technical_event() -> bool:
    return _active_event_name() == _technical_event_name()


def _cafe_unlock_state_path() -> Path:
    return ROOT_DIR / CAFE_UNLOCK_STATE_FILENAME


def _serialize_cafe_unlock_state(remaining: int) -> bytes:
    return (
        json.dumps(
            {"remaining_sessions": remaining},
            ensure_ascii=False,
            indent=4,
        ) + "\n"
    ).encode("utf-8")


def _load_cafe_unlock_sessions() -> int:
    """Load the durable allowance, failing closed for any unusable state."""
    path = _cafe_unlock_state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        remaining = payload.get("remaining_sessions") if isinstance(payload, dict) else None
        if (type(remaining) is not int
                or not 0 <= remaining <= MAX_UNLOCK_SESSIONS):
            raise ValueError("remaining_sessions must be an integer from 0 to 1000")
        return remaining
    except FileNotFoundError:
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Cafe unlock state is invalid; start remains locked: %s", exc)
        return 0


def _write_cafe_unlock_sessions(remaining: int) -> None:
    """Atomically persist a validated session allowance."""
    if (type(remaining) is not int
            or not 0 <= remaining <= MAX_UNLOCK_SESSIONS):
        raise ValueError("remaining_sessions must be an integer from 0 to 1000")
    path = _cafe_unlock_state_path()
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(_serialize_cafe_unlock_state(remaining))
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


_cafe_unlock_sessions_remaining = _load_cafe_unlock_sessions()


def _set_cafe_unlock_sessions(remaining: int) -> None:
    global _cafe_unlock_sessions_remaining
    _write_cafe_unlock_sessions(remaining)
    _cafe_unlock_sessions_remaining = remaining


def _consume_cafe_unlock_session() -> int:
    """Consume one completed Café session; persistence errors fail closed."""
    global _cafe_unlock_sessions_remaining
    if _cafe_unlock_sessions_remaining <= 0:
        log.info(
            "Cafe session completed after the allowance was reset; "
            "remaining sessions=0"
        )
        _cafe_unlock_sessions_remaining = 0
        return 0
    remaining = _cafe_unlock_sessions_remaining - 1
    try:
        _set_cafe_unlock_sessions(remaining)
    except (OSError, ValueError) as exc:
        # Never leave another start enabled when the durable decrement is
        # uncertain. Remove any older positive allowance so a process restart
        # sees a missing file and also fails closed.
        _cafe_unlock_sessions_remaining = 0
        log.error("Could not persist consumed Cafe session; failing closed: %s", exc)
        try:
            _cafe_unlock_state_path().unlink(missing_ok=True)
        except OSError as cleanup_exc:
            log.critical(
                "Could not remove stale Cafe unlock state after failed consume: %s",
                cleanup_exc,
            )
        return 0
    log.info("Cafe unlock consumed; remaining sessions=%d", remaining)
    return remaining


def _start_locked() -> bool:
    return _is_technical_event() and _cafe_unlock_sessions_remaining <= 0

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


CONFIG_EXPORT_FILENAMES = (
    CAFE_UNLOCK_STATE_FILENAME,
    "config_app.json",
    "config_camera.json",
)


def _build_config_export(root: Path = ROOT_DIR) -> bytes:
    """Combine the current runtime state and configs into one text document."""
    output = bytearray()
    for filename in CONFIG_EXPORT_FILENAMES:
        path = root / filename
        if filename == CAFE_UNLOCK_STATE_FILENAME and not path.is_file():
            payload = _serialize_cafe_unlock_state(
                _cafe_unlock_sessions_remaining)
        else:
            payload = path.read_bytes()
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


def _lan_ipv4_addresses() -> list[str]:
    """Best-effort private IPv4 addresses usable by hotspot/LAN viewers."""
    raw_addresses: set[str] = set()
    entries = []
    hostname_error = None
    try:
        entries = socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        hostname_error = exc
    raw_addresses.update(
        entry[4][0]
        for entry in entries
        if len(entry) > 4 and entry[4]
    )

    # Windows Mobile Hotspot uses a virtual adapter which hostname lookup may
    # omit. Get-NetIPAddress is built into supported Windows versions and does
    # not require administrator rights for this read-only query.
    if sys.platform == "win32":
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "Get-NetIPAddress -AddressFamily IPv4 "
                        "-AddressState Preferred | "
                        "ForEach-Object { $_.IPAddress }"
                    ),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode == 0:
                raw_addresses.update(completed.stdout.splitlines())
            else:
                log.warning(
                    "Could not query Windows viewer addresses: %s",
                    completed.stderr.strip() or f"exit {completed.returncode}",
                )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("Could not query Windows viewer addresses: %s", exc)

    if not raw_addresses and hostname_error:
        log.warning("Could not discover viewer LAN addresses: %s", hostname_error)

    addresses: set[ipaddress.IPv4Address] = set()
    for raw_address in raw_addresses:
        try:
            address = ipaddress.ip_address(raw_address.strip())
        except (AttributeError, ValueError):
            continue
        if (isinstance(address, ipaddress.IPv4Address)
                and address.is_private
                and not address.is_loopback
                and not address.is_link_local
                and not address.is_unspecified):
            addresses.add(address)
    hotspot_default = ipaddress.IPv4Address("192.168.137.1")
    if hotspot_default in addresses:
        return [str(hotspot_default)]
    return [
        str(address)
        for address in sorted(
            addresses,
            key=lambda address: (
                address != hotspot_default,
                address.packed[-1] != 1,
                int(address),
            ),
        )
    ]


def _viewer_urls() -> list[str]:
    return [
        f"http://{address}:{SERVER_PORT}/?viewer=1"
        for address in _lan_ipv4_addresses()
    ]


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
    msg = {
        "type": "state",
        "state": new_state,
        "start_locked": _start_locked(),
        "technical_event_active": _is_technical_event(),
        "unlock_sessions_remaining": _cafe_unlock_sessions_remaining,
    }
    if SESSION_ID:
        msg["session_id"] = SESSION_ID
    if SESSION_LINK:
        msg["session_link"] = SESSION_LINK
    if new_state == STATE and STATE_EXTRA:
        msg.update(STATE_EXTRA)
    if new_state == "template_select":
        msg["timeout"] = int(CONFIG["template_select_timeout"])
        msg["templates"] = [dict(option) for option in TEMPLATE_OPTIONS]
    return msg


async def set_state(new_state: str, extra: dict | None = None):
    global STATE, STATE_EXTRA
    STATE = new_state
    STATE_EXTRA = dict(extra or {})
    msg = _state_message(new_state)
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


async def _enqueue_session_after_video(
    session_id: str,
    photos: list[str],
    video_future: asyncio.Future,
    created_at: datetime,
    event_folder: str,
    session_folder: str,
) -> None:
    """Put captured media in the durable outbox as soon as video is ready."""
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
        photos,
        video_file,
        created_at=created_at,
        event_folder=event_folder,
        session_folder=session_folder,
    )


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


async def _finish_successful_session(
    output_path: Path,
    selected_template: str,
    camera_generation: int,
    session_uses_cafe_unlock: bool,
) -> None:
    """Queue the completed print, charge its allowance, then expose done."""
    if CONFIG["print_enabled"]:
        from .printer import enqueue_print
        await enqueue_print(str(output_path), CONFIG, selected_template)
        _require_session_camera(camera_generation)

    if session_uses_cafe_unlock:
        _consume_cafe_unlock_session()

    await set_state("done")


# --- Session flow ---
async def run_session():
    global _session_running, TEMPLATE_OPTIONS
    if _session_running:
        log.warning("Duplicate session start ignored")
        return
    if _start_locked():
        log.warning(
            "Session start blocked for technical event %r: no unlock sessions remain",
            _technical_event_name(),
        )
        await broadcast(_state_message(STATE))
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
        app.state.on_skip_print = None
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
        required_photos = template_photo_count(template, template_name)
        # A layout may intentionally use only the first captured photo, but it
        # must never reference a photo the session does not capture.
        if required_photos > num_photos:
            raise ValueError(
                f"Template {template_name!r} needs {required_photos} photos, "
                f"but the session captures {num_photos}"
            )
        if template.get("photo_choice") is True and required_photos != 1:
            raise ValueError(
                f"Photo-choice template {template_name!r} must reference "
                "exactly one photo"
            )
        layout = template["print_layout"]
        background = layout.get("background")
        if not isinstance(background, str) or not (template_dir / background).is_file():
            raise ValueError(f"Template background is missing: {template_name!r}")
        foreground = layout.get("foreground")
        if foreground is not None and (
            not isinstance(foreground, str)
            or not foreground
            or not (template_dir / foreground).is_file()
        ):
            raise ValueError(f"Template foreground is missing: {template_name!r}")
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
    session_uses_cafe_unlock = event_folder == _technical_event_name()
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

    session_id = SESSION_ID
    upload_task = asyncio.create_task(_enqueue_session_after_video(
        session_id,
        photos_copy,
        video_future,
        session_created_at,
        event_folder,
        session_folder,
    ))
    _track_background(upload_task, f"outbox preparation for {session_id}")

    link_task = asyncio.create_task(_prepare_session_link(
        session_id,
        session_created_at,
        event_folder,
        session_folder,
    ))
    _track_background(link_task, f"QR preparation for {session_id}")

    # Build real, session-specific options before showing template selection.
    await set_state("processing")
    preview_dir = session_dir / "previews"
    log.info("Generating previews for %d templates...", len(available_templates))
    preview_started = time.monotonic()
    preview_batch = await asyncio.get_running_loop().run_in_executor(
        None,
        generate_template_previews,
        template_dir,
        photos_copy,
        tpl_config,
        preview_dir,
    )
    _require_session_camera(camera_generation)
    preview_paths = dict(preview_batch)
    photo_choice_previews = getattr(preview_batch, "photo_choices", {})
    for template_name, preview_path in preview_paths.items():
        template = available_templates[template_name]
        label = template.get("label")
        if not isinstance(label, str) or not label.strip():
            label = template_name
        option = {
            "name": template_name,
            "label": label,
            "preview_url": (
                f"/photos/{SESSION_ID}/previews/{preview_path.name}"
            ),
        }
        choices = photo_choice_previews.get(template_name, [])
        if choices:
            option["photo_choice"] = True
            option["photo_previews"] = [{
                "photo_index": choice.photo_index,
                "with_frame_url": (
                    f"/photos/{SESSION_ID}/previews/{choice.with_frame.name}"
                ),
                "without_frame_url": (
                    f"/photos/{SESSION_ID}/previews/{choice.without_frame.name}"
                ),
            } for choice in choices]
        TEMPLATE_OPTIONS.append(option)
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
    chosen = {
        "template": selected_template,
        "photo_index": (
            0 if available_templates[selected_template].get("photo_choice") is True
            else None
        ),
        "with_frame": True,
        "skip_print": False,
    }

    def on_template_choice(t, photo_index=None, with_frame=None):
        if template_event.is_set():
            return
        if t not in selectable_templates:
            log.warning(f"Ignoring unknown template: {t}")
            return
        is_photo_choice = available_templates[t].get("photo_choice") is True
        if is_photo_choice:
            if (type(photo_index) is not int
                    or not 0 <= photo_index < len(SESSION_PHOTOS)):
                log.warning(
                    "Ignoring invalid photo index for %s: %r", t, photo_index)
                return
            if type(with_frame) is not bool:
                log.warning(
                    "Ignoring invalid frame choice for %s: %r", t, with_frame)
                return
        else:
            photo_index = None
            with_frame = True
        log.info(
            "Template chosen: %s, photo_index=%r, with_frame=%s",
            t,
            photo_index,
            with_frame,
        )
        chosen["template"] = t
        chosen["photo_index"] = photo_index
        chosen["with_frame"] = with_frame
        template_event.set()

    def on_skip_print():
        if template_event.is_set():
            return
        log.info("Print skipped by visitor")
        chosen["skip_print"] = True
        template_event.set()

    app.state.on_template_choice = on_template_choice
    app.state.on_skip_print = on_skip_print
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
    template_event.set()
    if chosen["skip_print"]:
        TEMPLATE_OPTIONS = []
        await set_state("idle")
        return

    selected_template = chosen["template"]
    selected_photo_index = chosen["photo_index"]
    selected_with_frame = chosen["with_frame"]
    log.info(
        "Selected template: %s, photo_index=%r, with_frame=%s",
        selected_template,
        selected_photo_index,
        selected_with_frame,
    )

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
            template = available_templates[selected_template]
            if template.get("photo_choice") is True:
                photo = SESSION_PHOTOS[selected_photo_index]
                if selected_with_frame:
                    result = compose(
                        template_dir, selected_template, [photo], tpl_config)
                    frame_label = "frame"
                else:
                    result = compose_unframed_photo(photo, tpl_config)
                    frame_label = "no_frame"
                path = session_dir / (
                    f"print_{selected_template}_photo_"
                    f"{selected_photo_index + 1:02d}_{frame_label}.jpg"
                )
            else:
                result = compose(
                    template_dir, selected_template, SESSION_PHOTOS, tpl_config)
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
    if output_path is None:
        raise RuntimeError("Session composition produced no print file")

    # Any compose/print-enqueue error happens before the durable allowance is
    # consumed, so a failed visitor session can be retried.
    await _finish_successful_session(
        output_path,
        selected_template,
        camera_generation,
        session_uses_cafe_unlock,
    )

    # Show done/QR screen before allowing the next session
    await asyncio.sleep(max(0, float(CONFIG.get("done_screen_seconds", 8))))
    if (camera and camera.is_connected
            and camera.connection_generation == camera_generation
            and not _camera_disconnected_event.is_set()):
        await set_state("idle")


# --- MJPEG live view stream ---
async def _mjpeg_generator():
    """Original full-rate stream used by the local production UI."""
    while True:
        frame = _latest_frame if _live_view_active else None
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n"
                b"\r\n" + frame + b"\r\n"
            )
        await asyncio.sleep(0.033)


async def _viewer_mjpeg_generator():
    """Bandwidth-limited stream used only by non-loopback LAN viewers."""
    frame_interval = 1 / REMOTE_LIVE_VIEW_FPS
    last_frame = None
    next_frame_at = 0.0
    while True:
        frame = _latest_frame if _live_view_active else None
        now = time.monotonic()
        if frame and frame is not last_frame and now >= next_frame_at:
            last_frame = frame
            next_frame_at = now + frame_interval
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n"
                b"\r\n" + frame + b"\r\n"
            )
        await asyncio.sleep(0.01)


@app.get("/live")
async def live_view(request: Request):
    client_host = request.client.host if request.client else None
    is_local = _is_loopback_host(client_host)
    fps = LOCAL_LIVE_VIEW_FPS if is_local else REMOTE_LIVE_VIEW_FPS
    generator = _mjpeg_generator() if is_local else _viewer_mjpeg_generator()
    return StreamingResponse(generator,
                             media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={
                                 "Cache-Control": "no-store, no-cache, must-revalidate",
                                 "Pragma": "no-cache",
                                 "X-Photobooth-Live-FPS": str(fps),
                             })


# --- Routes ---
app.mount("/photos", StaticFiles(directory=str(PHOTOS_DIR)), name="photos")
app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

FRONTEND_FILE_HEADERS = {"Cache-Control": "no-store"}


@app.get("/")
async def index():
    return FileResponse(
        str(FRONTEND_DIR / "index.html"), headers=FRONTEND_FILE_HEADERS)


@app.get("/style.css")
async def style():
    return FileResponse(
        str(FRONTEND_DIR / "style.css"), headers=FRONTEND_FILE_HEADERS)


@app.get("/app.js")
async def script():
    return FileResponse(
        str(FRONTEND_DIR / "app.js"), headers=FRONTEND_FILE_HEADERS)


@app.get("/api/config")
async def get_config():
    response = dict(CONFIG)
    poses_dir = FRONTEND_DIR / "assets" / "poses"
    image_extensions = {".jpg", ".jpeg", ".png", ".webp"}

    def natural_key(path: Path):
        return tuple(
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"(\d+)", path.name)
        )

    pose_files = sorted(
        (
            path for path in poses_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in image_extensions
        ),
        key=natural_key,
    ) if poses_dir.is_dir() else []
    response["pose_example_urls"] = [
        f"/assets/poses/{quote(path.name)}" for path in pose_files
    ]
    return response


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


_PRINT_QUEUE_LABELS = {
    "grid": "Grid",
    "strips": "Strips",
}


def _print_queue_status_message(records: list[dict]) -> tuple[str, bool]:
    lines = ["Очереди печати Windows:"]
    has_error = False
    for record in records:
        target = _PRINT_QUEUE_LABELS.get(
            record.get("target"),
            record.get("target", "?"),
        )
        printer_name = record.get("printer_name") or "неизвестен"
        error = record.get("error")
        if error:
            has_error = True
            lines.append(f"• {target} ({printer_name}): ошибка — {error}")
            continue
        jobs = record.get("jobs")
        if type(jobs) is not int or jobs < 0:
            has_error = True
            lines.append(
                f"• {target} ({printer_name}): число заданий неизвестно"
            )
        else:
            lines.append(
                f"• {target} ({printer_name}): заданий в очереди — {jobs}"
            )
    return "\n".join(lines), has_error


def _print_queue_clear_message(records: list[dict]) -> tuple[str, bool]:
    lines = ["Очистка очередей печати Windows:"]
    has_error = False
    for record in records:
        target = _PRINT_QUEUE_LABELS.get(
            record.get("target"),
            record.get("target", "?"),
        )
        printer_name = record.get("printer_name") or "неизвестен"
        shared_with = record.get("shared_with")
        if shared_with:
            shared_label = _PRINT_QUEUE_LABELS.get(shared_with, shared_with)
            lines.append(
                f"• {target} ({printer_name}): та же Windows-очередь; "
                f"результат указан в {shared_label}"
            )
            continue
        error = record.get("error")
        before = record.get("jobs_before")
        after = record.get("jobs_after")
        cleared = record.get("cleared")
        if error:
            has_error = True
            if before is None:
                lines.append(f"• {target} ({printer_name}): ошибка — {error}")
            else:
                lines.append(
                    f"• {target} ({printer_name}): удалено {cleared or 0}, "
                    f"осталось {after if after is not None else '?'} — {error}"
                )
            continue
        lines.append(
            f"• {target} ({printer_name}): было {before or 0}, "
            f"удалено {cleared or 0}, осталось {after or 0}"
        )
    return "\n".join(lines), has_error


async def handle_disk_command(command: dict) -> dict:
    """Execute one validated Disk command and return its response payload."""
    cmd = command["command"]
    data = command.get("data")
    command_id = command["command_id"]

    if cmd in ("print_queue", "clear_print_queue"):
        if data is not None:
            return {
                "status": "error",
                "message": "Команда очереди печати не принимает аргументы",
            }
        try:
            from .printer import (
                clear_windows_print_queues,
                get_windows_print_queues,
            )
            if cmd == "print_queue":
                records = await asyncio.to_thread(
                    get_windows_print_queues,
                    CONFIG,
                )
                message, has_error = _print_queue_status_message(records)
            else:
                records = await asyncio.to_thread(
                    clear_windows_print_queues,
                    CONFIG,
                )
                message, has_error = _print_queue_clear_message(records)
            return {
                "status": "error" if has_error else "ok",
                "message": message,
            }
        except Exception as exc:
            action = "просмотреть" if cmd == "print_queue" else "очистить"
            return {
                "status": "error",
                "message": f"Очереди печати не удалось {action}: {exc}",
            }

    if cmd == "print_image":
        if not CONFIG.get("print_enabled"):
            return {"status": "error", "message": "Печать на фотобудке отключена"}
        if not isinstance(data, dict):
            return {"status": "error", "message": "Задание печати не содержит данных"}

        artifact_path = data.get("artifact_path")
        event_folder = data.get("event_folder")
        job_id = str(data.get("job_id") or "")
        print_mode = str(data.get("print_mode") or "")
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return {"status": "error", "message": "Некорректный ID задания печати"}
        if print_mode not in ("fit", "fill"):
            return {"status": "error", "message": "Некорректный режим печати"}

        requested_event = str(event_folder or "").strip().strip("/")
        current_event = (
            yadisk_cloud.current_event_folder()
            or str(CONFIG.get("yadisk_folder") or "")
        ).strip().strip("/")
        if not requested_event or requested_event != current_event:
            log.warning(
                "Custom print rejected for stale event: job=%s requested=%r current=%r",
                job_id, requested_event, current_event,
            )
            return {
                "status": "error",
                "message": (
                    f"Фото относится к event «{requested_event or 'не указан'}», "
                    f"а на будке сейчас активен event «{current_event or 'не задан'}»"
                ),
            }

        source_filename = str(data.get("source_filename") or "")
        source_kind = str(data.get("telegram_source_kind") or "")
        source_mime = str(data.get("telegram_mime_type") or "")
        log.info(
            "Custom print received: job=%s mode=%s kind=%s filename=%s mime=%s "
            "artifact=%s expected_size=%s",
            job_id, print_mode, source_kind, source_filename, source_mime,
            artifact_path, data.get("source_size"),
        )
        keep_print_files = bool(CONFIG.get("keep_custom_print_files", True))
        job_dir = PRINT_JOBS_DIR / job_id
        original_path: Path | None = None
        output_path = job_dir / "print_4x6.jpg"
        try:
            payload = await yadisk_control.download_print_artifact(
                artifact_path, event_folder)
            log.info(
                "Custom print downloaded: job=%s bytes=%s artifact=%s",
                job_id, len(payload), artifact_path,
            )
            source_suffix = Path(str(artifact_path)).suffix.lower() or ".img"
            original_path = job_dir / f"original{source_suffix}"
            job_dir.mkdir(parents=True, exist_ok=True)
            original_temporary = original_path.with_name(original_path.name + ".tmp")
            original_temporary.write_bytes(payload)
            original_temporary.replace(original_path)
            log.info(
                "Custom print source saved: job=%s path=%s keep=%s",
                job_id, original_path, keep_print_files,
            )
            template_dir = TEMPLATES_DIR / CONFIG["template_pack"]
            template_config = json.loads(
                (template_dir / "config.json").read_text(encoding="utf-8"))
            raw_print_size = template_config.get("print_size", [3688, 2480])
            print_size = tuple(int(value) for value in raw_print_size)
            from .printer import prepare_custom_print
            await asyncio.to_thread(
                prepare_custom_print,
                payload,
                output_path,
                print_size,
                int(CONFIG.get("print_dpi", 600)),
                print_mode,
            )
        except Exception as exc:
            log.exception(
                "Custom print preparation failed: job=%s kind=%s filename=%s "
                "mime=%s artifact=%s",
                job_id, source_kind, source_filename, source_mime, artifact_path,
            )
            if not keep_print_files:
                for local_path in (original_path, output_path):
                    if local_path is not None:
                        local_path.unlink(missing_ok=True)
                try:
                    job_dir.rmdir()
                except OSError:
                    pass
            return {"status": "error", "message": f"Фото не поставлено на печать: {exc}"}

        async def enqueue_custom_print_after_ack() -> None:
            from .printer import enqueue_print
            await enqueue_print(
                str(output_path),
                CONFIG,
                delete_after=not keep_print_files,
                delete_paths=(
                    [str(original_path)]
                    if not keep_print_files and original_path is not None
                    else []
                ),
            )

        return {
            "status": "ok",
            "message": "Ваше фото добавлено в очередь и скоро будет распечатано.",
            "_post_action": enqueue_custom_print_after_ack,
        }

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
        if _start_locked():
            return {
                "status": "error",
                "message": (
                    f"Старт заблокирован для event «{_technical_event_name()}»: "
                    "сначала выполните /unblock"
                ),
                "start_locked": True,
                "unlock_sessions_remaining": _cafe_unlock_sessions_remaining,
            }
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

    if cmd == "unblock":
        sessions = data.get("sessions") if isinstance(data, dict) else None
        if (type(sessions) is not int
                or not 0 <= sessions <= MAX_UNLOCK_SESSIONS):
            return {
                "status": "error",
                "message": "sessions должно быть целым числом от 0 до 1000",
            }
        try:
            _set_cafe_unlock_sessions(sessions)
        except (OSError, ValueError) as exc:
            return {
                "status": "error",
                "message": f"Фотобудка не разблокирована: {exc}",
            }
        log.info("Cafe unlock updated: remaining sessions=%d", sessions)
        if STATE == "idle":
            await broadcast(_state_message(STATE))
        return {
            "status": "ok",
            "message": f"Остаток разрешённых фотосессий: {sessions}",
            "start_locked": _start_locked(),
            "unlock_sessions_remaining": _cafe_unlock_sessions_remaining,
        }

    if cmd == "status":
        hash_path = ROOT_DIR / ".update_hash"
        version = "unknown"
        if hash_path.exists():
            raw_version = hash_path.read_text(encoding="utf-8").strip()
            try:
                version_state = json.loads(raw_version)
            except ValueError:
                version_state = None
            if isinstance(version_state, dict):
                version = str(version_state.get("full") or "unknown")
            elif raw_version:
                version = raw_version
        connected = bool(camera and camera.is_connected)
        event = yadisk_cloud.current_event_folder() or str(CONFIG.get("yadisk_folder", ""))
        viewer_urls = await asyncio.to_thread(_viewer_urls)
        status_lines = [
            f"State: {STATE}",
            f"Camera: {'online' if connected else 'offline'}",
            f"Start locked: {'yes' if _start_locked() else 'no'}",
            f"Unlock sessions remaining: {_cafe_unlock_sessions_remaining}",
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
        if viewer_urls:
            status_lines.extend(f"Viewer: {url}" for url in viewer_urls)
        else:
            status_lines.append("Viewer: LAN IP unavailable")
        return {
            "status": "ok",
            "message": "\n".join(status_lines),
            "event_folder": event,
            "start_locked": _start_locked(),
            "unlock_sessions_remaining": _cafe_unlock_sessions_remaining,
            "viewer_urls": viewer_urls,
        }

    if cmd == "set_event":
        name = data.get("name", "") if isinstance(data, dict) else ""
        if STATE not in ("idle", "no_camera", "camera_searching"):
            return {"status": "error", "message": f"Event не изменён: state={STATE}"}
        if _background_uploads:
            return {"status": "error", "message": "Event не изменён: завершается текущая загрузка"}
        if name == _technical_event_name():
            try:
                _set_cafe_unlock_sessions(0)
            except (OSError, ValueError) as exc:
                return {
                    "status": "error",
                    "message": f"Event не изменён: Кафе не заблокировано: {exc}",
                }
        try:
            await yadisk_cloud.set_event_folder(name)
            _save_event_folder(name)
        except Exception as exc:
            return {"status": "error", "message": f"Event не изменён: {exc}"}
        if STATE == "idle":
            await broadcast(_state_message(STATE))
        return {
            "status": "ok",
            "message": f"Event активирован на будке: {name}",
            "event_folder": name,
            "start_locked": _start_locked(),
            "unlock_sessions_remaining": _cafe_unlock_sessions_remaining,
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
    client_host = ws.client.host if ws.client else None
    can_control = _is_loopback_host(client_host)
    await ws.accept()
    if ws not in CLIENTS:
        CLIENTS.append(ws)
    initial_state = _state_message(STATE)
    await ws.send_text(json.dumps(initial_state))

    # Show update log on first client connect
    update_log = getattr(app.state, "update_log_path", None)
    if update_log and os.path.exists(update_log):
        content = Path(update_log).read_text(
            encoding="utf-8", errors="replace")
        for line in content.strip().splitlines():
            log.info(f"[update] {line}")
        app.state.update_log_path = None

    try:
        while True:
            data = await ws.receive_text()
            if not can_control:
                continue
            msg = json.loads(data)

            if msg["type"] == "start_session" and STATE == "idle":
                if _start_locked():
                    await ws.send_text(json.dumps(_state_message(STATE)))
                elif camera and camera.is_connected:
                    asyncio.create_task(run_session())
                else:
                    await set_state("camera_searching" if camera else "no_camera")

            elif msg["type"] == "select_template" and STATE == "template_select":
                cb = getattr(app.state, "on_template_choice", None)
                if cb:
                    cb(
                        msg.get("template", ""),
                        msg.get("photo_index"),
                        msg.get("with_frame"),
                    )

            elif msg["type"] == "skip_print" and STATE == "template_select":
                cb = getattr(app.state, "on_skip_print", None)
                if cb:
                    cb()

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
