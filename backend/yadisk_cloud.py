"""Reliable Yandex.Disk outbox for photobooth sessions.

Original photos and video are uploaded once into a public per-session folder.
Yandex.Disk then copies them server-side into the flat event folder consumed by
the VPS.  A typed ``session_ready`` message is published to ``control/to_vps``
only after every flat copy has completed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp

log = logging.getLogger(__name__)

API = "https://cloud-api.yandex.net/v1/disk"
SCHEMA_VERSION = 2
STORAGE_LAYOUT = "event_sibling_v1"
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
_session_link_handler: Callable[[str, str], Awaitable[None]] | None = None
_prepared_links: dict[str, str] = {}


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


async def _persist_job(job: dict) -> None:
    """Persist delivery progress when this is a live durable-queue job."""
    async with _queue_lock:
        if any(queued is job for queued in _queue):
            _queue_save()


def set_session_link_handler(
    handler: Callable[[str, str], Awaitable[None]] | None,
) -> None:
    global _session_link_handler
    _session_link_handler = handler


async def _notify_session_link(session_id: str, public_url: str) -> None:
    if not _session_link_handler:
        return
    try:
        await _session_link_handler(session_id, public_url)
    except Exception:
        log.exception("YaDisk: session link handler failed for %s", session_id)


def session_folder_name(session_id: str, created_at: datetime) -> str:
    """Return the stable, human-readable folder name used by a session."""
    if not session_id or not session_id.isalnum():
        raise ValueError("session_id must be non-empty and alphanumeric")
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return f"{created_at.astimezone():%Y-%m-%d_%H-%M-%S}_{session_id}"


def sessions_root(event_folder: str) -> str:
    """Return the sibling folder that keeps guest-facing session directories."""
    folder = "/" + str(event_folder or "").strip().strip("/")
    if folder == "/":
        raise ValueError("invalid event folder")
    return f"{folder}_by_sessions"


def _legacy_session_folder_name(job: dict) -> str:
    session_id = str(job.get("session_id") or "session")
    try:
        created_at = datetime.fromisoformat(str(job.get("created_at") or ""))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if session_id.isalnum():
            return session_folder_name(session_id, created_at)
    except (TypeError, ValueError):
        pass

    stem = Path(str(job.get("manifest_name") or session_id)).stem
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    return safe[:180] or "legacy_session"


def _migrate_queue_jobs(jobs: list[dict]) -> tuple[list[dict], bool]:
    """Upgrade pending flat-layout jobs without losing originals or videos."""
    migrated: list[dict] = []
    changed = False
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("files"), list):
            log.error("YaDisk: skipped malformed pending queue entry")
            changed = True
            continue

        layout_changed = job.get("storage_layout") != STORAGE_LAYOUT
        if layout_changed:
            job["storage_layout"] = STORAGE_LAYOUT
            job.pop("public_url", None)
            changed = True

        photo_index = 0
        files = []
        for raw_entry in job["files"]:
            if not isinstance(raw_entry, dict):
                changed = True
                continue
            kind = raw_entry.get("kind")
            if kind == "print":
                log.info(
                    "YaDisk: removed legacy print file from pending session %s",
                    job.get("session_id", "?"),
                )
                changed = True
                continue
            if kind not in ("photo", "video"):
                log.error("YaDisk: skipped unsupported queued file kind %r", kind)
                changed = True
                continue

            entry = dict(raw_entry)
            if layout_changed:
                entry.pop("session_uploaded", None)
            if kind == "photo":
                photo_index += 1
                expected_name = f"photo_{photo_index:02d}{_safe_extension(str(entry.get('local_path', '')))}"
            else:
                expected_name = f"video{_safe_extension(str(entry.get('local_path', '')))}"
            if entry.get("session_name") != expected_name:
                entry["session_name"] = expected_name
                changed = True
            files.append(entry)

        if not files:
            log.error(
                "YaDisk: dropped pending session %s because it has no originals or video",
                job.get("session_id", "?"),
            )
            changed = True
            continue
        if job.get("session_folder_name") is None:
            job["session_folder_name"] = _legacy_session_folder_name(job)
            changed = True
        if job.get("files") != files:
            job["files"] = files
            changed = True
        migrated.append(job)
    return migrated, changed


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
        _queue, migrated = _migrate_queue_jobs(data)
        if migrated:
            _queue_save()
            log.info("YaDisk: pending queue migrated to per-session folders")
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


def build_session_job(session_id: str, photos: list[str], video: str | None,
                      created_at: datetime | None = None,
                      event_folder: str | None = None,
                      session_folder: str | None = None) -> dict:
    """Build a serializable outbox job with stable remote names."""
    if not session_id or not session_id.isalnum():
        raise ValueError("session_id must be non-empty and alphanumeric")

    created_at = created_at or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    prefix = created_at.astimezone().strftime("%Y%m%d_%H%M%S")
    base = f"{prefix}_{session_id}"
    folder_name = session_folder or session_folder_name(session_id, created_at)
    if (not folder_name or folder_name in (".", "..") or "/" in folder_name
            or "\\" in folder_name or len(folder_name) > 200):
        raise ValueError("invalid session folder name")
    files = []

    for index, local_path in enumerate(photos, start=1):
        files.append({
            "local_path": str(local_path),
            "name": f"{base}_photo_{index:02d}{_safe_extension(local_path)}",
            "session_name": f"photo_{index:02d}{_safe_extension(local_path)}",
            "kind": "photo",
            "index": index,
        })

    if video:
        files.append({
            "local_path": str(video),
            "name": f"{base}_video{_safe_extension(video)}",
            "session_name": f"video{_safe_extension(video)}",
            "kind": "video",
        })

    if not files:
        raise ValueError("cannot queue an empty session")

    return {
        "schema_version": SCHEMA_VERSION,
        "storage_layout": STORAGE_LAYOUT,
        "session_id": session_id,
        "created_at": created_at.isoformat(),
        "event_folder": event_folder,
        "session_folder_name": folder_name,
        "manifest_name": f"{base}.json",
        "files": files,
    }


async def enqueue_session(session_id: str, photos: list[str], video: str | None,
                          created_at: datetime | None = None,
                          event_folder: str | None = None,
                          session_folder: str | None = None) -> None:
    """Persist a complete local session for background delivery."""
    _queue_load()
    if event_folder is None:
        from .config import load_event_config
        folder_name = str(load_event_config().get("yadisk_folder") or "").strip().strip("/")
    else:
        folder_name = str(event_folder).strip().strip("/")
    if not folder_name or any(part in ("", ".", "..") for part in folder_name.split("/")):
        raise ValueError("yadisk_folder is missing or invalid")
    job = build_session_job(
        session_id, photos, video, created_at=created_at,
        event_folder="/" + folder_name, session_folder=session_folder)
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
    for path in (target, sessions_root(target)):
        if not await _ensure_directory(path):
            raise RuntimeError(f"не удалось создать папку {path}")
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
        paths = [_folder, sessions_root(_folder)]
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


async def _publish_directory(path: str) -> str | None:
    """Publish a folder and return its stable public Yandex.Disk URL."""
    try:
        async with _session.put(
            f"{API}/resources/publish", params={"path": path},
        ) as response:
            # 409 is harmless for an already-published resource; the metadata
            # read below is the source of truth for whether a URL exists.
            if response.status not in (200, 201, 409):
                log.warning(
                    f"YaDisk: publish directory {path}: {response.status} "
                    f"{await response.text()}"
                )
                return None

        for attempt in range(5):
            async with _session.get(
                f"{API}/resources",
                params={"path": path, "fields": "public_url"},
            ) as response:
                if response.status == 200:
                    public_url = str((await response.json()).get("public_url") or "")
                    if public_url:
                        return public_url
                elif response.status not in (404, 423):
                    log.warning(
                        f"YaDisk: read public URL {path}: {response.status} "
                        f"{await response.text()}"
                    )
                    return None
            await asyncio.sleep(min(attempt + 1, 3))
        log.warning(f"YaDisk: public URL did not appear for {path}")
        return None
    except Exception as exc:
        log.warning(f"YaDisk: publish directory {path} failed: {exc}")
        return None


async def prepare_session_share(session_id: str, created_at: datetime,
                                event_folder: str | None = None,
                                session_folder: str | None = None) -> str | None:
    """Publish an empty sibling session folder so its QR can be prepared early."""
    folder = "/" + str(event_folder or _folder).strip().strip("/")
    folder_name = session_folder or session_folder_name(session_id, created_at)
    if (folder == "/" or not folder_name or "/" in folder_name
            or "\\" in folder_name):
        log.warning("YaDisk: cannot prepare session share: invalid folder")
        return None
    if not await _connect():
        log.warning(f"YaDisk: cannot prepare QR folder for session {session_id}: offline")
        return None

    session_path = f"{sessions_root(folder)}/{folder_name}"
    if not await _ensure_directory(session_path):
        return None
    public_url = await _publish_directory(session_path)
    if public_url:
        _prepared_links[session_id] = public_url
        while len(_prepared_links) > 100:
            _prepared_links.pop(next(iter(_prepared_links)))
        log.info(
            "YaDisk: session %s QR prepared before media path=%s",
            session_id,
            session_path,
        )
        await _notify_session_link(session_id, public_url)
    return public_url


async def _resource_size_matches(remote_path: str, size: int,
                                 attempts: int = 10) -> bool:
    """Wait until an uploaded resource is visible with its expected size."""
    for attempt in range(attempts):
        try:
            async with _session.get(
                f"{API}/resources",
                params={"path": remote_path, "fields": "size"},
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("size") == size:
                        if attempt:
                            log.info(
                                "YaDisk: metadata visible path=%s after %d checks",
                                remote_path,
                                attempt + 1,
                            )
                        return True
                elif response.status not in (404, 423):
                    log.warning(f"YaDisk: verify {remote_path}: {response.status} "
                                f"{await response.text()}")
                    return False
        except Exception as exc:
            log.warning(f"YaDisk: verify {remote_path} failed: {exc}")
            return False
        if attempt + 1 < attempts:
            await asyncio.sleep(min(1 + attempt, 5))
    return False


async def _upload_path(local_path: Path, remote_path: str) -> tuple[bool, dict]:
    size = local_path.stat().st_size
    total_started = time.monotonic()
    log.info(
        "YaDisk: file upload started name=%s size=%.2f MiB",
        local_path.name,
        size / 1048576,
    )
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

        transfer_started = time.monotonic()
        with local_path.open("rb") as source:
            async with _transfer_session.put(href, data=source) as upload_response:
                if upload_response.status not in (201, 202):
                    log.warning(f"YaDisk: upload {remote_path}: {upload_response.status} "
                                f"{await upload_response.text()}")
                    return False, {}
        transfer_seconds = max(time.monotonic() - transfer_started, 0.001)

        verify_started = time.monotonic()
        if not await _resource_size_matches(remote_path, size):
            log.warning(f"YaDisk: uploaded file did not verify: {remote_path}")
            return False, {}
        verify_seconds = time.monotonic() - verify_started
        log.info(
            "YaDisk: file upload complete name=%s size=%.2f MiB "
            "transfer=%.2fs speed=%.2f MiB/s verify=%.2fs total=%.2fs",
            local_path.name,
            size / 1048576,
            transfer_seconds,
            size / 1048576 / transfer_seconds,
            verify_seconds,
            time.monotonic() - total_started,
        )
        return True, {"size": size}
    except Exception as exc:
        log.warning(f"YaDisk: upload {remote_path} failed: {exc}")
        return False, {}


async def _upload_bytes(data: bytes, remote_path: str) -> bool:
    total_started = time.monotonic()
    log.info(
        "YaDisk: manifest upload started path=%s size=%d bytes",
        remote_path,
        len(data),
    )
    try:
        async with _session.get(
            f"{API}/resources/upload",
            params={"path": remote_path, "overwrite": "true"},
        ) as response:
            if response.status != 200:
                log.warning(f"YaDisk: manifest URL: {response.status} {await response.text()}")
                return False
            href = (await response.json())["href"]
        transfer_started = time.monotonic()
        async with _transfer_session.put(href, data=data) as upload_response:
            if upload_response.status not in (201, 202):
                log.warning(f"YaDisk: manifest upload: {upload_response.status} "
                            f"{await upload_response.text()}")
                return False
        transfer_seconds = time.monotonic() - transfer_started
        verify_started = time.monotonic()
        verified = await _resource_size_matches(remote_path, len(data))
        verify_seconds = time.monotonic() - verify_started
        if not verified:
            log.warning("YaDisk: manifest did not verify path=%s", remote_path)
            return False
        log.info(
            "YaDisk: manifest upload complete path=%s transfer=%.2fs "
            "verify=%.2fs total=%.2fs",
            remote_path,
            transfer_seconds,
            verify_seconds,
            time.monotonic() - total_started,
        )
        return True
    except Exception as exc:
        log.warning(f"YaDisk: manifest upload failed: {exc}")
        return False


async def _wait_operation(href: str) -> bool:
    for _ in range(120):
        try:
            async with _session.get(href) as response:
                if response.status != 200:
                    log.warning(
                        f"YaDisk: copy operation status: {response.status} "
                        f"{await response.text()}"
                    )
                    return False
                status = (await response.json()).get("status")
        except Exception as exc:
            log.warning(f"YaDisk: copy operation status failed: {exc}")
            return False
        if status == "success":
            return True
        if status == "failed":
            return False
        await asyncio.sleep(1)
    log.warning("YaDisk: copy operation timed out")
    return False


async def _copy_path(source_path: str, destination_path: str) -> bool:
    """Copy inside Yandex.Disk and wait for completion without metadata reads."""
    started = time.monotonic()
    try:
        async with _session.post(
            f"{API}/resources/copy",
            params={
                "from": source_path,
                "path": destination_path,
                "overwrite": "true",
            },
        ) as response:
            if response.status == 201:
                log.info(
                    "YaDisk: server copy complete path=%s in %.2fs",
                    destination_path,
                    time.monotonic() - started,
                )
                return True
            if response.status == 202:
                body = await response.json()
                href = body.get("href")
                copied = bool(href and await _wait_operation(href))
                log.info(
                    "YaDisk: async server copy %s path=%s in %.2fs",
                    "complete" if copied else "failed",
                    destination_path,
                    time.monotonic() - started,
                )
                return copied
            log.warning(
                f"YaDisk: copy {source_path} -> {destination_path}: "
                f"{response.status} {await response.text()}"
            )
            return False
    except Exception as exc:
        log.warning(
            f"YaDisk: copy {source_path} -> {destination_path} failed: {exc}"
        )
        return False


async def _upload_job(job: dict) -> bool:
    job_started = time.monotonic()
    event_folder = job.get("event_folder") or _folder
    folder_name = job.get("session_folder_name") or _legacy_session_folder_name(job)
    session_root = sessions_root(event_folder)
    session_folder = f"{session_root}/{folder_name}"
    for path in (event_folder, session_root, session_folder, f"{_bus_root}/to_vps"):
        if not await _ensure_directory(path):
            return False

    total_files = len(job["files"])
    total_size = sum(
        Path(entry["local_path"]).stat().st_size
        for entry in job["files"]
        if Path(entry["local_path"]).is_file()
    )
    media_started = time.monotonic()
    log.info(
        "YaDisk: session %s media upload started files=%d size=%.2f MiB",
        job["session_id"],
        total_files,
        total_size / 1048576,
    )
    manifest_files = []
    for file_number, entry in enumerate(job["files"], start=1):
        local_path = Path(entry["local_path"])
        if not local_path.is_file():
            log.error(f"YaDisk: local session file disappeared: {local_path}")
            return False
        session_path = f"{session_folder}/{entry['session_name']}"
        size = local_path.stat().st_size
        already_uploaded = (
            entry.get("session_uploaded") is True
            and entry.get("size") == size
            and await _resource_size_matches(session_path, size, attempts=1)
        )
        if already_uploaded:
            metadata = {"size": size}
            log.info(
                "YaDisk: session %s file %d/%d already uploaded name=%s; skipped",
                job["session_id"],
                file_number,
                total_files,
                entry["session_name"],
            )
        else:
            log.info(
                "YaDisk: session %s uploading file %d/%d name=%s",
                job["session_id"],
                file_number,
                total_files,
                entry["session_name"],
            )
            ok, metadata = await _upload_path(local_path, session_path)
            if not ok:
                return False
            entry["size"] = metadata["size"]
            entry.pop("md5", None)
            entry["session_uploaded"] = True
            await _persist_job(job)

        manifest_entry = {key: value for key, value in entry.items()
                          if key not in ("local_path", "session_name",
                                         "session_uploaded")}
        manifest_entry.pop("md5", None)
        manifest_entry.update(metadata)
        manifest_files.append(manifest_entry)

    log.info(
        "YaDisk: session %s media upload complete files=%d size=%.2f MiB in %.2fs",
        job["session_id"],
        total_files,
        total_size / 1048576,
        time.monotonic() - media_started,
    )

    # Reuse the URL prepared during template selection. If that early attempt
    # failed, publish now as a fallback before secondary flat copies start.
    public_url = str(job.get("public_url") or _prepared_links.get(job["session_id"]) or "")
    if not public_url:
        public_url = str(await _publish_directory(session_folder) or "")
        if not public_url:
            return False
    if job.get("public_url") != public_url:
        job["public_url"] = public_url
        await _persist_job(job)
    log.info(
        "YaDisk: session %s QR folder ready path=%s",
        job["session_id"],
        session_folder,
    )
    await _notify_session_link(job["session_id"], public_url)

    copies_started = time.monotonic()
    for entry in job["files"]:
        session_path = f"{session_folder}/{entry['session_name']}"
        root_path = f"{event_folder}/{entry['name']}"
        log.info(
            "YaDisk: session %s copying %s into event root",
            job["session_id"],
            entry["session_name"],
        )
        if not await _copy_path(session_path, root_path):
            return False
    log.info(
        "YaDisk: session %s server copies complete files=%d in %.2fs",
        job["session_id"],
        total_files,
        time.monotonic() - copies_started,
    )

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

    _prepared_links.pop(job["session_id"], None)
    log.info(
        "YaDisk: session %s published files=%d total=%.2fs",
        job["session_id"],
        len(manifest_files),
        time.monotonic() - job_started,
    )
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
