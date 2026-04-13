"""Upload session ZIP to Beeline Cloud via WebDAV."""

import asyncio
import logging
import os
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

WEBDAV_URL = "https://webdav.cloudbeeline.ru/photobooth"


async def cloud_init():
    """Create upload folder on startup."""
    import aiohttp
    login = os.environ.get("BEELINECLOUD_LOGIN", "")
    password = os.environ.get("BEELINECLOUD_PASSWORD", "")
    if not login or not password:
        return
    try:
        auth = aiohttp.BasicAuth(login, password)
        async with aiohttp.ClientSession(auth=auth) as s:
            async with s.request("MKCOL", f"{WEBDAV_URL}/", timeout=aiohttp.ClientTimeout(total=10), ssl=False):
                pass
        log.info("Cloud: ready")
    except Exception as e:
        log.warning(f"Cloud: init failed: {e}")


async def cloud_upload(session_id: str, photos: list[str],
                       collage: str | None, video: str | None):
    login = os.environ.get("BEELINECLOUD_LOGIN", "")
    password = os.environ.get("BEELINECLOUD_PASSWORD", "")

    if not login or not password:
        log.warning("Beeline Cloud: credentials not set")
        return

    log.info(f"Cloud: packing session {session_id}...")
    try:
        zip_path = await asyncio.get_event_loop().run_in_executor(
            None, _make_zip, session_id, photos, collage, video
        )
        size_mb = Path(zip_path).stat().st_size / 1024 / 1024
        log.info(f"Cloud: archive {size_mb:.1f}MB, uploading...")

        await _upload(zip_path, login, password)
        Path(zip_path).unlink(missing_ok=True)
        log.info(f"Cloud: uploaded {Path(zip_path).name} ({size_mb:.1f}MB)")
    except Exception as e:
        log.error(f"Cloud: upload failed: {e}")


def _make_zip(session_id: str, photos: list[str],
              collage: str | None, video: str | None) -> str:
    session_dir = Path(photos[0]).parent if photos else Path(".")
    zip_path = str(session_dir / f"{session_id}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for i, p in enumerate(photos):
            if Path(p).exists():
                zf.write(p, f"photo_{i+1}.jpg")
        if video and Path(video).exists():
            zf.write(video, "video.mp4")

    return zip_path


async def _upload(file_path: str, login: str, password: str):
    import aiohttp

    auth = aiohttp.BasicAuth(login, password)
    data = Path(file_path).read_bytes()
    url = f"{WEBDAV_URL}/{Path(file_path).name}"

    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.put(url, data=data,
                               timeout=aiohttp.ClientTimeout(total=600),
                               ssl=False) as resp:
            if resp.status not in (200, 201, 204):
                body = await resp.text()
                raise RuntimeError(f"WebDAV PUT {resp.status}: {body}")
