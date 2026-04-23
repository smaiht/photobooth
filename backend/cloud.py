"""Upload session ZIP to VPS via Yandex Notes transport.

Persistent upload queue: if upload fails (no slots, network error), the ZIP
is kept on disk and added to a JSON queue file.  A background task retries
queued uploads whenever a slot becomes free.
"""

import asyncio
import base64
import hashlib
import json as _json
import logging
import os
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

log = logging.getLogger(__name__)

# Note titles
UPLOAD_NOTES = ["pb2vps_1", "pb2vps_2", "pb2vps_3", "pb2vps_4", "pb2vps_5", "pb2vps_6"]
CMD_NOTE = "vps2pb"

# State
_session = None  # aiohttp.ClientSession
_notes = {}  # {title: note_id}
_free_notes = set()  # titles of free notes
_command_handlers: list[Callable[[str, str | None], Awaitable[bool]]] = []

# Persistent upload queue
_upload_queue: list[dict] = []  # [{session_id, zip_path}]
_QUEUE_FILE: Path | None = None
_processing_queue = False


def register_command_handler(handler: Callable[[str, str | None], Awaitable[bool]]):
    """Register an app-level command handler without importing backend.main here."""
    if handler not in _command_handlers:
        _command_handlers.append(handler)


# --- Persistent upload queue ---

def _queue_file() -> Path:
    global _QUEUE_FILE
    if not _QUEUE_FILE:
        from .config import ROOT_DIR
        _QUEUE_FILE = Path(ROOT_DIR) / "upload_queue.json"
    return _QUEUE_FILE


