import os
import types
import unittest
from unittest.mock import patch

from backend import flash


class ChargeCycleTests(unittest.TestCase):
    def test_cycle_starts_at_low_and_ends_at_high(self):
        self.assertTrue(flash.next_cycle(False, flash.LOW))
        self.assertFalse(flash.next_cycle(True, flash.HIGH))

    def test_cycle_keeps_going_between_the_thresholds(self):
        middle = (flash.LOW + flash.HIGH) // 2
        self.assertTrue(flash.next_cycle(True, middle))
        self.assertFalse(flash.next_cycle(False, middle))

    def test_unknown_battery_changes_nothing(self):
        self.assertTrue(flash.next_cycle(True, None))
        self.assertFalse(flash.next_cycle(False, None))


class RelayPortTests(unittest.TestCase):
    def setUp(self):
        environ = patch.dict(os.environ)
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop("FLASH_RELAY_PORT", None)
        serial_class = patch.object(flash.serial, "Serial")
        self.serial_class = serial_class.start()
        self.addCleanup(serial_class.stop)

    def boards(self, *devices):
        found = [types.SimpleNamespace(device=device, vid=flash.RELAY_USB_ID[0],
                                       pid=flash.RELAY_USB_ID[1]) for device in devices]
        comports = patch.object(flash.list_ports, "comports", return_value=found)
        comports.start()
        self.addCleanup(comports.stop)

    def test_the_only_board_is_used(self):
        self.boards("board-a")
        flash.set_relay(True)
        self.assertEqual(self.serial_class.call_args.args[0], "board-a")

    def test_several_boards_are_refused_and_listed(self):
        self.boards("board-a", "board-b")
        with self.assertRaises(RuntimeError) as caught:
            flash.set_relay(True)
        self.assertIn("board-a", str(caught.exception))
        self.assertIn("board-b", str(caught.exception))
        self.serial_class.assert_not_called()

    def test_port_from_env_wins_over_several_boards(self):
        self.boards("board-a", "board-b")
        os.environ["FLASH_RELAY_PORT"] = "board-b"
        flash.set_relay(True)
        self.assertEqual(self.serial_class.call_args.args[0], "board-b")


if __name__ == "__main__":
    unittest.main()
