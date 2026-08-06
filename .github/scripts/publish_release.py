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
HASH_CHUNK_SIZE = 1024 * 1024

ARTIFACT_FILES = {
    "full": "photobooth-win.zip",
    "app": "photobooth-app.zip",
    "python": "photobooth-python.zip",
    "bin": "photobooth-bin.zip",
    "templates": "photobooth-templates.zip",
    "edsdk": "photobooth-edsdk.zip",
    "drivers": "photobooth-drivers.zip",
}

COMPONENT_ROOTS = {
    "python": "python/",
    "bin": "bin/",
    "templates": "templates/",
    "edsdk": "EDSDK_Win/",
    "drivers": "drivers/",
}


def log(message: str) -> None:
    print(message, flush=True)


def normalize_folder(value: str) -> str:
    name = str(value or "").strip().strip("/")
    if not name or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("invalid Yandex.Disk updates folder")
    return f"/{name}"


def _valid_sha256(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_artifact(name: str, path: Path, metadata: dict) -> dict:
    size = path.stat().st_size
    if size < 1:
        raise ValueError(f"{name} ZIP is empty")
    if metadata.get("file") != path.name or metadata.get("size") != size:
        raise ValueError(f"{name} ZIP does not match release metadata")
    content_sha = metadata.get("sha256")
    if not _valid_sha256(content_sha):
        raise ValueError(f"{name} content SHA-256 is invalid")

    md5 = hashlib.md5()
    archive_sha = hashlib.sha256() if name == "full" else None
    with path.open("rb") as source:
        while chunk := source.read(HASH_CHUNK_SIZE):
            md5.update(chunk)
            if archive_sha is not None:
                archive_sha.update(chunk)

    with zipfile.ZipFile(path) as archive:
        failed = archive.testzip()
        if failed:
            raise ValueError(f"{name} ZIP CRC failed: {failed}")
        names = {
            entry.replace("\\", "/")
            for entry in archive.namelist()
            if not entry.endswith(("/", "\\"))
        }
    if name in {"full", "app"}:
        if "app.py" not in names:
            raise ValueError(f"{name} ZIP does not contain app.py at its root")
    else:
        prefix = COMPONENT_ROOTS[name]
        invalid = sorted(entry for entry in names if not entry.startswith(prefix))
        if invalid:
            raise ValueError(f"{name} ZIP contains path outside {prefix}: {invalid[0]}")

    # Legacy clients validate full against its archive hash. Component hashes
    # deliberately identify sorted folder contents and ignore ZIP timestamps.
    status_sha = archive_sha.hexdigest() if archive_sha is not None else content_sha
    log(
        f"Artifact validated: {path.name}, {size / 1048576:.1f} MiB, "
        f"{len(names)} entries"
    )
    return {
        "name": name,
        "path": path,
        "size": size,
        "md5": md5.hexdigest(),
        "sha256": status_sha,
    }


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


async def resource_size_matches(
    session: aiohttp.ClientSession,
    path: str,
    expected_size: int,
) -> bool:
    async with session.get(
        f"{API}/resources",
        params={"path": path, "fields": "size"},
    ) as response:
        if response.status == 404:
            return False
        if response.status != 200:
            raise RuntimeError(
                f"cannot inspect {path}: {await response_error(response)}"
            )
        metadata = await response.json()
    return metadata.get("size") == expected_size


async def read_json_resource(
    api_session: aiohttp.ClientSession,
    transfer_session: aiohttp.ClientSession,
    path: str,
) -> dict | None:
    async with api_session.get(
        f"{API}/resources/download",
        params={"path": path},
    ) as response:
        if response.status == 404:
            return None
        if response.status != 200:
            raise RuntimeError(
                f"cannot request download URL for {path}: "
                f"{await response_error(response)}"
            )
        href = (await response.json()).get("href")
    if not href:
        raise RuntimeError(f"download URL is missing for {path}")
    async with transfer_session.get(href) as response:
        if response.status != 200:
            raise RuntimeError(
                f"cannot download {path}: {await response_error(response)}"
            )
        payload = json.loads(await response.read())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} root must be an object")
    return payload


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


def write_action_outputs(
    sha256: str,
    size: int,
    method: str,
    changed: list[str],
) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"sha256={sha256}\n")
        output.write(f"size_mib={size / 1048576:.1f}\n")
        output.write(f"method={method}\n")
        output.write(f"changed={','.join(changed) or 'none'}\n")


def load_artifacts(dist_dir: Path, metadata_path: Path) -> dict[str, dict]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or set(metadata) != set(ARTIFACT_FILES):
        raise ValueError("release metadata does not list the expected artifacts")
    artifacts = {}
    for name, filename in ARTIFACT_FILES.items():
        entry = metadata.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"release metadata for {name} is invalid")
        artifacts[name] = validate_artifact(
            name,
            (dist_dir / filename).resolve(),
            entry,
        )
    return artifacts


