"""Stable VPS-to-booth Yandex.Disk command channel."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable

import aiohttp

log = logging.getLogger(__name__)

API = "https://cloud-api.yandex.net/v1/disk"
SCHEMA_VERSION = 2
POLL_INTERVAL = 10
PAGE_SIZE = 100
# Normal snapshots are about 400 KB.  The larger ceiling allows one legacy
# 1 MB segment to be delivered immediately after upgrading the rotation size.
MAX_LOG_ARTIFACT_SIZE = 2 * 1024 * 1024
COMMAND_ID_RE = re.compile(r"^[a-f0-9]{32}$")

_session: aiohttp.ClientSession | None = None
_transfer_session: aiohttp.ClientSession | None = None
_root = ""
_token = ""
_configured = False


def normalize_folder(folder: str) -> str:
    name = str(folder or "").strip().strip("/")
    if not name or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("invalid Yandex.Disk control folder")
    return "/" + name


def validate_command(data: dict, filename: str = "") -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported command schema")
    if data.get("message_type") != "command":
        raise ValueError("invalid command message_type")
    command_id = data.get("command_id")
    if not isinstance(command_id, str) or not COMMAND_ID_RE.fullmatch(command_id):
        raise ValueError("invalid command_id")
    if filename and filename != f"{command_id}.json":
        raise ValueError("command filename does not match command_id")
    command = data.get("command")
    if not isinstance(command, str) or not command or len(command) > 50:
        raise ValueError("invalid command")
    command_data = data.get("data")
    if command_data is not None and not isinstance(command_data, (dict, str)):
        raise ValueError("invalid command data")
    reply_chat_id = data.get("reply_chat_id")
    if reply_chat_id is not None and not isinstance(reply_chat_id, (int, str)):
        raise ValueError("invalid reply_chat_id")
    return {
        "schema_version": SCHEMA_VERSION,
        "message_type": "command",
        "command_id": command_id,
        "command": command,
        "data": command_data,
        "created_at": str(data.get("created_at", "")),
        "reply_chat_id": reply_chat_id,
    }


async def _close_sessions() -> None:
    global _session, _transfer_session
    if _session and not _session.closed:
        await _session.close()
    if _transfer_session and not _transfer_session.closed:
        await _transfer_session.close()
    _session = None
    _transfer_session = None


async def _ensure_directory(path: str) -> None:
    async with _session.put(f"{API}/resources", params={"path": path}) as response:
        if response.status not in (201, 409):
            raise RuntimeError(
                f"create control directory {path}: {response.status} {await response.text()}")


async def _connect() -> bool:
    global _session, _transfer_session
    if not _configured:
        return False
    if _session and not _session.closed:
        return True
    await _close_sessions()
    _session = aiohttp.ClientSession(
        headers={"Authorization": f"OAuth {_token}"},
        timeout=aiohttp.ClientTimeout(total=60, connect=15),
    )
    _transfer_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=120, connect=20))
    try:
        current = ""
        for part in _root.strip("/").split("/"):
            current += "/" + part
            await _ensure_directory(current)
        for suffix in ("to_booth", "to_vps", "done", "done/to_booth",
                       "done/to_vps", "logs"):
            await _ensure_directory(f"{_root}/{suffix}")
        return True
    except Exception as exc:
        log.warning(f"Control: connection failed: {exc}")
        await _close_sessions()
        return False


async def _list_commands() -> list[dict]:
    result = []
    offset = 0
    path = f"{_root}/to_booth"
    while True:
        params = {
            "path": path,
            "limit": PAGE_SIZE,
            "offset": offset,
            "sort": "name",
            "fields": "_embedded.total,_embedded.items.name,_embedded.items.path,_embedded.items.type",
        }
        async with _session.get(f"{API}/resources", params=params) as response:
            if response.status != 200:
                raise RuntimeError(f"list commands: {response.status} {await response.text()}")
            embedded = (await response.json()).get("_embedded", {})
        items = embedded.get("items", [])
        result.extend(item for item in items
                      if item.get("type") == "file" and item.get("name", "").endswith(".json"))
        offset += len(items)
        if not items or offset >= int(embedded.get("total", offset)):
            return result


async def _download_bytes(remote_path: str, max_size: int = 1024 * 1024) -> bytes:
    async with _session.get(
        f"{API}/resources/download", params={"path": remote_path},
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"get download URL: {response.status} {await response.text()}")
        href = (await response.json())["href"]
    async with _transfer_session.get(href) as response:
        if response.status != 200:
            raise RuntimeError(f"download control file: {response.status} {await response.text()}")
        data = await response.read()
    if len(data) > max_size:
        raise ValueError("control file is too large")
    return data


async def _resource_matches(path: str, payload: bytes) -> bool:
    expected_md5 = hashlib.md5(payload).hexdigest()
    for attempt in range(10):
        async with _session.get(
            f"{API}/resources", params={"path": path, "fields": "size,md5"},
        ) as response:
            if response.status == 200:
                metadata = await response.json()
                if metadata.get("size") == len(payload) and metadata.get("md5") == expected_md5:
                    return True
            elif response.status not in (404, 423):
                return False
        await asyncio.sleep(min(attempt + 1, 3))
    return False


async def _upload_bytes(payload: bytes, remote_path: str) -> None:
    async with _session.get(
        f"{API}/resources/upload",
        params={"path": remote_path, "overwrite": "true"},
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"get upload URL: {response.status} {await response.text()}")
        href = (await response.json())["href"]
    async with _transfer_session.put(href, data=payload) as response:
        if response.status not in (201, 202):
            raise RuntimeError(f"upload control file: {response.status} {await response.text()}")
    if not await _resource_matches(remote_path, payload):
        raise RuntimeError(f"uploaded control file did not verify: {remote_path}")


async def upload_log(command_id: str, payload: bytes) -> str:
    if (not COMMAND_ID_RE.fullmatch(command_id)
            or not isinstance(payload, bytes)
            or len(payload) > MAX_LOG_ARTIFACT_SIZE):
        raise ValueError("invalid log upload")
    if not await _connect():
        raise RuntimeError("Yandex.Disk control is unavailable")
    remote_path = f"{_root}/logs/{command_id}.log"
    await _upload_bytes(payload, remote_path)
    return remote_path


async def _wait_operation(href: str) -> bool:
    for _ in range(30):
        async with _session.get(href) as response:
            if response.status != 200:
                return False
            status = (await response.json()).get("status")
        if status == "success":
            return True
        if status == "failed":
            return False
        await asyncio.sleep(1)
    return False


async def _move_done(filename: str) -> bool:
    params = {
        "from": f"{_root}/to_booth/{filename}",
        "path": f"{_root}/done/to_booth/{filename}",
        "overwrite": "true",
    }
    async with _session.post(f"{API}/resources/move", params=params) as response:
        if response.status == 201:
            return True
        if response.status == 202:
            href = (await response.json()).get("href")
            return bool(href and await _wait_operation(href))
        log.warning(f"Control: move command: {response.status} {await response.text()}")
        return False


def _response(command: dict, result: dict) -> tuple[dict, Callable[[], Awaitable[None]] | None]:
    post_action = result.pop("_post_action", None)
    response = {
        "schema_version": SCHEMA_VERSION,
        "message_type": "command_response",
        "command_id": command["command_id"],
        "command": command["command"],
        "status": result.get("status", "ok"),
        "message": str(result.get("message", "Готово")),
        "artifact_path": result.get("artifact_path"),
        "event_folder": result.get("event_folder"),
        "reply_chat_id": command.get("reply_chat_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return response, post_action


async def _process_command(
    item: dict,
    handler: Callable[[dict], Awaitable[dict]],
) -> bool:
    filename = item["name"]
    remote_path = str(item.get("path", "")).removeprefix("disk:")
    try:
        command = validate_command(
            json.loads((await _download_bytes(remote_path)).decode("utf-8")), filename)
    except Exception as exc:
        log.warning(f"Control: invalid command {filename}: {exc}")
        return await _move_done(filename)

    try:
        result = await handler(command)
        if not isinstance(result, dict):
            raise ValueError("command handler returned invalid result")
    except Exception as exc:
        log.exception(f"Control: command {command['command']} failed")
        result = {"status": "error", "message": str(exc)}

    response, post_action = _response(command, result)
    payload = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await _upload_bytes(
        payload, f"{_root}/to_vps/response_{command['command_id']}.json")
    if not await _move_done(filename):
        return False
    log.info(f"Control: completed {command['command']} ({command['command_id']})")
    if post_action:
        asyncio.create_task(post_action())
    return True


async def control_init(folder: str) -> bool:
    global _root, _token, _configured
    _token = os.environ.get("YADISK_TOKEN", "").strip()
    if not _token:
        log.warning("Control: YADISK_TOKEN not set")
        return False
    _root = normalize_folder(folder)
    _configured = True
    return await _connect()


async def control_poll_loop(handler: Callable[[dict], Awaitable[dict]]) -> None:
    while True:
        try:
            if await _connect():
                for item in await _list_commands():
                    await _process_command(item, handler)
        except Exception as exc:
            log.warning(f"Control: poll failed: {exc}")
            await _close_sessions()
        await asyncio.sleep(POLL_INTERVAL)


async def control_close() -> None:
    await _close_sessions()
