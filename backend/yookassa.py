"""Private YooKassa credentials and the booth's SBP API requests."""

import json
import logging
import os
import tempfile
import urllib.request
from pathlib import Path

import aiohttp

from .config import ROOT_DIR
from . import yadisk_updates

log = logging.getLogger(__name__)

REMOTE_FOLDER = "/photobooth_system/yookassa"
CACHE_FILENAME = "yookassa_credentials.json"
MAX_CREDENTIALS_SIZE = 4096
MAX_ARCHIVE_SIZE = 64 * 1024
REQUEST_TIMEOUT = 10
PAYMENT_POLL_INTERVAL_SECONDS = 2
API_URL = "https://api.yookassa.ru/v3"


class PaymentAPIError(Exception):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"YooKassa HTTP {status}")


async def request_payment(session: aiohttp.ClientSession, attempt: dict) -> dict:
    """Resume by ID, or repeat exactly the saved POST after an uncertain reply."""
    payment_id = attempt.get("id")
    method = "GET" if payment_id else "POST"
    url = f"{API_URL}/payments" + (f"/{payment_id}" if payment_id else "")
    options = {} if payment_id else {
        "json": attempt["request"],
        "headers": {"Idempotence-Key": attempt["request_id"]},
    }
    async with session.request(method, url, **options) as response:
        if response.status != 200:
            # Error bodies may contain merchant or customer data.
            raise PaymentAPIError(response.status)
        return await response.json()


def payment_result(response: dict, attempt: dict) -> dict:
    """Accept only a payment that belongs to this saved booth request."""
    if not isinstance(response, dict) or not all(
        isinstance(response.get(key), dict)
        for key in ("amount", "recipient", "metadata", "payment_method")
    ):
        raise ValueError("invalid payment response")
    payment_id = response.get("id")
    status = response.get("status")
    if (not isinstance(payment_id, str) or not payment_id
            or (attempt.get("id") and attempt["id"] != payment_id)
            or response["amount"] != attempt["request"]["amount"]
            or response["recipient"].get("account_id") != attempt["shop_id"]
            or response["metadata"].get("request_id") != attempt["request_id"]
            or response["payment_method"].get("type") != "sbp"
            or status not in ("pending", "waiting_for_capture", "succeeded", "canceled")
            or (status == "succeeded" and response.get("paid") is not True)):
        raise ValueError("payment does not match the booth request")
    result = {"id": payment_id, "status": status}
    if status == "pending":
        confirmation = response.get("confirmation") or {}
        if not isinstance(confirmation, dict):
            raise ValueError("invalid payment confirmation")
        qr = confirmation.get("confirmation_data") or attempt.get("qr", "")
        if not isinstance(qr, str) or not qr.startswith("https://qr.nspk.ru/"):
            raise ValueError("payment has no SBP QR")
        result["qr"] = qr
    if status == "canceled":
        result["cancellation_reason"] = (response.get("cancellation_details") or {}).get("reason", "")
    return result


def _parse_credentials(payload: bytes) -> dict[str, str]:
    if len(payload) > MAX_CREDENTIALS_SIZE:
        raise ValueError("credentials file is too large")
    data = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("credentials must be a JSON object")
    credentials = {}
    for name in ("SHOPID", "SHOPTOKEN"):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is missing")
        credentials[name] = value.strip()
    return credentials


def _download_credentials(token: str) -> bytes:
    link = yadisk_updates._download_link(
        REMOTE_FOLDER, token, timeout=REQUEST_TIMEOUT)
    if not link.startswith("https://"):
        raise ValueError("credentials download requires HTTPS")
    # Credentials travel as a folder ZIP, like the other system data. The
    # temporary storage request must not carry the Disk OAuth token.
    request = urllib.request.Request(
        link, headers={"User-Agent": "photobooth-yookassa/1"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        archive = response.read(MAX_ARCHIVE_SIZE + 1)
    if len(archive) > MAX_ARCHIVE_SIZE:
        raise ValueError("credentials archive is too large")
    return yadisk_updates._extract_folder_member_bytes(
        archive,
        folder_name=REMOTE_FOLDER.rsplit("/", 1)[-1],
        filename="credentials.json",
        max_size=MAX_CREDENTIALS_SIZE,
    )


def _save_credentials(path: Path, credentials: dict[str, str]) -> None:
    temporary = None
    try:
        # NamedTemporaryFile creates a private file on POSIX. Replace the
        # cache only after the entire new value has been written and closed.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(credentials, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_credentials(root: Path = ROOT_DIR) -> dict[str, str] | None:
    """Refresh the local cache at startup, falling back to its last good copy."""
    path = root / CACHE_FILENAME
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if token:
        try:
            credentials = _parse_credentials(_download_credentials(token))
        except Exception as exc:
            # Exception messages can contain signed storage URLs or file
            # contents. Log the error class without exposing either.
            log.warning("YooKassa: Disk credentials unavailable (%s)",
                        type(exc).__name__)
        else:
            try:
                _save_credentials(path, credentials)
            except OSError as exc:
                log.warning("YooKassa: could not save credentials cache (%s)",
                            type(exc).__name__)
            log.info("YooKassa: credentials loaded from Yandex.Disk")
            return credentials

    try:
        credentials = _parse_credentials(path.read_bytes())
    except (OSError, ValueError):
        log.warning("YooKassa: credentials are not available")
        return None
    log.info("YooKassa: using cached credentials")
    return credentials
