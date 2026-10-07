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
        for name in ("FLASH_RELAY_PORT", "CAMERA_RELAY_PORT"):
            os.environ.pop(name, None)
        switch = patch.object(flash.relay, "switch")
        self.switch = switch.start()
        self.addCleanup(switch.stop)

    def boards(self, *devices):
        found = [types.SimpleNamespace(device=device, vid=flash.RELAY_USB_ID[0],
                                       pid=flash.RELAY_USB_ID[1]) for device in devices]
        comports = patch.object(flash.list_ports, "comports", return_value=found)
        comports.start()
        self.addCleanup(comports.stop)

    def test_the_only_board_is_used(self):
        self.boards("board-a")
        flash.set_relay(True)
        self.switch.assert_called_once_with("board-a", True)

    def test_several_boards_are_refused_and_listed(self):
        self.boards("board-a", "board-b")
        with self.assertRaises(RuntimeError) as caught:
            flash.set_relay(True)
        self.assertIn("board-a", str(caught.exception))
        self.assertIn("board-b", str(caught.exception))
        self.switch.assert_not_called()

    def test_port_from_env_wins_over_several_boards(self):
        self.boards("board-a", "board-b")
        os.environ["FLASH_RELAY_PORT"] = "board-b"
        flash.set_relay(True)
        self.switch.assert_called_once_with("board-b", True)

    def test_the_camera_board_is_never_taken_for_the_charger(self):
        os.environ["CAMERA_RELAY_PORT"] = "board-a"
        self.boards("board-a", "board-b")
        flash.set_relay(True)
        self.switch.assert_called_once_with("board-b", True)

        self.switch.reset_mock()
        self.boards("board-a")
        with self.assertRaises(RuntimeError):
            flash.set_relay(True)
        self.switch.assert_not_called()

    def test_charger_and_camera_on_one_board_are_refused(self):
        os.environ["FLASH_RELAY_PORT"] = "board-a"
        os.environ["CAMERA_RELAY_PORT"] = "board-a"
        with self.assertRaises(RuntimeError):
            flash.set_relay(True)
        self.switch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
