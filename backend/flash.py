"""Keep the Neewer Q4 Pro battery between LOW and HIGH percent and guard its settings.

Every POLL_SECONDS the flash is asked over Bluetooth for its settings dump
(0x94), which returns all 15 telemetry and configuration packets at once:
  0x23  [75]                  Батарея: 75%
  0x22  [1]                   Статус сна: 1 (бодрствует, 0 = в standby) -> запись 0xA4
  0x25  [1]                   Конденсатор: 1 (заряжен, готов)
  0x24  [0]                   Код ошибки (если присылается)
  0x26  [0]                   Перегрев (если присылается)
  0x09  [1, 0, 5]             Прошивка: v1.0.5
  0x20  [1, 9, 0, 0, 0, 0]    Режим и мощность: вспышка сама меняет их при каждом кадре, только в лог
  0x0C  [18, 0, 18]           Радио 2.4G: канал Ch 18 (0x12), группа A (0), ID 18 (0 = OFF) -> запись 0x8B
  0x07  [0]                   Синхронизация: 0 = радио 2.4G (1 = S1, 2 = S2 выкл) -> запись 0x8D
  0x21  [0, 0, 40, 27]        Модельный свет: первый байт 0 = выкл, 1 = вкл (на время сессии);
                              яркость 40%, температура 2700K -> запись 0xA2
  0x99  [0, 1, 0, 0, 0]       Шторка / HSS: 1-я шторка, без HSS -> запись 0x99
  0x02  [0]                   Burst (серия): 0 (ВЫКЛ) -> запись 0x83
  0x0B  [0, 0, 0]             Mask / ALT: 0 (ВЫКЛ) -> запись 0x92
  0x03  [0, 0, 0]             TimeLapse: 0 (ВЫКЛ) -> запись 0x85
  0x05  [0]                   Сцены MOTIF: 0 (ВЫКЛ) -> запись 0x89
  0x08  [0, 0, 4, 0, 0, 0, 1] Меню: бипер=0(ВЫКЛ), звук_кнопок=0(ВЫКЛ), сон_вспышки=4(ВЫКЛ),
                              шаг=0(0.1), шкала=0(1/x), сон_экрана=0(ВЫКЛ), X-System=1(ВКЛ) -> запись 0x90
"""

import asyncio
import contextlib
import logging
import os
import time
import uuid

from bleak import BleakClient, BleakScanner
from serial.tools import list_ports

from . import relay, yadisk_control

# --- Настройки порога зарядки и интервала опроса ---
LOW = 25           # % батареи, при котором ВКЛЮЧАЕТСЯ зарядка (<= LOW)
HIGH = 85          # % батареи, при котором ВЫКЛЮЧАЕТСЯ зарядка (>= HIGH)
POLL_SECONDS = 60  # интервал опроса вспышки по Bluetooth в секундах

BLE_NAME = "Q4Pro"
WRITE = "69400002-b5a3-f393-e0a9-e50e24dcca99"
NOTIFY = "69400003-b5a3-f393-e0a9-e50e24dcca99"
DUMP_REQUEST = bytes.fromhex("85 94 01 00 1a")  # the flash answers with all its settings
RELAY_USB_ID = (0x1A86, 0x7523)  # CH340 chip of the LCUS-1 board


def _off_on(v):
    return f"{'ВКЛ' if v else 'ВЫКЛ'}({v})"


def _fmt_mode(b):
    mode = {0: "TTL", 1: "M(ручной)", 2: "Multi"}.get(b[0], str(b[0]))
    if b[0] == 1 and b[2:] == b"\x00\x00\x00\x00":
        return f"{mode}/шаг_{b[1]}"
    if b[0] == 2:
        return f"{mode}/шаг_{b[1]}/{b[4]}x{b[5]}Гц"
    return f"{mode}/{b[1]}" if b[2:] == b"\x00\x00\x00\x00" else f"{mode}/{b.hex(':')}"


def _fmt_radio(b):
    grp = "ABCDE"[b[1]] if b[1] < 5 else str(b[1])
    id_str = "OFF(0)" if b[2] == 0 else str(b[2])
    return f"Ch{b[0]}/гр.{grp}/ID_{id_str}"


def _fmt_menu(b):
    if len(b) < 7:
        return b.hex(":")
    sleep = {0: "5м", 1: "30м", 2: "60м", 3: "90м", 4: "ВЫКЛ"}.get(b[2], str(b[2]))
    step = {0: "0.1", 1: "1.0"}.get(b[3], str(b[3]))
    scale = {0: "1/x", 1: "десят."}.get(b[4], str(b[4]))
    scr = {0: "ВЫКЛ", 1: "30с", 2: "1м", 3: "1м30с", 4: "2м", 5: "2м30с", 6: "3м"}.get(b[5], str(b[5]))
    return (f"[бипер={_off_on(b[0])}, звук_кнопок={_off_on(b[1])}, сон={sleep}({b[2]}), "
            f"шаг={step}({b[3]}), шкала={scale}({b[4]}), экран={scr}({b[5]}), X-System={_off_on(b[6])}]")


