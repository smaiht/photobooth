"""Upload session ZIP to Yandex Disk via WebDAV."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

WEBDAV_BASE = "https://webdav.yandex.ru"
UPLOAD_PATH = "/_traffic/send_photos_to_vps"
LOGIN = os.environ.get("YADISK_LOGIN", "")
PASSWORD = os.environ.get("YADISK_PASSWORD", "")


async def yadisk_upload(session_id: str, photos: list[str],
                        collage: str | None, video: str | None):
    if not LOGIN or not PASSWORD:
        log.warning("YADISK credentials not set, skipping")
        return

    try:
        zip_path = await asyncio.get_event_loop().run_in_executor(
            None, _make_zip, session_id, photos, collage, video
        )
        await _upload_webdav(zip_path)
        Path(zip_path).unlink(missing_ok=True)
        log.info(f"Yandex Disk: uploaded {Path(zip_path).name}")
    except Exception as e:
        log.warning(f"Yandex Disk upload failed: {e}")


def _make_zip(session_id: str, photos: list[str],
              collage: str | None, video: str | None) -> str:
    session_dir = Path(photos[0]).parent if photos else Path(".")
    zip_path = str(session_dir / f"{session_id}.zip")

    meta = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "photos": [Path(p).name for p in photos],
        "collage": Path(collage).name if collage else None,
        "video": Path(video).name if video else None,
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False))
        for p in photos:
            if Path(p).exists():
                zf.write(p, Path(p).name)
        if collage and Path(collage).exists():
            zf.write(collage, Path(collage).name)
        if video and Path(video).exists():
            zf.write(video, Path(video).name)

    return zip_path


async def _upload_webdav(file_path: str):
    import aiohttp

    data = Path(file_path).read_bytes()
    md5 = hashlib.md5(data).hexdigest()
    sha256 = hashlib.sha256(data).hexdigest().upper()
    auth = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    url = f"{WEBDAV_BASE}{UPLOAD_PATH}/{Path(file_path).name}"

    async with aiohttp.ClientSession() as session:
        async with session.put(url, data=data, headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/binary",
            "Content-Length": str(len(data)),
            "Etag": md5,
            "Sha256": sha256,
            "Expect": "100-continue",
        }, timeout=aiohttp.ClientTimeout(total=300), expect100=True) as resp:
            if resp.status not in (200, 201, 204):
                body = await resp.text()
                raise RuntimeError(f"WebDAV PUT {resp.status}: {body}")
