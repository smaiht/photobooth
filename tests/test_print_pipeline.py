import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageChops

from backend.composer import compose
from backend import main
from backend.printer import _prepare_for_page, _printer_name, _set_devmode


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "templates" / "default"


class ComposerTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (TEMPLATE_DIR / "config.json").read_text(encoding="utf-8")
        )

    @staticmethod
    def _make_photos(folder: Path) -> list[Path]:
        colors = ["red", "green", "blue", "yellow"]
        paths = []
        for index, color in enumerate(colors):
            path = folder / f"photo_{index}.jpg"
            Image.new("RGB", (1500, 1000), color).save(path, quality=95)
            paths.append(path)
        return paths

    def test_grid_is_landscape_4x6(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photos = self._make_photos(Path(tmpdir))
            result = compose(TEMPLATE_DIR, "grid", photos, self.config)
            try:
                width, height = self.config["print_size"]
                self.assertEqual(result.size, (width, height))
                self.assertGreater(result.getpixel((width // 4, height // 4))[0], 200)
                self.assertGreater(result.getpixel((width * 3 // 4, height // 4))[1], 80)
                self.assertGreater(result.getpixel((width // 4, height * 3 // 4))[2], 200)
            finally:
                result.close()

    def test_default_backgrounds_are_native_resolution(self):
        with Image.open(TEMPLATE_DIR / "grid_bg.png") as grid:
            self.assertEqual(grid.size, tuple(self.config["print_size"]))
        with Image.open(TEMPLATE_DIR / "strip_bg.png") as strip:
            width, height = self.config["print_size"]
            self.assertEqual(strip.size, (height // 2, width))

    def test_slightly_wrong_sheet_uses_fit_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            photos = self._make_photos(folder)
            background = folder / "slightly_wrong.png"
            Image.new("RGB", (3700, 2490), "white").save(background)
            config = {
                "print_size": self.config["print_size"],
                "templates": {
                    "grid": {
                        "background": background.name,
                        "photos": self.config["templates"]["grid"]["photos"],
                    }
                },
            }
            with self.assertLogs("backend.composer", level="WARNING"):
                result = compose(folder, "grid", photos, config)
            try:
                self.assertEqual(result.size, tuple(config["print_size"]))
            finally:
                result.close()

    def test_strips_are_duplicated_on_landscape_4x6(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photos = self._make_photos(Path(tmpdir))
            result = compose(TEMPLATE_DIR, "strips", photos, self.config)
            try:
                width, height = self.config["print_size"]
                self.assertEqual(result.size, (width, height))
                first_strip = result.crop((0, 0, width, height // 2))
                second_strip = result.crop((0, height // 2, width, height))
                self.assertIsNone(ImageChops.difference(first_strip, second_strip).getbbox())
            finally:
                result.close()


class PrinterPreparationTests(unittest.TestCase):
    def test_rotates_landscape_sheet_for_portrait_driver(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sheet.jpg"
            Image.new("RGB", (3688, 2480), "red").save(source)
            prepared = _prepare_for_page(str(source), (2480, 3688), (600, 600))
            try:
                self.assertEqual(prepared.size, (2480, 3688))
            finally:
                prepared.close()

    def test_asymmetric_dpi_uses_physical_page_orientation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sheet.png"
            image = Image.new("RGB", (1800, 1200), "red")
            image.paste("blue", (900, 0, 1800, 1200))
            image.save(source)
            prepared = _prepare_for_page(str(source), (1844, 2480), (300, 600))
            try:
                self.assertEqual(prepared.size, (1844, 2480))
                self.assertGreater(prepared.getpixel((200, 1240))[0], 200)
                self.assertGreater(prepared.getpixel((1644, 1240))[2], 200)
            finally:
                prepared.close()


class DevModeTests(unittest.TestCase):
    @staticmethod
    def _constants():
        names = [
            "DM_PAPERSIZE", "DM_ORIENTATION", "DM_COPIES", "DM_PRINTQUALITY",
            "DM_YRESOLUTION", "DM_COLOR", "DM_SCALE", "DM_ICMMETHOD",
            "DM_ICMINTENT",
        ]
        values = {name: 1 << index for index, name in enumerate(names)}
        values.update({
            "DMORIENT_PORTRAIT": 1,
            "DMORIENT_LANDSCAPE": 2,
            "DMCOLOR_COLOR": 2,
            "DMICMMETHOD_SYSTEM": 2,
            "DMICM_CONTRAST": 2,
        })
        return SimpleNamespace(**values)

    def test_sets_dnp_high_quality_4x6(self):
        devmode = SimpleNamespace(Fields=0)
        constants = self._constants()
        _set_devmode(devmode, {
            "print_dpi": 600,
            "print_paper_size": 202,
            "print_orientation": "portrait",
            "print_copies": 1,
        }, constants)

        self.assertEqual(devmode.PaperSize, 202)
        self.assertEqual(devmode.Orientation, constants.DMORIENT_PORTRAIT)
        self.assertEqual(devmode.PrintQuality, 600)
        self.assertEqual(devmode.YResolution, 600)
        self.assertEqual(devmode.Copies, 1)
        self.assertEqual(devmode.Scale, 100)

    def test_selects_optional_strips_queue(self):
        config = {"printer_name": "DNP Cards", "printer_name_strips": "DNP Strips"}
        self.assertEqual(_printer_name(config, "grid"), "DNP Cards")
        self.assertEqual(_printer_name(config, "strips"), "DNP Strips")


class SessionGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_ignores_duplicate_session_start(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def fake_session():
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()

        main._session_running = False
        with patch.object(main, "_run_session", fake_session):
            first = asyncio.create_task(main.run_session())
            await entered.wait()
            await main.run_session()
            release.set()
            await first

        self.assertEqual(calls, 1)
        self.assertFalse(main._session_running)


if __name__ == "__main__":
    unittest.main()
