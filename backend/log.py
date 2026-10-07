"""Logging setup — one file only."""

import logging
import os
from pathlib import Path

_log_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = Path(_log_dir) / "photobooth.log"
# /logs sends the log as one response document, which has a size limit
# (yadisk_control.MAX_RESPONSE_DOCUMENT_SIZE), so only the tail is sent.
LOG_SNAPSHOT_BYTES = 400_000


def setup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
    )


def read_log_snapshot(log_path: Path = LOG_PATH, limit: int = LOG_SNAPSHOT_BYTES) -> bytes:
    """Return the last `limit` bytes of the log, starting at a whole line."""
    with open(log_path, "rb") as log_file:
        size = log_file.seek(0, os.SEEK_END)
        log_file.seek(max(0, size - limit))
        snapshot = log_file.read()
    if size > limit:
        snapshot = snapshot.partition(b"\n")[2]
    return snapshot
