"""Stable VPS-to-booth Yandex.Disk command channel."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import aiohttp

log = logging.getLogger(__name__)

API = "https://cloud-api.yandex.net/v1/disk"
# Use the desktop-client User-Agent workaround. Generic REST client user
# agents can receive heavily throttled uploader URLs for some file types.
YADISK_API_USER_AGENT = 'Yandex.Disk {"os":"windows"}'
SCHEMA_VERSION = 3
POLL_INTERVAL = 5
PAGE_SIZE = 100
# Normal snapshots are about 400 KB.  The larger ceiling allows one legacy
# 1 MB segment to be delivered immediately after upgrading the rotation size.
MAX_LOG_ARTIFACT_SIZE = 2 * 1024 * 1024
MAX_CONFIG_EXPORT_SIZE = 512 * 1024
MAX_PRINT_ARTIFACT_SIZE = 20 * 1024 * 1024
COMMAND_ID_RE = re.compile(r"^[a-f0-9]{32}$")
# An administrator notice is not a reply to a command, so it carries its own
# name pattern and a hard cap on how many may wait in to_vps.
MAX_BOOTH_NOTICE_TEXT = 3500
MAX_BOOTH_NOTICES = 20
BOOTH_NOTICE_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
BOOTH_NOTICE_NAME_RE = re.compile(
    r"^notice_[0-9]{8}T[0-9]{6}Z_[a-f0-9]{32}\.json$")
PRINT_ARTIFACT_NAME_RE = re.compile(
    r"^[0-9]{1,20}_[0-9]{8}T[0-9]{6}Z_[a-f0-9]{32}"
    r"\.[a-z0-9]{1,10}$")
REPLY_PROVIDERS = frozenset({"telegram", "vk"})

_session: aiohttp.ClientSession | None = None
_transfer_session: aiohttp.ClientSession | None = None
_root = ""
_token = ""
_configured = False


@dataclass(frozen=True)
class ReplyTarget:
    """Provider-neutral destination carried through the control protocol."""

    provider: str
    conversation_id: str | int

    def __post_init__(self) -> None:
        provider = str(self.provider or "").strip().lower()
        if provider not in REPLY_PROVIDERS:
            raise ValueError(
                f"unsupported reply provider: {provider or '<empty>'}")
        if (not isinstance(self.conversation_id, (str, int))
                or isinstance(self.conversation_id, bool)):
            raise ValueError("reply conversation_id must be a string or integer")
        conversation_id = str(self.conversation_id).strip()
        if not conversation_id:
            raise ValueError("reply conversation_id is required")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "conversation_id", conversation_id)

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "conversation_id": self.conversation_id,
        }

    @classmethod
    def from_value(cls, value: Any) -> ReplyTarget:
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise ValueError("reply_target must be an object")
        return cls(
            provider=value.get("provider", ""),
            conversation_id=value.get("conversation_id", ""),
        )


@dataclass(frozen=True)
class _PendingCommandResult:
    """A completed command whose response has not been acknowledged yet.

    The command file stays in ``to_booth`` when uploading its response fails.
    Without this cache the next poll would execute the handler again, which is
    unsafe for commands such as queue purge and also replaces their original
    before/after report with the result of the repeated operation.
    """

    fingerprint: str
    response: dict
    post_action: Callable[[], Awaitable[None]] | None


_pending_command_results: dict[str, _PendingCommandResult] = {}


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
    reply_target = ReplyTarget.from_value(data.get("reply_target"))
    return {
        "schema_version": SCHEMA_VERSION,
        "message_type": "command",
        "command_id": command_id,
        "command": command,
        "data": command_data,
        "created_at": str(data.get("created_at", "")),
        "reply_target": reply_target.to_dict(),
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
        headers={
            "Authorization": f"OAuth {_token}",
            "User-Agent": YADISK_API_USER_AGENT,
        },
        timeout=aiohttp.ClientTimeout(total=60, connect=15),
    )
    _transfer_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=120, connect=20),
        # Match urllib updater: honour the Windows/system proxy for CDN links.
        trust_env=True,
    )
    try:
        current = ""
        for part in _root.strip("/").split("/"):
            current += "/" + part
            await _ensure_directory(current)
        for suffix in ("to_booth", "to_vps", "logs", "configs"):
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


async def upload_config_export(command_id: str, payload: bytes) -> str:
    if (not COMMAND_ID_RE.fullmatch(command_id)
            or not isinstance(payload, bytes)
            or not payload
            or len(payload) > MAX_CONFIG_EXPORT_SIZE):
        raise ValueError("invalid config export upload")
    if not await _connect():
        raise RuntimeError("Yandex.Disk control is unavailable")
    remote_path = f"{_root}/configs/{command_id}.txt"
    await _upload_bytes(payload, remote_path)
    return remote_path


async def _prune_booth_notices(keep: int = MAX_BOOTH_NOTICES) -> None:
    """Drop the oldest unread notices so they cannot accumulate forever.

    A notice is addressed to the administrator rather than to a command, so a
    VPS that does not yet understand ``booth_notice`` simply ignores the file.
    Pruning keeps that situation bounded instead of filling ``to_vps``.
    """
    names: list[str] = []
    offset = 0
    while True:
        async with _session.get(
            f"{API}/resources",
            params={
                "path": f"{_root}/to_vps",
                "limit": PAGE_SIZE,
                "offset": offset,
                "fields": "_embedded.items.name,_embedded.items.type",
            },
        ) as response:
            if response.status != 200:
                return
            items = (await response.json()).get("_embedded", {}).get("items", [])
        for item in items:
            name = str(item.get("name", ""))
            if item.get("type") == "file" and BOOTH_NOTICE_NAME_RE.fullmatch(name):
                names.append(name)
        if len(items) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    # Names embed a UTC timestamp, so lexical order is chronological.
    for name in sorted(names)[:max(len(names) - keep + 1, 0)]:
        async with _session.delete(
            f"{API}/resources",
            params={"path": f"{_root}/to_vps/{name}", "permanently": "true"},
        ) as response:
            if response.status not in (202, 204, 404):
                log.warning(
                    "Control: could not prune notice %s: %s", name, response.status)


async def publish_booth_notice(kind: str, title: str, text: str) -> str:
    """Publish an unsolicited administrator notice into ``control/to_vps``.

    The booth holds no Telegram/VK credentials, so the VPS delivers this to the
    administrator. There is no ``reply_target``: the message is not an answer to
    any command, so the VPS uses its own configured administrator address.
    """
    if not isinstance(kind, str) or not BOOTH_NOTICE_KIND_RE.fullmatch(kind):
        raise ValueError("invalid notice kind")
    body = str(text or "")
    if len(body) > MAX_BOOTH_NOTICE_TEXT:
        body = body[:MAX_BOOTH_NOTICE_TEXT - 3] + "..."
    if not await _connect():
        raise RuntimeError("Yandex.Disk control is unavailable")
    created_at = datetime.now(timezone.utc)
    notice = {
        "schema_version": SCHEMA_VERSION,
        "message_type": "booth_notice",
        "notice_id": uuid.uuid4().hex,
        "kind": kind,
        "title": str(title or ""),
        "text": body,
        "created_at": created_at.isoformat(),
    }
    payload = json.dumps(
        notice, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    remote_path = (
        f"{_root}/to_vps/notice_"
        f"{created_at.strftime('%Y%m%dT%H%M%SZ')}_{notice['notice_id']}.json"
    )
    try:
        await _prune_booth_notices()
    except Exception as exc:
        log.warning("Control: notice pruning failed: %s", exc)
    await _upload_bytes(payload, remote_path)
    return remote_path


def _validate_print_artifact_path(
    remote_path: str,
    event_folder: str,
) -> str:
    event_name = str(event_folder or "").strip().strip("/")
    if (not event_name or event_name in (".", "..")
            or "/" in event_name or "\\" in event_name
            or any(ord(char) < 32 for char in event_name)
            or len(event_name) > 160):
        raise ValueError("invalid print artifact event")
    prefix = f"/{event_name}_by_sessions/0000_print_jobs/"
    if (not isinstance(remote_path, str)
            or not remote_path.startswith(prefix)
            or "/" in remote_path[len(prefix):]
            or not PRINT_ARTIFACT_NAME_RE.fullmatch(remote_path[len(prefix):])):
        raise ValueError("invalid print artifact path")
    return remote_path


async def download_print_artifact(
    remote_path: str,
    event_folder: str,
) -> bytes:
    if not await _connect():
        raise RuntimeError("Yandex.Disk control is unavailable")
    return await _download_bytes(
        _validate_print_artifact_path(remote_path, event_folder),
        MAX_PRINT_ARTIFACT_SIZE,
    )


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


async def _delete_command(filename: str) -> bool:
    path = f"{_root}/to_booth/{filename}"
    async with _session.delete(
        f"{API}/resources",
        params={"path": path, "permanently": "true"},
    ) as response:
        if response.status in (204, 404):
            return True
        if response.status == 202:
            href = (await response.json()).get("href")
            return bool(href and await _wait_operation(href))
        log.warning(
            "Control: delete command %s: %s %s",
            filename, response.status, await response.text(),
        )
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
        "reply_target": command["reply_target"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    for field in ("start_locked", "unlock_sessions_remaining"):
        if field in result:
            response[field] = result[field]
    return response, post_action


def _command_fingerprint(command: dict) -> str:
    """Identify the exact validated command associated with a cached result."""
    payload = json.dumps(
        command,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _process_command(
    item: dict,
    handler: Callable[[dict], Awaitable[dict]],
) -> bool:
    filename = item["name"]
    remote_path = str(item.get("path", "")).removeprefix("disk:")
    try:
        body = await _download_bytes(remote_path)
    except ValueError as exc:
        # A downloaded artifact that violates the size limit is permanently
        # invalid and must not block the queue forever.
        log.warning(f"Control: invalid command {filename}: {exc}")
        return await _delete_command(filename)
    except Exception as exc:
        # Network/download failures are transient. Keep the command in
        # to_booth so the next polling cycle retries it.
        log.warning(f"Control: command download failed {filename}: {exc}")
        return False

    try:
        command = validate_command(
            json.loads(body.decode("utf-8")), filename)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        log.warning(f"Control: invalid command {filename}: {exc}")
        return await _delete_command(filename)

    command_id = command["command_id"]
    fingerprint = _command_fingerprint(command)
    pending = _pending_command_results.get(command_id)
    if pending is not None and pending.fingerprint != fingerprint:
        # Reusing a command ID for different contents violates the protocol.
        # Never associate the first command's response with another action or
        # execute an ambiguous second action.
        log.error(
            "Control: command ID collision for %s; cached result retained",
            command_id,
        )
        return await _delete_command(filename)

    if pending is None:
        try:
            result = await handler(command)
            if not isinstance(result, dict):
                raise ValueError("command handler returned invalid result")
        except Exception as exc:
            log.exception(f"Control: command {command['command']} failed")
            result = {"status": "error", "message": str(exc)}

        response, post_action = _response(command, result)
        pending = _PendingCommandResult(
            fingerprint=fingerprint,
            response=response,
            post_action=post_action,
        )
        # Store the completed result before the first network write. If that
        # write times out, the command remains remote and the next poll must
        # retry delivery rather than invoke the handler again.
        _pending_command_results[command_id] = pending
    else:
        response = pending.response
        post_action = pending.post_action
        log.info(
            "Control: retrying cached response for %s (%s); "
            "command handler will not run again",
            command["command"],
            command_id,
        )

    payload = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await _upload_bytes(
        payload, f"{_root}/to_vps/response_{command_id}.json")
    if not await _delete_command(filename):
        return False
    _pending_command_results.pop(command_id, None)
    response_message = response["message"].replace("\n", " | ")[:500]
    completed_log = log.info if response["status"] == "ok" else log.warning
    completed_log(
        "Control: completed %s (%s) status=%s message=%s",
        command["command"], command["command_id"],
        response["status"], response_message,
    )
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
