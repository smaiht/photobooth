"""LCUS-1 USB relay (CH340 serial): one command per call, the board keeps its state."""

import ctypes
import os
import re
import sys

import serial
from serial.tools import list_ports

ON = bytes.fromhex("a0 01 01 a2")
OFF = bytes.fromhex("a0 01 00 a1")
RELAY_USB_ID = (0x1A86, 0x7523)  # CH340


def switch(port, on):
    with serial.Serial(port, 9600, write_timeout=1) as board:
        board.write(ON if on else OFF)
        board.flush()


def _usb_keyboards():
    if sys.platform != "win32":
        return []
    try:
        from ctypes import wintypes

        class RawInputDeviceList(ctypes.Structure):
            _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        count = wintypes.UINT(0)
        cb = ctypes.sizeof(RawInputDeviceList)
        if user32.GetRawInputDeviceList(None, ctypes.byref(count), cb) == 0xFFFFFFFF or not count.value:
            return []
        items = (RawInputDeviceList * count.value)()
        loaded = user32.GetRawInputDeviceList(items, ctypes.byref(count), cb)
        if loaded == 0xFFFFFFFF:
            return []
        found = []
        for i in range(loaded):
            if items[i].dwType != 1:  # RIM_TYPEKEYBOARD
                continue
            size = wintypes.UINT(512)
            buf = ctypes.create_unicode_buffer(512)
            if user32.GetRawInputDeviceInfoW(items[i].hDevice, 0x20000007, buf, ctypes.byref(size)) == 0xFFFFFFFF:
                continue
            m = re.search(r"VID_[0-9A-Fa-f]{4}&PID_[0-9A-Fa-f]{4}", buf.value)
            if m and m.group(0).upper() not in found:
                found.append(m.group(0).upper())
        return found
    except Exception:
        return []


def usb_status_lines():
    ports = list_ports.comports()
    devices = {p.device for p in ports}
    ch340 = [p.device for p in ports if (p.vid, p.pid) == RELAY_USB_ID]
    cam_port = os.environ.get("CAMERA_RELAY_PORT", "").strip()
    flash_port = os.environ.get("FLASH_RELAY_PORT", "").strip()

    def fmt_port(port):
        if not port:
            return "не задан"
        return f"🟢 {port}" if port in devices else f"🔴 {port} (нет)"

    ch340_str = ", ".join(ch340) if ch340 else "нет"
    lines = [
        f"• Реле USB: камера {fmt_port(cam_port)} · вспышка {fmt_port(flash_port)} (CH340: {ch340_str})",
    ]
    if sys.platform == "win32":
        kbds = _usb_keyboards()
        lines.append(
            f"• Поинтер 2.4G: 🟢 подключён ({', '.join(kbds)})"
            if kbds else "• Поинтер 2.4G: 🔴 не найден"
        )
    return lines
