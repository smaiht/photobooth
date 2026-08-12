"""Publish Photobooth release archives to Yandex.Disk."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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


def artifact_bundle_path(root: str, name: str) -> str:
    return f"{root}/artifacts/{name}_bundle"


def artifact_path(root: str, name: str) -> str:
    return f"{artifact_bundle_path(root, name)}/{name}.zip"


def _valid_sha256(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        archive_sha256 = file_sha256(path)
        expected_hash_type = "zip" if name == "full" else "folder"
        if (
            size < 1
            or entry.get("file") != filename
            or entry.get("size") != size
            or entry.get("hash_type") != expected_hash_type
            or not _valid_sha256(entry.get("sha256"))
            or (name == "full" and entry.get("sha256") != archive_sha256)
        ):
            raise ValueError(f"{name} ZIP does not match release metadata")

        artifacts[name] = {
            "name": name,
            "size": size,
            "sha256": entry["sha256"],
            "archive_sha256": archive_sha256,
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
    paths = []
    for part in root.strip("/").split("/"):
        current += f"/{part}"
        paths.append(current)
    paths.extend([
        f"{root}/artifacts",
        f"{root}/status_bundle",
        *(artifact_bundle_path(root, name) for name in ARTIFACT_FILES),
    ])
    for current in paths:
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


async def resource_metadata(
    session: aiohttp.ClientSession,
    path: str,
) -> dict[str, int | str] | None:
    async with session.get(
        f"{API}/resources",
        params={"path": path, "fields": "size,sha256"},
    ) as response:
        if response.status == 404:
            return None
        if response.status != 200:
            raise RuntimeError(
                f"cannot inspect {path}: {await response_error(response)}"
            )
        metadata = await response.json()
    size = metadata.get("size")
    sha256 = metadata.get("sha256")
    if type(size) is not int or size < 0:
        raise RuntimeError(f"resource has an invalid size: {path}")
    if isinstance(sha256, str):
        sha256 = sha256.lower()
    if not _valid_sha256(sha256):
        raise RuntimeError(f"resource has an invalid SHA-256: {path}")
    return {"size": size, "sha256": sha256}


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


async def resource_matches(
    session: aiohttp.ClientSession,
    path: str,
    expected_size: int,
    expected_sha256: str,
) -> bool:
    metadata = await resource_metadata(session, path)
    return metadata == {
        "size": expected_size,
        "sha256": expected_sha256,
    }


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
    expected_sha256: str,
) -> None:
    async with session.post(
        f"{API}/resources/upload",
        params={
            "url": source_url,
            "path": destination,
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
    metadata = await resource_metadata(session, destination)
    if metadata is None:
        raise RuntimeError(f"imported artifact is missing: {destination}")
    if metadata["size"] != expected_size:
        raise RuntimeError(
            f"imported artifact has the wrong size: {destination}; "
            f"expected {expected_size}, got {metadata['size']}"
        )
    if metadata["sha256"] != expected_sha256:
        raise RuntimeError(
            f"imported artifact has the wrong SHA-256: {destination}; "
            f"expected {expected_sha256}, got {metadata['sha256']}"
        )


async def delete_resource(
    session: aiohttp.ClientSession,
    path: str,
) -> None:
    async with session.delete(
        f"{API}/resources",
        params={
            "path": path,
            "permanently": "true",
            "force_async": "true",
        },
    ) as response:
        if response.status in (204, 404):
            return
        if response.status != 202:
            raise RuntimeError(
                f"cannot delete {path}: {await response_error(response)}"
            )
        href = (await response.json()).get("href")
    if not href:
        raise RuntimeError(f"delete operation URL is missing for {path}")
    await wait_operation(session, href, f"delete {path}")


async def cleanup_resources(
    session: aiohttp.ClientSession,
    paths,
) -> None:
    for path in paths:
        try:
            await delete_resource(session, path)
        except Exception as exc:
            log(f"Temporary artifact cleanup failed for {path}: {exc}")


async def move_resource(
    session: aiohttp.ClientSession,
    source: str,
    destination: str,
    expected_size: int,
    expected_sha256: str,
) -> None:
    operation_status = None
    async with session.post(
        f"{API}/resources/move",
        params={
            "from": source,
            "path": destination,
            "overwrite": "true",
            "force_async": "true",
        },
    ) as response:
        operation_status = response.status
        if response.status not in (201, 202):
            raise RuntimeError(
                f"cannot promote {source}: {await response_error(response)}"
            )
        href = (
            (await response.json()).get("href")
            if response.status == 202 else None
        )
    if operation_status == 202:
        if not href:
            raise RuntimeError(f"move operation URL is missing for {source}")
        await wait_operation(session, href, f"move {source} to {destination}")

    if not await resource_matches(
        session, destination, expected_size, expected_sha256,
    ):
        raise RuntimeError(f"promoted artifact does not match: {destination}")


def staging_path(
    root: str,
    artifact_name: str,
    publish_nonce: str,
    attempt: int,
) -> str:
    return (
        f"{root}/artifacts/.incoming-{artifact_name}-"
        f"{publish_nonce}-{attempt}.zip"
    )


async def stage_artifact(
    session: aiohttp.ClientSession,
    artifact: dict,
    root: str,
    source_base_url: str,
    publish_nonce: str,
) -> str:
    name = artifact["name"]
    for attempt in range(1, IMPORT_ATTEMPTS + 1):
        destination = staging_path(root, name, publish_nonce, attempt)
        log(
            f"{name}: importing release archive "
            f"(attempt {attempt}/{IMPORT_ATTEMPTS})"
        )
        source_url = release_asset_source_url(
            source_base_url,
            ARTIFACT_FILES[name],
            artifact["archive_sha256"],
            publish_nonce,
            attempt,
        )
        try:
            await import_release_url(
                session,
                source_url,
                destination,
                artifact["size"],
                artifact["archive_sha256"],
            )
            log(f"{name}: temporary archive verified")
            return destination
        except Exception as exc:
            await cleanup_resources(session, [destination])
            if attempt == IMPORT_ATTEMPTS:
                raise
            delay = IMPORT_BACKOFF_SECONDS[attempt - 1]
            log(
                f"{name}: import attempt {attempt}/{IMPORT_ATTEMPTS} "
                f"failed: {exc}; retrying in {delay}s"
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


async def replace_artifacts(
    session: aiohttp.ClientSession,
    artifacts: list[dict],
    root: str,
    source_base_url: str,
    publish_nonce: str,
) -> None:
    staged: dict[str, str] = {}
    pending_cleanup: set[str] = set()
    try:
        # Finish and verify every import before changing any public archive.
        for artifact in artifacts:
            temporary_path = await stage_artifact(
                session,
                artifact,
                root,
                source_base_url,
                publish_nonce,
            )
            staged[artifact["name"]] = temporary_path
            pending_cleanup.add(temporary_path)

        for artifact in artifacts:
            name = artifact["name"]
            temporary_path = staged[name]
            await move_resource(
                session,
                temporary_path,
                artifact_path(root, name),
                artifact["size"],
                artifact["archive_sha256"],
            )
            pending_cleanup.discard(temporary_path)
            log(f"{name}: published to {artifact_path(root, name)}")
    finally:
        await cleanup_resources(session, sorted(pending_cleanup))


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
    expected_bundle_path: str | None = None,
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
    bundle_path = record.get("bundle_path")
    size = record.get("size")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or not path.endswith(".zip")
        or (expected_path is not None and path != expected_path)
        or not isinstance(bundle_path, str)
        or not bundle_path.startswith("/")
        or path.rsplit("/", 1)[0] != bundle_path
        or (expected_bundle_path is not None
            and bundle_path != expected_bundle_path)
        or not isinstance(size, int)
        or size < 1
    ):
        return None

    result = {
        "path": path,
        "bundle_path": bundle_path,
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
    status_path = f"{root}/status_bundle/status.json"
    updated_at = datetime.now(timezone.utc).isoformat()
    publish_nonce = uuid.uuid4().hex
    changed: list[str] = []
    changed_artifacts: list[dict] = []
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
            bundle_path = artifact_bundle_path(root, name)
            release_path = artifact_path(root, name)
            previous = reusable_record(
                previous_status,
                artifact,
                release_path,
                bundle_path,
            )
            if previous and await resource_size_matches(
                api_session, previous["path"], previous["size"],
            ):
                status_artifacts[name] = previous
                log(f"Artifact unchanged; reusing {name}: {previous['path']}")
                continue

            changed.append(name)
            changed_artifacts.append(artifact)
            status_artifacts[name] = {
                "path": release_path,
                "bundle_path": bundle_path,
                "size": artifact["size"],
                "sha256": artifact["sha256"],
                "hash_type": artifact["hash_type"],
                "updated_at": updated_at,
            }

        await replace_artifacts(
            api_session,
            changed_artifacts,
            root,
            args.source_base_url,
            publish_nonce,
        )

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
