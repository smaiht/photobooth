"""Print service for DNP RX1HS.

Two modes:
  1. Hot Folder - copy image to watched folder, DNP utility prints automatically
  2. Windows Print Driver - send to printer via win32print / subprocess

Print queue runs in background, one job at a time.
"""

import asyncio
import shutil
import logging
from pathlib import Path
from collections import deque

log = logging.getLogger(__name__)

_print_queue: deque[dict] = deque()
_printing = False


async def enqueue_print(image_path: str, config: dict):
    """Add print job to queue. Returns immediately."""
    _print_queue.append({"path": image_path, "config": config})
    asyncio.create_task(_process_queue())


async def _process_queue():
    global _printing
    if _printing:
        return

    while _print_queue:
        _printing = True
        job = _print_queue.popleft()
        try:
            await asyncio.to_thread(_do_print, job["path"], job["config"])
            log.info(f"Printed: {job['path']}")
        except Exception as e:
            log.error(f"Print failed: {e}")
        _printing = False


def _do_print(image_path: str, config: dict):
    """Execute print - runs in thread pool."""
    hot_folder = config.get("hot_folder", "")
    printer_name = config.get("printer_name", "")

    if hot_folder and Path(hot_folder).is_dir():
        _print_hot_folder(image_path, hot_folder)
    else:
        _print_driver(image_path, printer_name)


def _print_hot_folder(image_path: str, folder: str):
    """Copy image to DNP Hot Folder - utility handles the rest."""
    dest = Path(folder) / Path(image_path).name
    shutil.copy2(image_path, dest)
    log.info(f"Copied to hot folder: {dest}")


def _print_driver(image_path: str, printer_name: str):
    """Print via Windows print driver."""
    import subprocess

    try:
        import win32print
        import win32api
        if not printer_name:
            printer_name = win32print.GetDefaultPrinter()
        log.info(f"Printing to {printer_name}")
        win32api.ShellExecute(0, "print", image_path, f'/d:"{printer_name}"', ".", 0)
    except ImportError:
        cmd = f'Start-Process -FilePath "{image_path}" -Verb Print -PassThru'
        subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=30)
