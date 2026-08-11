#!/usr/bin/env python3
"""Generate layout previews and oriented single-strip copies."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.text_layer import (  # noqa: E402  (path setup must run first)
    date_values,
    draw_text_blocks,
    validated_text_blocks,
)


TEMPLATES_DIR = Path(__file__).resolve().parent
PHOTO_SLOT_COLOR = (189, 189, 189)
PREVIEW_ROTATIONS = {
    "none": None,
    "cw": Image.Transpose.ROTATE_270,
    "ccw": Image.Transpose.ROTATE_90,
}


def _positive_size(raw, label: str) -> tuple[int, int]:
    if (not isinstance(raw, list) or len(raw) != 2
            or not all(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in raw
            )):
        raise ValueError(f"{label} must contain two positive integers")
    return raw[0], raw[1]


def _photo_size(raw, label: str) -> tuple[int, int]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    try:
        width = raw["width"]
        height = raw["height"]
    except KeyError as exc:
        raise ValueError(f"{label} needs width and height") from exc
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in (width, height)
    ):
        raise ValueError(f"{label} width and height must be positive integers")
    return width, height


def _layer_path(
    config_path: Path,
    raw_path: object,
    template_name: str,
    layer_name: str,
    required: bool,
) -> Path | None:
    if raw_path is None and not required:
        return None
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(
            f"{config_path}: template {template_name!r} has invalid {layer_name}"
        )
    pack_dir = config_path.parent.resolve()
    source_path = (pack_dir / raw_path).resolve()
    if pack_dir not in source_path.parents:
        raise ValueError(
            f"{config_path}: {layer_name} escapes template pack: {raw_path}"
        )
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    return source_path


def _slot_rectangles(
    config_path: Path,
    template_name: str,
    template: object,
    print_size: tuple[int, int],
) -> tuple[Path, Path | None, list[tuple[int, int, int, int]]]:
    if not isinstance(template, dict):
        raise ValueError(
            f"{config_path}: template {template_name!r} must be an object"
        )
    photo_width, photo_height = _photo_size(
        template.get("photo_size_px"),
        f"{config_path}: template {template_name!r}.photo_size_px",
    )
    layout = template.get("print_layout")
    if not isinstance(layout, dict):
        raise ValueError(
            f"{config_path}: template {template_name!r}.print_layout "
            "must be an object"
        )
    source_path = _layer_path(
        config_path,
        layout.get("background"),
        template_name,
        "background",
        required=True,
    )
    assert source_path is not None
    foreground_path = _layer_path(
        config_path,
        layout.get("foreground"),
        template_name,
        "foreground",
        required=False,
    )
    photos = layout.get("photos")
    if not isinstance(photos, list) or not photos:
        raise ValueError(
            f"{config_path}: template {template_name!r} has no photo slots"
        )

    print_width, print_height = print_size
    rectangles = []
    for slot_index, slot in enumerate(photos):
        if not isinstance(slot, dict):
            raise ValueError(
                f"{config_path}: invalid slot {slot_index} "
                f"in template {template_name!r}"
            )
        try:
            x = slot["x"]
            y = slot["y"]
        except KeyError as exc:
            raise ValueError(
                f"{config_path}: incomplete slot {slot_index} "
                f"in template {template_name!r}"
            ) from exc
        if not all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in (x, y)
        ):
            raise ValueError(
                f"{config_path}: slot {slot_index} in template "
                f"{template_name!r} has invalid coordinates"
            )
        if x + photo_width > print_width or y + photo_height > print_height:
            raise ValueError(
                f"{config_path}: slot {slot_index} in template "
                f"{template_name!r} exceeds print size {print_size}"
            )
        rectangles.append(
            (x, y, x + photo_width - 1, y + photo_height - 1)
        )
    return source_path, foreground_path, rectangles


def _write_preview(
    source_path: Path,
    foreground_path: Path | None,
    output_path: Path,
    print_size: tuple[int, int],
    rectangles: list[tuple[int, int, int, int]],
    template_name: str,
    text_blocks: list,
) -> None:
    with Image.open(source_path) as source:
        preview = source.convert("RGB")
    if preview.size != print_size:
        actual_size = preview.size
        preview.close()
        raise ValueError(
            f"{source_path}: expected background size {print_size}, got {actual_size}"
        )

    draw = ImageDraw.Draw(preview)
    for rectangle in rectangles:
        draw.rectangle(rectangle, fill=PHOTO_SLOT_COLOR)

    if foreground_path is not None:
        with Image.open(foreground_path) as source:
            if source.size != print_size:
                preview.close()
                raise ValueError(
                    f"{foreground_path}: expected foreground size "
                    f"{print_size}, got {source.size}"
                )
            if "A" not in source.getbands():
                preview.close()
                raise ValueError(
                    f"{foreground_path}: foreground must have an alpha channel"
                )
            foreground = source.convert("RGBA")
        try:
            preview.paste(foreground, (0, 0), foreground)
        finally:
            foreground.close()

    if text_blocks:
        # Same last layer as the print, so a layout check shows the caption
        # exactly where a guest will see it.
        draw_text_blocks(
            preview, text_blocks, date_values(datetime.now()), template_name)

    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        preview.save(temporary, "PNG", optimize=True)
        temporary.replace(output_path)
    finally:
        preview.close()
        temporary.unlink(missing_ok=True)


def _write_single_strip_preview(
    layout_preview_path: Path,
    output_path: Path,
    preview_rotation: object,
) -> None:
    if (not isinstance(preview_rotation, str)
            or preview_rotation not in PREVIEW_ROTATIONS):
        raise ValueError(
            f"{layout_preview_path}: unsupported preview_rotation "
            f"{preview_rotation!r}"
        )

    with Image.open(layout_preview_path) as preview:
        half_height = preview.height // 2
        if half_height < 1:
            raise ValueError(
                f"{layout_preview_path}: preview is too short to split"
            )
        strip = preview.crop((0, 0, preview.width, half_height))

    transpose = PREVIEW_ROTATIONS[preview_rotation]
    if transpose is not None:
        rotated = strip.transpose(transpose)
        strip.close()
        strip = rotated

    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        strip.save(temporary, "PNG", optimize=True)
        temporary.replace(output_path)
    finally:
        strip.close()
        temporary.unlink(missing_ok=True)


def _config_paths(pack_names: list[str]) -> list[Path]:
    if not pack_names:
        paths = sorted(TEMPLATES_DIR.rglob("config.json"))
        if not paths:
            raise RuntimeError(f"No template packs found under {TEMPLATES_DIR}")
        return paths

    paths = []
    for pack_name in pack_names:
        if (not pack_name or Path(pack_name).name != pack_name
                or pack_name in (".", "..")):
            raise ValueError(f"invalid template pack name: {pack_name!r}")
        config_path = TEMPLATES_DIR / pack_name / "config.json"
        if not config_path.is_file():
            raise FileNotFoundError(config_path)
        paths.append(config_path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate full-size template previews with configured photo slots "
            "filled in gray, plus single-strip views for split templates."
        )
    )
    parser.add_argument(
        "packs",
        nargs="*",
        help="template pack names; omit to process every pack",
    )
    args = parser.parse_args()

    generated = 0
    generated_single_strips = 0
    for config_path in _config_paths(args.packs):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        print_size = _positive_size(
            config.get("print_size"), f"{config_path}: print_size")
        templates = config.get("templates")
        if not isinstance(templates, dict) or not templates:
            raise ValueError(
                f"{config_path}: templates must be a non-empty object"
            )

        for template_name, template in templates.items():
            if (not isinstance(template_name, str) or not template_name
                    or Path(template_name).name != template_name):
                raise ValueError(
                    f"{config_path}: invalid template name {template_name!r}"
                )
            source_path, foreground_path, rectangles = _slot_rectangles(
                config_path, template_name, template, print_size)
            text_blocks = validated_text_blocks(
                template["print_layout"], template_name, print_size)
            output_path = source_path.with_name(
                f"{template_name}_layout_preview.png")
            _write_preview(
                source_path,
                foreground_path,
                output_path,
                print_size,
                rectangles,
                template_name,
                text_blocks,
            )
            generated += 1
            print(
                f"{config_path.parent.name}:{template_name}: "
                f"{source_path.name} -> {output_path.name} "
                f"({len(rectangles)} slot(s))"
            )

            preview_split = template.get("preview_split")
            if preview_split == "horizontal":
                single_strip_path = source_path.with_name(
                    f"{template_name}_single_strip_layout_preview.png")
                _write_single_strip_preview(
                    output_path,
                    single_strip_path,
                    template.get("preview_rotation"),
                )
                generated_single_strips += 1
                print(
                    f"{config_path.parent.name}:{template_name}: "
                    f"{output_path.name} -> {single_strip_path.name} "
                    f"(first half, rotation={template.get('preview_rotation')})"
                )

    print(
        f"Generated {generated} layout preview(s) and "
        f"{generated_single_strips} single-strip preview(s) with "
        f"slot color #{PHOTO_SLOT_COLOR[0]:02x}{PHOTO_SLOT_COLOR[1]:02x}"
        f"{PHOTO_SLOT_COLOR[2]:02x}"
    )


if __name__ == "__main__":
    main()
