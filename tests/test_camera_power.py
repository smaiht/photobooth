import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from backend import camera_power, main


class CameraPowerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for patcher in (
            patch.dict(os.environ, {"CAMERA_RELAY_PORT": "camera-board"}),
            patch.object(camera_power, "CUT_SECONDS", 0.05),
            patch.object(camera_power, "_lost", asyncio.Event()),
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

    async def stop_watcher(self):
        if self.watcher:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)

    async def until(self, condition):
        async with asyncio.timeout(2):
            while not condition():
                await asyncio.sleep(0.005)

    def ports_and_states(self):
        return [call.args for call in self.switch.call_args_list]

    async def test_lost_camera_loses_power_then_gets_it_back_and_the_admin_hears_once(self):
        self.watcher = asyncio.create_task(camera_power.watch())
        camera_power.camera_lost("USB lost")
        await self.until(lambda: self.switch.call_count == 3)

        # Powered at start, cut for the cycle, powered again.
        self.assertEqual(self.ports_and_states(), [
            ("camera-board", False), ("camera-board", True), ("camera-board", False)])
        await asyncio.sleep(0.05)  # no second notice follows the power coming back
        self.publish.assert_awaited_once()
        self.assertIn("USB lost", self.publish.await_args.args[2])

    async def test_power_comes_back_when_the_watcher_stops_mid_cycle(self):
        with patch.object(camera_power, "CUT_SECONDS", 30):
            self.watcher = asyncio.create_task(camera_power.watch())
            camera_power.camera_lost("USB lost")
            await self.until(lambda: ("camera-board", True) in self.ports_and_states())
            await self.stop_watcher()

        self.assertEqual(self.ports_and_states()[-1], ("camera-board", False))

    async def test_failed_cut_is_reported_and_the_watcher_survives(self):
        def switch(_port, cut):
            if cut:
                raise OSError("no board")

        self.switch.side_effect = switch
        self.watcher = asyncio.create_task(camera_power.watch())
        camera_power.camera_lost("USB lost")
        await self.until(lambda: self.publish.await_count == 1)

        self.assertIn("no board", self.publish.await_args.args[2])
        self.assertFalse(self.watcher.done())
        # Even a cut that failed is followed by a power-on command.
        self.assertEqual(self.ports_and_states()[-1], ("camera-board", False))

    async def test_without_a_relay_port_the_camera_is_left_alone(self):
        os.environ.pop("CAMERA_RELAY_PORT")
        camera_power.camera_lost("USB lost")

        await camera_power.watch()

        self.switch.assert_not_called()
        self.publish.assert_not_awaited()


class CameraLostWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_lost_camera_reaches_the_power_watcher(self):
        with patch.object(main, "_event_loop", asyncio.get_running_loop()), \
             patch.object(main, "STATE", "idle"), \
             patch.object(main, "_session_running", False), \
             patch.object(main, "CLIENTS", []), \
             patch.object(main, "_camera_disconnected_event", asyncio.Event()), \
             patch.object(camera_power, "camera_lost") as lost:
            main.on_camera_error("USB lost")
            await asyncio.sleep(0.05)

        lost.assert_called_once_with("USB lost")


if __name__ == "__main__":
    unittest.main()
