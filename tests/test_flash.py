import unittest

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


if __name__ == "__main__":
    unittest.main()
