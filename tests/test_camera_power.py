import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from backend import camera_power, main

SEARCHES = camera_power.SEARCHES_BEFORE_CUT


class CameraPowerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for patcher in (
            patch.dict(os.environ, {"CAMERA_RELAY_PORT": "camera-board"}),
            patch.object(camera_power, "CUT_SECONDS", 0.05),
            patch.object(camera_power, "_lost", asyncio.Event()),
            patch.object(camera_power, "_failed", 0),
            patch.object(camera_power, "_told", False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        switch = patch.object(camera_power.relay, "switch")
        self.switch = switch.start()
        self.addCleanup(switch.stop)
        publish = patch.object(
            camera_power.yadisk_control, "publish_booth_notice", AsyncMock())
        self.publish = publish.start()
        self.addCleanup(publish.stop)
        self.watcher = None
        self.addAsyncCleanup(self.stop_watcher)

    def start_watcher(self):
        self.watcher = asyncio.create_task(camera_power.watch())

    async def stop_watcher(self):
        if self.watcher:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)

    async def until(self, condition):
        async with asyncio.timeout(2):
            while not condition():
                await asyncio.sleep(0.005)

    def states(self):
        return [call.args[1] for call in self.switch.call_args_list]

    def searches_fail(self, count):
        for _ in range(count):
            camera_power.search_failed("No camera found")

    async def test_failed_searches_cut_the_power_then_give_it_back(self):
        self.start_watcher()
        self.searches_fail(SEARCHES)
        await self.until(lambda: len(self.states()) == 3)

        # Powered at start, cut, powered again.
        self.assertEqual(self.states(), [False, True, False])
        self.assertEqual(self.switch.call_args.args[0], "camera-board")

    async def test_fewer_failed_searches_leave_the_camera_alone(self):
        self.start_watcher()
        self.searches_fail(SEARCHES - 1)
        await asyncio.sleep(0.05)

        self.assertEqual(self.states(), [False])

    async def test_a_found_camera_starts_the_count_again(self):
        self.start_watcher()
        self.searches_fail(SEARCHES - 1)
        camera_power.camera_found()
        self.searches_fail(SEARCHES - 1)
        await asyncio.sleep(0.05)

        self.assertEqual(self.states(), [False])

    async def test_a_camera_that_stays_missing_gets_the_next_cut_after_the_same_searches(self):
        with patch.object(camera_power, "CUT_SECONDS", 0.2):
            self.start_watcher()
            self.searches_fail(SEARCHES)
            await self.until(lambda: self.states() == [False, True])
            self.searches_fail(SEARCHES + 2)  # while the power is cut: not counted
            await self.until(lambda: len(self.states()) == 3)
            await asyncio.sleep(0.05)

            self.searches_fail(SEARCHES - 1)
            await asyncio.sleep(0.05)
            self.assertEqual(len(self.states()), 3)
            self.searches_fail(1)
            await self.until(lambda: len(self.states()) == 5)

        self.assertEqual(self.states(), [False, True, False, True, False])

    async def test_the_admin_hears_once_per_outage(self):
        self.start_watcher()
        for cuts in (1, 2):
            self.searches_fail(SEARCHES)
            await self.until(lambda: len(self.states()) == 1 + 2 * cuts)
            await asyncio.sleep(0.05)
        self.publish.assert_awaited_once()
        self.assertIn("No camera found", self.publish.await_args.args[2])

        camera_power.camera_found()
        self.searches_fail(SEARCHES)
        await self.until(lambda: len(self.states()) == 7)
        await asyncio.sleep(0.05)
        self.assertEqual(self.publish.await_count, 2)

    async def test_power_comes_back_when_the_watcher_stops_mid_cycle(self):
        with patch.object(camera_power, "CUT_SECONDS", 30):
            self.start_watcher()
            self.searches_fail(SEARCHES)
            await self.until(lambda: self.states() == [False, True])
            await self.stop_watcher()

        self.assertEqual(self.states(), [False, True, False])

    async def test_failed_cut_is_reported_and_the_watcher_survives(self):
        def switch(_port, cut):
            if cut:
                raise OSError("no board")

        self.switch.side_effect = switch
        self.start_watcher()
        self.searches_fail(SEARCHES)
        await self.until(lambda: self.publish.await_count == 1)

        self.assertIn("no board", self.publish.await_args.args[2])
        self.assertFalse(self.watcher.done())
        # Even a cut that failed is followed by a power-on command.
        self.assertEqual(self.states()[-1], False)

    async def test_without_a_relay_port_the_camera_is_left_alone(self):
        os.environ.pop("CAMERA_RELAY_PORT")
        self.searches_fail(SEARCHES)

        await camera_power.watch()

        self.switch.assert_not_called()
        self.publish.assert_not_awaited()


class CameraSignalWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_failed_search_reaches_the_power_watcher(self):
        with patch.object(main, "_event_loop", asyncio.get_running_loop()), \
             patch.object(camera_power, "search_failed") as failed:
            main.on_camera_search_failed("search 1")
            main.on_camera_search_failed("search 2")
            await asyncio.sleep(0.01)

        self.assertEqual([call.args for call in failed.call_args_list],
                         [("search 1",), ("search 2",)])

    async def test_a_connected_camera_tells_the_power_watcher(self):
        with patch.object(main, "_event_loop", asyncio.get_running_loop()), \
             patch.object(main, "STATE", "camera_searching"), \
             patch.object(main, "_session_running", False), \
             patch.object(main, "CLIENTS", []), \
             patch.object(main, "_report_status_to_admin", AsyncMock()), \
             patch.object(camera_power, "camera_found") as found:
            main.on_camera_connected()
            await asyncio.sleep(0.01)

        found.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