def _queue_save():
    """Atomic write queue to disk."""
    try:
        path = _queue_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(_json.dumps(_upload_queue, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log.warning(f"Cloud: queue save failed: {e}")


def _queue_load():
    """Load queue from disk on startup. Also scan for orphaned ZIPs."""
    global _upload_queue
    path = _queue_file()
    if path.exists():
        try:
            _upload_queue = _json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Cloud: failed to load queue: {e}")
            _upload_queue = []

    # Scan for orphaned ZIPs (crash during upload before queue_add)
    from .config import PHOTOS_DIR
    queued_paths = {e["zip_path"] for e in _upload_queue}
    for zip_file in Path(PHOTOS_DIR).rglob("*.zip"):
        zp = str(zip_file)
        if zp not in queued_paths:
            sid = zip_file.stem
            _upload_queue.append({"session_id": sid, "zip_path": zp})
            log.info(f"Cloud: found orphaned ZIP: {sid}")

    # Remove entries whose ZIP no longer exists
    _upload_queue = [e for e in _upload_queue if Path(e["zip_path"]).exists()]
    _queue_save()
    if _upload_queue:
        log.info(f"Cloud: {len(_upload_queue)} uploads pending")


def _queue_add(session_id: str, zip_path: str):
    """Add a failed upload to the queue."""
    _upload_queue.append({"session_id": session_id, "zip_path": zip_path})
    _queue_save()
    log.info(f"Cloud: queued {session_id} ({len(_upload_queue)} in queue)")


def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("YANOTES_SECRET", "photobooth")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def _encrypt(data: bytes) -> str:
    return _fernet().encrypt(data).decode("ascii")


def _decrypt(token: str) -> bytes:
    return _fernet().decrypt(token.encode("ascii"))


def _encrypt_str(text: str) -> str:
    return _encrypt(text.encode("utf-8"))


def _decrypt_str(token: str) -> str:
    return _decrypt(token).decode("utf-8")


# --- Init ---

async def cloud_init():
    """Initialize Yandex Notes transport."""
    global _session, _notes, _free_notes
    from .yanotes import build_session, find_or_create_notes, list_notes

    _queue_load()

    cookie = os.environ.get("YANOTES_SESSION_ID", "")
    if not cookie:
        log.warning("Cloud: YANOTES_SESSION_ID not set")
        return

    try:
        log.info("Cloud: connecting to Yandex Notes...")
        _session = build_session(cookie)

        _notes = await find_or_create_notes(_session, UPLOAD_NOTES + [CMD_NOTE])
        log.info(f"Cloud: notes mapped: {_notes}")

        notes = await list_notes(_session)
        snippets = {n["id"]: n.get("snippet", "") for n in notes}

        _free_notes = set()
        for t in UPLOAD_NOTES:
            nid = _notes.get(t)
            if snippets.get(nid, ""):
                log.info(f"Cloud: {t} is OCCUPIED")
            else:
                _free_notes.add(t)
                log.info(f"Cloud: {t} is FREE")

        log.info(f"Cloud: free slots: {len(_free_notes)}/{len(UPLOAD_NOTES)}")
        log.info("Cloud: initialized OK")
        if _upload_queue and _free_notes:
            asyncio.create_task(_process_queue())
    except Exception as e:
        log.error(f"Cloud: init failed: {e}")


# --- Upload ---

async def cloud_upload(session_id: str, photos: list[str],
                       collage: str | None, video: str | None):
    """Pack and upload session. On failure, queue for retry."""
    if not _session:
        log.warning("Cloud: not initialized, skipping upload")
        return

    zip_path = None
    try:
        log.info(f"Cloud: packing session {session_id}...")
        zip_path = await asyncio.get_event_loop().run_in_executor(
            None, _make_zip, session_id, photos, video)
        size_mb = Path(zip_path).stat().st_size / 1048576
        log.info(f"Cloud: packed {size_mb:.1f}MB ({len(photos)} photos)")

        ok = await _upload(session_id, zip_path)
        if ok:
            Path(zip_path).unlink(missing_ok=True)
        else:
            _queue_add(session_id, zip_path)
    except Exception as e:
        log.error(f"Cloud: upload failed: {e}")
        if zip_path and Path(zip_path).exists():
            _queue_add(session_id, zip_path)


async def _upload(session_id: str, zip_path: str) -> bool:
    """Try to upload a ZIP with retries. Returns True on success."""
    from .yanotes import put_note_content

    if not _free_notes:
        log.warning(f"Cloud: no free slots ({len(UPLOAD_NOTES)} occupied)")
        return False

    title = _free_notes.pop()
    note_id = _notes[title]
    log.info(f"Cloud: using slot {title}, {len(_free_notes)} free remaining")

    def _prepare():
        data = Path(zip_path).read_bytes()
        log.info(f"Cloud: ZIP size: {len(data)/1048576:.1f}MB")
        payload = _encrypt(data)
        log.info(f"Cloud: encrypted: {len(payload)/1048576:.1f}MB")
        snippet = _encrypt_str(session_id)
        return payload, snippet

    try:
        payload, encrypted_snippet = await asyncio.get_event_loop().run_in_executor(None, _prepare)
    except Exception as e:
        _free_notes.add(title)
        log.error(f"Cloud: prepare failed: {e}")
        return False

    for attempt in range(5):
        try:
            log.info(f"Cloud: uploading to {title} (attempt {attempt + 1}/5)...")
            await put_note_content(_session, note_id, payload, snippet=encrypted_snippet)
            log.info(f"Cloud: uploaded to {title} OK")
            return True
        except Exception as e:
            log.warning(f"Cloud: upload attempt {attempt + 1} failed: {e}")
            if attempt < 4:
                await asyncio.sleep(5 * (attempt + 1))  # 5, 10, 15, 20s

    _free_notes.add(title)
    log.error(f"Cloud: all 5 attempts failed for {session_id}")
    return False


async def _process_queue():
    """Try to upload queued sessions. Called when a slot becomes free."""
    global _processing_queue
    if _processing_queue:
        return
    _processing_queue = True
    try:
        while _upload_queue and _free_notes and _session:
            entry = _upload_queue[0]
            zip_path = entry["zip_path"]
            session_id = entry["session_id"]

            if not Path(zip_path).exists():
                _upload_queue.pop(0)
                _queue_save()
                continue

            log.info(f"Cloud: retrying queued {session_id}...")
            ok = await _upload(session_id, zip_path)
            if ok:
                Path(zip_path).unlink(missing_ok=True)
                _upload_queue.pop(0)
                _queue_save()
                log.info(f"Cloud: queued {session_id} uploaded OK ({len(_upload_queue)} remaining)")
            else:
                break
    finally:
        _processing_queue = False  # no slots or network error, stop retrying


def _make_zip(session_id: str, photos: list[str], video: str | None) -> str:
    session_dir = Path(photos[0]).parent if photos else Path(".")
    zip_path = str(session_dir / f"{session_id}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, p in enumerate(photos):
            if Path(p).exists():
                zf.write(p, f"photo_{i+1}.jpg")
        if video and Path(video).exists():
            zf.write(video, "video.mp4")
    return zip_path


# --- Command polling ---

_cmd_revision = 0


async def cloud_poll_commands():
    """Background task: poll deltas every 2s. Updates free slots + handles commands."""
    global _cmd_revision
    from .yanotes import get_deltas, get_db_revision, get_note_content, clear_note, list_notes

    await asyncio.sleep(5)  # wait for init

    if not _session or not _notes:
        log.warning("Cloud: polling skipped, not initialized")
        return

    _cmd_revision = await get_db_revision(_session)
    log.info(f"Cloud: polling started, revision {_cmd_revision}")

    while True:
        try:
            deltas = await get_deltas(_session, _cmd_revision)
            new_rev = deltas.get("revision", _cmd_revision)
            items = deltas.get("items", [])
            if new_rev != _cmd_revision:
                _cmd_revision = new_rev

            if items:
                log.info(f"Cloud: {len(items)} deltas, revision {_cmd_revision}")
                notes = await list_notes(_session)

                for n in notes:
                    title = n.get("title", "")
                    snippet = n.get("snippet", "")
                    note_id = n.get("id", "")

                    # Update free upload slots
                    if title in UPLOAD_NOTES:
                        if not snippet:
                            if title not in _free_notes:
                                _free_notes.add(title)
                                log.info(f"Cloud: slot FREED: {title} ({len(_free_notes)} free)")
                                if _upload_queue:
                                    asyncio.create_task(_process_queue())
                        else:
                            _free_notes.discard(title)

                    # Check command note
                    if title == CMD_NOTE and snippet:
                        log.info(f"Cloud: command detected in {title}")
                        try:
                            cmd_name = _decrypt_str(snippet)
                            log.info(f"Cloud: command: {cmd_name}")

                            data = None
                            content, rev = await get_note_content(_session, note_id)
                            if content:
                                if isinstance(content, list):
                                    content = content[0]
                                try:
                                    attrs = content["children"][0]["children"][0].get("attributes", [])
                                    for attr in attrs:
                                        if attr[0] == "d" and attr[1]:
                                            data = _decrypt_str(attr[1])
                                            log.info(f"Cloud: command data ({len(data)} chars)")
                                            break
                                except (KeyError, IndexError):
                                    pass

                            await clear_note(_session, note_id)
                            log.info(f"Cloud: command note cleared")
                            await handle_command(cmd_name, data)
                        except Exception as e:
                            log.warning(f"Cloud: command error: {e}")

        except Exception as e:
            log.warning(f"Cloud: poll error: {e}")

        # Retry queued uploads if slots available (handles network-back scenario)
        if _upload_queue and _free_notes and not _processing_queue:
            asyncio.create_task(_process_queue())

        await asyncio.sleep(1)


async def handle_command(cmd: str, data: str | None):
    """Handle a command from VPS."""
    log.info(f"Cloud: handling command={cmd}, data={data[:200] if data else None}")

    # Transport-owned commands stay here because they only touch Yandex Notes/log upload.
    # App/session commands are delegated to handlers registered by main.py to avoid a
    # cloud.py -> main.py import cycle. TODO: replace this split with a small command
    # router module/table so every command is declared in one obvious place.
    if cmd == "send_logs":
        asyncio.create_task(_send_logs())
        return
    if cmd == "clear_logs":
        asyncio.create_task(_clear_logs())
        return
    if cmd == "ping":
        log.info("Cloud: pong")
        return

    for handler in list(_command_handlers):
        try:
            if await handler(cmd, data):
                return
        except Exception as e:
            log.warning(f"Cloud: command handler failed: {e}")

    log.info(f"Cloud: unknown command: {cmd}")


async def _send_logs():
    """Read photobooth.log and push to a free upload slot."""
    from .yanotes import put_note_content
    try:
        from .config import ROOT_DIR
        log_path = os.path.join(ROOT_DIR, "photobooth.log")
        if not os.path.exists(log_path):
            log.warning("Cloud: photobooth.log not found")
            return

        if not _free_notes:
            log.warning("Cloud: no free slots for logs")
            return

        text = open(log_path, encoding="utf-8").read()
        title = _free_notes.pop()
        note_id = _notes[title]
        payload = _encrypt_str(text)
        snippet = _encrypt_str("logs")
        log.info(f"Cloud: sending logs via {title} ({len(text)//1024}KB)")
        await put_note_content(_session, note_id, payload, snippet=snippet)
        log.info(f"Cloud: logs sent via {title}")
    except Exception as e:
        log.warning(f"Cloud: send_logs failed: {e}")


async def _clear_logs():
    """Drop old rotated logs and move current photobooth.log to photobooth.log.1."""
    from .yanotes import put_note_content
    try:
        from .config import ROOT_DIR
        from logging.handlers import RotatingFileHandler

        log_path = Path(ROOT_DIR) / "photobooth.log"
        for rotated in Path(ROOT_DIR).glob("photobooth.log.*"):
            if rotated.is_file():
                rotated.unlink(missing_ok=True)

        if log_path.exists() and log_path.stat().st_size > 0:
            for handler in logging.getLogger().handlers:
                if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == log_path:
                    handler.doRollover()
                    break
            else:
                log_path.replace(log_path.with_name("photobooth.log.1"))
                log_path.write_text("", encoding="utf-8")
        else:
            log_path.write_text("", encoding="utf-8")

        log.info("Cloud: logs rotated and current log cleared")

        if not _free_notes:
            return
        title = _free_notes.pop()
        note_id = _notes[title]
        snippet = _encrypt_str("clear_logs")
        await put_note_content(_session, note_id, "", snippet=snippet)
    except Exception as e:
        log.warning(f"Cloud: clear_logs failed: {e}")
