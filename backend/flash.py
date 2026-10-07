"""Keep the Neewer Q4 Pro battery between LOW and HIGH percent.

Every POLL_SECONDS the flash is asked over Bluetooth for its settings dump,
which carries the battery level, and the charger is switched by a USB relay
(LCUS-1). Packet layout: diagnostics/flash_probe.py.
"""

import asyncio
import contextlib
import logging
import os

from bleak import BleakClient, BleakScanner
from serial.tools import list_ports

from . import relay

BLE_NAME = "Q4Pro"
WRITE = "69400002-b5a3-f393-e0a9-e50e24dcca99"
NOTIFY = "69400003-b5a3-f393-e0a9-e50e24dcca99"
DUMP_REQUEST = bytes.fromhex("85 94 01 00 1a")  # the flash answers with all its settings
POLL_SECONDS = 60
LOW = 25   # a charge cycle starts at or below this percent
HIGH = 85  # and ends at or above this one
RELAY_USB_ID = (0x1A86, 0x7523)  # CH340 chip of the LCUS-1 board
# Reply tag -> name of its first payload byte in the log line.
EXTRA = {0x22: "awake", 0x25: "capacitor", 0x24: "error", 0x26: "overheat"}

log = logging.getLogger(__name__)
status = "выключено"
session_active = False
wake = asyncio.Event()


def next_cycle(cycle, battery):
    """A charge cycle starts at LOW and ends at HIGH; in between it goes on as it was."""
    if battery is None:
        return cycle
    if battery <= LOW:
        return True
    if battery >= HIGH:
        return False
    return cycle


def session(active):
    """A photo session started or ended; the watcher reacts at once.

    A start puts the charger off, an end checks the battery right away so the
    charge cycle resumes without waiting for the next poll.
    """
    global session_active
    session_active = active
    wake.set()


async def read_flash():
    """Connect, ask for the settings dump and return its packets as {tag: payload}."""
    packets = {}
    battery_seen = asyncio.Event()

    def on_data(_, data):
        if len(data) > 4 and data[0] == 0x85 and data[-1] == sum(data[:-1]) & 0xFF:
            packets[data[1]] = bytes(data[3:-1])
            if data[1] == 0x23:
                battery_seen.set()

    device = await BleakScanner.find_device_by_filter(
        lambda device, adv: BLE_NAME in (adv.local_name or device.name or ""), timeout=10)
    if device is None:
        raise RuntimeError("вспышка не найдена по Bluetooth")
    async with BleakClient(device, timeout=15) as client:
        await client.start_notify(NOTIFY, on_data)
        for _ in range(3):  # the first request after connecting can get lost
            await client.write_gatt_char(WRITE, DUMP_REQUEST, response=True)
            try:
                await asyncio.wait_for(battery_seen.wait(), 2)
                break
            except TimeoutError:
                pass
        else:
            raise RuntimeError("вспышка не отвечает")
        await asyncio.sleep(0.3)  # the rest of the dump follows the battery packet
    return packets


def set_relay(on):
    camera_port = os.environ.get("CAMERA_RELAY_PORT", "").strip()
    port = os.environ.get("FLASH_RELAY_PORT", "").strip()  # set in .env when the board is not alone
    if not port:
        ports = [p.device for p in list_ports.comports()
                 if (p.vid, p.pid) == RELAY_USB_ID and p.device != camera_port]
        if not ports:
            raise RuntimeError("LCUS-1 не найден (CH340)")
        if len(ports) > 1:  # identical boards cannot be told apart, so do not guess
            raise RuntimeError(f"найдено несколько LCUS-1 (CH340): {', '.join(ports)}; "
                               "задай FLASH_RELAY_PORT в .env")
        port = ports[0]
    if port == camera_port:  # the camera power must never follow the charge cycle
        raise RuntimeError("зарядка и камера указаны на одном реле")
    relay.switch(port, on)


async def watch(config):
    global status
    if not config.get("flash_enabled", False):
        status = "выключено"
        log.info("Flash: disabled")
        return
    log.info("Flash: battery watch started")
    cycle = False
    while True:
        battery, extra, problems = None, "", []
        if not session_active:  # no Bluetooth traffic while the flash fires
            try:
                packets = await asyncio.wait_for(read_flash(), 45)
                battery = min(packets[0x23][0], 100)
                extra = " ".join(f"{name}={packets[tag][0]}"
                                 for tag, name in EXTRA.items() if tag in packets)
            except Exception as exc:
                problems.append(str(exc) or type(exc).__name__)
        cycle = next_cycle(cycle, battery)
        charging = cycle and not session_active
        try:
            await asyncio.to_thread(set_relay, charging)
        except Exception as exc:
            problems.append(f"реле: {exc or type(exc).__name__}")
        state = f"зарядка {'вкл' if charging else 'выкл'}"
        if session_active:
            status = f"сессия, {state}"
        else:
            status = "; ".join([f"{battery}%, {state}" if battery is not None else state, *problems])
        parts = [
            f"battery={battery}%" if battery is not None else "battery=?",
            f"charging={'on' if charging else 'off'}",
            f"session={'yes' if session_active else 'no'}",
            extra, *problems,
        ]
        (log.warning if problems else log.info)("Flash: " + " ".join(p for p in parts if p))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), POLL_SECONDS)
        wake.clear()
