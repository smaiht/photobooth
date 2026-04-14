"""Upload session ZIP to VPS via Yandex Notes transport."""

import asyncio
import base64
import hashlib
import logging
import os
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

# Note titles
UPLOAD_NOTES = ["pb2vps_1", "pb2vps_2", "pb2vps_3", "pb2vps_4", "pb2vps_5", "pb2vps_6"]
CMD_NOTE = "vps2pb"

# State
_session = None  # aiohttp.ClientSession
_notes = {}  # {title: note_id}
_free_notes = set()  # titles of free notes


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
    except Exception as e:
        log.error(f"Cloud: init failed: {e}")


# --- Upload ---

async def cloud_upload(session_id: str, photos: list[str],
                       collage: str | None, video: str | None):
    """Pack and upload session."""
    if not _session:
        log.warning("Cloud: not initialized, skipping upload")
        return

    try:
        log.info(f"Cloud: packing session {session_id}...")
        zip_path = await asyncio.get_event_loop().run_in_executor(
            None, _make_zip, session_id, photos, video)
        size_mb = Path(zip_path).stat().st_size / 1048576
        log.info(f"Cloud: packed {size_mb:.1f}MB ({len(photos)} photos)")

        await _upload(session_id, zip_path)
        Path(zip_path).unlink(missing_ok=True)
    except Exception as e:
        log.error(f"Cloud: upload failed: {e}")


async def _upload(session_id: str, zip_path: str):
    from .yanotes import put_note_content

    if not _free_notes:
        log.warning(f"Cloud: no free slots! All {len(UPLOAD_NOTES)} occupied")
        return

    title = _free_notes.pop()
    note_id = _notes[title]
    log.info(f"Cloud: using slot {title}, {len(_free_notes)} free remaining")

    # Heavy ops in executor to not block event loop
    def _prepare():
        data = Path(zip_path).read_bytes()
        log.info(f"Cloud: ZIP size: {len(data)/1048576:.1f}MB")
        payload = _encrypt(data)
        log.info(f"Cloud: encrypted: {len(payload)/1048576:.1f}MB")
        snippet = _encrypt_str(session_id)
        return payload, snippet

    payload, encrypted_snippet = await asyncio.get_event_loop().run_in_executor(None, _prepare)

    log.info(f"Cloud: uploading to {title}...")
    try:
        await put_note_content(_session, note_id, payload, snippet=encrypted_snippet)
        log.info(f"Cloud: uploaded to {title} OK")
    except Exception as e:
        _free_notes.add(title)  # return slot on failure
        raise


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
                            handle_command(cmd_name, data)
                        except Exception as e:
                            log.warning(f"Cloud: command error: {e}")

        except Exception as e:
            log.warning(f"Cloud: poll error: {e}")

        await asyncio.sleep(1)


def handle_command(cmd: str, data: str | None):
    """Handle a command from VPS."""
    log.info(f"Cloud: handling command={cmd}, data={data[:200] if data else None}")

    if cmd == "restart":
        log.info("Cloud: restart requested by VPS")
    elif cmd == "update_config":
        log.info(f"Cloud: config update: {data}")
    elif cmd == "ping":
        log.info("Cloud: pong")
    else:
        log.info(f"Cloud: unknown command: {cmd}")
