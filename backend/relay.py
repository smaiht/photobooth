"""LCUS-1 USB relay (CH340 serial): one command per call, the board keeps its state."""

import serial

ON = bytes.fromhex("a0 01 01 a2")
OFF = bytes.fromhex("a0 01 00 a1")


def switch(port, on):
    with serial.Serial(port, 9600, write_timeout=1) as board:
        board.write(ON if on else OFF)
        board.flush()
