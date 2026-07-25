"""Publish a built photobooth release to Yandex.Disk from GitHub Actions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import aiohttp


API = "https://cloud-api.yandex.net/v1/disk"
IMPORT_ATTEMPTS = 5
IMPORT_BACKOFF_SECONDS = (2, 4, 8, 16)
OPERATION_ATTEMPTS = 300
VERIFY_ATTEMPTS = 12


def log(message: str) -> None:
    print(message, flush=True)


def normalize_folder(value: str) -> str:
    name = str(value or "").strip().strip("/")
    if not name or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("invalid Yandex.Disk updates folder")
    return f"/{name}"


def validate_release(path: Path) -> bytes:
    payload = path.read_bytes()
    if not payload:
        raise ValueError("release ZIP is empty")
    with zipfile.ZipFile(path) as archive:
        failed = archive.testzip()
        if failed:
            raise ValueError(f"release ZIP CRC failed: {failed}")
        names = {name.replace("\\", "/") for name in archive.namelist()}
    if "app.py" not in names:
        raise ValueError("release ZIP does not contain app.py at its root")
    log(
        f"Release validated: {path.name}, {len(payload) / 1048576:.1f} MiB, "
        f"{len(names)} entries"
    )
    return payload


async def response_error(response: aiohttp.ClientResponse) -> str:
    body = (await response.text()).strip()
    return f"HTTP {response.status}" + (f": {body}" if body else "")


async def ensure_directories(session: aiohttp.ClientSession, root: str) -> None:
    current = ""
    for part in root.strip("/").split("/") + ["artifacts"]:
        current += f"/{part}"
        async with session.put(f"{API}/resources", params={"path": current}) as response:
            if response.status not in (201, 409):
                raise RuntimeError(
                    f"cannot create Yandex.Disk directory {current}: "
                    f"{await response_error(response)}"
                )
        log(f"Yandex.Disk directory ready: {current}")


async def wait_operation(
    session: aiohttp.ClientSession,
    href: str,
    label: str,
) -> None:
    for attempt in range(1, OPERATION_ATTEMPTS + 1):
        async with session.get(href) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Yandex.Disk operation {label}: {await response_error(response)}"
                )
            status = (await response.json()).get("status")
        if attempt == 1 or attempt % 5 == 0 or status != "in-progress":
            log(f"Yandex.Disk operation {label}: {status} ({attempt}/{OPERATION_ATTEMPTS})")
        if status == "success":
            return
        if status == "failed":
            raise RuntimeError(f"Yandex.Disk operation failed: {label}")
        await asyncio.sleep(1)
    raise TimeoutError(f"Yandex.Disk operation timed out: {label}")


async def resource_matches(
    session: aiohttp.ClientSession,
    path: str,
    expected_size: int,
    expected_md5: str,
) -> bool:
    for attempt in range(1, VERIFY_ATTEMPTS + 1):
        async with session.get(
            f"{API}/resources",
            params={"path": path, "fields": "size,md5"},
        ) as response:
            if response.status == 200:
                metadata = await response.json()
                if (metadata.get("size") == expected_size
                        and metadata.get("md5") == expected_md5):
                    log(
                        f"Verified {path}: size={expected_size}, md5={expected_md5} "
                        f"({attempt}/{VERIFY_ATTEMPTS})"
                    )
                    return True
            elif response.status not in (404, 423):
                raise RuntimeError(
                    f"cannot verify {path}: {await response_error(response)}"
                )
        await asyncio.sleep(min(attempt, 5))
    return False


async def delete_staging(session: aiohttp.ClientSession, path: str) -> None:
    try:
        async with session.delete(
            f"{API}/resources",
            params={"path": path, "permanently": "true"},
        ) as response:
            if response.status not in (202, 204, 404):
                log(f"Warning: cannot remove staging {path}: {await response_error(response)}")
    except Exception as exc:
        log(f"Warning: staging cleanup failed for {path}: {exc}")


async def move_overwrite(
    session: aiohttp.ClientSession,
    source: str,
    destination: str,
) -> None:
    async with session.post(
        f"{API}/resources/move",
        params={"from": source, "path": destination, "overwrite": "true"},
    ) as response:
        if response.status == 201:
            return
        if response.status != 202:
            raise RuntimeError(
                f"cannot move imported artifact: {await response_error(response)}"
            )
        href = (await response.json()).get("href")
    if not href:
        raise RuntimeError("Yandex.Disk move did not return operation URL")
    await wait_operation(session, href, "move imported release")


async def import_release_url(
    session: aiohttp.ClientSession,
    source_url: str,
    destination: str,
    expected_size: int,
    expected_md5: str,
) -> None:
    parent, filename = destination.rsplit("/", 1)
    staging = f"{parent}/.{filename}.{uuid.uuid4().hex}.incoming.zip"
    moved = False
    try:
        async with session.post(
            f"{API}/resources/upload",
            params={
                "url": source_url,
                "path": staging,
                "disable_redirects": "false",
            },
        ) as response:
            if response.status != 202:
                raise RuntimeError(
                    f"server-side import rejected: {await response_error(response)}"
                )
            href = (await response.json()).get("href")
        if not href:
            raise RuntimeError("server-side import did not return operation URL")
        await wait_operation(session, href, "import GitHub release URL")
        if not await resource_matches(session, staging, expected_size, expected_md5):
            raise RuntimeError("imported staging artifact did not match local release")
        await move_overwrite(session, staging, destination)
        moved = True
        if not await resource_matches(
            session, destination, expected_size, expected_md5,
        ):
            raise RuntimeError("published imported artifact did not verify")
    finally:
        if not moved:
            await delete_staging(session, staging)


async def upload_file(
    api_session: aiohttp.ClientSession,
    transfer_session: aiohttp.ClientSession,
    destination: str,
    source_path: Path,
    expected_size: int,
    expected_md5: str,
) -> None:
    async with api_session.get(
        f"{API}/resources/upload",
        params={"path": destination, "overwrite": "true"},
    ) as response:
        if response.status != 200:
            raise RuntimeError(
                f"cannot request upload URL for {destination}: "
                f"{await response_error(response)}"
            )
        href = (await response.json()).get("href")
    if not href:
        raise RuntimeError(f"upload URL is missing for {destination}")
    started = time.monotonic()
    with source_path.open("rb") as source:
        async with transfer_session.put(href, data=source) as response:
            if response.status not in (201, 202):
                raise RuntimeError(
                    f"direct upload failed for {destination}: "
                    f"{await response_error(response)}"
                )
    log(
        f"Direct upload complete: {destination}, "
        f"{expected_size / 1048576:.1f} MiB in {time.monotonic() - started:.1f}s"
    )
    if not await resource_matches(
        api_session, destination, expected_size, expected_md5,
    ):
        raise RuntimeError(f"directly uploaded artifact did not verify: {destination}")


async def upload_bytes(
    api_session: aiohttp.ClientSession,
    transfer_session: aiohttp.ClientSession,
    destination: str,
    payload: bytes,
) -> None:
    async with api_session.get(
        f"{API}/resources/upload",
        params={"path": destination, "overwrite": "true"},
    ) as response:
        if response.status != 200:
            raise RuntimeError(
                f"cannot request upload URL for {destination}: "
                f"{await response_error(response)}"
            )
        href = (await response.json()).get("href")
    if not href:
        raise RuntimeError(f"upload URL is missing for {destination}")
    async with transfer_session.put(href, data=payload) as response:
        if response.status not in (201, 202):
            raise RuntimeError(
                f"upload failed for {destination}: {await response_error(response)}"
            )
    if not await resource_matches(
        api_session,
        destination,
        len(payload),
        hashlib.md5(payload).hexdigest(),
    ):
        raise RuntimeError(f"uploaded resource did not verify: {destination}")


def write_action_outputs(sha256: str, size: int, method: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"sha256={sha256}\n")
        output.write(f"size_mib={size / 1048576:.1f}\n")
        output.write(f"method={method}\n")


async def publish(args) -> None:
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        raise RuntimeError("YADISK_TOKEN is not configured")
    source_path = Path(args.file).resolve()
    payload = validate_release(source_path)
    size = len(payload)
    md5 = hashlib.md5(payload).hexdigest()
    sha256 = hashlib.sha256(payload).hexdigest()
    root = normalize_folder(args.folder)
    artifact_path = f"{root}/artifacts/full.zip"
    status_path = f"{root}/status.json"
    updated_at = datetime.now(timezone.utc).isoformat()
    status = {
        "schema_version": 1,
        "active": "full",
        "artifacts": {
            "full": {
                "path": artifact_path,
                "size": size,
                "sha256": sha256,
                "updated_at": updated_at,
            },
        },
    }
    status_payload = json.dumps(
        status, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")

    headers = {"Authorization": f"OAuth {token}"}
    api_timeout = aiohttp.ClientTimeout(total=90, connect=20)
    transfer_timeout = aiohttp.ClientTimeout(total=30 * 60, connect=30)
    method = "server-side-import"
    async with aiohttp.ClientSession(
        headers=headers, timeout=api_timeout,
    ) as api_session, aiohttp.ClientSession(
        timeout=transfer_timeout,
    ) as transfer_session:
        await ensure_directories(api_session, root)
        for attempt in range(1, IMPORT_ATTEMPTS + 1):
            log(f"Server-side import attempt {attempt}/{IMPORT_ATTEMPTS}")
            try:
                await import_release_url(
                    api_session,
                    args.source_url,
                    artifact_path,
                    size,
                    md5,
                )
                break
            except Exception as exc:
                log(f"Server-side import attempt {attempt}/{IMPORT_ATTEMPTS} failed: {exc}")
                if attempt == IMPORT_ATTEMPTS:
                    method = "direct-upload"
                    log("Fast import attempts exhausted; uploading local runner ZIP directly")
                    await upload_file(
                        api_session,
                        transfer_session,
                        artifact_path,
                        source_path,
                        size,
                        md5,
                    )
                    break
                delay = IMPORT_BACKOFF_SECONDS[attempt - 1]
                log(f"Retrying server-side import in {delay}s")
                await asyncio.sleep(delay)

        log("Artifact verified; publishing status.json last")
        await upload_bytes(
            api_session,
            transfer_session,
            status_path,
            status_payload,
        )

    write_action_outputs(sha256, size, method)
    log(
        f"Release published successfully: sha256={sha256[:16]}, "
        f"size={size / 1048576:.1f} MiB, method={method}"
    )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--folder", default="photobooth_system/updates")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(publish(parse_args()))
