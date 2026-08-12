#!/usr/bin/env python3
"""Compare the Yandex.Disk network paths used by the photobooth.

The script reads existing command/update files and, unless --no-upload is
given, uploads two temporary 2 MiB files (direct and system-proxy modes),
verifies them, downloads them back, and deletes them. Tokens, signed URL
queries, and command contents are never logged.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import aiohttp


ROOT = Path(__file__).resolve().parents[1]
API = "https://cloud-api.yandex.net/v1/disk"
BOOTH_UA = 'Yandex.Disk {"os":"windows"}'
UPDATER_UA = "photobooth-update/1"
READ_LIMIT = 64 * 1024
UPLOAD_TIMEOUT = 60
LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
URL_RE = re.compile(r"https?://[^\s\]\[()<>\"']+")


def load_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value:
            os.environ[key] = value


def clean_error(exc: BaseException, token: str) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if token:
        text = text.replace(token, "<token>")

    def redact_url(match: re.Match[str]) -> str:
        parsed = urllib.parse.urlsplit(match.group(0))
        return f"{parsed.scheme}://{parsed.hostname or 'host'}/<redacted>"

    return URL_RE.sub(redact_url, text).replace("\n", " | ")


def make_report(label: str):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = ROOT / "diagnostics" / f"yadisk_network_{label}_{stamp}.log"
    output = path.open("w", encoding="utf-8", buffering=1)

    def report(message: str) -> None:
        line = (
            f"{datetime.now().astimezone().isoformat(timespec='milliseconds')} "
            f"{message}"
        )
        print(line, flush=True)
        output.write(line + "\n")

    return path, report


def disk_path(value: object) -> str:
    return "/" + str(value or "").strip().strip("/")


def host_from_error(exc: BaseException) -> str:
    return str(getattr(exc, "host", "") or "unknown")


def proxy_summary() -> str:
    proxies = []
    for scheme, value in sorted(urllib.request.getproxies().items()):
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname or "configured"
        proxies.append(f"{scheme}={host}:{parsed.port}" if parsed.port else f"{scheme}={host}")
    return ",".join(proxies) or "none"


def resolve(host: str, report, token: str) -> None:
    started = time.monotonic()
    try:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = sorted({record[4][0] for record in records})
        report(
            f"DNS ok host={host} elapsed={time.monotonic() - started:.3f}s "
            f"addresses={','.join(addresses)}"
        )
    except Exception as exc:
        report(
            f"DNS failed host={host} elapsed={time.monotonic() - started:.3f}s "
            f"error={clean_error(exc, token)}"
        )


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.hosts: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hosts.append(urllib.parse.urlsplit(newurl).hostname or "unknown")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_json(url: str, token: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"OAuth {token}", "User-Agent": UPDATER_UA},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("JSON root is not an object")
    return result


def urllib_api(endpoint: str, token: str, timeout: float, **params) -> dict:
    url = f"{API}{endpoint}?{urllib.parse.urlencode(params)}"
    return urllib_json(url, token, timeout)


def urllib_list(path: str, token: str, timeout: float) -> list[dict]:
    result = urllib_api(
        "/resources",
        token,
        timeout,
        path=path,
        limit=100,
        fields=(
            "_embedded.items.name,_embedded.items.path,"
            "_embedded.items.type,_embedded.items.size"
        ),
    )
    items = result.get("_embedded", {}).get("items", [])
    return items if isinstance(items, list) else []


def urllib_download(
    label: str,
    remote_path: str,
    token: str,
    timeout: float,
    report,
    results: list[tuple[str, bool, str]],
) -> None:
    client = "urllib-updater"
    started = time.monotonic()
    redirects = Redirects()
    issued_host = "unknown"
    try:
        href = urllib_api(
            "/resources/download", token, timeout, path=remote_path,
        )["href"]
        issued_host = urllib.parse.urlsplit(href).hostname or "unknown"
        request = urllib.request.Request(
            href,
            headers={
                "User-Agent": UPDATER_UA,
                "Range": f"bytes=0-{READ_LIMIT - 1}",
                "Connection": "close",
            },
        )
        with urllib.request.build_opener(redirects).open(
            request, timeout=timeout,
        ) as response:
            payload = response.read(READ_LIMIT)
            final_host = urllib.parse.urlsplit(response.geturl()).hostname or "unknown"
            status = response.status
        report(
            f"DOWNLOAD ok client={client} target={label} status={status} "
            f"bytes={len(payload)} elapsed={time.monotonic() - started:.3f}s "
            f"issued={issued_host} redirects={','.join(redirects.hosts) or 'none'} "
            f"final={final_host}"
        )
        results.append((client, True, final_host))
    except Exception as exc:
        failed_host = redirects.hosts[-1] if redirects.hosts else issued_host
        report(
            f"DOWNLOAD failed client={client} target={label} "
            f"elapsed={time.monotonic() - started:.3f}s issued={issued_host} "
            f"redirects={','.join(redirects.hosts) or 'none'} "
            f"failed_host={failed_host} error={clean_error(exc, token)}"
        )
        results.append((client, False, failed_host))


async def api_json(session: aiohttp.ClientSession, endpoint: str, **params) -> dict:
    async with session.get(f"{API}{endpoint}", params=params) as response:
        if response.status != 200:
            raise RuntimeError(f"API HTTP {response.status}")
        result = await response.json()
    if not isinstance(result, dict):
        raise ValueError("JSON root is not an object")
    return result


async def aio_download(
    label: str,
    remote_path: str,
    token: str,
    api: aiohttp.ClientSession,
    transfer: aiohttp.ClientSession,
    client: str,
    report,
    results: list[tuple[str, bool, str]],
) -> None:
    started = time.monotonic()
    issued_host = "unknown"
    try:
        href = (await api_json(api, "/resources/download", path=remote_path))["href"]
        issued_host = urllib.parse.urlsplit(href).hostname or "unknown"
        async with transfer.get(
            href,
            headers={
                "Range": f"bytes=0-{READ_LIMIT - 1}",
                "Connection": "close",
            },
        ) as response:
            payload = await response.content.read(READ_LIMIT)
            final_host = response.url.host or "unknown"
            redirects = ",".join(item.url.host or "unknown" for item in response.history)
            status = response.status
        ok = status in (200, 206)
        report(
            f"DOWNLOAD {'ok' if ok else 'failed'} client={client} target={label} "
            f"status={status} bytes={len(payload)} "
            f"elapsed={time.monotonic() - started:.3f}s issued={issued_host} "
            f"redirects={redirects or 'none'} final={final_host}"
        )
        results.append((client, ok, final_host))
    except Exception as exc:
        failed_host = host_from_error(exc)
        if failed_host == "unknown":
            failed_host = issued_host
        report(
            f"DOWNLOAD failed client={client} target={label} "
            f"elapsed={time.monotonic() - started:.3f}s issued={issued_host} "
            f"failed_host={failed_host} error={clean_error(exc, token)}"
        )
        results.append((client, False, failed_host))


async def delete(api: aiohttp.ClientSession, path: str) -> bool:
    async with api.delete(
        f"{API}/resources",
        params={"path": path, "permanently": "true"},
    ) as response:
        if response.status in (204, 404):
            return True
        if response.status != 202:
            return False
        operation = (await response.json()).get("href")
    for _ in range(10):
        async with api.get(operation) as response:
            if response.status != 200:
                return False
            status = (await response.json()).get("status")
        if status == "success":
            return True
        if status == "failed":
            return False
        await asyncio.sleep(1)
    return False


async def upload_roundtrip(
    remote_path: str,
    payload: bytes,
    token: str,
    api: aiohttp.ClientSession,
    transfer: aiohttp.ClientSession,
    client: str,
    report,
    results: list[tuple[str, bool, str]],
) -> None:
    started = time.monotonic()
    upload_host = "unknown"
    uploaded = False
    try:
        href = (await api_json(
            api,
            "/resources/upload",
            path=remote_path,
            overwrite="true",
        ))["href"]
        upload_host = urllib.parse.urlsplit(href).hostname or "unknown"
        async with transfer.put(
            href, data=payload, timeout=UPLOAD_TIMEOUT,
        ) as response:
            final_host = response.url.host or upload_host
            status = response.status
        if status not in (201, 202):
            raise RuntimeError(f"upload HTTP {status}")
        uploaded = True

        expected_md5 = hashlib.md5(payload).hexdigest()
        verified = False
        for _ in range(8):
            metadata = await api_json(
                api, "/resources", path=remote_path, fields="size,md5",
            )
            if metadata.get("size") == len(payload) and metadata.get("md5") == expected_md5:
                verified = True
                break
            await asyncio.sleep(1)
        if not verified:
            raise RuntimeError("uploaded metadata did not verify")

        href = (await api_json(api, "/resources/download", path=remote_path))["href"]
        async with transfer.get(href, timeout=UPLOAD_TIMEOUT) as response:
            returned = await response.read()
            download_host = response.url.host or "unknown"
            download_status = response.status
        roundtrip = (
            download_status == 200
            and len(returned) == len(payload)
            and hashlib.md5(returned).hexdigest() == expected_md5
        )
        report(
            f"UPLOAD ok client={client} bytes={len(payload)} "
            f"elapsed={time.monotonic() - started:.3f}s upload_host={final_host} "
            f"metadata=ok roundtrip={'ok' if roundtrip else 'failed'} "
            f"download_status={download_status} download_host={download_host}"
        )
        results.append((f"upload-{client}", roundtrip, final_host))
    except Exception as exc:
        report(
            f"UPLOAD failed client={client} bytes={len(payload)} uploaded={uploaded} "
            f"elapsed={time.monotonic() - started:.3f}s host={upload_host} "
            f"error={clean_error(exc, token)}"
        )
        results.append((f"upload-{client}", False, host_from_error(exc)))
    finally:
        try:
            removed = await delete(api, remote_path)
        except Exception as exc:
            removed = False
            report(f"CLEANUP failed path={remote_path} error={clean_error(exc, token)}")
        if removed:
            report(f"CLEANUP ok path={remote_path}")
        else:
            report(f"CLEANUP residual_file={remote_path}")


async def run(args, report) -> int:
    load_env()
    token = os.environ.get("YADISK_TOKEN", "").strip()
    if not token:
        report("FATAL YADISK_TOKEN is missing")
        return 2
    config = json.loads((ROOT / "config_app.json").read_text(encoding="utf-8"))
    control = disk_path(config.get("yadisk_control_folder"))
    updates = disk_path(config.get("yadisk_updates_folder"))

    report(
        f"START label={args.label} platform={platform.platform()} "
        f"python={sys.version.split()[0]} aiohttp={aiohttp.__version__}"
    )
    report(
        f"SETTINGS timeout={args.timeout}s rounds={args.rounds} "
        f"upload={'off' if args.no_upload else str(args.upload_mib) + 'MiB'} "
        f"system_proxies={proxy_summary()}"
    )
    report("SECRETS token=redacted signed_urls=redacted command_bodies=not_read")

    for host in (
        "cloud-api.yandex.net",
        "downloader.disk.yandex.ru",
        "uploader.disk.yandex.net",
    ):
        await asyncio.to_thread(resolve, host, report, token)

    results: list[tuple[str, bool, str]] = []
    try:
        commands = await asyncio.to_thread(
            urllib_list, f"{control}/to_booth", token, args.timeout,
        )
        report(f"API ok client=urllib list=commands items={len(commands)}")
    except Exception as exc:
        commands = []
        report(f"API failed client=urllib list=commands error={clean_error(exc, token)}")
    try:
        artifacts = await asyncio.to_thread(
            urllib_list, f"{updates}/artifacts", token, args.timeout,
        )
        report(f"API ok client=urllib list=artifacts items={len(artifacts)}")
    except Exception as exc:
        artifacts = []
        report(f"API failed client=urllib list=artifacts error={clean_error(exc, token)}")

    command_targets = [
        (f"command:{str(item.get('name', ''))[:8]}", str(item.get("path", "")).removeprefix("disk:"))
        for item in commands
        if item.get("type") == "file" and str(item.get("name", "")).endswith(".json")
    ][:args.max_commands]
    artifact_targets = [
        (f"artifact:{item.get('name')}", str(item.get("path", "")).removeprefix("disk:"))
        for item in artifacts
        if item.get("type") == "file" and str(item.get("name", "")).endswith(".zip")
    ][:args.max_artifacts]
    report(
        f"TARGETS commands={len(command_targets)} artifacts={len(artifact_targets)} "
        f"plus=status.json"
    )

    timeout = aiohttp.ClientTimeout(total=args.timeout, connect=min(8, args.timeout))
    async with aiohttp.ClientSession(
        headers={"Authorization": f"OAuth {token}", "User-Agent": BOOTH_UA},
        timeout=timeout,
        trust_env=False,
    ) as api, aiohttp.ClientSession(
        timeout=timeout,
        trust_env=False,
    ) as direct, aiohttp.ClientSession(
        timeout=timeout,
        trust_env=True,
    ) as system_proxy:
        for label, path in [("status.json", f"{updates}/status.json"), *command_targets]:
            await asyncio.to_thread(
                urllib_download, label, path, token, args.timeout, report, results,
            )
            for round_number in range(1, args.rounds + 1):
                await aio_download(
                    f"{label}:round-{round_number}", path, token, api, direct,
                    "aiohttp-direct", report, results,
                )
                await aio_download(
                    f"{label}:round-{round_number}", path, token, api, system_proxy,
                    "aiohttp-system-proxy", report, results,
                )

        for label, path in artifact_targets:
            await asyncio.to_thread(
                urllib_download, label, path, token, args.timeout, report, results,
            )

        if not args.no_upload:
            probe_id = f"{args.label}_{uuid.uuid4().hex[:12]}"
            payload_size = args.upload_mib * 1024 * 1024
            block = b"photobooth-network-probe-0123456789\n"
            payload = (block * (payload_size // len(block) + 1))[:payload_size]
            await upload_roundtrip(
                f"{control}/configs/network_probe_{probe_id}_media.jpg",
                payload, token, api, direct, "booth-media-direct", report, results,
            )
            await upload_roundtrip(
                f"{control}/configs/network_probe_{probe_id}_control.json",
                payload, token, api, system_proxy, "booth-control-system-proxy",
                report, results,
            )

    report("SUMMARY")
    counts = Counter((client, ok) for client, ok, _host in results)
    for client in sorted({client for client, _ok, _host in results}):
        report(
            f"SUMMARY client={client} ok={counts[(client, True)]} "
            f"failed={counts[(client, False)]}"
        )
    host_counts = Counter((host, ok) for _client, ok, host in results)
    for (host, ok), count in sorted(host_counts.items()):
        report(f"SUMMARY host={host} result={'ok' if ok else 'failed'} count={count}")
    report("DONE")
    return 0


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="probe")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--max-commands", type=int, default=4)
    parser.add_argument("--max-artifacts", type=int, default=4)
    parser.add_argument("--upload-mib", type=int, default=2)
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    if not LABEL_RE.fullmatch(args.label):
        parser.error("invalid --label")
    if args.quick:
        args.rounds, args.max_commands, args.max_artifacts = 1, 1, 2
    if not 1 <= args.rounds <= 10:
        parser.error("--rounds must be 1..10")
    if not 2 <= args.timeout <= 60:
        parser.error("--timeout must be 2..60")
    if not 0 <= args.max_commands <= 20 or not 0 <= args.max_artifacts <= 8:
        parser.error("invalid target limit")
    if not 1 <= args.upload_mib <= 16:
        parser.error("--upload-mib must be 1..16")
    return args


def main() -> int:
    args = parse_args()
    report_path, report = make_report(args.label)
    try:
        return asyncio.run(run(args, report))
    except KeyboardInterrupt:
        report("INTERRUPTED; partial report preserved")
        return 130
    except Exception as exc:
        report(f"FATAL {clean_error(exc, os.environ.get('YADISK_TOKEN', ''))}")
        return 1
    finally:
        print(f"Report: {report_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
