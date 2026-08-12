"""Minimal stdlib-only Yandex.Disk update client used before FastAPI starts."""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

API = "https://cloud-api.yandex.net/v1/disk"
MAX_UPDATE_SIZE = 2 * 1024 * 1024 * 1024
# Show sub-MiB progress; app.py throttles UI updates separately.
DOWNLOAD_CHUNK_SIZE = 256 * 1024
DOWNLOAD_TIMEOUT = 60
DOWNLOAD_RETRY_DELAYS = (2, 4, 8, 16)
# status.json is tiny and is fetched before the booth starts. Short requests
# plus backoff survive normal Windows network warm-up without holding the booth
# on the loading screen for many minutes when the network is genuinely down.
STATUS_REQUEST_TIMEOUT = 10
STATUS_RETRY_DELAYS = (2, 4, 8, 16)

ProgressCallback = Callable[[int, int, float, int, int], None]
RetryCallback = Callable[[int, int, float, Exception], None]
log = logging.getLogger("update")


class ArtifactIntegrityError(ValueError):
    """Downloaded bytes do not match the published artifact metadata."""


class StatusNotFound(FileNotFoundError):
    """The API confirms that the published status pointer does not exist."""


class StatusStorageLinkError(ConnectionError):
    """A newly issued temporary storage link could not serve status.json."""


def normalize_folder(folder: str) -> str:
    name = str(folder or "").strip().strip("/")
    if not name or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("invalid Yandex.Disk updates folder")
    return "/" + name


def _request(method: str, url: str, token: str, *, params: dict | None = None,
             data: bytes | None = None, timeout: float = DOWNLOAD_TIMEOUT):
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
    return urllib.request.urlopen(request, timeout=timeout)


