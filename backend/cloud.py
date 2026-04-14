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
UPLOAD_NOTES = ["pb2vps_1", "pb2vps_2", "pb2vps_3"]
CMD_NOTE = "vps2pb"

# State
_session = None
_notes = {}  # {title: note_id}
_free_notes = set()  # titles of free notes


def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("YANOTES_SECRET", "photobooth")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def _encrypt(data: bytes) -> str:
    """Encrypt bytes, return ASCII string (Fernet base64)."""
    return _fernet().encrypt(data).decode("ascii")


def _decrypt(token: str) -> bytes:
    """Decrypt ASCII token back to bytes."""
    return _fernet().decrypt(token.encode("ascii"))


def _encrypt_str(text: str) -> str:
    return _encrypt(text.encode("utf-8"))


def _decrypt_str(token: str) -> str:
    return _decrypt(token).decode("utf-8")


# --- Init ---

def _init_sync():
    """Create session and find/create notes."""
    global _session, _notes, _free_notes
    from .yanotes import build_session, find_or_create_notes, list_notes

    cookie = os.environ.get("YANOTES_SESSION_ID", "")
    if not cookie:
        log.warning("Cloud: YANOTES_SESSION_ID not set")
        return False

    log.info("Cloud: connecting to Yandex Notes...")
    _session = build_session(cookie)

    all_titles = UPLOAD_NOTES + [CMD_NOTE]
    _notes = find_or_create_notes(_session, all_titles)
    log.info(f"Cloud: notes mapped: {_notes}")

    # Check which upload notes are free (empty snippet = free)
    notes = list_notes(_session)
    snippets = {}
    for n in notes:
        if n["id"] in _notes.values():
            snippets[n["id"]] = n.get("snippet", "")

    _free_notes = set()
    for t in UPLOAD_NOTES:
        nid = _notes.get(t)
        snippet = snippets.get(nid, "")
        if snippet:
            log.info(f"Cloud: {t} is OCCUPIED (snippet present)")
        else:
            _free_notes.add(t)
            log.info(f"Cloud: {t} is FREE")

    log.info(f"Cloud: free slots: {len(_free_notes)}/{len(UPLOAD_NOTES)}")
    return True


async def cloud_init():
    """Initialize Yandex Notes transport."""
    try:
        ok = await asyncio.get_event_loop().run_in_executor(None, _init_sync)
        if ok:
            log.info("Cloud: initialized OK")
    except Exception as e:
        log.error(f"Cloud: init failed: {e}")


# --- Upload ---

def _upload_sync(session_id: str, zip_path: str):
    """Encrypt and upload ZIP to a free note."""
    from .yanotes import put_note_content

    if not _session or not _notes:
        log.warning("Cloud: not initialized, cannot upload")
        return

    if not _free_notes:
        log.warning(f"Cloud: no free slots! All {len(UPLOAD_NOTES)} occupied")
        return

    title = _free_notes.pop()
    note_id = _notes[title]
    log.info(f"Cloud: using slot {title} (note {note_id}), {len(_free_notes)} free remaining")

    # Read ZIP
    data = Path(zip_path).read_bytes()
    log.info(f"Cloud: ZIP size: {len(data)/1048576:.1f}MB")

    # Encrypt ZIP → base64 payload
    payload = _encrypt(data)
    log.info(f"Cloud: encrypted payload: {len(payload)/1048576:.1f}MB")

    # Encrypt session_id for snippet
    encrypted_snippet = _encrypt_str(session_id)
    log.info(f"Cloud: uploading to {title}...")

    put_note_content(_session, note_id, payload, snippet=encrypted_snippet)
    log.info(f"Cloud: uploaded to {title} OK")


async def cloud_upload(session_id: str, photos: list[str],
                       collage: str | None, video: str | None):
    """Pack and upload session."""
    if not _session:
        log.warning("Cloud: not initialized, skipping upload")
        return

    try:
        log.info(f"Cloud: packing session {session_id}...")
        zip_path = await asyncio.get_event_loop().run_in_executor(
            None, _make_zip, session_id, photos, video
        )
        size_mb = Path(zip_path).stat().st_size / 1048576
        log.info(f"Cloud: packed {size_mb:.1f}MB ({len(photos)} photos)")

        await asyncio.get_event_loop().run_in_executor(
            None, _upload_sync, session_id, zip_path
        )
        Path(zip_path).unlink(missing_ok=True)
    except Exception as e:
        log.error(f"Cloud: upload failed: {e}")


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


def _poll_sync():
    """Poll deltas. Update free slots + check for commands. Returns (cmd, data) or None."""
    global _cmd_revision
    from .yanotes import get_deltas, get_db_revision, get_note_content, clear_note, list_notes

    if not _session or not _notes:
        return None

    # Init revision on first call
    if _cmd_revision == 0:
        _cmd_revision = get_db_revision(_session)
        log.info(f"Cloud: initial revision: {_cmd_revision}")
        return None

    # Get deltas
    deltas = get_deltas(_session, _cmd_revision)
    new_rev = deltas.get("revision", _cmd_revision)
    items = deltas.get("items", [])

    if new_rev != _cmd_revision:
        _cmd_revision = new_rev

    if not items:
        return None

    log.info(f"Cloud: {len(items)} deltas, revision {_cmd_revision}")

    # Refresh note snippets
    notes = list_notes(_session)
    cmd_result = None

    for n in notes:
        title = n.get("title", "")
        snippet = n.get("snippet", "")
        note_id = n.get("id", "")

        # Update free upload slots
        if title in UPLOAD_NOTES:
            if not snippet:
                if title not in _free_notes:
                    _free_notes.add(title)
                    log.info(f"Cloud: slot FREED: {title} (now {len(_free_notes)} free)")
            else:
                _free_notes.discard(title)

        # Check command note
        if title == CMD_NOTE and snippet:
            log.info(f"Cloud: command detected in {title}")
            try:
                cmd_name = _decrypt_str(snippet)
                log.info(f"Cloud: command name: {cmd_name}")

                # Fetch data from attribute
                data = None
                content, rev = get_note_content(_session, note_id)
                log.info(f"Cloud: fetched command content (rev={rev})")
                if content:
                    if isinstance(content, list):
                        content = content[0]
                    try:
                        attrs = content["children"][0]["children"][0].get("attributes", [])
                        for attr in attrs:
                            if attr[0] == "d" and attr[1]:
                                data = _decrypt_str(attr[1])
                                log.info(f"Cloud: command data decrypted ({len(data)} chars)")
                                break
                    except (KeyError, IndexError):
                        pass

                # Clear command note
                clear_note(_session, note_id)
                log.info(f"Cloud: command note cleared")
                cmd_result = (cmd_name, data)
            except Exception as e:
                log.warning(f"Cloud: command parse error: {e}")

    return cmd_result


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


async def cloud_poll_commands():
    """Background task: poll deltas every 2s. Updates free slots + handles commands."""
    await asyncio.sleep(5)  # wait for init
    log.info("Cloud: polling started")
    while True:
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, _poll_sync)
            if result:
                cmd, data = result
                handle_command(cmd, data)
        except Exception as e:
            log.warning(f"Cloud: poll error: {e}")
        await asyncio.sleep(2)
