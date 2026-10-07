"""Power-cycle the camera through a USB relay while searching for it keeps failing.

The camera adapter goes through the NC contact of an LCUS-1 relay, so the
camera is powered by default and switching the relay on cuts its power. The
board is picked by CAMERA_RELAY_PORT in .env; without it nothing is done.

Every SEARCHES_BEFORE_CUT failed searches in a row the power is cut for
CUT_SECONDS. After it comes back the searches are counted from zero again, so
a camera that is still missing gets the next cut, until it is found.
"""

import asyncio
import logging
import os
import uuid

from . import relay, yadisk_control

SEARCHES_BEFORE_CUT = 3
CUT_SECONDS = 10

log = logging.getLogger(__name__)
_lost = asyncio.Event()
_reason = ""
_failed = 0    # failed searches since the camera was found or the power came back
_told = False  # the admin already knows about this outage


def search_failed(reason):
    """One more search for the camera came back empty."""
    global _failed, _reason
    _failed += 1
    if _failed >= SEARCHES_BEFORE_CUT:
        _reason = str(reason)[:300]
        _lost.set()


def camera_found():
    global _failed, _told
    _failed = 0
    _told = False


async def _power(port, cut):
    await asyncio.to_thread(relay.switch, port, cut)


async def _tell_admin(text):
    """One notice per outage: a camera that never returns must not flood the chat."""
    global _told
    if _told:
        return
    try:
        await yadisk_control.publish_booth_notice(
            "camera_power", "Камера не найдена", text, notice_id=uuid.uuid4().hex)
        _told = True
    except Exception as exc:
        # The booth must stay usable even when the notice cannot be delivered.
        log.warning("Camera power: notice not published: %s", exc)


async def _cycle(port, reason):
    global _failed
    notice = None
    try:
        await _power(port, True)
        log.warning("Camera power: camera not found after %d searches (%s), power off for %ss",
                    SEARCHES_BEFORE_CUT, reason, CUT_SECONDS)
        notice = asyncio.create_task(_tell_admin(
            f"Камера не найдена после {SEARCHES_BEFORE_CUT} попыток поиска ({reason}). "
            f"Питание камеры выключено на {CUT_SECONDS} с, потом включится само. "
            "Если камера не найдётся и после этого, отключение повторится."))
        await asyncio.sleep(CUT_SECONDS)
    finally:
        # Always give the power back, also when the cut failed or the app stops.
        try:
            await _power(port, False)
            log.info("Camera power: power back on")
        except Exception as exc:
            log.error("Camera power: relay did not give the power back: %s", exc)
        # The searches that failed while the power was cut do not count.
        _failed = 0
        _lost.clear()
    await notice


async def watch():
    port = os.environ.get("CAMERA_RELAY_PORT", "").strip()
    if not port:
        log.info("Camera power: CAMERA_RELAY_PORT is not set, the camera is never power-cycled")
        return
    try:
        # Powered for sure, also after a stop in the middle of a cycle.
        await _power(port, False)
        log.info("Camera power: relay on %s, camera powered", port)
    except Exception as exc:
        log.error("Camera power: relay on %s does not answer: %s", port, exc)
    while True:
        await _lost.wait()
        try:
            await _cycle(port, _reason)
        except Exception as exc:  # the cut itself failed
            log.error("Camera power: relay did not cut the power: %s", exc)
            await _tell_admin(f"Камера не найдена после {SEARCHES_BEFORE_CUT} попыток поиска "
                              f"({_reason}), но реле не сработало: {exc}")
