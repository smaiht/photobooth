"""Reliable Yandex.Disk outbox for photobooth sessions.

Media files stay flat in the event folder so it can be shared as an album.
After every file is present and verified, a typed ``session_ready`` message is
published to the stable ``control/to_vps`` inbox.  The message carries its
event folder, so delivery never depends on both machines switching events at
the same instant.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

API = "https://cloud-api.yandex.net/v1/disk"
SCHEMA_VERSION = 2
RETRY_MIN_SECONDS = 5
RETRY_MAX_SECONDS = 60

_session: aiohttp.ClientSession | None = None
_transfer_session: aiohttp.ClientSession | None = None
_folder = ""
_bus_root = ""
_token = ""
_queue: list[dict] = []
_queue_file: Path | None = None
_queue_lock = asyncio.Lock()
_queue_loaded = False
_configured = False


def _queue_path() -> Path:
    global _queue_file
    if _queue_file is None:
        from .config import ROOT_DIR
        _queue_file = Path(ROOT_DIR) / "yadisk_queue.json"
    return _queue_file


def _queue_save() -> None:
    try:
        path = _queue_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_queue, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        log.error(f"YaDisk: queue save failed: {exc}")
        raise


def _queue_load() -> None:
    global _queue, _queue_loaded
    if _queue_loaded:
        return
    _queue_loaded = True
    path = _queue_path()
    if not path.exists():
        _queue = []
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("queue root must be a list")
        if data and "files" not in data[0]:
            raise ValueError("legacy per-file queue requires manual migration")
        _queue = data
        if _queue:
            log.info(f"YaDisk: loaded {len(_queue)} pending sessions")
    except Exception as exc:
        log.error(f"YaDisk: queue load failed: {exc}")
        _queue = []


def _safe_extension(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if not suffix or len(suffix) > 10 or not suffix[1:].isalnum():
        return ".bin"
    return suffix


def build_session_job(session_id: str, photos: list[str], collage: str | None,
                      video: str | None, created_at: datetime | None = None,
                      event_folder: str | None = None) -> dict:
    """Build a serializable outbox job with stable remote names."""
    if not session_id or not session_id.isalnum():
        raise ValueError("session_id must be non-empty and alphanumeric")

    created_at = created_at or datetime.now(timezone.utc)
    prefix = created_at.astimezone().strftime("%Y%m%d_%H%M%S")
    base = f"{prefix}_{session_id}"
    files = []

    for index, local_path in enumerate(photos, start=1):
        files.append({
            "local_path": str(local_path),
            "name": f"{base}_photo_{index:02d}{_safe_extension(local_path)}",
            "kind": "photo",
            "index": index,
        })

    if collage:
        files.append({
            "local_path": str(collage),
            "name": f"{base}_print{_safe_extension(collage)}",
            "kind": "print",
        })

    if video:
        files.append({
            "local_path": str(video),
            "name": f"{base}_video{_safe_extension(video)}",
            "kind": "video",
        })

    if not files:
        raise ValueError("cannot queue an empty session")

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "created_at": created_at.isoformat(),
        "event_folder": event_folder,
        "manifest_name": f"{base}.json",
        "files": files,
    }


async def enqueue_session(session_id: str, photos: list[str], collage: str | None,
                          video: str | None) -> None:
    """Persist a complete local session for background delivery."""
    _queue_load()
    from .config import load_event_config
    folder_name = str(load_event_config().get("yadisk_folder") or "").strip().strip("/")
    if not folder_name or any(part in ("", ".", "..") for part in folder_name.split("/")):
        raise ValueError("yadisk_folder is missing or invalid")
    job = build_session_job(
        session_id, photos, collage, video, event_folder="/" + folder_name)
    missing = [entry["local_path"] for entry in job["files"]
               if not Path(entry["local_path"]).is_file()]
    if missing:
        raise FileNotFoundError(f"session files missing: {missing}")

    async with _queue_lock:
        # Re-queueing the same session is idempotent.
        _queue[:] = [entry for entry in _queue
                     if entry.get("session_id") != session_id]
        _queue.append(job)
        _queue_save()
    log.info(f"YaDisk: queued session {session_id} ({len(job['files'])} files)")


def pending_count() -> int:
    _queue_load()
    return len(_queue)


async def set_event_folder(folder_name: str) -> None:
    """Switch future sessions after all jobs for the previous event are uploaded."""
    global _folder
    name = str(folder_name or "").strip()
    if (not name or name in (".", "..") or "/" in name or "\\" in name
            or any(ord(char) < 32 for char in name) or len(name) > 160):
        raise ValueError("invalid event folder name")
    if pending_count():
        raise RuntimeError("есть незавершённые загрузки предыдущего event")
    if not await _connect():
        raise RuntimeError("Яндекс Диск недоступен")
    target = "/" + name
    if not await _ensure_directory(target):
        raise RuntimeError(f"не удалось создать папку {target}")
    _folder = target
    log.info(f"YaDisk: active event changed to {_folder}")


def current_event_folder() -> str:
    return _folder.lstrip("/")


async def _close_sessions() -> None:
    global _session, _transfer_session
    if _session and not _session.closed:
        await _session.close()
    if _transfer_session and not _transfer_session.closed:
        await _transfer_session.close()
    _session = None
    _transfer_session = None


async def _connect() -> bool:
    global _session, _transfer_session
    if not _configured:
        return False
    if _session and not _session.closed:
        return True

    await _close_sessions()
    timeout = aiohttp.ClientTimeout(total=60, connect=15)
    _session = aiohttp.ClientSession(
        headers={"Authorization": f"OAuth {_token}"}, timeout=timeout)
    _transfer_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=600, connect=30))

    try:
        paths = [_folder]
        current = ""
        for part in _bus_root.strip("/").split("/"):
            current += "/" + part
            paths.append(current)
        paths.append(f"{_bus_root}/to_vps")
        for path in paths:
            if not await _ensure_directory(path):
                await _close_sessions()
                return False
        log.info(f"YaDisk: connected, event folder {_folder}")
        return True
    except Exception as exc:
        log.warning(f"YaDisk: connect failed: {exc}")
        await _close_sessions()
        return False


async def _ensure_directory(path: str) -> bool:
    try:
        async with _session.put(f"{API}/resources", params={"path": path}) as response:
            if response.status in (201, 409):
                return True
            log.warning(f"YaDisk: create directory {path}: {response.status} "
                        f"{await response.text()}")
            return False
    except Exception as exc:
        log.warning(f"YaDisk: create directory {path} failed: {exc}")
        return False


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _resource_matches(remote_path: str, size: int, md5: str | None) -> bool:
    """Wait for a 202 upload to become visible and verify its metadata."""
    for attempt in range(10):
        try:
            async with _session.get(
                f"{API}/resources",
                params={"path": remote_path, "fields": "size,md5"},
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    remote_md5 = data.get("md5")
                    if data.get("size") == size and (not md5 or not remote_md5 or remote_md5 == md5):
                        return True
                elif response.status not in (404, 423):
                    log.warning(f"YaDisk: verify {remote_path}: {response.status} "
                                f"{await response.text()}")
                    return False
        except Exception as exc:
            log.warning(f"YaDisk: verify {remote_path} failed: {exc}")
            return False
        await asyncio.sleep(min(1 + attempt, 5))
    return False


async def _upload_path(local_path: Path, remote_path: str) -> tuple[bool, dict]:
    size = local_path.stat().st_size
    md5 = await asyncio.to_thread(_file_md5, local_path)
    try:
        async with _session.get(
            f"{API}/resources/upload",
            params={"path": remote_path, "overwrite": "true"},
        ) as response:
            if response.status != 200:
                log.warning(f"YaDisk: upload URL {remote_path}: {response.status} "
                            f"{await response.text()}")
                return False, {}
            href = (await response.json())["href"]

        with local_path.open("rb") as source:
            async with _transfer_session.put(href, data=source) as upload_response:
                if upload_response.status not in (201, 202):
                    log.warning(f"YaDisk: upload {remote_path}: {upload_response.status} "
                                f"{await upload_response.text()}")
                    return False, {}

        if not await _resource_matches(remote_path, size, md5):
            log.warning(f"YaDisk: uploaded file did not verify: {remote_path}")
            return False, {}
        return True, {"size": size, "md5": md5}
    except Exception as exc:
        log.warning(f"YaDisk: upload {remote_path} failed: {exc}")
        return False, {}


async def _upload_bytes(data: bytes, remote_path: str) -> bool:
    try:
        async with _session.get(
            f"{API}/resources/upload",
            params={"path": remote_path, "overwrite": "true"},
        ) as response:
            if response.status != 200:
                log.warning(f"YaDisk: manifest URL: {response.status} {await response.text()}")
                return False
            href = (await response.json())["href"]
        async with _transfer_session.put(href, data=data) as upload_response:
            if upload_response.status not in (201, 202):
                log.warning(f"YaDisk: manifest upload: {upload_response.status} "
                            f"{await upload_response.text()}")
                return False
        return await _resource_matches(remote_path, len(data), None)
    except Exception as exc:
        log.warning(f"YaDisk: manifest upload failed: {exc}")
        return False


async def _upload_job(job: dict) -> bool:
    event_folder = job.get("event_folder") or _folder
    for path in (event_folder, f"{_bus_root}/to_vps"):
        if not await _ensure_directory(path):
            return False

    manifest_files = []
    for entry in job["files"]:
        local_path = Path(entry["local_path"])
        if not local_path.is_file():
            log.error(f"YaDisk: local session file disappeared: {local_path}")
            return False
        remote_path = f"{event_folder}/{entry['name']}"
        ok, metadata = await _upload_path(local_path, remote_path)
        if not ok:
            return False
        manifest_entry = {key: value for key, value in entry.items()
                          if key != "local_path"}
        manifest_entry.update(metadata)
        manifest_files.append(manifest_entry)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "message_type": "session_ready",
        "event_folder": event_folder.lstrip("/"),
        "session_id": job["session_id"],
        "created_at": job["created_at"],
        "files": manifest_files,
    }
    payload = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    manifest_path = f"{_bus_root}/to_vps/session_{job['manifest_name']}"
    if not await _upload_bytes(payload, manifest_path):
        return False

    log.info(f"YaDisk: session {job['session_id']} published "
             f"({len(manifest_files)} files)")
    return True


async def yadisk_init() -> bool:
    """Load configuration and make an initial connection attempt."""
    global _folder, _bus_root, _token, _configured
    _queue_load()
    _token = os.environ.get("YADISK_TOKEN", "").strip()
    if not _token:
        log.warning("YaDisk: YADISK_TOKEN not set, worker will stay disabled")
        return False

    from .config import load_event_config
    config = load_event_config()
    folder_name = str(config.get("yadisk_folder") or "").strip().strip("/")
    bus_name = str(config.get("yadisk_control_folder") or "").strip().strip("/")
    if not folder_name or any(part in ("", ".", "..") for part in folder_name.split("/")):
        log.warning("YaDisk: yadisk_folder is missing or invalid")
        return False
    if not bus_name or any(part in ("", ".", "..") for part in bus_name.split("/")):
        log.warning("YaDisk: yadisk_control_folder is missing or invalid")
        return False

    _folder = "/" + folder_name
    _bus_root = "/" + bus_name
    _configured = True
    return await _connect()


async def yadisk_close() -> None:
    await _close_sessions()


async def yadisk_upload_queue_loop() -> None:
    """Deliver the local upload queue forever with bounded retry backoff."""
    delay = RETRY_MIN_SECONDS
    while True:
        if not _configured:
            await asyncio.sleep(RETRY_MAX_SECONDS)
            continue
        if not _queue:
            delay = RETRY_MIN_SECONDS
            await asyncio.sleep(2)
            continue
        if not await _connect():
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_SECONDS)
            continue

        job = _queue[0]
        if await _upload_job(job):
            async with _queue_lock:
                if _queue and _queue[0].get("session_id") == job.get("session_id"):
                    _queue.pop(0)
                    _queue_save()
            delay = RETRY_MIN_SECONDS
            continue

        await _close_sessions()
        await asyncio.sleep(delay)
        delay = min(delay * 2, RETRY_MAX_SECONDS)
