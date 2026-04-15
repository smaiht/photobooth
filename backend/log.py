"""Logging setup — file only."""

import logging
import os
from logging.handlers import RotatingFileHandler

_log_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            RotatingFileHandler(
                os.path.join(_log_dir, "photobooth.log"),
                encoding="utf-8", maxBytes=1_000_000, backupCount=1),
        ],
    )
