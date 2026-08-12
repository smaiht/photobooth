import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image, ImageChops, ImageStat

from backend.composer import (
    PhotoChoicePreview,
    PreviewBatch,
    compose,
    compose_unframed_photo,
    generate_template_previews,
    template_photo_count,
)
from backend.text_layer import DATE_TOKENS, date_values
from backend import composer as composer_module
from backend import text_layer
from backend import main
from backend.printer import (
    _print_driver,
    _printer_name,
    clear_windows_print_queues,
    get_windows_print_queues,
    prepare_custom_print,
)


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

    def test_unframed_photo_covers_the_complete_print_raster(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            source = Image.new("RGB", (200, 100), "green")
            try:
                source.paste("red", (0, 0, 30, 100))
                source.paste("blue", (170, 0, 200, 100))
                source.save(folder / "wide.png")
            finally:
                source.close()

            result = compose_unframed_photo(
                folder / "wide.png", {"print_size": [100, 100]})
            try:
                self.assertEqual(result.size, (100, 100))
                for point in ((0, 0), (99, 0), (0, 99), (99, 99), (50, 50)):
                    red, green, blue = result.getpixel(point)
                    self.assertLess(red, 30)
                    self.assertGreater(green, 100)
                    self.assertLess(blue, 30)
            finally:
                result.close()

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


class TemplateTextTests(unittest.TestCase):
    """Text is the last layer and never blocks a print when it fails."""

    FONT = "Comfortaa-VariableFont_wght.ttf"

    def setUp(self):
        self.moment = datetime(2026, 8, 8, 9, 20, 43)

    @staticmethod
    def _pack(folder: Path, texts, size=(400, 200)) -> dict:
        Image.new("RGB", size, "white").save(folder / "background.png")
        Image.new("RGB", size, "white").save(folder / "photo.png")
        layout = {
            "background": "background.png",
            "photos": [{"photo_index": 0, "x": 0, "y": 0, "rotate": "none"}],
        }
        if texts is not None:
            layout["texts"] = texts
        return {
            "print_size": list(size),
            "templates": {
                "grid": {
                    "photo_size_px": {"width": size[0], "height": 100},
                    "print_layout": layout,
                    "preview_rotation": "none",
                    "preview_split": "none",
                },
            },
        }

    def _block(self, **overrides) -> dict:
        block = {
            "box": {"x": 0, "y": 100, "width": 400, "height": 100},
            "align": "center",
            "valign": "middle",
            "rotate": "none",
            "font": self.FONT,
            "color": "#000000",
            "lines": [{"text": "{dd}.{mm}.{yyyy}", "size": 40}],
        }
        block.update(overrides)
        return block

    @staticmethod
    def _ink(image: Image.Image, box: tuple[int, int, int, int]) -> int:
        region = image.crop(box).convert("L")
        try:
            return sum(count for value, count in enumerate(
                region.histogram()) if value < 128)
        finally:
            region.close()

    def test_date_tokens_use_russian_genitive_month(self):
        values = date_values(self.moment)
        self.assertEqual(values["{dd}.{mm}.{yyyy}"], "08.08.2026")
        self.assertEqual(values["{dd} {month_ru} {yyyy}"], "8 августа 2026")
        # Every documented token must resolve, or a pack could reference one
        # that silently stays literal.
        self.assertEqual(set(values), set(DATE_TOKENS))

    def test_january_and_december_do_not_fall_off_the_month_table(self):
        self.assertEqual(
            date_values(datetime(2026, 1, 1))["{dd} {month_ru} {yyyy}"],
            "1 января 2026",
        )
        self.assertEqual(
            date_values(datetime(2026, 12, 31))["{dd} {month_ru} {yyyy}"],
            "31 декабря 2026",
        )

    def test_date_is_drawn_inside_its_box(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config = self._pack(folder, [self._block()])
            result = compose(
                folder, "grid", [folder / "photo.png"], config,
                text_values=date_values(self.moment),
            )
            try:
                self.assertGreater(self._ink(result, (0, 100, 400, 200)), 100)
                # The photo area above the box must stay untouched.
                self.assertEqual(self._ink(result, (0, 0, 400, 100)), 0)
            finally:
                result.close()

    def test_absent_texts_key_keeps_the_sheet_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            without = compose(
                folder, "grid", [folder / "photo.png"],
                self._pack(folder, None),
            )
            try:
                self.assertEqual(self._ink(without, (0, 0, 400, 200)), 0)
            finally:
                without.close()

    def test_text_is_drawn_over_the_foreground(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config = self._pack(folder, [self._block()])
            foreground = Image.new("RGBA", (400, 200), (255, 255, 255, 255))
            try:
                foreground.save(folder / "foreground.png")
            finally:
                foreground.close()
            config["templates"]["grid"]["print_layout"]["foreground"] = \
                "foreground.png"
            result = compose(
                folder, "grid", [folder / "photo.png"], config,
                text_values=date_values(self.moment),
            )
            try:
                # An opaque white foreground would hide any earlier layer, so
                # visible ink proves the text came last.
                self.assertGreater(self._ink(result, (0, 100, 400, 200)), 100)
            finally:
                result.close()

    def test_a_failing_block_is_skipped_and_the_sheet_still_composes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config = self._pack(folder, [
                self._block(font="NoSuchFont.ttf"),
                self._block(lines=[{"text": "{unknown}", "size": 40}]),
            ])
            with self.assertLogs("backend.text_layer", level="ERROR") as logs:
                result = compose(
                    folder, "grid", [folder / "photo.png"], config,
                    text_values=date_values(self.moment),
                )
            try:
                self.assertEqual(result.size, (400, 200))
                self.assertEqual(self._ink(result, (0, 0, 400, 200)), 0)
            finally:
                result.close()
            self.assertEqual(len(logs.output), 2)
            self.assertIn("font not found", logs.output[0])
            self.assertIn("unknown token", logs.output[1])

    def test_align_moves_the_text_within_the_box(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            positions = {}
            for align in ("left", "right"):
                config = self._pack(folder, [self._block(align=align)])
                result = compose(
                    folder, "grid", [folder / "photo.png"], config,
                    text_values=date_values(self.moment),
                )
                try:
                    positions[align] = (
                        self._ink(result, (0, 100, 100, 200)),
                        self._ink(result, (300, 100, 400, 200)),
                    )
                finally:
                    result.close()
            self.assertGreater(positions["left"][0], positions["left"][1])
            self.assertGreater(positions["right"][1], positions["right"][0])

    def test_weight_changes_stroke_thickness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            ink = {}
            for weight in (300, 700):
                config = self._pack(folder, [self._block(
                    lines=[{"text": "08.08.2026", "size": 40, "weight": weight}],
                )])
                result = compose(
                    folder, "grid", [folder / "photo.png"], config,
                    text_values=date_values(self.moment),
                )
                try:
                    ink[weight] = self._ink(result, (0, 100, 400, 200))
                finally:
                    result.close()
            self.assertGreater(ink[700], ink[300])

    def test_out_of_range_weight_is_clamped_and_logged(self):
        with self.assertLogs("backend.text_layer", level="ERROR") as logs:
            clamped = text_layer._load_font(self.FONT, 40, 5000)
        limit = text_layer._load_font(self.FONT, 40, 700)
        self.assertEqual(
            clamped.getbbox("08.08.2026"), limit.getbbox("08.08.2026"))
        self.assertIn("Out-of-range weight=5000", logs.output[0])

    def test_line_overrides_only_what_it_declares(self):
        blocks = text_layer.validated_text_blocks(
            {"texts": [self._block(
                color="#111111",
                size=30,
                weight=400,
                lines=[
                    {"text": "первая"},
                    {"text": "вторая", "size": 50, "color": "#222222"},
                ],
            )]},
            "grid",
            (400, 200),
        )
        first, second = blocks[0].lines
        self.assertEqual((first.size, first.color, first.weight), (30, "#111111", 400))
        self.assertEqual((second.size, second.color), (50, "#222222"))
        # An override must not drop the block-level font or weight.
        self.assertEqual(second.font, first.font)
        self.assertEqual(second.weight, 400)

    def test_structural_mistakes_in_a_pack_are_refused(self):
        cases = {
            "texts must be a list": {"texts": {}},
            "box exceeds the print size": [self._block(
                box={"x": 0, "y": 100, "width": 500, "height": 100})],
            "unsupported align": [self._block(align="middle")],
            "unsupported valign": [self._block(valign="center")],
            "unsupported rotate": [self._block(rotate="upside")],
            "needs a non-empty lines list": [self._block(lines=[])],
            "size must be an integer": [self._block(
                lines=[{"text": "x", "size": 0}])],
            "needs a font file name": [self._block(
                font="../secrets.ttf", lines=[{"text": "x", "size": 20}])],
            "line_spacing must be": [self._block(line_spacing=99)],
        }
        for message, texts in cases.items():
            with self.subTest(message=message):
                layout = texts if isinstance(texts, dict) else {"texts": texts}
                with self.assertRaisesRegex(ValueError, message):
                    text_layer.validated_text_blocks(layout, "grid", (400, 200))

    def test_rotated_block_turns_with_the_strip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config = self._pack(
                folder,
                [self._block(
                    box={"x": 150, "y": 0, "width": 100, "height": 400},
                    rotate="ccw",
                    lines=[{"text": "08.08.2026", "size": 40}],
                )],
                size=(400, 400),
            )
            config["templates"]["grid"]["photo_size_px"] = {
                "width": 100, "height": 100}
            result = compose(
                folder, "grid", [folder / "photo.png"], config,
                text_values=date_values(self.moment),
            )
            try:
                # A rotated line is taller than wide, so ink stays in the narrow
                # vertical box instead of spilling sideways.
                self.assertGreater(self._ink(result, (150, 0, 250, 400)), 100)
                self.assertEqual(self._ink(result, (0, 0, 150, 400)), 0)
                self.assertEqual(self._ink(result, (250, 0, 400, 400)), 0)
            finally:
                result.close()

    def test_preview_scales_text_with_the_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config = self._pack(folder, [self._block()], size=(400, 200))
            output_dir = folder / "previews"
            with Image.open(folder / "photo.png") as source:
                photo = source.convert("RGB")
            try:
                preview = composer_module._compose_preview(
                    folder, "grid", [photo], config, (400, 200), 200,
                    date_values(self.moment),
                )
            finally:
                photo.close()
            try:
                self.assertEqual(preview.size, (200, 100))
                # The box occupies the lower half at any scale.
                self.assertGreater(self._ink(preview, (0, 50, 200, 100)), 20)
                self.assertEqual(self._ink(preview, (0, 0, 200, 50)), 0)
            finally:
                preview.close()
            self.assertFalse(output_dir.exists())

    def test_session_previews_receive_the_same_values_as_the_print(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config = self._pack(folder, [self._block()])
            output_dir = folder / "previews"
            batch = generate_template_previews(
                folder,
                [folder / "photo.png"],
                config,
                output_dir,
                preview_width=200,
                text_values=date_values(self.moment),
            )
            with Image.open(batch["grid"]) as preview:
                self.assertGreater(self._ink(preview, (0, 50, 200, 100)), 20)

    def test_colour_parsing_accepts_rgb_and_rgba_only(self):
        self.assertEqual(text_layer._parse_color("#ff8000"), (255, 128, 0, 255))
        self.assertEqual(
            text_layer._parse_color("#ff800080"), (255, 128, 0, 128))
        for invalid in ("ff8000", "#fff", "#gggggg", ""):
            with self.subTest(color=invalid):
                with self.assertRaises(ValueError):
                    text_layer._parse_color(invalid)


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

    def test_photo_choice_reuses_reduced_photos_for_four_preview_pairs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            config, photos = self._make_pack(folder)
            Image.new("RGB", (600, 400), "white").save(folder / "single.png")
            config["templates"] = {
                "single": {
                    "label": "1 фото",
                    "photo_choice": True,
                    "photo_size_px": {"width": 500, "height": 300},
                    "print_layout": {
                        "background": "single.png",
                        "photos": [{
                            "photo_index": 0,
                            "x": 50,
                            "y": 50,
                            "rotate": "none",
                        }],
                    },
                    "preview_rotation": "none",
                    "preview_split": "none",
                },
            }
            output_dir = folder / "previews"

            with patch(
                "backend.composer._load_reduced_photos",
                wraps=composer_module._load_reduced_photos,
            ) as load_photos:
                batch = generate_template_previews(
                    folder, photos, config, output_dir, preview_width=300)

            self.assertIsInstance(batch, PreviewBatch)
            load_photos.assert_called_once_with(photos)
            self.assertEqual(list(batch), ["single"])
            choices = batch.photo_choices["single"]
            self.assertEqual(
                [choice.photo_index for choice in choices], list(range(4)))
            self.assertEqual(batch["single"], choices[0].with_frame)
            self.assertEqual(len(list(output_dir.glob("*.jpg"))), 8)

            expected_colors = (
                (255, 0, 0),
                (0, 128, 0),
                (0, 0, 255),
                (255, 255, 0),
            )
            for choice, expected in zip(choices, expected_colors):
                with Image.open(choice.with_frame) as framed, \
                     Image.open(choice.without_frame) as unframed:
                    self.assertEqual(framed.size, (300, 200))
                    self.assertEqual(unframed.size, (300, 200))
                    self.assertGreater(min(framed.getpixel((2, 2))), 220)
                    center = framed.getpixel((150, 100))
                    edge = unframed.getpixel((2, 2))
                    for actual, wanted in zip(center, expected):
                        self.assertAlmostEqual(actual, wanted, delta=30)
                    for actual, wanted in zip(edge, expected):
                        self.assertAlmostEqual(actual, wanted, delta=30)

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

    def test_driver_paper_size_id_is_logged_without_configuration_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            system32 = root / "System32"
            system32.mkdir()
            (system32 / "rundll32.exe").write_bytes(b"exe")
            (system32 / "shimgvw.dll").write_bytes(b"dll")
            source = root / "print_grid.jpg"
            source.write_bytes(b"jpeg")

            devmode = Mock(
                PaperSize=179,
                FormName="",
                Orientation=1,
                PrintQuality=600,
                YResolution=600,
                Copies=1,
            )
            win32print = Mock()
            win32print.OpenPrinter.return_value = "handle"
            win32print.GetPrinter.return_value = {
                "pDriverName": "DNP DS-RX1 Driver",
                "pPortName": "USB001",
                "pDevMode": devmode,
            }
            completed = Mock(returncode=0, stdout="", stderr="")

            with patch.dict(sys.modules, {"win32print": win32print}), \
                 patch.dict(os.environ, {"SystemRoot": str(root)}), \
                 patch("backend.printer.Image.open") as open_image, \
                 patch("backend.printer.subprocess.run", return_value=completed), \
                 self.assertLogs("backend.printer", level="INFO") as captured:
                raster = open_image.return_value.__enter__.return_value
                raster.size = (3688, 2480)
                raster.info = {"dpi": (600, 600)}
                _print_driver(str(source), {"printer_name": "DS-RX1"}, "grid")

            messages = "\n".join(captured.output)
            self.assertIn("paper_size=179", messages)
            self.assertIn("diagnostic only", messages)
            self.assertNotIn("do not match", messages)

    def test_reports_grid_and_strips_windows_job_counts(self):
        job_counts = {
            "DNP Cards": 3,
            "DNP Strips": 1,
        }
        win32print = Mock()
        win32print.OpenPrinter.side_effect = lambda name: name
        win32print.GetPrinter.side_effect = (
            lambda handle, _level: {"cJobs": job_counts[handle]}
        )

        with patch.dict(sys.modules, {"win32print": win32print}):
            records = get_windows_print_queues({
                "printer_name": "DNP Cards",
                "printer_name_strips": "DNP Strips",
            })

        self.assertEqual(records, [
            {
                "target": "grid",
                "printer_name": "DNP Cards",
                "jobs": 3,
                "error": None,
            },
            {
                "target": "strips",
                "printer_name": "DNP Strips",
                "jobs": 1,
                "error": None,
            },
        ])
        self.assertEqual(win32print.ClosePrinter.call_count, 2)

    def test_clears_both_windows_queues_and_reports_before_after(self):
        job_counts = {
            "DNP Cards": 3,
            "DNP Strips": 1,
        }
        win32print = Mock()
        win32print.PRINTER_ACCESS_ADMINISTER = 4
        win32print.PRINTER_CONTROL_PURGE = 3
        win32print.OpenPrinter.side_effect = lambda name, *_args: name
        win32print.GetPrinter.side_effect = (
            lambda handle, _level: {"cJobs": job_counts[handle]}
        )

        def purge(handle, _level, _printer, command):
            self.assertEqual(command, 3)
            job_counts[handle] = 0

        win32print.SetPrinter.side_effect = purge

        with patch.dict(sys.modules, {"win32print": win32print}):
            records = clear_windows_print_queues({
                "printer_name": "DNP Cards",
                "printer_name_strips": "DNP Strips",
            })

        self.assertEqual(records, [
            {
                "printer_name": "DNP Cards",
                "jobs_before": 3,
                "jobs_after": 0,
                "cleared": 3,
                "error": None,
                "target": "grid",
            },
            {
                "printer_name": "DNP Strips",
                "jobs_before": 1,
                "jobs_after": 0,
                "cleared": 1,
                "error": None,
                "target": "strips",
            },
        ])
        self.assertEqual(win32print.SetPrinter.call_count, 2)

    def test_clear_falls_back_to_deleting_owned_jobs_without_admin_access(self):
        jobs = {
            "DNP Cards": [101, 102],
            "DNP Strips": [],
        }
        win32print = Mock()
        win32print.PRINTER_ACCESS_ADMINISTER = 4
        win32print.PRINTER_CONTROL_PURGE = 3
        win32print.JOB_CONTROL_DELETE = 5

        def open_printer(name, *defaults):
            if defaults:
                raise PermissionError("admin access denied")
            return name

        win32print.OpenPrinter.side_effect = open_printer
        win32print.GetPrinter.side_effect = (
            lambda handle, _level: {"cJobs": len(jobs[handle])}
        )
        win32print.SetPrinter.side_effect = PermissionError("purge denied")
        win32print.EnumJobs.side_effect = (
            lambda handle, *_args: [
                {"JobId": job_id} for job_id in jobs[handle]
            ]
        )

        def delete_job(handle, job_id, _level, _job, command):
            self.assertEqual(command, 5)
            jobs[handle].remove(job_id)

        win32print.SetJob.side_effect = delete_job

        with patch.dict(sys.modules, {"win32print": win32print}):
            records = clear_windows_print_queues({
                "printer_name": "DNP Cards",
                "printer_name_strips": "DNP Strips",
            })

        self.assertEqual(records[0]["cleared"], 2)
        self.assertEqual(records[0]["jobs_after"], 0)
        self.assertIsNone(records[0]["error"])
        self.assertEqual(win32print.SetJob.call_count, 2)

    def test_same_physical_queue_is_purged_only_once(self):
        job_count = 2
        win32print = Mock()
        win32print.PRINTER_ACCESS_ADMINISTER = 4
        win32print.PRINTER_CONTROL_PURGE = 3
        win32print.OpenPrinter.side_effect = lambda name, *_args: name
        win32print.GetPrinter.side_effect = (
            lambda _handle, _level: {"cJobs": job_count}
        )

        def purge(*_args):
            nonlocal job_count
            job_count = 0

        win32print.SetPrinter.side_effect = purge

        with patch.dict(sys.modules, {"win32print": win32print}):
            records = clear_windows_print_queues({
                "printer_name": "DNP Cards",
                "printer_name_strips": "",
            })

        self.assertEqual(win32print.SetPrinter.call_count, 1)
        self.assertNotIn("shared_with", records[0])
        self.assertEqual(records[1]["shared_with"], "grid")


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


class SessionDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_outbox_waits_for_video(self):
        video_future = asyncio.get_running_loop().create_future()
        created_at = object()
        with patch(
            "backend.main.yadisk_cloud.enqueue_session",
            new_callable=AsyncMock,
        ) as enqueue:
            task = asyncio.create_task(main._enqueue_session_after_video(
                "session123",
                ["photo1.jpg", "photo2.jpg"],
                video_future,
                created_at,
                "event",
                "session-folder",
            ))
            await asyncio.sleep(0)
            enqueue.assert_not_awaited()

            video_future.set_result("session.mp4")
            await task

        enqueue.assert_awaited_once_with(
            "session123",
            ["photo1.jpg", "photo2.jpg"],
            "session.mp4",
            created_at=created_at,
            event_folder="event",
            session_folder="session-folder",
        )

    async def test_skip_uploads_media_without_printing_or_consuming_unlock(self):
        class Camera:
            is_connected = True
            connection_generation = 1

            def set_download_dir(self, path):
                self.download_dir = Path(path)

            def start_live_view(self):
                pass

            def stop_live_view(self):
                pass

            def take_picture(self, _tag=""):
                photo_number = len(main.SESSION_PHOTOS) + 1
                main.SESSION_PHOTOS.append(
                    str(self.download_dir / f"photo_{photo_number}.jpg"))

        states = []

        async def set_state(state, _extra=None):
            main.STATE = state
            states.append(state)
            if state == "template_select":
                main.app.state.on_skip_print()

        def previews(_template_dir, _photos, config, output_dir, **_kwargs):
            return {
                name: Path(output_dir) / f"{name}.jpg"
                for name in config["templates"]
            }

        uploaded = asyncio.Event()

        async def enqueue(*_args, **_kwargs):
            uploaded.set()

        recorder = Mock()
        recorder.stop_and_encode.return_value = "session.mp4"
        config = dict(main.CONFIG)
        config.update({
            "num_photos": 4,
            "pre_countdown_delay": 0,
            "countdown_seconds": 0,
            "countdown_sound_seconds": 0,
            "template_select_timeout": 1,
            "done_screen_seconds": 0,
            "default_template": "grid",
            "template_pack": "default",
            "technical_event_name": "Кафе",
            "yadisk_folder": "Кафе",
            "print_enabled": True,
        })

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.multiple(
                 main,
                 camera=Camera(),
                 video_recorder=recorder,
                 CONFIG=config,
                 PHOTOS_DIR=Path(tmpdir),
                 CLIENTS=[],
                 STATE="idle",
                 SESSION_ID="",
                 SESSION_PHOTOS=[],
                 SESSION_LINK="",
                 TEMPLATE_OPTIONS=[],
                 SESSION_COUNT=0,
                 _session_running=False,
                 _background_uploads=set(),
                 _camera_disconnected_event=asyncio.Event(),
             ), \
             patch("backend.main._start_locked", return_value=False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"), \
             patch("backend.main.yadisk_cloud.enqueue_session",
                   new_callable=AsyncMock, side_effect=enqueue) as upload, \
             patch("backend.main._prepare_session_link",
                   new_callable=AsyncMock), \
             patch("backend.main.generate_template_previews",
                   side_effect=previews), \
             patch("backend.main.compose") as compose_print, \
             patch("backend.printer.enqueue_print",
                   new_callable=AsyncMock) as print_job, \
             patch("backend.main._consume_cafe_unlock_session") as consume, \
             patch("backend.main.broadcast", new_callable=AsyncMock), \
             patch("backend.main.set_state", side_effect=set_state):
            await main.run_session()
            await asyncio.wait_for(uploaded.wait(), timeout=1)
            if main._background_uploads:
                await asyncio.gather(*list(main._background_uploads))

            self.assertEqual(main.STATE, "idle")
            self.assertEqual(len(upload.await_args.args[1]), 4)
            self.assertEqual(upload.await_args.args[2], "session.mp4")
            self.assertFalse(any(Path(tmpdir).rglob("print_*.jpg")))

        self.assertIn("template_select", states)
        self.assertNotIn("composing", states)
        compose_print.assert_not_called()
        print_job.assert_not_awaited()
        consume.assert_not_called()

    async def test_single_choice_uses_selected_original_and_unframed_cover(self):
        class Camera:
            is_connected = True
            connection_generation = 1

            def set_download_dir(self, path):
                self.download_dir = Path(path)

            def start_live_view(self):
                pass

            def stop_live_view(self):
                pass

            def take_picture(self, _tag=""):
                photo_number = len(main.SESSION_PHOTOS) + 1
                main.SESSION_PHOTOS.append(
                    str(self.download_dir / f"photo_{photo_number}.jpg"))

        states = []
        exposed_options = []

        async def set_state(state, _extra=None):
            main.STATE = state
            states.append(state)
            if state == "template_select":
                exposed_options.extend(main.TEMPLATE_OPTIONS)
                choose = main.app.state.on_template_choice
                choose("single", True, True)
                choose("single", 4, True)
                choose("single", 2, "false")
                choose("single", 2, False)

        def previews(_template_dir, _photos, config, output_dir, **_kwargs):
            paths = {
                name: Path(output_dir) / f"{name}.jpg"
                for name in config["templates"]
            }
            choices = [
                PhotoChoicePreview(
                    index,
                    Path(output_dir) / f"single_{index + 1}_frame.jpg",
                    Path(output_dir) / f"single_{index + 1}_no_frame.jpg",
                )
                for index in range(4)
            ]
            paths["single"] = choices[0].with_frame
            return PreviewBatch(paths, {"single": choices})

        uploaded = asyncio.Event()

        async def enqueue(*_args, **_kwargs):
            uploaded.set()

        recorder = Mock()
        recorder.stop_and_encode.return_value = "session.mp4"
        config = dict(main.CONFIG)
        config.update({
            "num_photos": 4,
            "pre_countdown_delay": 0,
            "countdown_seconds": 0,
            "countdown_sound_seconds": 0,
            "template_select_timeout": 1,
            "done_screen_seconds": 0,
            "default_template": "grid",
            "template_pack": "kvas01aug26",
            "technical_event_name": "Кафе",
            "yadisk_folder": "event",
            "print_enabled": False,
        })

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.multiple(
                 main,
                 camera=Camera(),
                 video_recorder=recorder,
                 CONFIG=config,
                 PHOTOS_DIR=Path(tmpdir),
                 CLIENTS=[],
                 STATE="idle",
                 SESSION_ID="",
                 SESSION_PHOTOS=[],
                 SESSION_LINK="",
                 TEMPLATE_OPTIONS=[],
                 SESSION_COUNT=0,
                 _session_running=False,
                 _background_uploads=set(),
                 _camera_disconnected_event=asyncio.Event(),
             ), \
             patch("backend.main._start_locked", return_value=False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"), \
             patch("backend.main.yadisk_cloud.enqueue_session",
                   new_callable=AsyncMock, side_effect=enqueue), \
             patch("backend.main._prepare_session_link",
                   new_callable=AsyncMock), \
             patch("backend.main.generate_template_previews",
                   side_effect=previews), \
             patch("backend.main.compose") as compose_with_frame, \
             patch(
                 "backend.main.compose_unframed_photo",
                 side_effect=lambda *_args: Image.new("RGB", (120, 80), "red"),
             ) as compose_without_frame, \
             patch("backend.main.broadcast", new_callable=AsyncMock), \
             patch("backend.main.set_state", side_effect=set_state):
            await main.run_session()
            await asyncio.wait_for(uploaded.wait(), timeout=1)
            if main._background_uploads:
                await asyncio.gather(*list(main._background_uploads))

            selected_path = compose_without_frame.call_args.args[0]
            self.assertEqual(Path(selected_path).name, "photo_3.jpg")
            self.assertEqual(
                len(list(Path(tmpdir).rglob(
                    "print_single_photo_03_no_frame.jpg"))),
                1,
            )

        single_option = next(
            option for option in exposed_options if option["name"] == "single")
        self.assertTrue(single_option["photo_choice"])
        self.assertEqual(len(single_option["photo_previews"]), 4)
        self.assertIn("template_select", states)
        self.assertIn("composing", states)
        compose_with_frame.assert_not_called()
        compose_without_frame.assert_called_once()

    async def test_touch_activity_extends_template_selection_timeout(self):
        class Camera:
            is_connected = True
            connection_generation = 1

            def set_download_dir(self, path):
                self.download_dir = Path(path)

            def start_live_view(self):
                pass

            def stop_live_view(self):
                pass

            def take_picture(self, _tag=""):
                photo_number = len(main.SESSION_PHOTOS) + 1
                main.SESSION_PHOTOS.append(
                    str(self.download_dir / f"photo_{photo_number}.jpg"))

        select_timeout = 0.2
        extensions = 4
        chosen_templates = []

        async def keep_touching():
            # Each touch restarts the full timeout, so the late choice below
            # arrives long after the original deadline would have expired.
            for _ in range(extensions):
                await asyncio.sleep(select_timeout / 2)
                main.app.state.on_template_activity()
            await asyncio.sleep(select_timeout / 2)
            main.app.state.on_template_choice("strips")

        async def set_state(state, _extra=None):
            main.STATE = state
            states.append(state)
            if state == "template_select":
                asyncio.create_task(keep_touching())

        states = []

        def previews(_template_dir, _photos, config, output_dir, **_kwargs):
            return {
                name: Path(output_dir) / f"{name}.jpg"
                for name in config["templates"]
            }

        uploaded = asyncio.Event()

        async def enqueue(*_args, **_kwargs):
            uploaded.set()

        def compose_template(_dir, name, _photos, _config, **_kwargs):
            chosen_templates.append(name)
            return Image.new("RGB", (120, 80), "white")

        recorder = Mock()
        recorder.stop_and_encode.return_value = "session.mp4"
        config = dict(main.CONFIG)
        config.update({
            "num_photos": 4,
            "pre_countdown_delay": 0,
            "countdown_seconds": 0,
            "countdown_sound_seconds": 0,
            "template_select_timeout": select_timeout,
            "done_screen_seconds": 0,
            "default_template": "grid",
            "template_pack": "kvas01aug26",
            "technical_event_name": "Кафе",
            "yadisk_folder": "event",
            "print_enabled": False,
        })

        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.multiple(
                 main,
                 camera=Camera(),
                 video_recorder=recorder,
                 CONFIG=config,
                 PHOTOS_DIR=Path(tmpdir),
                 CLIENTS=[],
                 STATE="idle",
                 SESSION_ID="",
                 SESSION_PHOTOS=[],
                 SESSION_LINK="",
                 TEMPLATE_OPTIONS=[],
                 SESSION_COUNT=0,
                 _session_running=False,
                 _background_uploads=set(),
                 _camera_disconnected_event=asyncio.Event(),
             ), \
             patch("backend.main._start_locked", return_value=False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"), \
             patch("backend.main.yadisk_cloud.enqueue_session",
                   new_callable=AsyncMock, side_effect=enqueue), \
             patch("backend.main._prepare_session_link",
                   new_callable=AsyncMock), \
             patch("backend.main.generate_template_previews",
                   side_effect=previews), \
             patch("backend.main.compose", side_effect=compose_template), \
             patch("backend.main.broadcast", new_callable=AsyncMock), \
             patch("backend.main.set_state", side_effect=set_state):
            await main.run_session()
            await asyncio.wait_for(uploaded.wait(), timeout=2)
            if main._background_uploads:
                await asyncio.gather(*list(main._background_uploads))

        # The late choice won, not the default template that a single
        # non-extendable timeout would have selected.
        self.assertEqual(chosen_templates, ["strips"])
        self.assertGreater(
            time.monotonic() - started, select_timeout * (extensions + 1) / 2)
        self.assertIsNone(main.app.state.on_template_activity)

    async def test_touch_after_choice_neither_prints_twice_nor_delays_session(self):
        class Camera:
            is_connected = True
            connection_generation = 1

            def set_download_dir(self, path):
                self.download_dir = Path(path)

            def start_live_view(self):
                pass

            def stop_live_view(self):
                pass

            def take_picture(self, _tag=""):
                photo_number = len(main.SESSION_PHOTOS) + 1
                main.SESSION_PHOTOS.append(
                    str(self.download_dir / f"photo_{photo_number}.jpg"))

        select_timeout = 30.0
        states = []
        chosen_templates = []
        activity_results = []

        async def set_state(state, _extra=None):
            main.STATE = state
            states.append(state)
            if state == "template_select":
                main.app.state.on_template_choice("strips")
                # Touches that land after the choice: a stray finger, or the
                # frontend flushing a queued pointer event.
                for _ in range(3):
                    activity_results.append(
                        main.app.state.on_template_activity())
                # A second choice must not replace the locked-in one either.
                main.app.state.on_template_choice("grid")
                main.app.state.on_skip_print()

        def previews(_template_dir, _photos, config, output_dir, **_kwargs):
            return {
                name: Path(output_dir) / f"{name}.jpg"
                for name in config["templates"]
            }

        uploaded = asyncio.Event()

        async def enqueue(*_args, **_kwargs):
            uploaded.set()

        def compose_template(_dir, name, _photos, _config, **_kwargs):
            chosen_templates.append(name)
            return Image.new("RGB", (120, 80), "white")

        recorder = Mock()
        recorder.stop_and_encode.return_value = "session.mp4"
        config = dict(main.CONFIG)
        config.update({
            "num_photos": 4,
            "pre_countdown_delay": 0,
            "countdown_seconds": 0,
            "countdown_sound_seconds": 0,
            "template_select_timeout": select_timeout,
            "done_screen_seconds": 0,
            "default_template": "grid",
            "template_pack": "kvas01aug26",
            "technical_event_name": "Кафе",
            "yadisk_folder": "event",
            "print_enabled": True,
        })

        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.multiple(
                 main,
                 camera=Camera(),
                 video_recorder=recorder,
                 CONFIG=config,
                 PHOTOS_DIR=Path(tmpdir),
                 CLIENTS=[],
                 STATE="idle",
                 SESSION_ID="",
                 SESSION_PHOTOS=[],
                 SESSION_LINK="",
                 TEMPLATE_OPTIONS=[],
                 SESSION_COUNT=0,
                 _session_running=False,
                 _background_uploads=set(),
                 _camera_disconnected_event=asyncio.Event(),
             ), \
             patch("backend.main._start_locked", return_value=False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"), \
             patch("backend.main.yadisk_cloud.enqueue_session",
                   new_callable=AsyncMock, side_effect=enqueue), \
             patch("backend.main._prepare_session_link",
                   new_callable=AsyncMock), \
             patch("backend.main.generate_template_previews",
                   side_effect=previews), \
             patch("backend.main.compose", side_effect=compose_template), \
             patch("backend.printer.enqueue_print",
                   new_callable=AsyncMock) as print_job, \
             patch("backend.main.broadcast", new_callable=AsyncMock), \
             patch("backend.main.set_state", side_effect=set_state):
            await main.run_session()
            await asyncio.wait_for(uploaded.wait(), timeout=2)
            if main._background_uploads:
                await asyncio.gather(*list(main._background_uploads))

        # Post-choice touches are refused, so the frontend gets no countdown
        # restart and the wait loop is not held open by them.
        self.assertEqual(activity_results, [False, False, False])
        self.assertLess(time.monotonic() - started, select_timeout / 2)
        # Exactly one composition and one print job, from the first choice.
        self.assertEqual(chosen_templates, ["strips"])
        print_job.assert_awaited_once()
        self.assertEqual(Path(print_job.await_args.args[0]).name,
                         "print_strips.jpg")
        self.assertEqual(print_job.await_args.args[2], "strips")
        self.assertEqual(states.count("composing"), 1)
        self.assertEqual(states.count("printing") + states.count("done"), 1)

    async def test_template_options_expose_session_originals_for_the_viewer(self):
        class Camera:
            is_connected = True
            connection_generation = 1

            def set_download_dir(self, path):
                self.download_dir = Path(path)

            def start_live_view(self):
                pass

            def stop_live_view(self):
                pass

            def take_picture(self, _tag=""):
                photo_number = len(main.SESSION_PHOTOS) + 1
                main.SESSION_PHOTOS.append(
                    str(self.download_dir / f"photo_{photo_number}.jpg"))

        exposed_options = []

        async def set_state(state, _extra=None):
            main.STATE = state
            if state == "template_select":
                exposed_options.extend(main.TEMPLATE_OPTIONS)
                main.app.state.on_template_choice("grid")

        def previews(_template_dir, _photos, config, output_dir, **_kwargs):
            paths = {
                name: Path(output_dir) / f"{name}.jpg"
                for name in config["templates"]
            }
            choices = [
                PhotoChoicePreview(
                    index,
                    Path(output_dir) / f"single_{index + 1}_frame.jpg",
                    Path(output_dir) / f"single_{index + 1}_no_frame.jpg",
                )
                for index in range(4)
            ]
            paths["single"] = choices[0].with_frame
            return PreviewBatch(paths, {"single": choices})

        uploaded = asyncio.Event()

        async def enqueue(*_args, **_kwargs):
            uploaded.set()

        recorder = Mock()
        recorder.stop_and_encode.return_value = "session.mp4"
        config = dict(main.CONFIG)
        config.update({
            "num_photos": 4,
            "pre_countdown_delay": 0,
            "countdown_seconds": 0,
            "countdown_sound_seconds": 0,
            "template_select_timeout": 1,
            "done_screen_seconds": 0,
            "default_template": "grid",
            "template_pack": "kvas01aug26",
            "technical_event_name": "Кафе",
            "yadisk_folder": "event",
            "print_enabled": False,
        })

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.multiple(
                 main,
                 camera=Camera(),
                 video_recorder=recorder,
                 CONFIG=config,
                 PHOTOS_DIR=Path(tmpdir),
                 CLIENTS=[],
                 STATE="idle",
                 SESSION_ID="",
                 SESSION_PHOTOS=[],
                 SESSION_LINK="",
                 TEMPLATE_OPTIONS=[],
                 SESSION_COUNT=0,
                 _session_running=False,
                 _background_uploads=set(),
                 _camera_disconnected_event=asyncio.Event(),
             ), \
             patch("backend.main._start_locked", return_value=False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"), \
             patch("backend.main.yadisk_cloud.enqueue_session",
                   new_callable=AsyncMock, side_effect=enqueue), \
             patch("backend.main._prepare_session_link",
                   new_callable=AsyncMock), \
             patch("backend.main.generate_template_previews",
                   side_effect=previews), \
             patch("backend.main.compose",
                   return_value=Image.new("RGB", (120, 80), "white")), \
             patch("backend.main.broadcast", new_callable=AsyncMock), \
             patch("backend.main.set_state", side_effect=set_state):
            await main.run_session()
            await asyncio.wait_for(uploaded.wait(), timeout=2)
            if main._background_uploads:
                await asyncio.gather(*list(main._background_uploads))

        single = next(
            option for option in exposed_options if option["name"] == "single")
        originals = [
            preview["original_url"] for preview in single["photo_previews"]]
        # Full-size session frames, served straight from the mounted /photos.
        self.assertEqual(len(originals), 4)
        for index, url in enumerate(originals, start=1):
            with self.subTest(photo=index):
                self.assertTrue(url.startswith("/photos/"))
                self.assertTrue(url.endswith(f"/photo_{index}.jpg"))
                self.assertNotIn("/previews/", url)

    async def test_timeout_fallback_uses_configured_frame_default(self):
        class Camera:
            is_connected = True
            connection_generation = 1

            def set_download_dir(self, path):
                self.download_dir = Path(path)

            def start_live_view(self):
                pass

            def stop_live_view(self):
                pass

            def take_picture(self, _tag=""):
                photo_number = len(main.SESSION_PHOTOS) + 1
                main.SESSION_PHOTOS.append(
                    str(self.download_dir / f"photo_{photo_number}.jpg"))

        async def set_state(state, _extra=None):
            main.STATE = state

        def previews(_template_dir, _photos, config, output_dir, **_kwargs):
            paths = {
                name: Path(output_dir) / f"{name}.jpg"
                for name in config["templates"]
            }
            choices = [
                PhotoChoicePreview(
                    index,
                    Path(output_dir) / f"single_{index + 1}_frame.jpg",
                    Path(output_dir) / f"single_{index + 1}_no_frame.jpg",
                )
                for index in range(4)
            ]
            paths["single"] = choices[0].with_frame
            return PreviewBatch(paths, {"single": choices})

        uploaded = asyncio.Event()

        async def enqueue(*_args, **_kwargs):
            uploaded.set()

        recorder = Mock()
        recorder.stop_and_encode.return_value = "session.mp4"
        config = dict(main.CONFIG)
        config.update({
            "num_photos": 4,
            "pre_countdown_delay": 0,
            "countdown_seconds": 0,
            "countdown_sound_seconds": 0,
            "template_select_timeout": 0.05,
            "done_screen_seconds": 0,
            # A photo_choice template as the silent fallback is the only case
            # where the booth-side frame default is actually used.
            "default_template": "single",
            "photo_choice_default_with_frame": False,
            "template_pack": "kvas01aug26",
            "technical_event_name": "Кафе",
            "yadisk_folder": "event",
            "print_enabled": False,
        })

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.multiple(
                 main,
                 camera=Camera(),
                 video_recorder=recorder,
                 CONFIG=config,
                 PHOTOS_DIR=Path(tmpdir),
                 CLIENTS=[],
                 STATE="idle",
                 SESSION_ID="",
                 SESSION_PHOTOS=[],
                 SESSION_LINK="",
                 TEMPLATE_OPTIONS=[],
                 SESSION_COUNT=0,
                 _session_running=False,
                 _background_uploads=set(),
                 _camera_disconnected_event=asyncio.Event(),
             ), \
             patch("backend.main._start_locked", return_value=False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="event"), \
             patch("backend.main.yadisk_cloud.enqueue_session",
                   new_callable=AsyncMock, side_effect=enqueue), \
             patch("backend.main._prepare_session_link",
                   new_callable=AsyncMock), \
             patch("backend.main.generate_template_previews",
                   side_effect=previews), \
             patch("backend.main.compose") as compose_with_frame, \
             patch(
                 "backend.main.compose_unframed_photo",
                 side_effect=lambda *_args: Image.new("RGB", (120, 80), "red"),
             ) as compose_without_frame, \
             patch("backend.main.broadcast", new_callable=AsyncMock), \
             patch("backend.main.set_state", side_effect=set_state):
            await main.run_session()
            await asyncio.wait_for(uploaded.wait(), timeout=2)
            if main._background_uploads:
                await asyncio.gather(*list(main._background_uploads))

        # Nobody touched the screen: the configured default decided, so the
        # unframed compositor ran and the framed one did not.
        compose_without_frame.assert_called_once()
        compose_with_frame.assert_not_called()


class PrintBasketTests(unittest.TestCase):
    """Basket normalization: the one-tap path is the single-item case."""

    AVAILABLE = {
        "grid": {},
        "strips": {},
        "single": {"photo_choice": True},
    }
    SELECTABLE = {"grid", "strips", "single"}

    def normalize(self, raw, photo_count=4):
        return main._normalize_print_item(
            raw, self.SELECTABLE, self.AVAILABLE, photo_count)

    def test_plain_template_ignores_photo_fields(self):
        item = self.normalize({
            "template": "grid",
            "photo_index": 3,
            "with_frame": False,
        })
        self.assertEqual(item, {
            "template": "grid",
            "photo_index": None,
            "with_frame": True,
            "copies": 1,
        })

    def test_photo_choice_requires_valid_index_and_frame(self):
        for raw in (
            {"template": "single"},
            {"template": "single", "photo_index": 4, "with_frame": True},
            {"template": "single", "photo_index": -1, "with_frame": True},
            {"template": "single", "photo_index": True, "with_frame": True},
            {"template": "single", "photo_index": 2},
            {"template": "single", "photo_index": 2, "with_frame": "false"},
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(self.normalize(raw))

        self.assertEqual(
            self.normalize(
                {"template": "single", "photo_index": 2, "with_frame": False}),
            {
                "template": "single",
                "photo_index": 2,
                "with_frame": False,
                "copies": 1,
            },
        )

    def test_unknown_template_and_bad_copies_are_rejected(self):
        for raw in (
            {"template": "unknown"},
            {"template": None},
            "grid",
            {"template": "grid", "copies": 0},
            {"template": "grid", "copies": -2},
            {"template": "grid", "copies": 1.5},
            {"template": "grid", "copies": "2"},
            {"template": "grid", "copies": True},
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(self.normalize(raw))

    def test_identical_entries_merge_but_frame_variants_stay_apart(self):
        merged = main._merge_print_items([
            {"template": "strips", "photo_index": None,
             "with_frame": True, "copies": 1},
            {"template": "strips", "photo_index": None,
             "with_frame": True, "copies": 2},
            {"template": "single", "photo_index": 1,
             "with_frame": True, "copies": 1},
            {"template": "single", "photo_index": 1,
             "with_frame": False, "copies": 1},
        ])

        # Three strips sheets compose once; the framed and unframed versions of
        # the same photo remain two different sheets.
        self.assertEqual(merged, [
            {"template": "strips", "photo_index": None,
             "with_frame": True, "copies": 3},
            {"template": "single", "photo_index": 1,
             "with_frame": True, "copies": 1},
            {"template": "single", "photo_index": 1,
             "with_frame": False, "copies": 1},
        ])

    def test_multi_select_is_limited_to_the_technical_event(self):
        config = {
            "multi_print_enabled": True,
            "technical_event_name": "Кафе",
        }
        with patch.object(main, "CONFIG", config), \
             patch("backend.main._active_event_name", return_value="Кафе"):
            self.assertTrue(main._multi_print_available())
        with patch.object(main, "CONFIG", config), \
             patch("backend.main._active_event_name",
                   return_value="Свадьба Ивановых"):
            self.assertFalse(main._multi_print_available())

        disabled = dict(config, multi_print_enabled=False)
        with patch.object(main, "CONFIG", disabled), \
             patch("backend.main._active_event_name", return_value="Кафе"):
            self.assertFalse(main._multi_print_available())

    def test_sheet_limit_falls_back_for_unusable_values(self):
        for raw in (0, -1, 21, 2.5, "6", True, None):
            with self.subTest(raw=raw), \
                 patch.object(main, "CONFIG", {"multi_print_max_sheets": raw}):
                self.assertEqual(
                    main._multi_print_max_sheets(),
                    main.DEFAULT_MULTI_PRINT_MAX_SHEETS,
                )
        with patch.object(main, "CONFIG", {"multi_print_max_sheets": 8}):
            self.assertEqual(main._multi_print_max_sheets(), 8)

    def test_config_has_valid_multi_print_fields(self):
        config = json.loads(
            (ROOT / "config_app.json").read_text(encoding="utf-8"))
        self.assertIsInstance(config["multi_print_enabled"], bool)
        sheet_limit = config["multi_print_max_sheets"]
        self.assertIsInstance(sheet_limit, int)
        self.assertNotIsInstance(sheet_limit, bool)
        self.assertGreaterEqual(sheet_limit, 1)
        self.assertLessEqual(sheet_limit, main.MAX_MULTI_PRINT_SHEETS)


class MultiPrintSessionTests(unittest.IsolatedAsyncioTestCase):
    """A basket reaches the printer as several sheets from one session."""

    class Camera:
        is_connected = True
        connection_generation = 1

        def set_download_dir(self, path):
            self.download_dir = Path(path)

        def start_live_view(self):
            pass

        def stop_live_view(self):
            pass

        def take_picture(self, _tag=""):
            photo_number = len(main.SESSION_PHOTOS) + 1
            main.SESSION_PHOTOS.append(
                str(self.download_dir / f"photo_{photo_number}.jpg"))

    @staticmethod
    def _previews(_template_dir, _photos, config, output_dir, **_kwargs):
        paths = {
            name: Path(output_dir) / f"{name}.jpg"
            for name in config["templates"]
        }
        choices = [
            PhotoChoicePreview(
                index,
                Path(output_dir) / f"single_{index + 1}_frame.jpg",
                Path(output_dir) / f"single_{index + 1}_no_frame.jpg",
            )
            for index in range(4)
        ]
        paths["single"] = choices[0].with_frame
        return PreviewBatch(paths, {"single": choices})

    async def _run(self, choose, *, multi_print=True, max_sheets=6,
                   select_timeout=30):
        """Run one full session, letting ``choose`` drive the basket."""
        composed = []
        unframed = []
        states = []

        async def set_state(state, extra=None):
            main.STATE = state
            states.append((state, extra))
            if state == "template_select":
                choose(main.app.state.on_template_choice)

        uploaded = asyncio.Event()

        async def enqueue(*_args, **_kwargs):
            uploaded.set()

        def compose_template(_dir, name, photos, _config, **_kwargs):
            composed.append((name, len(photos)))
            return Image.new("RGB", (120, 80), "white")

        def compose_plain(photo, _config):
            unframed.append(Path(photo).name)
            return Image.new("RGB", (120, 80), "red")

        recorder = Mock()
        recorder.stop_and_encode.return_value = "session.mp4"
        config = dict(main.CONFIG)
        config.update({
            "num_photos": 4,
            "pre_countdown_delay": 0,
            "countdown_seconds": 0,
            "countdown_sound_seconds": 0,
            "template_select_timeout": select_timeout,
            "done_screen_seconds": 0,
            "default_template": "grid",
            "template_pack": "kvas01aug26",
            "technical_event_name": "Кафе",
            "yadisk_folder": "Кафе",
            "print_enabled": True,
            "multi_print_enabled": multi_print,
            "multi_print_max_sheets": max_sheets,
        })

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.multiple(
                 main,
                 camera=self.Camera(),
                 video_recorder=recorder,
                 CONFIG=config,
                 PHOTOS_DIR=Path(tmpdir),
                 CLIENTS=[],
                 STATE="idle",
                 SESSION_ID="",
                 SESSION_PHOTOS=[],
                 SESSION_LINK="",
                 TEMPLATE_OPTIONS=[],
                 SESSION_COUNT=0,
                 _session_running=False,
                 _background_uploads=set(),
                 _camera_disconnected_event=asyncio.Event(),
             ), \
             patch("backend.main._start_locked", return_value=False), \
             patch("backend.main.yadisk_cloud.current_event_folder",
                   return_value="Кафе"), \
             patch("backend.main.yadisk_cloud.enqueue_session",
                   new_callable=AsyncMock, side_effect=enqueue), \
             patch("backend.main._prepare_session_link",
                   new_callable=AsyncMock), \
             patch("backend.main.generate_template_previews",
                   side_effect=self._previews), \
             patch("backend.main.compose", side_effect=compose_template), \
             patch("backend.main.compose_unframed_photo",
                   side_effect=compose_plain), \
             patch("backend.printer.enqueue_print",
                   new_callable=AsyncMock) as print_job, \
             patch("backend.main._consume_cafe_unlock_session") as consume, \
             patch("backend.main.broadcast", new_callable=AsyncMock), \
             patch("backend.main.set_state", side_effect=set_state):
            await main.run_session()
            await asyncio.wait_for(uploaded.wait(), timeout=2)
            if main._background_uploads:
                await asyncio.gather(*list(main._background_uploads))
            queued = [
                (Path(call.args[0]).name, call.args[2])
                for call in print_job.await_args_list
            ]

        return {
            "queued": queued,
            "composed": composed,
            "unframed": unframed,
            "states": states,
            "consumed": consume.call_count,
        }

    async def test_mixed_basket_prints_every_sheet_from_one_composition_each(self):
        def choose(select):
            select("", None, None, [
                {"template": "strips", "copies": 2},
                {"template": "grid", "copies": 2},
                {"template": "single", "photo_index": 1,
                 "with_frame": False, "copies": 1},
            ])

        result = await self._run(choose)

        # Six sheets: 2 strips (= 4 physical strips), 2 grid postcards, 1 photo.
        self.assertEqual(result["queued"], [
            ("print_strips.jpg", "strips"),
            ("print_strips.jpg", "strips"),
            ("print_grid.jpg", "grid"),
            ("print_grid.jpg", "grid"),
            ("print_single_photo_02_no_frame.jpg", "single"),
        ])
        # Each distinct layout is composed exactly once, copies reuse the JPEG.
        self.assertEqual(result["composed"], [("strips", 4), ("grid", 4)])
        self.assertEqual(result["unframed"], ["photo_2.jpg"])
        # One session, one allowance, regardless of the sheet count.
        self.assertEqual(result["consumed"], 1)
        done = [extra for state, extra in result["states"] if state == "done"]
        self.assertEqual(done, [{"print_sheets": 5}])

    async def test_basket_over_the_sheet_limit_is_refused_entirely(self):
        def choose(select):
            select("", None, None, [
                {"template": "grid", "copies": 4},
                {"template": "strips", "copies": 3},
            ])
            # The oversized basket was ignored, so the guest can still choose.
            select("strips")

        result = await self._run(choose, max_sheets=6)

        self.assertEqual(result["queued"], [("print_strips.jpg", "strips")])

    async def test_one_invalid_entry_rejects_the_whole_basket(self):
        def choose(select):
            select("", None, None, [
                {"template": "grid", "copies": 1},
                {"template": "single", "photo_index": 9, "with_frame": True},
            ])
            select("grid")

        result = await self._run(choose)

        # A partial print would charge the guest for sheets they never chose.
        self.assertEqual(result["queued"], [("print_grid.jpg", "grid")])

    async def test_basket_is_refused_outside_the_technical_event(self):
        def choose(select):
            select("", None, None, [{"template": "grid", "copies": 2}])
            select("grid")

        result = await self._run(choose, multi_print=False)

        self.assertEqual(result["queued"], [("print_grid.jpg", "grid")])

    async def test_single_tap_still_prints_exactly_one_sheet(self):
        def choose(select):
            select("strips")

        result = await self._run(choose)

        self.assertEqual(result["queued"], [("print_strips.jpg", "strips")])
        self.assertEqual(result["composed"], [("strips", 4)])
        self.assertEqual(result["consumed"], 1)
        done = [extra for state, extra in result["states"] if state == "done"]
        self.assertEqual(done, [{"print_sheets": 1}])

    async def test_duplicate_taps_in_a_basket_merge_into_copies(self):
        def choose(select):
            select("", None, None, [
                {"template": "grid", "copies": 1},
                {"template": "grid", "copies": 1},
                {"template": "grid", "copies": 1},
            ])

        result = await self._run(choose)

        self.assertEqual(result["queued"], [
            ("print_grid.jpg", "grid"),
            ("print_grid.jpg", "grid"),
            ("print_grid.jpg", "grid"),
        ])
        self.assertEqual(result["composed"], [("grid", 4)])

    async def test_timeout_prints_one_default_sheet_not_an_unsent_basket(self):
        """An abandoned screen must not spend a roll on an unconfirmed basket.

        The basket only ever reaches the booth when the guest presses the print
        button, so a walk-away falls back to the single default sheet exactly as
        it did before multi-select existed.
        """
        def choose(_select):
            pass

        result = await self._run(choose, select_timeout=0.1)

        self.assertEqual(result["queued"], [("print_grid.jpg", "grid")])
        done = [extra for state, extra in result["states"] if state == "done"]
        self.assertEqual(done, [{"print_sheets": 1}])


if __name__ == "__main__":
    unittest.main()
