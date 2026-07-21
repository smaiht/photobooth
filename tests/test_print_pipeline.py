import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat

from backend.composer import compose, generate_template_previews
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


class PreviewComposerTests(unittest.TestCase):
    @staticmethod
    def _make_pack(folder: Path) -> tuple[dict, list[Path]]:
        photos = []
        for index, color in enumerate(("red", "green", "blue", "yellow")):
            path = folder / f"photo_{index}.jpg"
            Image.new("RGB", (900, 600), color).save(path, quality=95)
            photos.append(path)

        Image.new("RGB", (600, 400), "white").save(folder / "grid.png")
        Image.new("RGB", (600, 400), "lightgray").save(folder / "grid_alt.png")
        Image.new("RGB", (200, 600), "white").save(folder / "strip.png")
        Image.new("RGB", (200, 600), "lightgray").save(folder / "strip_alt.png")
        grid_slots = [
            {"x": 10, "y": 10, "w": 280, "h": 180},
            {"x": 310, "y": 10, "w": 280, "h": 180},
            {"x": 10, "y": 210, "w": 280, "h": 180},
            {"x": 310, "y": 210, "w": 280, "h": 180},
        ]
        strip_slots = [
            {"x": 10, "y": 10 + index * 145, "w": 180, "h": 130}
            for index in range(4)
        ]
        config = {
            "print_size": [600, 400],
            "templates": {
                "strips": {
                    "label": "2 полоски",
                    "background": "strip.png",
                    "duplicate": True,
                    "photos": strip_slots,
                },
                "grid": {
                    "label": "4 фото",
                    "background": "grid.png",
                    "photos": grid_slots,
                },
                "strips_alt": {
                    "background": "strip_alt.png",
                    "duplicate": True,
                    "photos": strip_slots,
                },
                "grid_alt": {
                    "background": "grid_alt.png",
                    "photos": grid_slots,
                },
            },
        }
        return config, photos

    def test_generates_all_configured_options_at_screen_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config, photos = self._make_pack(folder)
            output_dir = folder / "session" / "previews"

            results = generate_template_previews(
                folder, photos, config, output_dir, preview_width=300)

            self.assertEqual(list(results), list(config["templates"]))
            self.assertEqual(len(list(output_dir.glob("*.jpg"))), 4)
            self.assertFalse(any(output_dir.glob("print_*.jpg")))
            for result_path in results.values():
                with Image.open(result_path) as preview:
                    self.assertEqual(preview.size, (300, 200))
            with Image.open(folder / "grid_preview.jpg") as grid_cache:
                self.assertEqual(grid_cache.size, (300, 200))
            with Image.open(folder / "strip_preview.jpg") as strip_cache:
                self.assertEqual(strip_cache.size, (100, 300))

            with Image.open(results["strips"]) as strips:
                top = strips.crop((0, 0, 300, 100))
                bottom = strips.crop((0, 100, 300, 200))
                difference = ImageChops.difference(top, bottom)
                self.assertLess(max(ImageStat.Stat(difference).mean), 1)

    def test_background_cache_is_reused_and_rebuilt_when_stale_or_wrong(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config, photos = self._make_pack(folder)
            config["templates"] = {"grid": config["templates"]["grid"]}
            output_dir = folder / "previews"
            source_path = folder / "grid.png"
            cache_path = folder / "grid_preview.jpg"

            generate_template_previews(
                folder, photos, config, output_dir, preview_width=300)
            first_mtime = cache_path.stat().st_mtime_ns
            generate_template_previews(
                folder, photos, config, output_dir, preview_width=300)
            self.assertEqual(cache_path.stat().st_mtime_ns, first_mtime)

            Image.new("RGB", (600, 400), "blue").save(source_path)
            source_stat = source_path.stat()
            os.utime(source_path, ns=(
                source_stat.st_atime_ns,
                max(source_stat.st_mtime_ns, first_mtime + 1),
            ))
            generate_template_previews(
                folder, photos, config, output_dir, preview_width=300)
            with Image.open(cache_path) as rebuilt:
                self.assertEqual(rebuilt.size, (300, 200))
                self.assertGreater(rebuilt.getpixel((2, 2))[2], 200)

            Image.new("RGB", (1, 1), "black").save(cache_path)
            cache_stat = cache_path.stat()
            os.utime(cache_path, ns=(
                cache_stat.st_atime_ns,
                source_path.stat().st_mtime_ns + 1_000_000_000,
            ))
            generate_template_previews(
                folder, photos, config, output_dir, preview_width=300)
            with Image.open(cache_path) as repaired:
                self.assertEqual(repaired.size, (300, 200))

    def test_reduced_photos_are_closed_after_preview_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config, photos = self._make_pack(folder)
            config["templates"] = {"grid": config["templates"]["grid"]}
            reduced = [Image.new("RGB", (300, 200), "red") for _ in range(4)]

            with patch("backend.composer._load_reduced_photos", return_value=reduced):
                generate_template_previews(
                    folder, photos, config, folder / "previews", preview_width=300)

            for image in reduced:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))


class PreviewLifecycleTests(unittest.TestCase):
    def test_startup_cleanup_removes_only_session_preview_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photos_dir = Path(tmpdir)
            preview_dir = photos_dir / "session-a" / "previews"
            preview_dir.mkdir(parents=True)
            (preview_dir / "preview.jpg").write_bytes(b"preview")
            keep_dir = photos_dir / "session-a" / "previews_backup"
            keep_dir.mkdir()
            keep_file = keep_dir / "keep.jpg"
            keep_file.write_bytes(b"keep")

            with patch.object(main, "PHOTOS_DIR", photos_dir):
                main._cleanup_stale_preview_dirs()

            self.assertFalse(preview_dir.exists())
            self.assertTrue(keep_file.exists())

    def test_cleanup_refuses_any_other_directory_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            keep_dir = Path(tmpdir) / "session"
            keep_dir.mkdir()
            with self.assertRaises(ValueError):
                main._remove_preview_dir(keep_dir)
            self.assertTrue(keep_dir.exists())

    def test_template_state_recovers_dynamic_options(self):
        options = [{
            "name": "new_template",
            "label": "Новый шаблон",
            "preview_url": "/photos/session/previews/preview_01.jpg",
        }]
        with patch.object(main, "TEMPLATE_OPTIONS", options), \
             patch.object(main, "SESSION_ID", "session"), \
             patch.object(main, "SESSION_LINK", ""):
            message = main._state_message("template_select")

        self.assertEqual(message["templates"], options)
        self.assertEqual(message["timeout"], int(main.CONFIG["template_select_timeout"]))


class FrontendPreviewTests(unittest.TestCase):
    def test_template_choices_are_dynamic_and_processing_has_own_screen(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="screen-processing"', html)
        self.assertIn('id="template-options"', html)
        self.assertNotIn('data-template="strips"', html)
        self.assertNotIn('data-template="grid"', html)
        self.assertIn('document.createElement("button")', script)
        self.assertIn('processing: "processing"', script)


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
