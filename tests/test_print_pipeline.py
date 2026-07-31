import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image, ImageChops, ImageStat

from backend.composer import compose, generate_template_previews, template_photo_count
from backend import main
from backend.printer import _print_driver, _printer_name, prepare_custom_print


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
            self.assertEqual(strip.size, tuple(self.config["print_size"]))

    def test_canon_6000x4000_ratio_matches_every_photo_slot(self):
        for template in self.config["templates"].values():
            size = template["photo_size_px"]
            width, height = size["width"], size["height"]
            for slot in template["print_layout"]["photos"]:
                if slot.get("rotate") == "ccw":
                    self.assertEqual(width * 6000, height * 4000)
                else:
                    self.assertEqual(width * 4000, height * 6000)

    def test_mismatched_photo_is_fitted_whole_without_slot_crop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            Image.new("RGB", (100, 100), "blue").save(folder / "background.png")
            source = folder / "wide.png"
            Image.new("RGB", (200, 100), "red").save(source)
            config = {
                "print_size": [100, 100],
                "templates": {
                    "grid": {
                        "photo_size_px": {"width": 100, "height": 100},
                        "print_layout": {
                            "background": "background.png",
                            "photos": [{
                                "photo_index": 0,
                                "x": 0,
                                "y": 0,
                                "rotate": "none",
                            }],
                        },
                        "preview_rotation": "none",
                        "preview_split": "none",
                    },
                },
            }

            result = compose(folder, "grid", [source], config)
            try:
                self.assertGreater(result.getpixel((50, 0))[2], 200)
                self.assertGreater(result.getpixel((50, 50))[0], 200)
                self.assertGreater(result.getpixel((50, 99))[2], 200)
            finally:
                result.close()

    def test_optional_foreground_is_composited_after_photos(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            Image.new("RGB", (100, 100), "blue").save(folder / "background.png")
            Image.new("RGB", (100, 100), "red").save(folder / "photo.png")
            foreground = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            try:
                foreground.paste((0, 255, 0, 255), (40, 40, 60, 60))
                foreground.save(folder / "foreground.png")
            finally:
                foreground.close()
            config = {
                "print_size": [100, 100],
                "templates": {
                    "grid": {
                        "photo_size_px": {"width": 100, "height": 100},
                        "print_layout": {
                            "background": "background.png",
                            "foreground": "foreground.png",
                            "photos": [{
                                "photo_index": 0,
                                "x": 0,
                                "y": 0,
                                "rotate": "none",
                            }],
                        },
                        "preview_rotation": "none",
                        "preview_split": "none",
                    },
                },
            }

            result = compose(folder, "grid", [folder / "photo.png"], config)
            try:
                self.assertGreater(result.getpixel((10, 10))[0], 200)
                self.assertGreater(result.getpixel((50, 50))[1], 200)
                self.assertLess(result.getpixel((50, 50))[0], 50)
            finally:
                result.close()

    def test_foreground_requires_native_size_and_alpha(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            Image.new("RGB", (100, 100), "white").save(folder / "background.png")
            Image.new("RGB", (100, 100), "red").save(folder / "photo.png")
            config = {
                "print_size": [100, 100],
                "templates": {
                    "grid": {
                        "photo_size_px": {"width": 100, "height": 100},
                        "print_layout": {
                            "background": "background.png",
                            "foreground": "foreground.png",
                            "photos": [{
                                "photo_index": 0,
                                "x": 0,
                                "y": 0,
                                "rotate": "none",
                            }],
                        },
                        "preview_rotation": "none",
                        "preview_split": "none",
                    },
                },
            }

            Image.new("RGBA", (99, 100), (0, 0, 0, 0)).save(
                folder / "foreground.png")
            with self.assertRaisesRegex(ValueError, "foreground must be"):
                compose(folder, "grid", [folder / "photo.png"], config)

            Image.new("RGB", (100, 100), "white").save(
                folder / "foreground.png")
            with self.assertRaisesRegex(ValueError, "alpha channel"):
                compose(folder, "grid", [folder / "photo.png"], config)

    def test_template_may_use_only_first_available_session_photo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            Image.new("RGB", (120, 80), "white").save(folder / "background.png")
            first = folder / "first.png"
            second = folder / "second.png"
            Image.new("RGB", (100, 60), "red").save(first)
            Image.new("RGB", (100, 60), "green").save(second)
            template = {
                "photo_size_px": {"width": 100, "height": 60},
                "print_layout": {
                    "background": "background.png",
                    "photos": [{
                        "photo_index": 0,
                        "x": 10,
                        "y": 10,
                        "rotate": "none",
                    }],
                },
                "preview_rotation": "none",
                "preview_split": "none",
            }
            config = {
                "print_size": [120, 80],
                "templates": {"single": template},
            }

            self.assertEqual(template_photo_count(template, "single"), 1)
            result = compose(folder, "single", [first, second], config)
            try:
                pixel = result.getpixel((60, 40))
                self.assertGreater(pixel[0], 200)
                self.assertLess(pixel[1], 80)
            finally:
                result.close()

    def test_single_template_spans_the_four_grid_slots(self):
        template_dir = ROOT / "templates" / "kvas01aug26"
        config = json.loads(
            (template_dir / "config.json").read_text(encoding="utf-8")
        )
        grid = config["templates"]["grid"]
        single = config["templates"]["single"]
        grid_width = grid["photo_size_px"]["width"]
        grid_height = grid["photo_size_px"]["height"]
        grid_slots = grid["print_layout"]["photos"]
        left = min(slot["x"] for slot in grid_slots)
        top = min(slot["y"] for slot in grid_slots)
        right = max(slot["x"] + grid_width for slot in grid_slots)
        bottom = max(slot["y"] + grid_height for slot in grid_slots)

        self.assertEqual(
            single["photo_size_px"],
            {"width": right - left, "height": bottom - top},
        )
        self.assertEqual(single["print_layout"]["photos"], [{
            "photo_index": 0,
            "x": left,
            "y": top,
            "rotate": "none",
        }])

    def test_wrong_background_size_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            photos = self._make_photos(folder)
            background = folder / "slightly_wrong.png"
            Image.new("RGB", (3700, 2490), "white").save(background)
            config = {
                "print_size": self.config["print_size"],
                "templates": {
                    "grid": {
                        "photo_size_px": self.config["templates"]["grid"][
                            "photo_size_px"
                        ],
                        "print_layout": {
                            "background": background.name,
                            "photos": self.config["templates"]["grid"][
                                "print_layout"
                            ]["photos"],
                        },
                        "preview_rotation": "none",
                        "preview_split": "none",
                    }
                },
            }
            with self.assertRaisesRegex(ValueError, "background must be"):
                compose(folder, "grid", photos, config)

    def test_strips_are_duplicated_inside_measured_print_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photos = self._make_photos(Path(tmpdir))
            result = compose(TEMPLATE_DIR, "strips", photos, self.config)
            try:
                width, height = self.config["print_size"]
                self.assertEqual(result.size, (width, height))
                trim = self.config["print_trim"]
                visible = result.crop((
                    trim["left"],
                    trim["top"],
                    width - trim["right"],
                    height - trim["bottom"],
                ))
                try:
                    # The measured area has an odd height, so omit its unmatched
                    # center row and compare the two physical 2-inch halves.
                    half = visible.height // 2
                    first_strip = visible.crop((0, 0, visible.width, half))
                    second_strip = visible.crop((
                        0, visible.height - half, visible.width, visible.height))
                    try:
                        difference = ImageChops.difference(
                            first_strip, second_strip)
                        try:
                            self.assertLess(max(ImageStat.Stat(difference).mean), 0.2)
                        finally:
                            difference.close()
                    finally:
                        first_strip.close()
                        second_strip.close()
                finally:
                    visible.close()
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
        Image.new("RGB", (600, 400), "white").save(folder / "strip.png")
        Image.new("RGB", (600, 400), "lightgray").save(folder / "strip_alt.png")
        grid_slots = [
            {"photo_index": 0, "x": 10, "y": 10, "rotate": "none"},
            {"photo_index": 1, "x": 310, "y": 10, "rotate": "none"},
            {"photo_index": 2, "x": 10, "y": 210, "rotate": "none"},
            {"photo_index": 3, "x": 310, "y": 210, "rotate": "none"},
        ]
        strip_slots = [
            {
                "photo_index": index,
                "x": 10 + index * 100,
                "y": row_y,
                "rotate": "ccw",
            }
            for row_y in (10, 255)
            for index in range(4)
        ]
        config = {
            "print_size": [600, 400],
            "templates": {
                "strips": {
                    "label": "2 полоски",
                    "photo_size_px": {"width": 90, "height": 135},
                    "print_layout": {
                        "background": "strip.png",
                        "photos": strip_slots,
                    },
                    "preview_rotation": "cw",
                    "preview_split": "horizontal",
                },
                "grid": {
                    "label": "4 фото",
                    "photo_size_px": {"width": 280, "height": 180},
                    "print_layout": {
                        "background": "grid.png",
                        "photos": grid_slots,
                    },
                    "preview_rotation": "none",
                    "preview_split": "none",
                },
                "strips_alt": {
                    "photo_size_px": {"width": 90, "height": 135},
                    "print_layout": {
                        "background": "strip_alt.png",
                        "photos": strip_slots,
                    },
                    "preview_rotation": "cw",
                    "preview_split": "horizontal",
                },
                "grid_alt": {
                    "photo_size_px": {"width": 280, "height": 180},
                    "print_layout": {
                        "background": "grid_alt.png",
                        "photos": grid_slots,
                    },
                    "preview_rotation": "none",
                    "preview_split": "none",
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
                self.assertEqual(strip_cache.size, (300, 200))

            with Image.open(results["strips"]) as strips:
                self.assertLess(max(strips.getpixel((10, 10))), 80)
                self.assertGreater(strips.getpixel((120, 20))[0], 200)
                self.assertGreater(strips.getpixel((180, 30))[0], 200)
                self.assertLess(max(strips.getpixel((150, 100))), 80)
                self.assertGreater(strips.getpixel((120, 50))[1], 80)
                self.assertGreater(strips.getpixel((120, 85))[2], 200)

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

    def test_foreground_preview_cache_preserves_alpha_and_is_composited_last(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config, photos = self._make_pack(folder)
            config["templates"] = {"grid": config["templates"]["grid"]}
            config["templates"]["grid"]["print_layout"][
                "foreground"
            ] = "grid_after.png"
            source_path = folder / "grid_after.png"
            cache_path = folder / "grid_after_preview.png"
            output_dir = folder / "previews"

            foreground = Image.new("RGBA", (600, 400), (0, 0, 0, 0))
            try:
                foreground.paste((0, 255, 0, 255), (60, 60, 180, 160))
                foreground.save(source_path)
            finally:
                foreground.close()

            # A fresh-looking RGB cache is still invalid because alpha was lost.
            Image.new("RGB", (300, 200), "black").save(cache_path)
            cache_stat = cache_path.stat()
            os.utime(cache_path, ns=(
                cache_stat.st_atime_ns,
                source_path.stat().st_mtime_ns + 1_000_000_000,
            ))

            results = generate_template_previews(
                folder, photos, config, output_dir, preview_width=300)
            with Image.open(cache_path) as cached:
                self.assertEqual(cached.mode, "RGBA")
                self.assertEqual(cached.size, (300, 200))
                self.assertEqual(cached.getpixel((0, 0))[3], 0)
                self.assertGreater(cached.getpixel((50, 50))[3], 250)
            with Image.open(results["grid"]) as preview:
                green = preview.getpixel((50, 50))
                red = preview.getpixel((125, 50))
                self.assertGreater(green[1], 180)
                self.assertLess(green[0], 80)
                self.assertGreater(red[0], 180)
                self.assertLess(red[1], 80)

            first_mtime = cache_path.stat().st_mtime_ns
            generate_template_previews(
                folder, photos, config, output_dir, preview_width=300)
            self.assertEqual(cache_path.stat().st_mtime_ns, first_mtime)

            foreground = Image.new("RGBA", (600, 400), (0, 0, 0, 0))
            try:
                foreground.paste((0, 0, 255, 255), (60, 60, 180, 160))
                foreground.save(source_path)
            finally:
                foreground.close()
            source_stat = source_path.stat()
            os.utime(source_path, ns=(
                source_stat.st_atime_ns,
                max(source_stat.st_mtime_ns, first_mtime + 1),
            ))

            results = generate_template_previews(
                folder, photos, config, output_dir, preview_width=300)
            self.assertGreater(cache_path.stat().st_mtime_ns, first_mtime)
            with Image.open(results["grid"]) as preview:
                blue = preview.getpixel((50, 50))
                self.assertGreater(blue[2], 180)
                self.assertLess(blue[1], 80)

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


class PrinterQueueTests(unittest.TestCase):
    def test_selects_optional_strips_queue(self):
        config = {"printer_name": "DNP Cards", "printer_name_strips": "DNP Strips"}
        self.assertEqual(_printer_name(config, "grid"), "DNP Cards")
        self.assertEqual(_printer_name(config, "strips"), "DNP Strips")

    def test_submits_jpeg_through_windows_image_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            system32 = root / "System32"
            system32.mkdir()
            (system32 / "rundll32.exe").write_bytes(b"exe")
            (system32 / "shimgvw.dll").write_bytes(b"dll")
            source = root / "print grid.jpg"
            Image.new("RGB", (60, 40), "red").save(source)

            win32print = Mock()
            win32print.OpenPrinter.return_value = "handle"
            win32print.GetPrinter.return_value = {
                "pDriverName": "DNP DS-RX1 Driver",
                "pPortName": "USB001",
            }
            completed = Mock(returncode=0, stdout="", stderr="")
            with patch.dict(sys.modules, {"win32print": win32print}), \
                 patch.dict(os.environ, {"SystemRoot": str(root)}), \
                 patch("backend.printer.subprocess.run", return_value=completed) as run:
                _print_driver(str(source), {"printer_name": "DS-RX1"}, "grid")

            win32print.OpenPrinter.assert_called_once_with("DS-RX1")
            win32print.ClosePrinter.assert_called_once_with("handle")
            command = run.call_args.args[0]
            self.assertEqual(command[0], str(system32 / "rundll32.exe"))
            self.assertEqual(
                command[1], f"{system32 / 'shimgvw.dll'},ImageView_PrintTo")
            self.assertEqual(
                command[2:], [
                    "/pt",
                    str(source.resolve()),
                    "DS-RX1",
                    "DNP DS-RX1 Driver",
                    "USB001",
                ],
            )


class CustomPrintPreparationTests(unittest.TestCase):
    @staticmethod
    def _source_payload(size=(200, 100), color="red") -> bytes:
        import io

        output = io.BytesIO()
        Image.new("RGB", size, color).save(output, "PNG")
        return output.getvalue()

    def test_fit_keeps_whole_image_and_adds_white_margins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "fit.jpg"
            prepare_custom_print(
                self._source_payload(), output, (120, 80), 600, "fit")

            with Image.open(output) as result:
                self.assertEqual(result.size, (120, 80))
                self.assertGreater(min(result.getpixel((60, 2))), 245)
                self.assertGreater(result.getpixel((60, 40))[0], 220)
                self.assertLess(result.getpixel((60, 40))[1], 40)

    def test_fill_covers_page_and_crops_center(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "fill.jpg"
            prepare_custom_print(
                self._source_payload(), output, (120, 80), 600, "fill")

            with Image.open(output) as result:
                self.assertEqual(result.size, (120, 80))
                for point in ((2, 2), (60, 40), (117, 77)):
                    red, green, blue = result.getpixel(point)
                    self.assertGreater(red, 220)
                    self.assertLess(green, 40)
                    self.assertLess(blue, 40)

    def test_portrait_source_is_rotated_before_fitting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "portrait.jpg"
            orientation = prepare_custom_print(
                self._source_payload((100, 200)),
                output,
                (120, 80),
                600,
                "fill",
            )

            self.assertEqual(orientation, "вертикальная")
            with Image.open(output) as result:
                self.assertEqual(result.size, (120, 80))
                self.assertGreater(result.getpixel((2, 2))[0], 220)

    def test_rejects_unknown_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "mode"):
                prepare_custom_print(
                    self._source_payload(),
                    Path(tmpdir) / "bad.jpg",
                    mode="stretch",
                )


class CustomPrintCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_explicit_fit_or_fill_mode(self):
        with patch.dict(main.CONFIG, {"print_enabled": True}):
            result = await main.handle_disk_command({
                "command": "print_image",
                "command_id": "a" * 32,
                "data": {"job_id": "b" * 32},
            })

        self.assertEqual(result["status"], "error")
        self.assertIn("режим", result["message"].lower())

    async def test_passes_selected_mode_to_renderer(self):
        payload = CustomPrintPreparationTests._source_payload()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(main, "PRINT_JOBS_DIR", Path(tmpdir)), \
             patch.dict(main.CONFIG, {
                 "print_enabled": True,
                 "keep_custom_print_files": True,
                 "template_pack": "default",
                 "print_dpi": 600,
             }), \
             patch(
                 "backend.main.yadisk_control.download_print_artifact",
                 AsyncMock(return_value=payload),
             ), \
             patch(
                 "backend.main.yadisk_cloud.current_event_folder",
                 return_value="event",
             ), \
             patch(
                 "backend.printer.prepare_custom_print",
                 return_value="горизонтальная",
             ) as prepare:
            result = await main.handle_disk_command({
                "command": "print_image",
                "command_id": "a" * 32,
                "data": {
                    "job_id": "b" * 32,
                    "print_mode": "fill",
                    "artifact_path": "/event_by_sessions/0000_print_jobs/image.png",
                    "event_folder": "event",
                    "sender_id": 123,
                },
            })

        self.assertEqual(result["status"], "ok")
        self.assertEqual(prepare.call_args.args[-1], "fill")

    async def test_rejects_print_for_stale_event_before_download(self):
        download = AsyncMock()
        with patch.dict(main.CONFIG, {
                 "print_enabled": True,
                 "yadisk_folder": "new_event",
             }), \
             patch(
                 "backend.main.yadisk_cloud.current_event_folder",
                 return_value="new_event",
             ), \
             patch(
                 "backend.main.yadisk_control.download_print_artifact",
                 download,
             ), \
             patch("backend.printer.prepare_custom_print") as prepare:
            result = await main.handle_disk_command({
                "command": "print_image",
                "command_id": "a" * 32,
                "data": {
                    "job_id": "b" * 32,
                    "print_mode": "fill",
                    "artifact_path": (
                        "/old_event_by_sessions/0000_print_jobs/image.png"
                    ),
                    "event_folder": "old_event",
                },
            })

        self.assertEqual(result["status"], "error")
        self.assertIn("old_event", result["message"])
        self.assertIn("new_event", result["message"])
        self.assertNotIn("_post_action", result)
        download.assert_not_awaited()
        prepare.assert_not_called()


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
        with patch.object(main, "_run_session", fake_session), \
             patch("backend.main._start_locked", return_value=False):
            first = asyncio.create_task(main.run_session())
            await entered.wait()
            await main.run_session()
            release.set()
            await first

        self.assertEqual(calls, 1)
        self.assertFalse(main._session_running)


if __name__ == "__main__":
    unittest.main()
