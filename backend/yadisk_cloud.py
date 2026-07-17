"""Yandex.Disk uploader for photobooth sessions.

All session files (photos + video) go into one flat folder on Yandex.Disk.
Filename format: <YYYYMMDD>_<HHMMSS>_<session_id>_<index>.<ext>

On init: ensure folder exists.
On upload: serialise via semaphore (one file at a time -- faster on slow nets).
On failure: persist to upload_queue.json, retry every 5s in background.
"""

import asyncio
import json as _json
import logging
import os
from datetime import datetime
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

API = "https://cloud-api.yandex.net/v1/disk"

# State
_session: aiohttp.ClientSession | None = None
_folder: str = ""
_initialized = False
_upload_lock = asyncio.Lock()  # one upload at a time

# Persistent retry queue
_queue: list[dict] = []  # [{local_path, remote_name}]
_QUEUE_FILE: Path | None = None


# --- Queue persistence ---

def _queue_path() -> Path:
    global _QUEUE_FILE
    if not _QUEUE_FILE:
        from .config import ROOT_DIR
        _QUEUE_FILE = Path(ROOT_DIR) / "yadisk_queue.json"
    return _QUEUE_FILE


def _queue_save():
    try:
        path = _queue_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(_json.dumps(_queue, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log.warning(f"YaDisk: queue save failed: {e}")


def _queue_load():
    global _queue
    path = _queue_path()
    if not path.exists():
        return
    try:
        _queue = _json.loads(path.read_text(encoding="utf-8"))
        _queue = [e for e in _queue if Path(e["local_path"]).exists()]
        _queue_save()
        if _queue:
            log.info(f"YaDisk: {len(_queue)} pending uploads loaded")
    except Exception as e:
        log.warning(f"YaDisk: queue load failed: {e}")
        _queue = []


# --- Init ---

async def yadisk_init():
    """Create aiohttp session, ensure target folder exists, load queue."""
    global _session, _folder, _initialized

    _queue_load()

    token = os.environ.get("YADISK_TOKEN", "")
    if not token:
        log.warning("YaDisk: YADISK_TOKEN not set, uploads disabled")
        return

    from .config import load_event_config
    folder_name = (load_event_config().get("yadisk_folder") or "").strip()
    if not folder_name:
        log.warning("YaDisk: yadisk_folder not set in config")
        return
    _folder = "/" + folder_name.lstrip("/")

    _session = aiohttp.ClientSession(headers={"Authorization": f"OAuth {token}"})

    try:
        async with _session.put(f"{API}/resources", params={"path": _folder}) as r:
            if r.status == 201:
                log.info(f"YaDisk: created folder {_folder}")
            elif r.status == 409:
                log.info(f"YaDisk: folder {_folder} already exists")
            else:
                log.warning(f"YaDisk: create folder status {r.status}: {await r.text()}")
                await _session.close()
                _session = None
                return
    except Exception as e:
        log.error(f"YaDisk: init failed: {e}")
        await _session.close()
        _session = None
        return

    _initialized = True


async def yadisk_close():
    global _session
    if _session:
        await _session.close()
        _session = None


# --- Upload ---

def make_remote_name(session_id: str, index: int, total: int, ext: str) -> str:
    """<YYYYMMDD_HHMMSS>_<session_id>_<index>of<total>.<ext>

    `total` is the total number of files the session will produce. The VPS
    poller waits until <total> files for the same session appear, then sends
    them as one TG album.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{session_id}_{index}of{total}.{ext.lstrip('.')}"


async def upload_file(local_path: str, remote_name: str) -> bool:
    """Upload one file.  Serialised via semaphore.  On failure -> queue.

    Returns True on success.
    """
    if not _initialized:
        log.warning(f"YaDisk: not initialized, queueing {remote_name}")
        _queue.append({"local_path": local_path, "remote_name": remote_name})
        _queue_save()
        return False

    if not Path(local_path).exists():
        log.warning(f"YaDisk: local file missing: {local_path}")
        return False

    async with _upload_lock:
        ok = await _do_upload(local_path, remote_name)

    if not ok:
        _queue.append({"local_path": local_path, "remote_name": remote_name})
        _queue_save()
        log.info(f"YaDisk: queued {remote_name} ({len(_queue)} pending)")
    return ok


async def _do_upload(local_path: str, remote_name: str) -> bool:
    """Get upload URL from API, then PUT the file there.  No retries here."""
    remote_path = f"{_folder}/{remote_name}"
    try:
        async with _session.get(f"{API}/resources/upload",
                                params={"path": remote_path, "overwrite": "true"}) as r:
            if r.status != 200:
                log.warning(f"YaDisk: get upload-url status {r.status}: {await r.text()}")
                return False
            href = (await r.json())["href"]

        with open(local_path, "rb") as f:
            async with _session.put(href, data=f) as r2:
                if r2.status not in (201, 202):
                    log.warning(f"YaDisk: PUT status {r2.status}: {await r2.text()}")
                    return False

        log.info(f"YaDisk: uploaded {remote_name}")
        return True
    except Exception as e:
        log.warning(f"YaDisk: upload {remote_name} failed: {e}")
        return False


# --- Retry queue (background) ---

async def yadisk_poll_queue():
    """Drain the queue every 5 seconds.  Run as a background task."""
    while True:
        await asyncio.sleep(5)
        if not _queue or not _initialized:
            continue
        async with _upload_lock:
            while _queue and _initialized:
                entry = _queue[0]
                if not Path(entry["local_path"]).exists():
                    _queue.pop(0)
                    _queue_save()
                    continue
                ok = await _do_upload(entry["local_path"], entry["remote_name"])
                if ok:
                    _queue.pop(0)
                    _queue_save()
                else:
                    break  # network/auth still down, wait next tick
