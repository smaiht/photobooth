"""Small stdlib-only Yandex.Disk update client used before FastAPI starts."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://cloud-api.yandex.net/v1/disk"
MAX_UPDATE_SIZE = 2 * 1024 * 1024 * 1024


def normalize_folder(folder: str) -> str:
    name = str(folder or "").strip().strip("/")
    if not name or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("invalid Yandex.Disk updates folder")
    return "/" + name


def _request(method: str, url: str, token: str, *, params: dict | None = None,
             data: bytes | None = None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"OAuth {token}",
            "User-Agent": "photobooth-update/1",
        },
    )
    return urllib.request.urlopen(request, timeout=60)


def read_status(folder: str) -> dict | None:
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        return None
    root = normalize_folder(folder)
    try:
        with _request("GET", f"{API}/resources/download", token,
                      params={"path": f"{root}/status.json"}) as response:
            link = json.loads(response.read())["href"]
        request = urllib.request.Request(
            link, headers={"User-Agent": "photobooth-update/1"})
        with urllib.request.urlopen(request, timeout=60) as response:
            status = json.loads(response.read())
        if not isinstance(status, dict):
            raise ValueError("status.json root must be an object")
        return status
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def download_artifact(status: dict, destination: Path) -> tuple[int, str]:
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        raise RuntimeError("YADISK_TOKEN is not set")
    path = status.get("path")
    size = status.get("size")
    expected_sha = status.get("sha256")
    if (not isinstance(path, str) or not path.startswith("/")
            or ".." in path.split("/") or not path.endswith(".zip")):
        raise ValueError("invalid update artifact path")
    if not isinstance(size, int) or size < 1 or size > MAX_UPDATE_SIZE:
        raise ValueError("invalid update artifact size")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError("invalid update artifact sha256")

    with _request("GET", f"{API}/resources/download", token,
                  params={"path": path}) as response:
        link = json.loads(response.read())["href"]
    request = urllib.request.Request(
        link, headers={"User-Agent": "photobooth-update/1"})
    digest = hashlib.sha256()
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=600) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPDATE_SIZE:
                raise ValueError("update artifact exceeds maximum size")
            digest.update(chunk)
            output.write(chunk)

    actual_sha = digest.hexdigest()
    if total != size or actual_sha != expected_sha:
        raise ValueError(
            f"update checksum mismatch: size {total}/{size}, sha {actual_sha}/{expected_sha}")
    return total, actual_sha
