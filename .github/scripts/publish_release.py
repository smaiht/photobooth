"""Publish Photobooth release archives to Yandex.Disk."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiohttp


API = "https://cloud-api.yandex.net/v1/disk"
IMPORT_ATTEMPTS = 3
IMPORT_BACKOFF_SECONDS = (2, 4)
OPERATION_ATTEMPTS = 300

ARTIFACT_FILES = {
    "full": "photobooth-win.zip",
    "app": "photobooth-app.zip",
    "assets": "photobooth-assets.zip",
    "python": "photobooth-python.zip",
    "bin": "photobooth-bin.zip",
    "templates": "photobooth-templates.zip",
    "edsdk": "photobooth-edsdk.zip",
    "drivers": "photobooth-drivers.zip",
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


def load_artifacts(dist_dir: Path, metadata_path: Path) -> dict[str, dict]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or set(metadata) != set(ARTIFACT_FILES):
        raise ValueError("release metadata does not list the expected artifacts")

    artifacts = {}
    for name, filename in ARTIFACT_FILES.items():
        entry = metadata.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"release metadata for {name} is invalid")

        path = (dist_dir / filename).resolve()
        size = path.stat().st_size
        expected_hash_type = "zip" if name == "full" else "folder"
        if (
            size < 1
            or entry.get("file") != filename
            or entry.get("size") != size
            or entry.get("hash_type") != expected_hash_type
            or not _valid_sha256(entry.get("sha256"))
        ):
            raise ValueError(f"{name} ZIP does not match release metadata")

        artifacts[name] = {
            "name": name,
            "size": size,
            "sha256": entry["sha256"],
            "hash_type": expected_hash_type,
        }
        log(
            f"Artifact ready: {filename}, {size / 1048576:.1f} MiB, "
            f"hash_type={expected_hash_type}"
        )
    return artifacts


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
        if status == "success":
            return
        if status == "failed":
            raise RuntimeError(f"Yandex.Disk operation failed: {label}")
        await asyncio.sleep(1)
    raise TimeoutError(f"Yandex.Disk operation timed out: {label}")


async def resource_size(
    session: aiohttp.ClientSession,
    path: str,
) -> int | None:
    async with session.get(
        f"{API}/resources",
        params={"path": path, "fields": "size"},
    ) as response:
        if response.status == 404:
            return None
        if response.status != 200:
            raise RuntimeError(
                f"cannot inspect {path}: {await response_error(response)}"
            )
        metadata = await response.json()
    size = metadata.get("size")
    if type(size) is not int or size < 0:
        raise RuntimeError(f"resource has an invalid size: {path}")
    return size


async def resource_size_matches(
    session: aiohttp.ClientSession,
    path: str,
    expected_size: int,
) -> bool:
    return await resource_size(session, path) == expected_size


def release_asset_source_url(
    source_base_url: str,
    filename: str,
    sha256: str,
    publish_nonce: str,
    attempt: int,
) -> str:
    """Return a fresh URL so Yandex never reuses an older remote import."""
    asset_url = f"{source_base_url.rstrip('/')}/{filename}"
    separator = "&" if "?" in asset_url else "?"
    query = urllib.parse.urlencode({
        "photobooth_sha256": sha256,
        "publish_nonce": publish_nonce,
        "attempt": attempt,
    })
    return f"{asset_url}{separator}{query}"


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


async def import_release_url(
    session: aiohttp.ClientSession,
    source_url: str,
    destination: str,
    expected_size: int,
) -> None:
    async with session.post(
        f"{API}/resources/upload",
        params={
            "url": source_url,
            "path": destination,
            "overwrite": "true",
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

    await wait_operation(session, href, destination)
    actual_size = await resource_size(session, destination)
    if actual_size != expected_size:
        raise RuntimeError(
            f"imported artifact has the wrong size: {destination}; "
            f"expected {expected_size}, got {actual_size}"
        )


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


def reusable_record(
    previous_status: dict | None,
    artifact: dict,
    expected_path: str | None = None,
) -> dict | None:
    if not isinstance(previous_status, dict):
        return None
    previous_artifacts = previous_status.get("artifacts")
    if not isinstance(previous_artifacts, dict):
        return None
    record = previous_artifacts.get(artifact["name"])
    if not isinstance(record, dict) or record.get("sha256") != artifact["sha256"]:
        return None

    path = record.get("path")
    size = record.get("size")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or not path.endswith(".zip")
        or (expected_path is not None and path != expected_path)
        or not isinstance(size, int)
        or size < 1
    ):
        return None

    result = {
        "path": path,
        "size": size,
        "sha256": artifact["sha256"],
        "hash_type": artifact["hash_type"],
    }
    if isinstance(record.get("updated_at"), str):
        result["updated_at"] = record["updated_at"]
    return result


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


async def publish(args) -> None:
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        raise RuntimeError("YADISK_TOKEN is not configured")

    artifacts = load_artifacts(
        Path(args.dist_dir).resolve(),
        Path(args.metadata).resolve(),
    )
    root = normalize_folder(args.folder)
    status_path = f"{root}/status.json"
    updated_at = datetime.now(timezone.utc).isoformat()
    publish_nonce = uuid.uuid4().hex
    changed: list[str] = []
    status_artifacts: dict[str, dict] = {}

    headers = {"Authorization": f"OAuth {token}"}
    api_timeout = aiohttp.ClientTimeout(total=90, connect=20)
    transfer_timeout = aiohttp.ClientTimeout(total=90, connect=20)
    async with aiohttp.ClientSession(
        headers=headers, timeout=api_timeout,
    ) as api_session, aiohttp.ClientSession(
        timeout=transfer_timeout,
    ) as transfer_session:
        await ensure_directories(api_session, root)
        previous_status = await read_json_resource(
            api_session, transfer_session, status_path,
        )

        for name, artifact in artifacts.items():
            artifact_path = f"{root}/artifacts/{name}.zip"
            previous = reusable_record(
                previous_status, artifact, artifact_path,
            )
            if previous and await resource_size_matches(
                api_session, previous["path"], previous["size"],
            ):
                status_artifacts[name] = previous
                log(f"Artifact unchanged; reusing {name}: {previous['path']}")
                continue

            changed.append(name)
            for attempt in range(1, IMPORT_ATTEMPTS + 1):
                source_url = release_asset_source_url(
                    args.source_base_url,
                    ARTIFACT_FILES[name],
                    artifact["sha256"],
                    publish_nonce,
                    attempt,
                )
                try:
                    await import_release_url(
                        api_session,
                        source_url,
                        artifact_path,
                        artifact["size"],
                    )
                    break
                except Exception as exc:
                    if attempt == IMPORT_ATTEMPTS:
                        raise
                    delay = IMPORT_BACKOFF_SECONDS[attempt - 1]
                    log(
                        f"{name}: import attempt {attempt}/{IMPORT_ATTEMPTS} "
                        f"failed: {exc}; retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)

            status_artifacts[name] = {
                "path": artifact_path,
                "size": artifact["size"],
                "sha256": artifact["sha256"],
                "hash_type": artifact["hash_type"],
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
        await upload_bytes(
            api_session, transfer_session, status_path, status_payload,
        )

    method = "server-side-import" if changed else "unchanged"
    full = status_artifacts["full"]
    write_action_outputs(full["sha256"], full["size"], method, changed)
    log(
        f"Release published: full={full['sha256'][:16]}, "
        f"size={full['size'] / 1048576:.1f} MiB, "
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
