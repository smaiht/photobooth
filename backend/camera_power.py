"""Bring a broken camera back: a USB relay power cut and, when needed, a new process.

The camera adapter goes through the NC contact of an LCUS-1 relay, so the
camera is powered by default and switching the relay on cuts its power. The
board is picked by CAMERA_RELAY_PORT in .env; without it nothing is done.

- A cut alone (CUT_SECONDS) revives a camera that is connected but stuck: no
  live view, refused shots, no photo. EDSDK keeps working and opens it again.
- A reset is a cut followed by an app restart, for everything else: a camera
  that failed or dropped off USB while connected, one EDSDK cannot open, EDSDK
  stuck in a call. Such a camera keeps its old session, EDSDK keeps a stale one,
  and opening the camera again in the same process can crash the process. So
  the camera stays off and a new process gives the power back and opens it fresh.
- A camera that is not on USB at all only gets cuts: no process can open it.

A process started by a reset knows it (RESTART_ENV): the admin already has the
notice, so a camera that keeps failing does not flood the chat.
"""

import asyncio
import contextlib
import logging
import os
import uuid

from . import relay, yadisk_control

SEARCHES_BEFORE_CUT = 5
CUT_SECONDS = 10
RESTART_ENV = "PHOTOBOOTH_CAMERA_RESTART"

log = logging.getLogger(__name__)
_restarted = os.environ.pop(RESTART_ENV, "") == "1"  # this process was started by a reset
_lost = asyncio.Event()
_reason = ""
_remedy = "cut"   # "cut" or "reset"
_failed = 0       # failed searches since the camera was found or the power came back
_told = _restarted  # the admin already knows about this outage
_cutting = False  # the relay holds the camera unpowered on purpose right now


def search_failed(reason):
    """One more search for the camera came back empty."""
    global _failed
    if _cutting:  # searches during the cut do not count
        return
    _failed += 1
    if _failed >= SEARCHES_BEFORE_CUT:
        _start(f"Камера не найдена после {SEARCHES_BEFORE_CUT} попыток поиска ({reason})",
               "cut" if reason == "No camera found" else "reset")


def camera_hung(reason):
    """The camera is connected but stopped working: no live view, no shot, no photo."""
    _start(f"Камера не отвечает ({reason})", "cut")


def camera_lost(reason):
    """A connected camera failed or dropped off USB, not by our own cut."""
    if not _cutting:
        _start(f"Камера отключилась ({reason})", "reset")


def sdk_stuck(reason):
    """EDSDK stays stuck in a call even after the power cut."""
    _start(f"Камера не отвечает ({reason})", "reset")


def _start(reason, remedy):
    global _reason, _remedy
    _reason, _remedy = reason[:300], remedy
    _lost.set()


def camera_found():
    global _failed, _told
    _failed = 0
    _told = False


def set_relay(on):
    port = os.environ.get("CAMERA_RELAY_PORT", "").strip()
    if not port:
        raise RuntimeError("CAMERA_RELAY_PORT не задан в .env")
    relay.switch(port, not on)


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


async def _cycle(port, reason, camera_alive):
    global _failed, _cutting
    notice = None
    kept_power = False
    _cutting = True  # before the switch: the camera drops at once
    try:
        await _power(port, True)
        log.warning("Camera power: %s, power off for %ss", reason, CUT_SECONDS)
        notice = asyncio.create_task(_tell_admin(
            f"{reason}. Питание камеры выключено на {CUT_SECONDS} с, потом включится само. "
            "Если камера не найдётся и после этого, будка перезапустится."))
        await asyncio.sleep(CUT_SECONDS)
        # An unpowered camera cannot stay connected: the relay did not switch.
        kept_power = camera_alive()
    finally:
        _cutting = False
        # Always give the power back, also when the cut failed or the app stops.
        try:
            await _power(port, False)
            log.info("Camera power: power back on")
        except Exception as exc:
            log.error("Camera power: relay did not give the power back: %s", exc)
        _failed = 0
        _lost.clear()
    await notice
    if kept_power:
        log.error("Camera power: the camera stayed connected through the cut, "
                  "the relay on %s did not cut its power", port)


async def _reset(port, reason, restart):
    """Power off and restart; the new process gives the power back when it starts."""
    global _cutting
    _cutting = True
    try:
        await _power(port, True)
    except Exception as exc:  # a fresh EDSDK may still help
        log.error("Camera power: relay did not cut the power: %s", exc)
    log.warning("Camera power: %s, power off and restarting the app", reason)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(_tell_admin(
            f"{reason}. Будка выключила питание камеры и перезапускается, "
            "чтобы открыть её заново."), 5)
    os.environ[RESTART_ENV] = "1"
    await restart()


async def watch(camera_alive=lambda: False, restart=None):
    port = os.environ.get("CAMERA_RELAY_PORT", "").strip()
    if not port:
        log.info("Camera power: CAMERA_RELAY_PORT is not set, the camera is never power-cycled")
        return
    try:
        # Powered for sure, also after a reset or a stop in the middle of a cycle.
        await _power(port, False)
        log.info("Camera power: relay on %s, camera powered", port)
    except Exception as exc:
        log.error("Camera power: relay on %s does not answer: %s", port, exc)
    while True:
        await _lost.wait()
        _lost.clear()
        try:
            if _remedy == "reset" and restart:
                await _reset(port, _reason, restart)
                return
            await _cycle(port, _reason, camera_alive)
        except Exception as exc:  # the cut itself failed
            log.error("Camera power: relay did not cut the power: %s", exc)
            await _tell_admin(f"{_reason}, но реле не сработало: {exc}")