# Read-only telemetry tags -> (name, formatter).
EXTRA = {
    0x20: ("режим", _fmt_mode),  # the flash changes it itself at every shot, so it is not guarded
    0x25: ("конденсатор", lambda b: f"{'готов' if b[0] == 1 else 'заряжается'}({b[0]})"),
    0x24: ("ошибка", lambda b: str(b[0])),
    0x26: ("перегрев", lambda b: str(b[0])),
}


# The modeling light is the first byte of its settings (40%, 2700K): a session turns it
# on for autofocus and off again after the last shot.
LAMP_TAG, LAMP_WRITE = 0x21, 0xA2
LAMP_ON, LAMP_OFF = bytes.fromhex("01 00 28 1b"), bytes.fromhex("00 00 28 1b")
LAMP_SECONDS = 20  # a Bluetooth command that takes longer is dropped

# (reply_tag, write_tag, expected_payload, name, formatter)
SETTINGS = (
    (0x22, 0xA4, b"\x01", "сон_статус", lambda b: f"{'бодрствует' if b[0] == 1 else 'standby'}({b[0]})"),
    # Channel 18, group A, ID 18: the same as on the Godox X2T-C trigger.
    (0x0C, 0x8B, bytes.fromhex("12 00 12"), "радио_2.4G", _fmt_radio),
    (0x07, 0x8D, b"\x00", "синхр", lambda b: f"{ {0: '2.4G_радио', 1: 'S1', 2: 'S2'}.get(b[0], b[0]) }({b[0]})"),
    (LAMP_TAG, LAMP_WRITE, LAMP_OFF, "модельный_свет",
     lambda b: f"{'ВКЛ' if b[0] else 'ВЫКЛ'}/{b[2]}%/{b[3]}00K" if b[1] == 0 else b.hex(":")),
    (0x99, 0x99, bytes.fromhex("00 01 00 00 00"), "шторка_HSS",
     lambda b: "1я_шторка_без_HSS" if b == b"\x00\x01\x00\x00\x00" else (
         "HSS" if b == b"\x00\x01\x00\x00\x01" else b.hex(":"))),
    (0x02, 0x83, b"\x00", "burst", lambda b: _off_on(b[0])),
    (0x0B, 0x92, b"\x00\x00\x00", "mask_ALT", lambda b: "ВЫКЛ(0)" if b == b"\x00\x00\x00" else b.hex(":")),
    (0x03, 0x85, b"\x00\x00\x00", "timelapse", lambda b: "ВЫКЛ(0)" if b == b"\x00\x00\x00" else b.hex(":")),
    (0x05, 0x89, b"\x00", "сцены_motif", lambda b: _off_on(b[0])),
    (0x08, 0x90, bytes.fromhex("00 00 04 00 00 00 01"), "меню", _fmt_menu),
)


def write_packet(write_tag, payload):
    body = bytes([0x85, write_tag, len(payload), *payload])
    return body + bytes([sum(body) & 0xFF])


def parse_dump(packets):
    items, fixes = [], []
    for tag, (name, fmt) in EXTRA.items():
        if tag in packets:
            items.append(f"{name}={fmt(packets[tag])}")
    if 0x09 in packets:
        items.append("прошивка=v" + ".".join(str(b) for b in packets[0x09]))
    for tag, _, expected, name, fmt in SETTINGS:
        if tag not in packets:
            continue
        actual = fmt(packets[tag])
        if packets[tag] == expected:
            items.append(f"{name}={actual}")
        else:
            target = fmt(expected)
            items.append(f"{name}={actual}->{target}")
            if packets[tag] != LAMP_ON:  # a session is on, not a drift
                fixes.append(f"{name}: {actual} → {target}")
    items.append(f"(расходится: {', '.join(fixes)})" if fixes else "(все ок)")
    return " ".join(items), fixes

log = logging.getLogger(__name__)
status = "выключено"
session_active = False
stress_test = False  # the stress test switches the charger itself; the watcher only reads the flash
wake = asyncio.Event()
_lamp = False  # the modeling light was last sent on (a session) or off
_poll = None  # the Bluetooth poll in progress; a session start cuts it short
_device = None  # the flash found by the last scan
_client = None  # the open link to the flash
_session_at = 0.0  # when the session started


def next_cycle(cycle, battery):
    """A charge cycle starts at LOW and ends at HIGH; in between it goes on as it was.

    If the flash does not respond over Bluetooth (battery is None), turn charging on.
    """
    if battery is None:
        return True
    if battery <= LOW:
        return True
    if battery >= HIGH:
        return False
    return cycle


def session(active):
    """A photo session started or ended; the watcher reacts at once.

    A start cuts a poll in progress short (it takes 6-7 s, the first shot is 6 s
    away), puts the charger off and the modeling light on, and no new poll starts
    during the session, so no Bluetooth traffic overlaps the flash firing. An end
    (after the last shot) puts the light off, then the polls and the charge cycle
    resume.
    """
    global session_active, _session_at
    if active != session_active:
        session_active = active
        _session_at = time.monotonic()
        if active and _poll:
            _poll.cancel()
        wake.set()