def reusable_record(previous_status: dict | None, artifact: dict) -> dict | None:
    if not isinstance(previous_status, dict):
        return None
    previous_artifacts = previous_status.get("artifacts")
    if not isinstance(previous_artifacts, dict):
        return None
    record = previous_artifacts.get(artifact["name"])
    if not isinstance(record, dict):
        return None
    if record.get("sha256") != artifact["sha256"]:
        return None
    path = record.get("path")
    size = record.get("size")
    if (not isinstance(path, str) or not path.startswith("/")
            or not path.endswith(".zip") or not isinstance(size, int) or size < 1):
        return None
    return record.copy()


async def publish(args) -> None:
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        raise RuntimeError("YADISK_TOKEN is not configured")
    dist_dir = Path(args.dist_dir).resolve()
    metadata_path = Path(args.metadata).resolve()
    artifacts = load_artifacts(dist_dir, metadata_path)
    root = normalize_folder(args.folder)
    status_path = f"{root}/status.json"
    updated_at = datetime.now(timezone.utc).isoformat()

    headers = {"Authorization": f"OAuth {token}"}
    api_timeout = aiohttp.ClientTimeout(total=90, connect=20)
    transfer_timeout = aiohttp.ClientTimeout(total=30 * 60, connect=30)
    methods: set[str] = set()
    changed: list[str] = []
    status_artifacts: dict[str, dict] = {}
    async with aiohttp.ClientSession(
        headers=headers, timeout=api_timeout,
    ) as api_session, aiohttp.ClientSession(
        timeout=transfer_timeout,
    ) as transfer_session:
        await ensure_directories(api_session, root)
        previous_status = await read_json_resource(
            api_session, transfer_session, status_path,
        )

        for name in ARTIFACT_FILES:
            artifact = artifacts[name]
            previous = reusable_record(previous_status, artifact)
            if previous and await resource_size_matches(
                api_session, previous["path"], previous["size"],
            ):
                status_artifacts[name] = previous
                log(f"Artifact unchanged; reusing {name}: {previous['path']}")
                continue

            changed.append(name)
            artifact_path = (
                f"{root}/artifacts/{name}-{artifact['sha256'][:16]}.zip"
            )
            source_url = (
                f"{args.source_base_url.rstrip('/')}/{ARTIFACT_FILES[name]}"
            )
            artifact_method = "server-side-import"
            for attempt in range(1, IMPORT_ATTEMPTS + 1):
                log(
                    f"{name}: server-side import attempt "
                    f"{attempt}/{IMPORT_ATTEMPTS}"
                )
                try:
                    await import_release_url(
                        api_session,
                        source_url,
                        artifact_path,
                        artifact["size"],
                        artifact["md5"],
                    )
                    break
                except Exception as exc:
                    log(
                        f"{name}: server-side import attempt "
                        f"{attempt}/{IMPORT_ATTEMPTS} failed: {exc}"
                    )
                    if attempt == IMPORT_ATTEMPTS:
                        artifact_method = "direct-upload"
                        log(f"{name}: importing failed; uploading runner ZIP")
                        await upload_file(
                            api_session,
                            transfer_session,
                            artifact_path,
                            artifact["path"],
                            artifact["size"],
                            artifact["md5"],
                        )
                        break
                    delay = IMPORT_BACKOFF_SECONDS[attempt - 1]
                    log(f"{name}: retrying import in {delay}s")
                    await asyncio.sleep(delay)
            methods.add(artifact_method)
            status_artifacts[name] = {
                "path": artifact_path,
                "size": artifact["size"],
                "sha256": artifact["sha256"],
                "updated_at": updated_at,
            }

        status = {
            "schema_version": 1,
            "active": "full",
            "source_commit": args.commit,
            "artifacts": status_artifacts,
        }
        status_payload = json.dumps(
            status, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")

        log("Artifact verified; publishing status.json last")
        await upload_bytes(
            api_session,
            transfer_session,
            status_path,
            status_payload,
        )

    if not methods:
        method = "unchanged"
    elif methods == {"server-side-import"}:
        method = "server-side-import"
    elif methods == {"direct-upload"}:
        method = "direct-upload"
    else:
        method = "mixed"
    full = status_artifacts["full"]
    write_action_outputs(
        full["sha256"], full["size"], method, changed,
    )
    log(
        f"Release published successfully: full={full['sha256'][:16]}, "
        f"size={full['size'] / 1048576:.1f} MiB, method={method}, "
        f"changed={','.join(changed) or 'none'}"
    )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--source-base-url", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--folder", default="photobooth_system/updates")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(publish(parse_args()))
