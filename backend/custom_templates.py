"""Synchronize user-managed template packs before the backend starts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

from collections.abc import Callable
from pathlib import Path

from .ca import ca_context

API = "https://cloud-api.yandex.net/v1/disk"
REMOTE_ROOT = "/photobooth_system/templates_custom"
STATE_FILE = ".pack_state.json"
USER_AGENT = "photobooth-custom-templates/1"
MAX_FILES_PER_PACK = 200
MAX_FILE_SIZE = 512 * 1024 * 1024
MAX_PACK_SIZE = 1024 * 1024 * 1024

StatusCallback = Callable[[str], None]


def _raise_if_cancelled(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("custom template sync cancelled")


def _request_json(method: str, url: str, token: str, **params) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        method=method,
        headers={"Authorization": f"OAuth {token}", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30, context=ca_context()) as response:
        raw = response.read()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Yandex.Disk returned invalid JSON")
    return payload


def _ensure_remote_root(token: str, remote_root: str, cancel_event=None) -> None:
    current = ""
    for part in remote_root.strip("/").split("/"):
        _raise_if_cancelled(cancel_event)
        current += "/" + part
        try:
            _request_json("PUT", f"{API}/resources", token, path=current)
        except urllib.error.HTTPError as exc:
            if exc.code != 409:
                raise


def _list_directory(path: str, token: str, cancel_event=None) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        _raise_if_cancelled(cancel_event)
        payload = _request_json(
            "GET", f"{API}/resources", token,
            path=path, limit=1000, offset=offset,
        )
        embedded = payload.get("_embedded")
        page = embedded.get("items") if isinstance(embedded, dict) else None
        if not isinstance(page, list):
            raise ValueError(f"invalid Yandex.Disk directory listing: {path}")
        items.extend(item for item in page if isinstance(item, dict))
        _raise_if_cancelled(cancel_event)
        if len(page) < 1000:
            return items
        offset += len(page)


def _safe_name(value) -> str:
    name = str(value or "")
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"unsafe Yandex.Disk entry name: {name!r}")
    return name


def _pack_files(remote_pack: str, token: str, cancel_event=None) -> dict[str, dict]:
    files: dict[str, dict] = {}

    def walk(remote_dir: str, relative_dir: str = "") -> None:
        for item in _list_directory(remote_dir, token, cancel_event):
            _raise_if_cancelled(cancel_event)
            name = _safe_name(item.get("name"))
            relative = f"{relative_dir}/{name}" if relative_dir else name
            item_type = item.get("type")
            if item_type == "dir":
                walk(f"{remote_dir}/{name}", relative)
                continue
            if item_type != "file":
                raise ValueError(f"unsupported resource type in {remote_pack}: {name}")
            size = item.get("size")
            digest = item.get("md5")
            if (not isinstance(size, int) or size < 0 or size > MAX_FILE_SIZE
                    or not isinstance(digest, str) or len(digest) != 32):
                raise ValueError(f"invalid file metadata in {remote_pack}: {relative}")
            files[relative] = {
                "size": size,
                "md5": digest.lower(),
                "remote_path": f"{remote_dir}/{name}",
            }
            if len(files) > MAX_FILES_PER_PACK:
                raise ValueError(f"too many files in custom pack {remote_pack}")

    walk(remote_pack)
    if sum(item["size"] for item in files.values()) > MAX_PACK_SIZE:
        raise ValueError(f"custom pack is too large: {remote_pack}")
    return files


def _download_file(
    remote: dict,
    destination: Path,
    token: str,
    on_progress: Callable[[int, float], None] | None = None,
    cancel_event=None,
) -> None:
    _raise_if_cancelled(cancel_event)
    payload = _request_json(
        "GET", f"{API}/resources/download", token,
        path=remote["remote_path"],
    )
    href = payload.get("href")
    if not isinstance(href, str) or not href.startswith(("http://", "https://")):
        raise ValueError("Yandex.Disk returned an invalid download URL")
    request = urllib.request.Request(href, headers={"User-Agent": USER_AGENT})
    digest = hashlib.md5()
    total = 0
    started = time.monotonic()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with urllib.request.urlopen(
                request, timeout=60, context=ca_context()) as response, \
                temporary.open("wb") as output:
            while True:
                _raise_if_cancelled(cancel_event)
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                _raise_if_cancelled(cancel_event)
                total += len(chunk)
                if total > remote["size"]:
                    raise ValueError("custom template file exceeds declared size")
                digest.update(chunk)
                output.write(chunk)
                if on_progress:
                    elapsed = max(time.monotonic() - started, 0.001)
                    on_progress(total, total / elapsed)
        if total != remote["size"] or digest.hexdigest() != remote["md5"]:
            raise ValueError("custom template file checksum mismatch")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _read_state(pack_dir: Path) -> dict[str, dict]:
    try:
        payload = json.loads((pack_dir / STATE_FILE).read_text(encoding="utf-8"))
        files = payload.get("files") if isinstance(payload, dict) else None
        return files if isinstance(files, dict) else {}
    except (OSError, ValueError):
        return {}


def _state_matches(pack_dir: Path, local: dict, remote: dict) -> bool:
    expected = {
        name: {"size": item["size"], "md5": item["md5"]}
        for name, item in remote.items()
    }
    if local != expected:
        return False
    return all(
        (pack_dir / name).is_file()
        and (pack_dir / name).stat().st_size == item["size"]
        for name, item in remote.items()
    )


def _sync_pack(
    name: str,
    remote: dict[str, dict],
    custom_root: Path,
    stage_root: Path,
    token: str,
    num_photos: int,
    default_template: str,
    on_progress: StatusCallback | None = None,
    cancel_event=None,
) -> bool:
    from .composer import load_template_pack

    _raise_if_cancelled(cancel_event)
    destination = custom_root / name
    old_state = _read_state(destination)
    if _state_matches(destination, old_state, remote):
        return False

    stage = stage_root / name
    if destination.is_dir():
        shutil.copytree(destination, stage)
    else:
        stage.mkdir(parents=True)

    for path in sorted(stage.rglob("*"), reverse=True):
        if path.is_file() and path.name != STATE_FILE:
            relative = path.relative_to(stage).as_posix()
            if relative not in remote:
                path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass

    downloads = []
    for relative, metadata in remote.items():
        target = stage / relative
        old = old_state.get(relative)
        if not (
            old == {"size": metadata["size"], "md5": metadata["md5"]}
            and target.is_file()
            and target.stat().st_size == metadata["size"]
        ):
            downloads.append((metadata, target))

    download_total = sum(metadata["size"] for metadata, _ in downloads)
    downloaded = 0
    last_ui_time = 0.0

    def report_progress(current: int, speed: float, *, force: bool = False) -> None:
        nonlocal last_ui_time
        if not on_progress:
            return
        now = time.monotonic()
        total_downloaded = downloaded + current
        if not force and total_downloaded < download_total and now - last_ui_time < 0.25:
            return
        if total_downloaded <= 0:
            on_progress(f"{name}: Подключение к Яндекс Диску")
        else:
            percent = min(
                100,
                round(total_downloaded * 100 / max(download_total, 1)),
            )
            on_progress(
                f"{name}: Скачивание {percent}% · "
                f"{total_downloaded / 1048576:.2f}/"
                f"{download_total / 1048576:.2f} МБ · "
                f"{speed / 1048576:.2f} МБ/с"
            )
        last_ui_time = now

    if downloads:
        report_progress(0, 0, force=True)
    for metadata, target in downloads:
        _raise_if_cancelled(cancel_event)
        if cancel_event is not None:
            _download_file(
                metadata, target, token,
                on_progress=report_progress if on_progress else None,
                cancel_event=cancel_event,
            )
        elif on_progress:
            _download_file(metadata, target, token, report_progress)
        else:
            _download_file(metadata, target, token)
        downloaded += metadata["size"]

    _raise_if_cancelled(cancel_event)
    state = {
        "files": {
            name: {"size": item["size"], "md5": item["md5"]}
            for name, item in sorted(remote.items())
        }
    }
    (stage / STATE_FILE).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    load_template_pack(stage, num_photos, default_template)

    backup = custom_root / f".{name}.backup.{os.getpid()}"
    shutil.rmtree(backup, ignore_errors=True)
    if destination.exists():
        destination.replace(backup)
    try:
        stage.replace(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    shutil.rmtree(backup, ignore_errors=True)
    return True


def sync_custom_templates(
    custom_root: Path,
    *,
    num_photos: int,
    default_template: str,
    remote_root: str = REMOTE_ROOT,
    on_status: StatusCallback | None = None,
    on_progress: StatusCallback | None = None,
    cancel_event=None,
) -> dict[str, int]:
    """Mirror valid remote packs into a local cache; never replace one partially."""
    from .config import TEMPLATE_PACK_RE

    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        return {"updated": 0, "removed": 0, "failed": 0}
    remote_root = "/" + remote_root.strip("/")
    custom_root.mkdir(parents=True, exist_ok=True)
    _raise_if_cancelled(cancel_event)
    try:
        root_items = _list_directory(remote_root, token, cancel_event)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        _ensure_remote_root(token, remote_root, cancel_event)
        root_items = []

    snapshots: dict[str, dict[str, dict]] = {}
    failed = 0
    for item in root_items:
        _raise_if_cancelled(cancel_event)
        if item.get("type") != "dir":
            continue
        name = _safe_name(item.get("name"))
        if not TEMPLATE_PACK_RE.fullmatch(name):
            failed += 1
            if on_status:
                on_status(f"Пропущена папка с некорректным именем: {name}")
            continue
        try:
            if on_progress:
                on_progress(f"{name}: проверка файлов...")
            snapshots[name] = _pack_files(
                f"{remote_root}/{name}", token, cancel_event)
        except InterruptedError:
            raise
        except Exception as exc:
            failed += 1
            if on_status:
                on_status(f"Не удалось прочитать шаблон {name}: {exc}")

    remote_names = {
        _safe_name(item.get("name"))
        for item in root_items
        if item.get("type") == "dir"
        and TEMPLATE_PACK_RE.fullmatch(str(item.get("name") or ""))
    }
    local_names = {
        path.name for path in custom_root.iterdir()
        if path.is_dir() and TEMPLATE_PACK_RE.fullmatch(path.name)
    }
    changed_names = {
        name for name, files in snapshots.items()
        if not _state_matches(custom_root / name, _read_state(custom_root / name), files)
    }
    if on_status:
        if snapshots or local_names - remote_names:
            on_status("Кастомные шаблоны:")
            for name in sorted(snapshots):
                action = "↓" if name in changed_names else "✓"
                state = "скачать" if name in changed_names else "актуально"
                on_status(f"{action} {name} — {state}")
            for name in sorted(local_names - remote_names):
                on_status(f"− {name} — удалить")
        else:
            on_status("Кастомных шаблонов нет")

    updated = 0
    stage_root = custom_root / f".sync.{os.getpid()}"
    shutil.rmtree(stage_root, ignore_errors=True)
    stage_root.mkdir()
    try:
        for name, files in snapshots.items():
            _raise_if_cancelled(cancel_event)
            try:
                if _sync_pack(
                    name, files, custom_root, stage_root, token,
                    num_photos, default_template,
                    on_progress=on_progress,
                    cancel_event=cancel_event,
                ):
                    updated += 1
                    if on_status:
                        on_status(f"Обновлён кастомный шаблон: {name}")
            except InterruptedError:
                raise
            except Exception as exc:
                failed += 1
                if on_status:
                    on_status(f"Кастомный шаблон {name} оставлен без изменений: {exc}")
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)

    removed = 0
    for path in custom_root.iterdir():
        _raise_if_cancelled(cancel_event)
        if path.is_dir() and TEMPLATE_PACK_RE.fullmatch(path.name) and path.name not in remote_names:
            shutil.rmtree(path)
            removed += 1
            if on_status:
                on_status(f"Удалён кастомный шаблон: {path.name}")
    return {"updated": updated, "removed": removed, "failed": failed}
