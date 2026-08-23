"""Photobooth backend - FastAPI + WebSocket.

State machine:
  IDLE -> COUNTDOWN -> CAPTURE -> (repeat num_photos times) -> PROCESSING
  -> TEMPLATE_SELECT -> (COMPOSING -> DONE -> IDLE | IDLE when printing is skipped)
"""

import asyncio
import functools
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse

from .config import (
    ASSETS_DIR,
    EDSDK_DLL,
    FRONTEND_DIR,
    PHOTOS_DIR,
    PRINT_JOBS_DIR,
    ROOT_DIR,
    TEMPLATES_DIR,
    apply_camera_preset,
    camera_exposure_options,
    lens_max_aperture_hint,
    load_event_config,
    preset_names,
    update_app_config_field,
    update_camera_config_field,
    update_template_pack,
)
from .composer import (
    DEFAULT_PRINT_SIZE,
    compose,
    compose_unframed_photo,
    generate_template_previews,
    template_photo_count,
)
from .text_layer import date_values
from .log import read_log_snapshot
from .video import VideoRecorder
from . import system_service, yadisk_cloud, yadisk_control

log = logging.getLogger(__name__)

app = FastAPI()


class FrontendStaticFiles(StaticFiles):
    """Serve the frontend without letting WebView retain an old release."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store"
        return response


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
EVENT_HISTORY_FILENAME = "event_history.json"
EVENT_HISTORY_ARCHIVE_DIRNAME = "event_history_archive"
EVENT_HISTORY_SCHEMA_VERSION = 1
STATUS_REPORT_INTERVAL_SECONDS = 30 * 60
MAX_UNLOCK_SESSIONS = 1000
DEFAULT_MULTI_PRINT_MAX_SHEETS = 6
MAX_MULTI_PRINT_SHEETS = 20

_event_history_ready = False


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


def _event_history_path() -> Path:
    return ROOT_DIR / EVENT_HISTORY_FILENAME


def _event_history_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _new_event_history(event: str) -> dict:
    return {
        "schema_version": EVENT_HISTORY_SCHEMA_VERSION,
        "event": event,
        "entries": [],
    }


def _parse_event_history(raw: str | bytes) -> dict:
    payload = json.loads(raw)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != EVENT_HISTORY_SCHEMA_VERSION
        or not isinstance(payload.get("event"), str)
        or not isinstance(payload.get("entries"), list)
    ):
        raise ValueError("unsupported event history format")
    return payload


def _load_event_history(path: Path) -> dict:
    return _parse_event_history(path.read_bytes())


def _write_event_history(payload: dict) -> None:
    path = _event_history_path()
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _archive_event_history(*, invalid: bool = False) -> Path:
    archive_dir = ROOT_DIR / EVENT_HISTORY_ARCHIVE_DIRNAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    suffix = "_invalid" if invalid else ""
    destination = archive_dir / f"{stamp}{suffix}.json"
    _event_history_path().replace(destination)
    return destination


def _append_event_history_entry(payload: dict, entry: dict, at: str) -> None:
    payload["entries"].append({"at": at, **entry})


def _event_history_summary(payload: dict) -> str:
    """Summarize sessions and physical print sheets from one event journal."""
    sessions = 0
    retakes = 0
    multiple_copy_sessions = 0
    total_prints = 0
    grid_prints = 0
    strips_prints = 0
    custom_prints = 0

    entries = payload.get("entries") if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "custom_print_job":
            if entry.get("result") == "print_queued":
                total_prints += 1
                custom_prints += 1
            continue
        if entry.get("type") != "photo_session":
            continue

        sessions += 1
        if entry.get("result") == "retake":
            retakes += 1
        if entry.get("result") != "print_queued":
            continue

        items = entry.get("items")
        if not isinstance(items, dict):
            continue
        session_prints = sum(
            copies for copies in items.values()
            if type(copies) is int and copies > 0
        )
        total_prints += session_prints
        grid = items.get("grid")
        strips = items.get("strips")
        if type(grid) is int and grid > 0:
            grid_prints += grid
        if type(strips) is int and strips > 0:
            strips_prints += strips
        if session_prints > 1:
            multiple_copy_sessions += 1

    event = str(payload.get("event") or "не задан")
    single_prints = (
        total_prints - grid_prints - strips_prints - custom_prints)
    return "\n".join((
        f"📊 ИТОГ ИВЕНТА: {event}",
        f"• Сессии: {sessions} · ретейки: {retakes} · "
        f"с несколькими копиями: {multiple_copy_sessions}",
        f"• Отпечатки: {total_prints} · Grid: {grid_prints} · "
        f"Strips: {strips_prints} · Single: {single_prints} · "
        f"Print jobs: {custom_prints}",
    ))


def _event_history_attachment(path: Path) -> dict[str, str]:
    """Build one document and its matching summary from the same file."""
    text = path.read_text(encoding="utf-8")
    history = _parse_event_history(text)
    return {
        "document": yadisk_control.response_document(text.encode("utf-8")),
        "document_caption": _event_history_summary(history),
    }


def _start_event_history() -> None:
    """Open the current event journal and record this application start."""
    global _event_history_ready
    _event_history_ready = False
    event = _active_event_name()
    path = _event_history_path()
    now = _event_history_now()
    try:
        try:
            payload = _load_event_history(path)
        except FileNotFoundError:
            payload = _new_event_history(event)
        except (OSError, ValueError) as exc:
            archived = _archive_event_history(invalid=True)
            log.warning(
                "Invalid event history archived as %s: %s", archived, exc)
            payload = _new_event_history(event)
        else:
            previous_event = payload["event"]
            if previous_event != event:
                _append_event_history_entry(payload, {
                    "type": "event_ended",
                    "next_event": event,
                    "reason": "event_changed_before_application_start",
                }, now)
                _write_event_history(payload)
                archived = _archive_event_history()
                log.info(
                    "Event history archived for %r: %s",
                    previous_event,
                    archived,
                )
                payload = _new_event_history(event)
                _append_event_history_entry(payload, {
                    "type": "event_started",
                    "previous_event": previous_event,
                    "source": {"actor": "system"},
                }, now)

        _append_event_history_entry(
            payload,
            {"type": "application_started"},
            _event_history_now(),
        )
        _write_event_history(payload)
        _event_history_ready = True
    except (OSError, ValueError):
        log.exception("Could not start event history")


def _record_event_history(entry: dict) -> None:
    """Append one fact without letting journal I/O interrupt the booth."""
    if not _event_history_ready:
        return
    try:
        path = _event_history_path()
        try:
            payload = _load_event_history(path)
        except FileNotFoundError:
            payload = _new_event_history(_active_event_name())
        except (OSError, ValueError) as exc:
            archived = _archive_event_history(invalid=True)
            log.warning(
                "Invalid event history archived as %s: %s", archived, exc)
            payload = _new_event_history(_active_event_name())
        _append_event_history_entry(payload, entry, _event_history_now())
        _write_event_history(payload)
    except (OSError, ValueError):
        log.exception("Could not append event history entry: %s", entry.get("type"))


def _switch_event_history(new_event: str, source: dict) -> Path | None:
    """Archive the old event intact and create the next event journal."""
    if not _event_history_ready:
        return None
    try:
        archived = None
        previous_event = None
        now = _event_history_now()
        try:
            payload = _load_event_history(_event_history_path())
        except FileNotFoundError:
            log.warning(
                "Previous event history was missing; started journal for %r",
                new_event,
            )
        except ValueError as exc:
            invalid_archive = _archive_event_history(invalid=True)
            log.warning(
                "Invalid event history archived as %s before switching to "
                "%r: %s",
                invalid_archive,
                new_event,
                exc,
            )
        else:
            previous_event = payload["event"]
            if previous_event == new_event:
                return None
            _append_event_history_entry(payload, {
                "type": "event_ended",
                "next_event": new_event,
                "source": source,
            }, now)
            _write_event_history(payload)
            archived = _archive_event_history()

        payload = _new_event_history(new_event)
        event_started = {
            "type": "event_started",
            "source": source,
        }
        if previous_event is not None:
            event_started["previous_event"] = previous_event
        _append_event_history_entry(payload, event_started, now)
        _write_event_history(payload)
        if archived is not None:
            log.info(
                "Event history archived for %r: %s",
                previous_event,
                archived,
            )
        return archived
    except (OSError, ValueError):
        log.exception("Could not switch event history to %r", new_event)
        return None


def _command_history_source(command: dict, actor: str = "administrator") -> dict:
    source = {
        "actor": actor,
        "command": command.get("command"),
        "command_id": command.get("command_id"),
    }
    reply_target = command.get("reply_target")
    if isinstance(reply_target, dict) and reply_target.get("provider"):
        source["provider"] = reply_target["provider"]
    return source


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


def _multi_print_max_sheets() -> int:
    """Clamp the basket limit so a misedited config cannot waste a whole roll."""
    raw = CONFIG.get("multi_print_max_sheets", DEFAULT_MULTI_PRINT_MAX_SHEETS)
    if type(raw) is not int or not 1 <= raw <= MAX_MULTI_PRINT_SHEETS:
        log.warning(
            "multi_print_max_sheets=%r is unusable; falling back to %d",
            raw, DEFAULT_MULTI_PRINT_MAX_SHEETS,
        )
        return DEFAULT_MULTI_PRINT_MAX_SHEETS
    return raw


def _multi_print_available() -> bool:
    """Return the global multi-select switch for every event mode."""
    return CONFIG.get("multi_print_enabled") is True

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

def _format_camera_config_report(report: dict) -> list[str]:
    """Render a camera config report as short Telegram/VK friendly lines."""
    if not isinstance(report, dict):
        return []
    lines: list[str] = []
    camera_entries = report.get("camera") or []
    if camera_entries:
        exposure_order = {"av": 0, "tv": 1, "iso": 2}
        exposure_entries = sorted(
            (entry for entry in camera_entries
             if entry.get("field") in exposure_order),
            key=lambda entry: exposure_order[entry.get("field")],
        )
        other_entries = [
            entry for entry in camera_entries
            if entry.get("field") not in exposure_order
        ]

        def append_entries(entries: list[dict]) -> None:
            applied: list[str] = []

            def flush_applied() -> None:
                if applied:
                    lines.append("✓ " + " · ".join(applied))
                    applied.clear()

            for entry in entries:
                label = entry.get("label")
                actual = entry.get("actual", "unavailable")
                if entry.get("available") and entry.get("verifiable") \
                        and entry.get("matches"):
                    applied.append(f"{label}={actual}")
                    if len(applied) == 3:
                        flush_applied()
                    continue

                flush_applied()
                if not entry.get("available"):
                    lines.append(f"? {label}=unavailable")
                elif not entry.get("verifiable"):
                    lines.append(f"• {label}={actual}")
                else:
                    requested = entry.get("requested")
                    lines.append(
                        f"❌ {label} не применилось: "
                        f"запрошено {requested} · фактически {actual}"
                    )
                    offered = entry.get("offered")
                    if offered:
                        lines.append(
                            f"↳ SetProp {label}: камера разрешает сейчас — "
                            + " · ".join(str(value) for value in offered)
                        )
            flush_applied()

        append_entries(exposure_entries)
        append_entries(other_entries)
    host_entries = report.get("host") or []
    if host_entries:
        host_values = [
            f"{entry.get('label')}={entry.get('value')}"
            for entry in host_entries
        ]
        for index in range(0, len(host_values), 3):
            lines.append(
                "• Приложение: "
                + " · ".join(host_values[index:index + 3]))
    return lines


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
        msg["multi_print"] = _multi_print_available()
        msg["multi_print_max_sheets"] = _multi_print_max_sheets()
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
            await _report_status_to_admin()

        asyncio.run_coroutine_threadsafe(show_ready(), _event_loop)


async def _report_status_to_admin(title: str = "Фотобудка готова") -> None:
    """Push the full booth status to the administrator.

    Runs on every successful camera setup, both at launch and after a USB
    reconnect.  The same report is returned by ``/status``.
    """
    try:
        text = await _status_report_text()
        attachment = {}
        try:
            attachment = await asyncio.to_thread(
                _event_history_attachment, _event_history_path())
        except (OSError, ValueError) as exc:
            log.warning("Event history not attached to booth status: %s", exc)
        await yadisk_control.publish_booth_notice(
            "booth_status", title, text, **attachment)
    except Exception as exc:
        # The booth must stay usable even when the notice cannot be delivered.
        log.warning("Could not publish booth status: %s", exc)
        return
    log.info("Booth status published for the administrator")


async def _periodic_status_service() -> None:
    while True:
        await asyncio.sleep(STATUS_REPORT_INTERVAL_SECONDS)
        await _report_status_to_admin("Статус фотобудки")


def _normalize_print_item(
    raw: dict,
    selectable_templates: set[str],
    available_templates: dict,
    photo_count: int,
) -> dict | None:
    """Validate one basket entry and return it normalized, or ``None``.

    Every rejection is logged and rejects the entry outright: a silently
    repaired entry would print a sheet the guest never asked for.
    """
    if not isinstance(raw, dict):
        log.warning("Ignoring malformed print item: %r", raw)
        return None
    name = raw.get("template")
    if not isinstance(name, str) or name not in selectable_templates:
        log.warning("Ignoring unknown template: %r", name)
        return None
    photo_index = raw.get("photo_index")
    with_frame = raw.get("with_frame")
    if available_templates[name].get("photo_choice") is True:
        if type(photo_index) is not int or not 0 <= photo_index < photo_count:
            log.warning(
                "Ignoring invalid photo index for %s: %r", name, photo_index)
            return None
        if type(with_frame) is not bool:
            log.warning(
                "Ignoring invalid frame choice for %s: %r", name, with_frame)
            return None
    else:
        photo_index = None
        with_frame = True
    copies = raw.get("copies", 1)
    if type(copies) is not int or copies < 1:
        log.warning("Ignoring invalid copies for %s: %r", name, copies)
        return None
    return {
        "template": name,
        "photo_index": photo_index,
        "with_frame": with_frame,
        "copies": copies,
    }


def _merge_print_items(items: list[dict]) -> list[dict]:
    """Collapse identical entries so one layout is composed exactly once."""
    merged: dict[tuple, dict] = {}
    for item in items:
        key = (item["template"], item["photo_index"], item["with_frame"])
        if key in merged:
            merged[key]["copies"] += item["copies"]
        else:
            merged[key] = dict(item)
    return list(merged.values())


def _print_item_label(item: dict) -> str:
    label = item["template"]
    if item["photo_index"] is not None:
        frame = "с рамкой" if item["with_frame"] else "без рамки"
        label += f"[фото {item['photo_index'] + 1}, {frame}]"
    if item["copies"] > 1:
        label += f" x{item['copies']}"
    return label


def _history_print_items(items: list[dict]) -> dict[str, int]:
    """Compact a basket into printable choice names and copy counts."""
    result: dict[str, int] = {}
    for item in items:
        name = item["template"]
        if item["photo_index"] is not None:
            frame = "frame" if item["with_frame"] else "no_frame"
            name = f"{name}_{frame}_{item['photo_index'] + 1}"
        result[name] = result.get(name, 0) + item["copies"]
    return result


def _countdown_timing() -> tuple[float, int, int]:
    pre_countdown_delay = max(0.0, float(CONFIG["pre_countdown_delay"]))
    countdown_seconds = max(0, int(CONFIG["countdown_seconds"]))
    countdown_sound_seconds = int(CONFIG["countdown_sound_seconds"])
    countdown_sound_seconds = max(0, min(countdown_sound_seconds, countdown_seconds))
    return pre_countdown_delay, countdown_seconds, countdown_sound_seconds


async def _finish_successful_session(
    sheets: list[tuple[Path, str]],
    camera_generation: int,
    session_uses_cafe_unlock: bool,
    history_entry: dict | None = None,
    test_session: bool = False,
) -> None:
    """Queue every composed sheet, charge the allowance, then expose done.

    ``sheets`` is already expanded: one entry per physical 4x6 sheet, so two
    copies of the same layout appear twice and reuse one composed JPEG.
    """
    print_enabled = CONFIG["print_enabled"] and not test_session
    if print_enabled:
        from .printer import enqueue_print
        for sheet_path, sheet_template in sheets:
            await enqueue_print(str(sheet_path), CONFIG, sheet_template)
        _require_session_camera(camera_generation)

    if history_entry is not None:
        _record_event_history({
            **history_entry,
            "result": (
                "print_queued"
                if print_enabled
                else "completed_without_print"
            ),
        })

    if session_uses_cafe_unlock:
        _consume_cafe_unlock_session()

    await set_state("done", {"print_sheets": len(sheets)})


# --- Session flow ---
async def run_session(test_session: bool = False):
    global _session_running, TEMPLATE_OPTIONS
    if _session_running:
        log.warning("Duplicate session start ignored")
        return
    if not test_session and _start_locked():
        log.warning(
            "Session start blocked for technical event %r: no unlock sessions remain",
            _technical_event_name(),
        )
        await broadcast(_state_message(STATE))
        return
    previous_session_id = SESSION_ID
    _session_running = True
    try:
        await _run_session(test_session=test_session)
    except CameraSessionAborted as exc:
        log.warning("Session aborted: %s", exc)
        if (not test_session
                and SESSION_ID and SESSION_ID != previous_session_id):
            _record_event_history({
                "type": "photo_session",
                "session_id": SESSION_ID,
                "result": "aborted",
                "reason": str(exc),
            })
        _clear_live_view()
        SESSION_PHOTOS.clear()
        video_recorder.abort()
        await set_state(
            "idle" if camera and camera.is_connected else "camera_searching")
    except Exception as exc:
        log.exception("Session error")
        if (not test_session
                and SESSION_ID and SESSION_ID != previous_session_id):
            _record_event_history({
                "type": "photo_session",
                "session_id": SESSION_ID,
                "result": "failed",
                "reason": str(exc),
            })
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
        app.state.on_template_activity = None
        TEMPLATE_OPTIONS = []
        if SESSION_ID:
            try:
                _remove_preview_dir(PHOTOS_DIR / SESSION_ID / "previews")
            except OSError:
                log.exception("Could not remove session template previews")
        if (camera and camera.is_connected
                and STATE in ("no_camera", "camera_searching")):
            await set_state("idle")


async def _run_session(test_session: bool = False):
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
    template_dir = TEMPLATES_DIR / CONFIG["template_pack"]
    tpl_config = json.loads((template_dir / "config.json").read_text(encoding="utf-8"))
    available_templates = tpl_config.get("templates", {})
    if not isinstance(available_templates, dict) or not available_templates:
        raise ValueError(f"No templates configured in {template_dir}")
    tpl_print_size = tuple(tpl_config.get("print_size", DEFAULT_PRINT_SIZE))
    for template_name, template in available_templates.items():
        required_photos = template_photo_count(
            template, template_name, tpl_print_size)
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
    # Local booth date, resolved once per session: a session started at 23:59
    # must not print tomorrow's date, and preview and print must agree.
    text_values = date_values(session_created_at.astimezone())
    event_folder = (
        yadisk_cloud.current_event_folder()
        or str(CONFIG.get("yadisk_folder") or "").strip().strip("/")
    )
    session_uses_cafe_unlock = (
        not test_session and event_folder == _technical_event_name())
    session_folder = yadisk_cloud.session_folder_name(
        SESSION_ID, session_created_at)
    SESSION_PHOTOS = []
    session_dir = PHOTOS_DIR / SESSION_ID
    session_dir.mkdir(exist_ok=True)
    log.info(f"=== Session {SESSION_ID} started ===")

    pre_countdown_delay, countdown_seconds, countdown_sound_seconds = _countdown_timing()
    if test_session:
        countdown_seconds = 2
        countdown_sound_seconds = min(countdown_sound_seconds, countdown_seconds)

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
        if not test_session:
            _record_event_history({
                "type": "photo_session",
                "session_id": SESSION_ID,
                "result": "failed",
                "reason": "photo_download_timeout",
            })
        await broadcast({"type": "error", "message": "Photo download error. Try again."})
        await asyncio.sleep(3)
        await set_state("idle")
        return

    photos_copy = SESSION_PHOTOS[:]
    if test_session:
        video_recorder.abort()
    else:
        # Start video encoding in background (all frames + photos ready)
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
        functools.partial(
            generate_template_previews,
            template_dir,
            photos_copy,
            tpl_config,
            preview_dir,
            text_values=text_values,
        ),
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
                # Full-size original for the magnifier. Previews are 720 px
                # wide, so only this file has detail worth zooming into.
                "original_url": (
                    f"/photos/{SESSION_ID}/"
                    f"{Path(SESSION_PHOTOS[choice.photo_index]).name}"
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
    # One source of truth for the frame default: the frontend reads the same
    # config field through /api/config.
    default_with_frame = CONFIG["photo_choice_default_with_frame"] is True
    multi_print_allowed = _multi_print_available()
    max_sheets = _multi_print_max_sheets()
    # A single tap is the one-item case of the same basket, so there is only one
    # code path from here to the printer.
    chosen = {
        "items": [{
            "template": selected_template,
            "photo_index": (
                0 if available_templates[selected_template].get("photo_choice") is True
                else None
            ),
            "with_frame": default_with_frame,
            "copies": 1,
        }],
        "skip_print": False,
        "selection": "timeout",
    }

    def on_template_choice(t, photo_index=None, with_frame=None, items=None):
        if template_event.is_set():
            return
        if items is None:
            raw_items = [{
                "template": t,
                "photo_index": photo_index,
                "with_frame": with_frame,
                "copies": 1,
            }]
        elif not isinstance(items, list) or not items:
            log.warning("Ignoring empty or malformed print basket: %r", items)
            return
        elif not multi_print_allowed:
            log.warning(
                "Ignoring print basket: multi-select is disabled"
            )
            return
        else:
            raw_items = items

        normalized = []
        for raw in raw_items:
            item = _normalize_print_item(
                raw, selectable_templates, available_templates,
                len(SESSION_PHOTOS),
            )
            # One bad entry rejects the whole basket: printing a partial
            # selection would charge the guest for sheets they did not confirm.
            if item is None:
                return
            normalized.append(item)

        normalized = _merge_print_items(normalized)
        sheets = sum(item["copies"] for item in normalized)
        limit = max_sheets if items is not None else 1
        if sheets > limit:
            log.warning(
                "Ignoring print basket of %d sheets: limit is %d",
                sheets, limit,
            )
            return

        log.info(
            "Print basket chosen: %d sheet(s): %s",
            sheets,
            ", ".join(_print_item_label(item) for item in normalized),
        )
        chosen["items"] = normalized
        chosen["selection"] = "guest"
        template_event.set()

    def on_skip_print():
        if template_event.is_set():
            return
        log.info("Print skipped by visitor")
        chosen["skip_print"] = True
        chosen["selection"] = "guest"
        template_event.set()

    # Any touch on the template screen restarts the full timeout, so a visitor
    # who is still choosing never loses the session to the default template.
    select_timeout = float(CONFIG["template_select_timeout"])
    loop = asyncio.get_running_loop()
    deadline = {"at": loop.time() + select_timeout}
    extend_event = asyncio.Event()

    def on_template_activity():
        # A touch that arrives after the choice is already locked in must not
        # move the deadline or report a restarted countdown.
        if template_event.is_set():
            return False
        deadline["at"] = loop.time() + select_timeout
        extend_event.set()
        return True

    app.state.on_template_choice = on_template_choice
    app.state.on_skip_print = on_skip_print
    app.state.on_template_activity = on_template_activity
    await set_state("template_select")
    log.info("Waiting for template choice...")
    choice_task = asyncio.create_task(template_event.wait())
    disconnect_task = asyncio.create_task(_camera_disconnected_event.wait())
    extend_task = asyncio.create_task(extend_event.wait())
    try:
        while True:
            remaining = deadline["at"] - loop.time()
            if remaining <= 0:
                log.info(f"Template timeout, using default: {selected_template}")
                break
            done, _ = await asyncio.wait(
                (choice_task, disconnect_task, extend_task),
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            _require_session_camera(camera_generation)
            if choice_task in done or disconnect_task in done:
                break
            if extend_task in done:
                extend_event.clear()
                extend_task = asyncio.create_task(extend_event.wait())
                log.info("Template selection extended by visitor touch")
                continue
            log.info(f"Template timeout, using default: {selected_template}")
            break
    finally:
        app.state.on_template_activity = None
        for task in (choice_task, disconnect_task, extend_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(
            choice_task, disconnect_task, extend_task, return_exceptions=True)
    template_event.set()
    if chosen["skip_print"]:
        if not test_session:
            _record_event_history({
                "type": "photo_session",
                "session_id": SESSION_ID,
                "result": "retake",
            })
        TEMPLATE_OPTIONS = []
        await set_state("idle")
        return

    selected_items = chosen["items"]
    total_sheets = sum(item["copies"] for item in selected_items)
    log.info(
        "Selected %d sheet(s): %s",
        total_sheets,
        ", ".join(_print_item_label(item) for item in selected_items),
    )

    # Compose the local print files. They never enter the cloud outbox.
    await set_state("composing", {"print_sheets": total_sheets})
    TEMPLATE_OPTIONS = []
    try:
        _remove_preview_dir(preview_dir)
    except OSError:
        log.exception("Could not remove session template previews: %s", preview_dir)
    log.info(f"SESSION_PHOTOS: {SESSION_PHOTOS}")
    composed: list[tuple[Path, str]] = []
    if SESSION_PHOTOS:
        def _compose_item(item: dict) -> Path:
            name = item["template"]
            photo_index = item["photo_index"]
            with_frame = item["with_frame"]
            log.info(f"Composing {name}...")
            template = available_templates[name]
            if template.get("photo_choice") is True:
                photo = SESSION_PHOTOS[photo_index]
                if with_frame:
                    result = compose(
                        template_dir, name, [photo], tpl_config,
                        text_values=text_values)
                    frame_label = "frame"
                else:
                    result = compose_unframed_photo(photo, tpl_config)
                    frame_label = "no_frame"
                path = session_dir / (
                    f"print_{name}_photo_"
                    f"{photo_index + 1:02d}_{frame_label}.jpg"
                )
            else:
                result = compose(
                    template_dir, name, SESSION_PHOTOS, tpl_config,
                    text_values=text_values)
                path = session_dir / f"print_{name}.jpg"
            try:
                dpi = int(CONFIG.get("print_dpi", 600))
                result.save(str(path), "JPEG", quality=95, subsampling=0, dpi=(dpi, dpi))
            finally:
                result.close()
            return path

        for item in selected_items:
            # Identical entries were merged, so each layout is composed once
            # and its single JPEG is queued as many times as requested.
            item_path = await loop.run_in_executor(None, _compose_item, item)
            _require_session_camera(camera_generation)
            log.info(f"Composed: {item_path}")
            composed.extend(
                [(item_path, item["template"])] * item["copies"])
    else:
        log.warning("No photos to compose!")

    _require_session_camera(camera_generation)
    if not composed:
        raise RuntimeError("Session composition produced no print file")

    # Any compose/print-enqueue error happens before the durable allowance is
    # consumed, so a failed visitor session can be retried.
    history_entry = {
        "type": "photo_session",
        "session_id": SESSION_ID,
        "items": _history_print_items(selected_items),
    }
    if chosen["selection"] == "timeout":
        history_entry["selection"] = "timeout"
    await _finish_successful_session(
        composed,
        camera_generation,
        session_uses_cafe_unlock,
        None if test_session else history_entry,
        test_session=test_session,
    )

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
                b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n"
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
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/api/config")
async def get_config():
    response = dict(CONFIG)
    poses_dir = ASSETS_DIR / "poses"
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


@app.post("/api/system/action")
def handle_system_action(payload: dict):
    action = payload.get("action", "")
    return system_service.launch_system_action(action)


@app.get("/api/network/status")
def get_network_status():
    return system_service.list_network_adapters()


@app.post("/api/network/set")
def set_network(payload: dict):
    return system_service.set_adapter(
        payload.get("name", ""),
        payload.get("enabled"),
    )


async def _do_restart():
    _record_event_history({
        "type": "application_restart_requested",
    })
    log.info("Restart requested!")
    await _shutdown_services()
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
    lines = []
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
            lines.append(f"⚠️ {target} · {printer_name}: {error}")
            continue
        jobs = record.get("jobs")
        if type(jobs) is not int or jobs < 0:
            has_error = True
            lines.append(
                f"⚠️ {target} · {printer_name}: число заданий неизвестно"
            )
        else:
            lines.append(
                f"• {target} · {printer_name} — в очереди: {jobs}"
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


def _printer_info_message(info: dict) -> str:
    lines = [
        f"• DNP · {info['printer_name']}: {info['status']}",
    ]
    remaining = info.get("media_remaining")
    capacity = info.get("media_capacity")
    if remaining is None:
        media = "остаток не удалось прочитать"
    elif capacity is None:
        media = f"остаток {remaining}"
    else:
        media = f"остаток {remaining}/{capacity}"
    lines.append(
        f"• Отпечатков: всего {info['total_count']} · {media}"
    )
    return "\n".join(lines)


def _printer_status_lines() -> list[str]:
    """Read the DNP hardware state and both Windows print queues."""
    from .printer import get_dnp_printer_info, get_windows_print_queues

    lines: list[str] = []
    try:
        lines.extend(_printer_info_message(
            get_dnp_printer_info(CONFIG)).splitlines())
    except Exception as exc:
        lines.append(f"⚠️ DNP: {exc}")

    try:
        records = get_windows_print_queues(CONFIG)
        message, _has_error = _print_queue_status_message(records)
        lines.extend(message.splitlines())
    except Exception as exc:
        lines.append(f"⚠️ Windows-очереди: {exc}")
    return lines


async def _status_report_text() -> str:
    """Build the single status report used by startup notices and /status."""
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

    event = _active_event_name() or "не задан"
    technical_event = event == _technical_event_name()
    start_locked = _start_locked()
    event_lines = [
        "🎪 СОБЫТИЕ",
        f"• Будка: {event}",
    ]
    template_lines = [
        f"🖼 ШАБЛОН: {CONFIG.get('template_pack', 'unknown')}",
    ]
    session_lines = [
        "🎟 СЕССИИ",
        f"• Технический ивент: {'да' if technical_event else 'нет'}",
    ]
    if technical_event:
        session_lines.append(
            f"• Допуск: {'🔴 закрыт' if start_locked else '🟢 открыт'} · "
            f"сессий осталось: {_cafe_unlock_sessions_remaining}"
        )
    else:
        session_lines.append("• Допуск: ♾ без ограничений")

    connected = bool(camera and camera.is_connected)
    camera_lines = [
        f"📷 КАМЕРА: {'🟢 подключена' if connected else '🔴 не подключена'}",
    ]
    blocks = [event_lines, template_lines, session_lines, camera_lines]
    disk_free = None
    snapshot_method = getattr(camera, "status_snapshot", None) if camera else None
    if snapshot_method:
        snapshot = snapshot_method()
        identity = snapshot.get("product_name") or snapshot.get("model")
        if identity:
            camera_lines.append(f"• Модель: {identity}")
        lens_info = []
        if snapshot.get("lens"):
            lens_info.append(f"Объектив: {snapshot['lens']}")
        focal_length = snapshot.get("focal_length_mm")
        if type(focal_length) is int and focal_length > 0:
            lens_info.append(f"Фокусное: {focal_length} мм")
        if lens_info:
            camera_lines.append("• " + " · ".join(lens_info))
        health = []
        for label, key in (
            ("Питание", "battery"),
            ("Температура", "temperature"),
            ("AE", "ae_mode"),
            ("Auto-off", "auto_power_off"),
        ):
            if snapshot.get(key) is not None:
                health.append(f"{label}: {snapshot[key]}")
        if health:
            camera_lines.append("• " + " · ".join(health))
        disk_free = snapshot.get("disk_free_bytes")
        if snapshot.get("last_shutdown_timer_extension_result"):
            camera_lines.append(
                "• Продление таймера камеры: "
                f"{snapshot['last_shutdown_timer_extension_result']} at "
                f"{snapshot.get('last_shutdown_timer_extension_at') or 'unknown'}")
        if snapshot.get("last_disconnect_reason"):
            camera_lines.append(
                "⚠️ Последнее отключение: "
                f"{snapshot['last_disconnect_reason']} at "
                f"{snapshot.get('last_disconnect_at') or 'unknown'}")
        if snapshot.get("last_cleanup_result"):
            camera_lines.append(
                "• Последняя очистка: "
                f"{snapshot['last_cleanup_result']} at "
                f"{snapshot.get('last_cleanup_at') or 'unknown'}")
        config_report = snapshot.get("config_report")
        config_lines = _format_camera_config_report(config_report)
        if config_lines:
            config_ok = (
                isinstance(config_report, dict)
                and bool(config_report.get("camera"))
                and not config_report.get("mismatched")
                and not config_report.get("unavailable")
            )
            config_title = f"⚙️ КОНФИГ КАМЕРЫ: {'✅' if config_ok else '❌'}"
            report_at = snapshot.get("config_report_at")
            if report_at:
                try:
                    checked_at = datetime.fromisoformat(
                        str(report_at)).astimezone().strftime("%d.%m.%Y %H:%M")
                except ValueError:
                    checked_at = str(report_at)
                config_title += f" · {checked_at}"
            config_block = [config_title]
            config_block.extend(config_lines)
            blocks.append(config_block)
    print_enabled = CONFIG.get("print_enabled") is True
    blocks.append([
        f"🖨 ПРИНТЕР: {'🟢 печать включена' if print_enabled else '🔴 печать выключена'}",
        *await asyncio.to_thread(_printer_status_lines),
    ])
    pending_sessions = yadisk_cloud.pending_count()
    system_lines = [
        f"☁️ СИСТЕМА: {STATE}",
        (
            f"⚠️ Яндекс.Диск: незавершённых сессий — {pending_sessions}"
            if pending_sessions
            else "• Яндекс.Диск: ✅ всё отправлено"
        ),
    ]
    if isinstance(disk_free, int):
        system_lines.append(
            f"• Диск фото: {disk_free / (1024 ** 3):.2f} GiB свободно")
    system_lines.append(
        f"• Версия: {version[:12] if version != 'unknown' else version}")
    blocks.append(system_lines)

    control_lines = ["🎛 УПРАВЛЕНИЕ"]
    try:
        presets = preset_names()
    except (OSError, ValueError, json.JSONDecodeError):
        presets = []
    if presets:
        control_lines.append(
            "• /light <имя>: "
            + json.dumps(presets, ensure_ascii=False))
    try:
        aperture_hint = lens_max_aperture_hint()
    except (OSError, ValueError, json.JSONDecodeError):
        aperture_hint = ""
    if aperture_hint:
        control_lines.append(f"• {aperture_hint}")
    try:
        exposure_options = camera_exposure_options()
    except (OSError, ValueError, json.JSONDecodeError):
        exposure_options = {}
    for field, values in exposure_options.items():
        control_lines.append(
            f"• /{field}: " + json.dumps(values, ensure_ascii=False))
    if len(control_lines) > 1:
        blocks.append(control_lines)
    return "\n\n".join("\n".join(block) for block in blocks)


def _clear_runtime_directory(path: Path) -> tuple[int, int]:
    """Delete only the contents of one fixed application runtime directory."""
    path.mkdir(parents=True, exist_ok=True)
    file_count = 0
    directory_count = 0
    for _root, directories, files in os.walk(path, followlinks=False):
        file_count += len(files)
        directory_count += len(directories)
    for child in path.iterdir():
        if child.is_symlink() or not child.is_dir():
            child.unlink(missing_ok=True)
        else:
            shutil.rmtree(child)
    return file_count, directory_count


async def handle_disk_command(command: dict) -> dict:
    """Execute one validated Disk command and return its response payload."""
    cmd = command["command"]
    data = command.get("data")
    command_id = command["command_id"]

    if cmd in ("clear_photos", "clear_print_jobs"):
        if data is not None:
            return {
                "status": "error",
                "message": "Команда очистки файлов не принимает аргументы",
            }
        from .printer import print_queue_busy
        if _session_running:
            return {
                "status": "error",
                "message": "Очистка не выполнена: сейчас идёт фотосессия",
            }
        if print_queue_busy():
            return {
                "status": "error",
                "message": "Очистка не выполнена: внутренняя очередь печати не пуста",
            }
        if cmd == "clear_photos":
            if _background_uploads:
                return {
                    "status": "error",
                    "message": "Очистка photos не выполнена: готовятся файлы сессии",
                }
            pending_uploads = yadisk_cloud.pending_count()
            if pending_uploads:
                return {
                    "status": "error",
                    "message": (
                        "Очистка photos не выполнена: незавершённых загрузок — "
                        f"{pending_uploads}"
                    ),
                }
            target = PHOTOS_DIR
            label = "photos"
        else:
            target = PRINT_JOBS_DIR
            label = "photos_print_jobs"
        try:
            files, directories = _clear_runtime_directory(target)
        except OSError as exc:
            return {
                "status": "error",
                "message": f"Папку {label} не удалось очистить: {exc}",
            }
        return {
            "status": "ok",
            "message": (
                f"Папка {label} очищена: удалено файлов — {files}, "
                f"папок — {directories}"
            ),
        }

    if cmd == "clear_print_queue":
        if data is not None:
            return {
                "status": "error",
                "message": "Команда принтера не принимает аргументы",
            }
        try:
            from .printer import clear_windows_print_queues
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
            return {
                "status": "error",
                "message": f"Не удалось очистить очереди печати: {exc}",
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
        custom_print_entry = {
            "type": "custom_print_job",
            "job_id": job_id,
            "print_mode": print_mode,
            "source": _command_history_source(command, "messenger_user"),
        }
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
            _record_event_history({
                **custom_print_entry,
                "result": "failed",
                "stage": "preparation",
                "reason": str(exc),
            })
            return {"status": "error", "message": f"Фото не поставлено на печать: {exc}"}

        async def enqueue_custom_print_after_ack() -> None:
            from .printer import enqueue_print
            try:
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
            except Exception as exc:
                _record_event_history({
                    **custom_print_entry,
                    "result": "failed",
                    "stage": "enqueue",
                    "reason": str(exc),
                })
                raise
            _record_event_history({
                **custom_print_entry,
                "result": "print_queued",
            })

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

    if cmd == "set_app_config":
        if STATE not in ("idle", "no_camera", "camera_searching"):
            return {
                "status": "error",
                "message": f"Настройка приложения не изменена: state={STATE}",
            }
        if _background_uploads:
            return {
                "status": "error",
                "message": (
                    "Настройка приложения не изменена: "
                    "завершается подготовка загрузки"
                ),
            }
        if not isinstance(data, dict):
            return {
                "status": "error",
                "message": "Настройка приложения не изменена: нет field/value",
            }
        try:
            field, old_value, new_value, changed = update_app_config_field(
                data.get("field", ""), data.get("value"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "status": "error",
                "message": f"Настройка приложения не изменена: {exc}",
            }
        old_text = json.dumps(old_value, ensure_ascii=False)
        new_text = json.dumps(new_value, ensure_ascii=False)
        message = (
            f"Параметр приложения {field}: {old_text} → {new_text}. "
            if changed
            else f"Параметр приложения {field} уже равен {new_text}. "
        )
        if changed:
            _record_event_history({
                "type": "configuration_changed",
                "section": "application",
                "field": field,
                "old": old_value,
                "new": new_value,
                "source": _command_history_source(command),
            })
        return {
            "status": "ok",
            "message": message + "Перезапуск подтверждён",
            "_post_action": _do_restart,
        }

    if cmd == "set_template_pack":
        if STATE not in ("idle", "no_camera", "camera_searching"):
            return {
                "status": "error",
                "message": f"Template pack не изменён: state={STATE}",
            }
        if _background_uploads:
            return {
                "status": "error",
                "message": (
                    "Template pack не изменён: завершается подготовка загрузки"
                ),
            }
        name = data.get("name", "") if isinstance(data, dict) else ""
        try:
            old_name, new_name, changed = update_template_pack(name)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "status": "error",
                "message": f"Template pack не изменён: {exc}",
            }
        if changed:
            message = (
                f"Template pack: {old_name} → {new_name}. "
                "Перезапуск подтверждён"
            )
            _record_event_history({
                "type": "configuration_changed",
                "section": "application",
                "field": "template_pack",
                "old": old_name,
                "new": new_name,
                "source": _command_history_source(command),
            })
        else:
            message = (
                f"Template pack уже выбран: {new_name}. "
                "Перезапуск подтверждён"
            )
        return {
            "status": "ok",
            "message": message,
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
        _record_event_history({
            "type": "configuration_changed",
            "section": "camera",
            "field": field,
            "old": old_value,
            "new": new_value,
            "source": _command_history_source(command),
        })
        return {
            "status": "ok",
            "message": (
                f"Параметр камеры {field}: {old_text} → {new_text}. "
                "Перезапуск подтверждён"
            ),
            "_post_action": _do_restart,
        }

    if cmd == "set_camera_preset":
        if STATE not in ("idle", "no_camera", "camera_searching"):
            return {
                "status": "error",
                "message": f"Пресет не применён: state={STATE}",
            }
        if _background_uploads:
            return {
                "status": "error",
                "message": "Пресет не применён: завершается подготовка загрузки",
            }
        if not isinstance(data, dict):
            return {
                "status": "error",
                "message": "Пресет не применён: отсутствует name",
            }
        name = data.get("name", "")
        try:
            label, changes, hint = apply_camera_preset(name)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "status": "error",
                "message": f"Пресет не применён: {exc}",
            }
        lines = [f"Пресет «{label}» применён"]
        if changes:
            lines.extend(
                f"{field}: {json.dumps(old, ensure_ascii=False)} → "
                f"{json.dumps(new, ensure_ascii=False)}"
                for field, (old, new) in changes.items()
            )
        else:
            lines.append("Все параметры уже соответствуют пресету")
        if hint:
            lines.append(f"Подсказка: {hint}")
        lines.append("Перезапуск подтверждён")
        if changes:
            _record_event_history({
                "type": "camera_preset_applied",
                "preset": name,
                "changes": {
                    field: {"old": old, "new": new}
                    for field, (old, new) in changes.items()
                },
                "source": _command_history_source(command),
            })
        return {
            "status": "ok",
            "message": "\n".join(lines),
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
            _record_event_history({
                "type": "admin_command",
                "command": cmd,
                "command_id": command_id,
            })
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
        previous_sessions = _cafe_unlock_sessions_remaining
        try:
            _set_cafe_unlock_sessions(sessions)
        except (OSError, ValueError) as exc:
            return {
                "status": "error",
                "message": f"Фотобудка не разблокирована: {exc}",
            }
        log.info("Cafe unlock updated: remaining sessions=%d", sessions)
        if previous_sessions != sessions:
            _record_event_history({
                "type": "access_changed",
                "field": "unlock_sessions_remaining",
                "old": previous_sessions,
                "new": sessions,
                "source": _command_history_source(command),
            })
        if STATE == "idle":
            await broadcast(_state_message(STATE))
        return {
            "status": "ok",
            "message": f"Остаток разрешённых фотосессий: {sessions}",
            "start_locked": _start_locked(),
            "unlock_sessions_remaining": _cafe_unlock_sessions_remaining,
        }

    if cmd == "status":
        event = _active_event_name()
        result = {
            "status": "ok",
            "message": await _status_report_text(),
            "event_folder": event,
            "start_locked": _start_locked(),
            "unlock_sessions_remaining": _cafe_unlock_sessions_remaining,
        }
        try:
            result.update(await asyncio.to_thread(
                _event_history_attachment, _event_history_path()))
        except (OSError, ValueError) as exc:
            log.warning("Event history not attached to status: %s", exc)
        return result

    if cmd == "set_event":
        name = data.get("name", "") if isinstance(data, dict) else ""
        if STATE not in ("idle", "no_camera", "camera_searching"):
            return {"status": "error", "message": f"Event не изменён: state={STATE}"}
        if _background_uploads:
            return {"status": "error", "message": "Event не изменён: завершается текущая загрузка"}
        previous_unlock_sessions = _cafe_unlock_sessions_remaining
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
        source = _command_history_source(command)
        archived_history = _switch_event_history(name, source)
        if previous_unlock_sessions != _cafe_unlock_sessions_remaining:
            _record_event_history({
                "type": "access_changed",
                "field": "unlock_sessions_remaining",
                "old": previous_unlock_sessions,
                "new": _cafe_unlock_sessions_remaining,
                "source": source,
            })
        if STATE == "idle":
            await broadcast(_state_message(STATE))
        result = {
            "status": "ok",
            "message": f"Event активирован на будке: {name}",
            "event_folder": name,
            "start_locked": _start_locked(),
            "unlock_sessions_remaining": _cafe_unlock_sessions_remaining,
        }
        if archived_history is not None:
            try:
                result.update(await asyncio.to_thread(
                    _event_history_attachment, archived_history))
            except (OSError, ValueError) as exc:
                log.warning(
                    "Previous event history not attached: %s", exc)
        return result

    if cmd == "send_logs":
        log_path = ROOT_DIR / "photobooth.log"
        if not log_path.is_file():
            return {"status": "error", "message": "photobooth.log не найден"}
        payload = await asyncio.to_thread(read_log_snapshot, log_path)
        return {
            "status": "ok",
            "message": "Лог готов",
            "document": yadisk_control.response_document(payload),
        }

    if cmd == "get_config":
        try:
            payload = await asyncio.to_thread(_build_config_export)
        except OSError as exc:
            return {
                "status": "error",
                "message": f"Конфиги не отправлены: {exc}",
            }
        return {
            "status": "ok",
            "message": "Конфиги фотобудки готовы",
            "document": yadisk_control.response_document(payload),
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
        camera_stopped = await asyncio.to_thread(camera.stop)
        if camera_stopped:
            log.info("Camera stopped")
        else:
            log.error("Camera did not stop cleanly before backend shutdown")
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
        content = Path(update_log).read_text(
            encoding="utf-8", errors="replace")
        for line in content.strip().splitlines():
            log.info(f"[update] {line}")
        app.state.update_log_path = None

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg["type"] == "start_session" and STATE == "idle":
                test_session = msg.get("test_session") is True
                if not test_session and _start_locked():
                    await ws.send_text(json.dumps(_state_message(STATE)))
                elif camera and camera.is_connected:
                    asyncio.create_task(run_session(
                        test_session=test_session))
                else:
                    await set_state("camera_searching" if camera else "no_camera")

            elif msg["type"] == "select_template" and STATE == "template_select":
                cb = getattr(app.state, "on_template_choice", None)
                if cb:
                    cb(
                        msg.get("template", ""),
                        msg.get("photo_index"),
                        msg.get("with_frame"),
                        msg.get("items"),
                    )

            elif msg["type"] == "skip_print" and STATE == "template_select":
                cb = getattr(app.state, "on_skip_print", None)
                if cb:
                    cb()

            elif msg["type"] == "template_activity" and STATE == "template_select":
                cb = getattr(app.state, "on_template_activity", None)
                if cb and cb():
                    await ws.send_text(json.dumps({
                        "type": "template_timer",
                        "timeout": int(CONFIG["template_select_timeout"]),
                    }))

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
    _start_event_history()
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
    _service_tasks.add(asyncio.create_task(_periodic_status_service()))


@app.on_event("shutdown")
async def app_shutdown():
    await _shutdown_services()


# Keep this catch-all mount last: API, WebSocket, live view, assets and photos
# must get the first chance to match their own routes.
app.mount(
    "/",
    FrontendStaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)
