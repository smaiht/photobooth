"""Logging setup — file only."""

import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler

_log_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = Path(_log_dir) / "photobooth.log"
LOG_MAX_BYTES = 200_000
LOG_BACKUP_COUNT = 1


def setup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            RotatingFileHandler(
                LOG_PATH,
                encoding="utf-8",
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
            ),
        ],
    )


def read_log_snapshot(log_path: Path = LOG_PATH) -> bytes:
    """Return the previous and active log segments in chronological order."""
    log_path = Path(log_path)
    handler = next((
        candidate
        for candidate in logging.getLogger().handlers
        if (isinstance(candidate, RotatingFileHandler)
            and Path(candidate.baseFilename).resolve() == log_path.resolve())
    ), None)

    if handler:
        handler.acquire()
    try:
        snapshot = bytearray()
        for path in (log_path.with_name(log_path.name + ".1"), log_path):
            if not path.is_file():
                continue
            segment = path.read_bytes()
            if snapshot and segment and not snapshot.endswith(b"\n"):
                snapshot.extend(b"\n")
            snapshot.extend(segment)
        return bytes(snapshot)
    finally:
        if handler:
            handler.release()