def _read_status_once(root: str, token: str) -> dict:
    # Ask for a new storage URL on every attempt. Yandex download links are
    # temporary, and retrying a link issued while the network was unhealthy is
    # less reliable than resolving the path again through the API.
    try:
        link = _download_link(
            f"{root}/status.json",
            token,
            timeout=STATUS_REQUEST_TIMEOUT,
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise StatusNotFound from exc
        raise
    request = urllib.request.Request(
        link, headers={"User-Agent": "photobooth-update/1"})
    try:
        with urllib.request.urlopen(
            request,
            timeout=STATUS_REQUEST_TIMEOUT,
        ) as response:
            status = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # A 403/404 from cloud-api means a permanent token/path problem, but
        # the same response from the freshly issued temporary storage URL can
        # be propagation or expiry. Resolve a new link on the next attempt.
        if exc.code in {403, 404}:
            raise StatusStorageLinkError(
                f"temporary status link returned HTTP {exc.code}"
            ) from exc
        raise
    if not isinstance(status, dict):
        raise ValueError("status.json root must be an object")
    return status


def read_status(
    folder: str,
    *,
    on_retry: RetryCallback | None = None,
    retry_delays: Sequence[float] = STATUS_RETRY_DELAYS,
) -> dict | None:
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        return None
    root = normalize_folder(folder)
    delays = tuple(float(delay) for delay in retry_delays)
    if any(delay < 0 for delay in delays):
        raise ValueError("invalid status retry delay")
    attempts = len(delays) + 1
    for attempt in range(1, attempts + 1):
        log.info(
            "Disk update: status check attempt %d/%d",
            attempt,
            attempts,
        )
        try:
            return _read_status_once(root, token)
        except StatusNotFound:
            return None
        except Exception as exc:
            error = exc

        if (attempt >= attempts
                or not _retryable_status_error(error)):
            raise error
        delay = delays[attempt - 1]
        if on_retry:
            on_retry(attempt, attempts, delay, error)
        time.sleep(delay)

    raise AssertionError("unreachable")


def _download_link(
    path: str,
    token: str,
    *,
    timeout: float = DOWNLOAD_TIMEOUT,
) -> str:
    with _request("GET", f"{API}/resources/download", token,
                  params={"path": path}, timeout=timeout) as response:
        payload = json.loads(response.read())
    link = payload.get("href") if isinstance(payload, dict) else None
    if not isinstance(link, str) or not link.startswith(("http://", "https://")):
        raise ValueError("invalid Yandex.Disk download link")
    return link


def _retryable_network_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {408, 425, 429, 500, 502, 503, 504}
    if isinstance(exc, (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        http.client.HTTPException,
        ssl.SSLError,
    )):
        return True
    if isinstance(exc, OSError):
        # Socket errors raised while reading a response are not always wrapped
        # in URLError, especially on Windows.
        return exc.errno in {32, 54, 60, 101, 104, 110, 111, 113} \
            or getattr(exc, "winerror", None) in {
                64, 10051, 10053, 10054, 10060, 10061, 10065, 11001,
            }
    return False


def _retryable_download_error(exc: Exception) -> bool:
    return (
        isinstance(exc, ArtifactIntegrityError)
        or _retryable_network_error(exc)
    )


def _retryable_status_error(exc: Exception) -> bool:
    # A cleanly truncated tiny response may surface only as invalid JSON rather
    # than a socket exception. Fetch it again, but do not retry other schema or
    # validation errors caused by a bad published status file.
    return (
        isinstance(exc, json.JSONDecodeError)
        or _retryable_network_error(exc)
    )


def _download_artifact_once(
    artifact: dict,
    destination: Path,
    token: str,
    *,
    progress: ProgressCallback | None,
    attempt: int,
    attempts: int,
    verify_sha256: bool,
) -> tuple[int, str]:
    path = artifact["path"]
    size = artifact["size"]
    expected_sha = artifact["sha256"]
    if progress:
        progress(0, size, 0.0, attempt, attempts)
    link = _download_link(path, token)
    storage_host = urllib.parse.urlsplit(link).hostname or "unknown"
    log.info(
        "Disk update: storage host %s (attempt %d/%d)",
        storage_host,
        attempt,
        attempts,
    )
    request = urllib.request.Request(
        link, headers={"User-Agent": "photobooth-update/1"})
    digest = hashlib.sha256()
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        started = time.monotonic()
        with destination.open("wb") as output:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPDATE_SIZE:
                    raise ArtifactIntegrityError(
                        "update artifact exceeds maximum size")
                if total > size:
                    raise ArtifactIntegrityError(
                        "update artifact exceeds declared size")
                digest.update(chunk)
                output.write(chunk)
                if progress:
                    elapsed = max(time.monotonic() - started, 0.001)
                    progress(total, size, total / elapsed, attempt, attempts)

    actual_sha = digest.hexdigest()
    if total != size or (verify_sha256 and actual_sha != expected_sha):
        raise ArtifactIntegrityError(
            f"update checksum mismatch: size {total}/{size}, "
            f"sha {actual_sha}/{expected_sha}")
    return total, actual_sha


def download_artifact(
    artifact: dict,
    destination: Path,
    *,
    progress: ProgressCallback | None = None,
    on_retry: RetryCallback | None = None,
    retry_delays: Sequence[float] = DOWNLOAD_RETRY_DELAYS,
    verify_sha256: bool = True,
) -> tuple[int, str]:
    """Download and verify an artifact, retrying transient storage failures.

    A fresh Yandex.Disk download URL is requested for every attempt. Partial
    files are removed before retrying, so bytes from different attempts can
    never be mixed.
    """
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        raise RuntimeError("YADISK_TOKEN is not set")
    path = artifact.get("path")
    size = artifact.get("size")
    expected_sha = artifact.get("sha256")
    if (not isinstance(path, str) or not path.startswith("/")
            or ".." in path.split("/") or not path.endswith(".zip")):
        raise ValueError("invalid update artifact path")
    if not isinstance(size, int) or size < 1 or size > MAX_UPDATE_SIZE:
        raise ValueError("invalid update artifact size")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError("invalid update artifact sha256")

    delays = tuple(float(delay) for delay in retry_delays)
    if any(delay < 0 for delay in delays):
        raise ValueError("invalid update retry delay")
    attempts = len(delays) + 1
    for attempt in range(1, attempts + 1):
        destination.unlink(missing_ok=True)
        try:
            return _download_artifact_once(
                artifact,
                destination,
                token,
                progress=progress,
                attempt=attempt,
                attempts=attempts,
                verify_sha256=verify_sha256,
            )
        except Exception as exc:
            destination.unlink(missing_ok=True)
            if (attempt >= attempts
                    or not _retryable_download_error(exc)):
                raise
            delay = delays[attempt - 1]
            if on_retry:
                on_retry(attempt, attempts, delay, exc)
            time.sleep(delay)

    raise AssertionError("unreachable")
