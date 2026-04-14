"""Yandex Notes transport layer.

Uses Yandex Notes API to transfer data via note attributes.
Data is encrypted with Fernet (AES-128-CBC) using a shared key.
"""

import base64
import datetime
import hashlib
import json
import logging
import requests

BASE = "https://cloud-api.yandex.ru/yadisk_web/v1"
log = logging.getLogger(__name__)


def make_fernet_key(password: str) -> bytes:
    """Derive Fernet key from password string."""
    return base64.urlsafe_b64encode(hashlib.sha256(password.encode()).digest())


def build_session(session_id: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("Session_id", session_id)
    s.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://disk.yandex.ru",
        "Referer": "https://disk.yandex.ru/",
        "Accept": "application/json",
    })
    return s


def list_notes(s: requests.Session) -> list[dict]:
    """List all active notes (not deleted)."""
    r = s.get(f"{BASE}/notes/notes", timeout=15)
    r.raise_for_status()
    notes = r.json()
    if isinstance(notes, dict):
        notes = notes.get("items", notes.get("notes", []))
    return [n for n in notes if 1 not in n.get("tags", [])]


def create_note(s: requests.Session, title: str) -> str:
    """Create note, return note_id."""
    r = s.post(f"{BASE}/notes/notes", json={"title": title, "snippet": "", "tags": []}, timeout=15)
    r.raise_for_status()
    obj = r.json()
    if isinstance(obj, list):
        obj = obj[0]
    return obj.get("id") or obj.get("newNoteId") or obj.get("noteId")


def get_note_content(s: requests.Session, note_id: str) -> tuple[dict | None, str | None]:
    """Get note content and revision."""
    r = s.get(f"{BASE}/notes/notes/{note_id}/content", timeout=60)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    return r.json(), r.headers.get("x-actual-revision")


def put_note_content(s: requests.Session, note_id: str, payload: str, snippet: str) -> None:
    """Write payload string into note attribute."""
    content = {"name": "$root", "children": [
        {"name": "paragraph", "children": [
            {"data": ".", "attributes": [["d", payload]]} if payload else {"data": "."}
        ]},
    ]}
    body = {
        "content": json.dumps(content, ensure_ascii=False, separators=(",", ":")),
        "snippet": snippet,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Mtime": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    r = s.put(f"{BASE}/notes/notes/{note_id}/content_with_meta",
              headers=headers, data=json.dumps(body, ensure_ascii=False), timeout=120)
    r.raise_for_status()


def clear_note(s: requests.Session, note_id: str) -> None:
    """Clear note content and snippet."""
    put_note_content(s, note_id, "", "")


def get_db_revision(s: requests.Session) -> int:
    """Get current database revision."""
    r = s.get(f"{BASE}/data/app/databases/.ext.yanotes@notes", timeout=15)
    r.raise_for_status()
    return r.json().get("revision", 0)


def get_deltas(s: requests.Session, base_revision: int) -> dict:
    """Get changes since base_revision."""
    r = s.get(f"{BASE}/data/app/databases/.ext.yanotes@notes/deltas",
              params={"base_revision": base_revision, "limit": 100}, timeout=15)
    r.raise_for_status()
    return r.json()


def find_or_create_notes(s: requests.Session, titles: list[str]) -> dict[str, str]:
    """Ensure notes with given titles exist. Returns {title: note_id}."""
    existing = list_notes(s)
    title_to_id = {}
    for n in existing:
        t = n.get("title", "")
        if t in titles:
            title_to_id[t] = n["id"]

    for t in titles:
        if t not in title_to_id:
            note_id = create_note(s, t)
            log.info(f"Created note '{t}': {note_id}")
            title_to_id[t] = note_id

    return title_to_id