async def _link():
    """The open connection to the flash, opened when there is none.

    A scan takes 1-5 s and a connection 1-3 s on Windows, a command only 0.06 s, so
    the device found once is reused and the link stays open between sessions: the
    session start finds it ready. It is closed while the flash fires.
    """
    global _client, _device
    if _client is None or not _client.is_connected:
        if _device is None:
            _device = await BleakScanner.find_device_by_filter(
                lambda device, adv: BLE_NAME in (adv.local_name or device.name or ""), timeout=10)
            if _device is None:
                raise RuntimeError("вспышка не найдена по Bluetooth")
        _client = BleakClient(_device, timeout=15)
        await _client.connect()
    return _client


async def _unlink():
    global _client
    client, _client = _client, None
    if client:
        with contextlib.suppress(Exception):
            await client.disconnect()


@contextlib.asynccontextmanager
async def _connect():
    global _device
    try:
        yield await _link()
    except Exception:
        _device = None  # gone or at a new address: scan again next time
        await _unlink()
        raise


async def _write(write_tag, payload):
    async with _connect() as client:
        await client.write_gatt_char(WRITE, write_packet(write_tag, payload), response=True)


async def read_flash():
    """Connect, ask for the settings dump and return its packets as {tag: payload}."""
    packets = {}
    battery_seen = asyncio.Event()

    def on_data(_, data):
        if len(data) > 4 and data[0] == 0x85 and data[-1] == sum(data[:-1]) & 0xFF:
            packets[data[1]] = bytes(data[3:-1])
            if data[1] == 0x23:
                battery_seen.set()

    async with _connect() as client:
        await client.start_notify(NOTIFY, on_data)
        try:
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
            for tag, write_tag, expected, *_ in SETTINGS:
                if tag in packets and packets[tag] != expected:
                    await client.write_gatt_char(WRITE, write_packet(write_tag, expected), response=True)
                    await asyncio.sleep(0.1)
        finally:
            with contextlib.suppress(Exception):
                await client.stop_notify(NOTIFY)
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


async def _charger(on):
    """Switch the charger relay; returns the problems, if any."""
    if stress_test:  # the stress test switches it itself
        return []
    try:
        await asyncio.to_thread(set_relay, on)
        return []
    except Exception as exc:
        return [f"реле: {exc or type(exc).__name__}"]


async def watch(config):
    try:
        await _watch(config)
    finally:
        await _unlink()  # the next process must find the flash free


async def _watch(config):
    global status, _lamp, _poll
    if not config.get("flash_enabled", False):
        status = "выключено"
        log.info("Flash: disabled")
        return
    log.info("Flash: battery watch started")
    cycle = False
    while True:
        battery, extra, fixes, problems = None, "", [], []
        if session_active:  # the charger goes off before the light: the first shot is near
            problems += await _charger(False)
        if session_active != _lamp:  # a session started or ended
            _lamp = session_active
            try:
                await asyncio.wait_for(
                    _write(LAMP_WRITE, LAMP_ON if session_active else LAMP_OFF), LAMP_SECONDS)
                log.info("Flash: modeling light %s, %.1f s after the session %s",
                         "on" if session_active else "off", time.monotonic() - _session_at,
                         "start" if session_active else "end")
            except Exception as exc:
                problems.append(f"свет: {exc or type(exc).__name__}")
            if session_active:
                await _unlink()  # no Bluetooth link while the flash fires
        if not session_active:  # no Bluetooth traffic while the flash fires
            _poll = asyncio.create_task(asyncio.wait_for(read_flash(), 45))
            try:
                packets = await _poll
                battery = min(packets[0x23][0], 100)
                extra, fixes = parse_dump(packets)
            except asyncio.CancelledError:
                watcher = asyncio.current_task()
                if watcher is None or watcher.cancelling():
                    raise  # the watcher itself is stopping
                extra = "опрос прерван: началась сессия"
            except Exception as exc:
                problems.append(str(exc) or type(exc).__name__)
            finally:
                _poll = None
        if fixes:
            try:
                await yadisk_control.publish_booth_notice(
                    "flash",
                    "Настройки вспышки восстановлены",
                    "Сбились настройки вспышки, возвращены к эталону:\n" + "\n".join(fixes),
                    notice_id=uuid.uuid4().hex,
                )
            except Exception as exc:
                log.warning("Flash: notice not published: %s", exc)
        charging = False
        if not session_active:
            cycle = next_cycle(cycle, battery)
            charging = cycle
            problems += await _charger(charging)
        state = ("зарядкой щёлкает нагрузочный тест" if stress_test
                 else f"зарядка {'вкл' if charging else 'выкл'}")
        if session_active:
            status = f"сессия, {state}"
        else:
            status = "; ".join([f"{battery}%, {state}" if battery is not None else state, *problems])
        parts = [
            f"battery={battery}%" if battery is not None else "battery=?",
            "charging=stress" if stress_test else f"charging={'on' if charging else 'off'}",
            f"session={'yes' if session_active else 'no'}",
            extra, *problems,
        ]
        (log.warning if (problems or fixes) else log.info)("Flash: " + " ".join(p for p in parts if p))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), POLL_SECONDS)
        wake.clear()
