"""Logging setup — file only."""

import logging
import os

_log_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(_log_dir, "photobooth.log"), encoding="utf-8"),
        ],
    )
