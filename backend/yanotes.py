"""Yandex Notes transport layer (async, aiohttp)."""

import datetime
import json
import logging
import aiohttp

BASE = "https://cloud-api.yandex.ru/yadisk_web/v1"
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://disk.yandex.ru",
    "Referer": "https://disk.yandex.ru/",
    "Accept": "application/json",
}


def build_session(session_id: str) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers=HEADERS,
        cookies={"Session_id": session_id},
    )


async def list_notes(s: aiohttp.ClientSession) -> list[dict]:
    async with s.get(f"{BASE}/notes/notes", timeout=aiohttp.ClientTimeout(total=10)) as r:
        r.raise_for_status()
        notes = await r.json()
    if isinstance(notes, dict):
        notes = notes.get("items", notes.get("notes", []))
    return [n for n in notes if 1 not in n.get("tags", [])]


async def create_note(s: aiohttp.ClientSession, title: str) -> str:
    async with s.post(f"{BASE}/notes/notes",
                      json={"title": title, "snippet": "", "tags": []},
                      timeout=aiohttp.ClientTimeout(total=15)) as r:
        r.raise_for_status()
        obj = await r.json()
    if isinstance(obj, list):
        obj = obj[0]
    return obj.get("id") or obj.get("newNoteId") or obj.get("noteId")


async def get_note_content(s: aiohttp.ClientSession, note_id: str) -> tuple[dict | None, str | None]:
    async with s.get(f"{BASE}/notes/notes/{note_id}/content",
                     timeout=aiohttp.ClientTimeout(total=600)) as r:
        if r.status == 404:
            return None, None
        r.raise_for_status()
        raw = await r.read()
        logging.getLogger(__name__).info(f"get_note_content: {len(raw)} bytes")
        import json
        return json.loads(raw), r.headers.get("x-actual-revision")


async def put_note_content(s: aiohttp.ClientSession, note_id: str, payload: str, snippet: str):
    content = {"name": "$root", "children": [
        {"name": "paragraph", "children": [
            {"data": ".", "attributes": [["d", payload]]} if payload else {"data": "."}
        ]},
    ]}
    body = {
        "content": json.dumps(content, separators=(",", ":")),
        "snippet": snippet,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Mtime": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    async with s.put(f"{BASE}/notes/notes/{note_id}/content_with_meta",
                     headers=headers, data=json.dumps(body),
                     timeout=aiohttp.ClientTimeout(total=120)) as r:
        r.raise_for_status()


async def clear_note(s: aiohttp.ClientSession, note_id: str):
    await put_note_content(s, note_id, "", "")


async def get_db_revision(s: aiohttp.ClientSession) -> int:
    async with s.get(f"{BASE}/data/app/databases/.ext.yanotes@notes",
                     timeout=aiohttp.ClientTimeout(total=10)) as r:
        r.raise_for_status()
        data = await r.json()
    return data.get("revision", 0)


async def get_deltas(s: aiohttp.ClientSession, base_revision: int) -> dict:
    async with s.get(f"{BASE}/data/app/databases/.ext.yanotes@notes/deltas",
                     params={"base_revision": base_revision, "limit": 100},
                     timeout=aiohttp.ClientTimeout(total=10)) as r:
        r.raise_for_status()
        return await r.json()


async def find_or_create_notes(s: aiohttp.ClientSession, titles: list[str]) -> dict[str, str]:
    existing = await list_notes(s)
    title_to_id = {}
    for n in existing:
        t = n.get("title", "")
        if t in titles:
            title_to_id[t] = n["id"]

    for t in titles:
        if t not in title_to_id:
            note_id = await create_note(s, t)
            log.info(f"Created note '{t}': {note_id}")
            title_to_id[t] = note_id

    return title_to_id
