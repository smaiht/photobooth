"""Ask a NEEWER Q4 Pro flash for its battery and state over BLE.

The protocol comes from the NEEWER Studio 5.7.6 APK (FlashCommandUtil).
Turn Bluetooth on in the flash menu, close the NEEWER app on the phone, then:

    pip install bleak
    python diagnostics/flash_probe.py            # find a device named *Q4*, ask it, print replies
    python diagnostics/flash_probe.py scan       # list BLE devices around (to learn the flash name)
    python diagnostics/flash_probe.py NAME|ADDR  # pick the flash by part of its name or by address
"""

import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

SERVICE = "69400001-b5a3-f393-e0a9-e50e24dcca99"
WRITE = "69400002-b5a3-f393-e0a9-e50e24dcca99"
NOTIFY = "69400003-b5a3-f393-e0a9-e50e24dcca99"

# Request tags: battery, standby, error, capacitor, firmware, full config dump.
QUERIES = [0xA7, 0xA5, 0xA8, 0xA9, 0x93, 0x94]
# Reply tag (second byte) -> meaning of the payload bytes.
REPLIES = {
    0x23: "battery %",
    0x22: "awake=1 / standby=0",
    0x24: "error code",
    0x25: "capacitor",
    0x26: "overheat",
    0x09: "firmware",
}


def packet(tag):
    body = bytes([0x85, tag, 0x01, 0x00])
    return body + bytes([sum(body) & 0xFF])


def show(_, data):
    ok = len(data) > 1 and data[-1] == sum(data[:-1]) & 0xFF
    name = REPLIES.get(data[1], "") if len(data) > 1 else ""
    print(f"  <- {data.hex(' ')}  {name} {list(data[3:-1])}{'' if ok else '  (checksum?)'}")


async def scan():
    found = await BleakScanner.discover(timeout=8, return_adv=True)
    for device, adv in sorted(found.values(), key=lambda pair: -pair[1].rssi):
        mark = "  <- NEEWER service" if SERVICE in adv.service_uuids else ""
        print(f"{adv.rssi:4} dB  {device.address}  {adv.local_name or device.name or '-'}{mark}")


async def probe(target):
    def match(device, adv):
        name = adv.local_name or device.name or ""
        return target.lower() in name.lower() or target.lower() == device.address.lower()

    started = time.monotonic()
    device = await BleakScanner.find_device_by_filter(match, timeout=15)
    if device is None:
        sys.exit(f"Не нашёл «{target}». Включи Bluetooth в меню вспышки, закрой приложение "
                 "NEEWER на телефоне; `scan` покажет имена устройств рядом.")
    print(f"found {device.name} {device.address} after {time.monotonic() - started:.1f}s")
    async with BleakClient(device, timeout=15) as client:
        print(f"connected after {time.monotonic() - started:.1f}s")
        properties = client.services.get_characteristic(WRITE).properties
        print("write characteristic:", properties)
        await client.start_notify(NOTIFY, show)
        for tag in QUERIES:
            print(f"-> {packet(tag).hex(' ')}")
            await client.write_gatt_char(WRITE, packet(tag), response="write" in properties)
            await asyncio.sleep(0.7)
        await asyncio.sleep(2)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "Q4"
    asyncio.run(scan() if arg == "scan" else probe(arg))
