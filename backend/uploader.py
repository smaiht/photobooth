"""Upload service — Telegram Bot.

Sends each session to a Telegram chat as:
1. Media album: 4 compressed photos + video (pretty in chat)
2. Document album: 4 original photos + collage (full quality)

Post-event: zip entire event folder for manual backup.
"""

import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)

QUEUE_FILE = Path("photos") / "_upload_queue.json"


class Uploader:
    def __init__(self, config: dict):
        self.tg_bot_token = config.get("tg_bot_token", "")
        self.tg_chat_id = config.get("tg_chat_id", "")
        self._queue: list[dict] = []
        self._load_queue()

    def _load_queue(self):
        if QUEUE_FILE.exists():
            try:
                self._queue = json.loads(QUEUE_FILE.read_text())
            except Exception:
                self._queue = []

    def _save_queue(self):
        QUEUE_FILE.write_text(json.dumps(self._queue, ensure_ascii=False))

    async def upload_session(self, session_id: str, photos: list[str],
                              collage: str | None = None, video: str | None = None):
        entry = {
            "session_id": session_id,
            "photos": photos,
            "collage": collage,
            "video": video,
            "timestamp": datetime.now().isoformat(),
            "done": False,
            "retries": 0,
        }
        self._queue.append(entry)
        self._save_queue()
        asyncio.create_task(self._process_entry(entry))

    async def _process_entry(self, entry: dict):
        if not self.tg_bot_token or not self.tg_chat_id:
            log.warning("TG_BOT_TOKEN or TG_CHAT_ID not set")
            return

        # Retry up to 3 times immediately, then give up to background queue
        for attempt in range(10):
            try:
                import aiohttp

                base = f"https://api.telegram.org/bot{self.tg_bot_token}"
                chat = self.tg_chat_id

                async with aiohttp.ClientSession() as session:
                    await self._send_media_album(session, base, chat, entry)
                    await self._send_document_album(session, base, chat, entry)

                entry["done"] = True
                if entry in self._queue:
                    self._queue.remove(entry)
                log.info(f"Telegram sent: session {entry['session_id']}")
                self._save_queue()
                return

            except Exception as e:
                log.warning(f"Telegram attempt {attempt + 1}/10 failed: {e}")
                if attempt < 9:
                    await asyncio.sleep(1)

        entry["retries"] += 1
        log.warning(f"Telegram queued for later: session {entry['session_id']}")
        self._save_queue()

    async def _send_media_album(self, session, base: str, chat: str, entry: dict):
        """Send compressed photos + video as media album (looks nice in chat)."""
        import aiohttp

        media = []
        files = {}

        for i, photo_path in enumerate(entry["photos"]):
            p = Path(photo_path)
            if not p.exists():
                continue
            key = f"photo{i}"
            media.append({
                "type": "photo",
                "media": f"attach://{key}",
                **({"caption": f"📸 #{entry['session_id']}"} if i == 0 else {}),
            })
            files[key] = p

        if entry.get("video") and Path(entry["video"]).exists():
            media.append({"type": "video", "media": "attach://video"})
            files["video"] = Path(entry["video"])

        if media:
            await self._send_media_group(session, base, chat, media, files)

    async def _send_document_album(self, session, base: str, chat: str, entry: dict):
        """Send original photos + collage as documents (no compression)."""
        import aiohttp

        media = []
        files = {}

        for i, photo_path in enumerate(entry["photos"]):
            p = Path(photo_path)
            if not p.exists():
                continue
            key = f"doc{i}"
            media.append({
                "type": "document",
                "media": f"attach://{key}",
                **({"caption": "📎 Оригиналы"} if i == 0 else {}),
            })
            files[key] = p

        if entry.get("collage") and Path(entry["collage"]).exists():
            media.append({"type": "document", "media": "attach://collage"})
            files["collage"] = Path(entry["collage"])

        if media:
            await self._send_media_group(session, base, chat, media, files)

    async def _send_media_group(self, session, base: str, chat: str,
                                 media: list, files: dict[str, Path]):
        import aiohttp

        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat))
        data.add_field("media", json.dumps(media))

        for name, path in files.items():
            data.add_field(name, open(path, "rb"), filename=path.name)

        async with session.post(f"{base}/sendMediaGroup", data=data,
                                 timeout=aiohttp.ClientTimeout(total=120),
                                 ssl=False) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Telegram {resp.status}: {body}")

    async def retry_pending(self):
        for entry in list(self._queue):
            if not entry.get("done") and entry["retries"] < 10:
                await self._process_entry(entry)
