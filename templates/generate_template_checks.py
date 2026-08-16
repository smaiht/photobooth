#!/usr/bin/env python3
"""Generate manual layout checks first, then print-trim checks."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.text_layer import (  # noqa: E402  (path setup must run first)
    ROTATION_TRANSPOSE,
    date_values,
    draw_text_blocks,
    validated_text_blocks,
)


TEMPLATES_DIR = Path(__file__).resolve().parent
CHECKS_DIR_NAME = "checks"
PHOTO_SLOT_COLOR = (189, 189, 189)
TRIM_OPACITY = 0.75
TRIM_COLOR = (255, 0, 0, round(255 * TRIM_OPACITY))


def _config_paths(pack_names: list[str]) -> list[Path]:
    if not pack_names:
        paths = sorted(TEMPLATES_DIR.glob("*/config.json"))
        if not paths:
            raise RuntimeError(f"No template packs found under {TEMPLATES_DIR}")
        return paths

    paths = []
    for pack_name in pack_names:
        if Path(pack_name).name != pack_name or pack_name in ("", ".", ".."):
            raise ValueError(f"invalid template pack name: {pack_name!r}")
        config_path = TEMPLATES_DIR / pack_name / "config.json"
        if not config_path.is_file():
            raise FileNotFoundError(config_path)
        paths.append(config_path)
    return paths


def _print_size(config: dict, config_path: Path) -> tuple[int, int]:
    raw = config.get("print_size")
    if (not isinstance(raw, list) or len(raw) != 2
            or not all(isinstance(value, int) and value > 0 for value in raw)):
        raise ValueError(f"{config_path}: print_size must be two positive integers")
    return raw[0], raw[1]


def _trim(config: dict, config_path: Path, size: tuple[int, int]):
    raw = config.get("print_trim")
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path}: print_trim must be an object")
    try:
        trim = tuple(raw[name] for name in ("left", "top", "right", "bottom"))
    except KeyError as exc:
        raise ValueError(
            f"{config_path}: print_trim needs left, top, right and bottom"
        ) from exc
    if not all(isinstance(value, int) and value >= 0 for value in trim):
        raise ValueError(f"{config_path}: print_trim values must be non-negative")
    expected_visible = (size[0] - trim[0] - trim[2], size[1] - trim[1] - trim[3])
    if list(expected_visible) != raw.get("visible_size"):
        raise ValueError(
            f"{config_path}: print_trim.visible_size must be {expected_visible}"
        )
    return trim


def _asset_path(pack_dir: Path, raw_path: object, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"{label} must be a file name")
    path = (pack_dir / raw_path).resolve()
    if pack_dir.resolve() not in path.parents:
        raise ValueError(f"{label} escapes template pack: {raw_path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _template_items(config_path: Path, config: dict, size: tuple[int, int]):
    templates = config.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ValueError(f"{config_path}: templates must be a non-empty object")

    items = []
    for name, template in templates.items():
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError(f"{config_path}: invalid template name {name!r}")
        if not isinstance(template, dict):
            raise ValueError(f"{config_path}: template {name!r} must be an object")
        layout = template.get("print_layout")
        if not isinstance(layout, dict):
            raise ValueError(f"{config_path}: template {name!r} has no print_layout")
        background = _asset_path(
            config_path.parent, layout.get("background"), f"template {name!r} background"
        )
        foreground_name = layout.get("foreground")
        foreground = (
            _asset_path(
                config_path.parent,
                foreground_name,
                f"template {name!r} foreground",
            )
            if foreground_name is not None
            else None
        )
        texts = validated_text_blocks(layout, name, size)
        items.append((name, template, layout, background, foreground, texts))
    return items


def _load_image(
    path: Path,
    size: tuple[int, int],
    mode: str,
    require_alpha: bool = False,
) -> Image.Image:
    with Image.open(path) as source:
        if source.size != size:
            raise ValueError(f"{path}: expected {size}, got {source.size}")
        if require_alpha and "A" not in source.getbands():
            raise ValueError(f"{path}: foreground must have an alpha channel")
        return source.convert(mode)


def _add_foreground(
    canvas: Image.Image,
    foreground_path: Path | None,
    size: tuple[int, int],
) -> None:
    if foreground_path is None:
        return
    foreground = _load_image(foreground_path, size, "RGBA", require_alpha=True)
    try:
        if canvas.mode == "RGBA":
            canvas.alpha_composite(foreground)
        else:
            canvas.paste(foreground, (0, 0), foreground)
    finally:
        foreground.close()


def _save_png(image: Image.Image, output_path: Path) -> None:
    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        image.save(temporary, "PNG", optimize=True)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_layout(
    item,
    size: tuple[int, int],
    text_values: dict[str, str],
    output_path: Path,
) -> None:
    name, template, layout, background_path, foreground_path, texts = item
    photo_size = template.get("photo_size_px")
    if not isinstance(photo_size, dict):
        raise ValueError(f"template {name!r} has no photo_size_px")
    photo_width = photo_size.get("width")
    photo_height = photo_size.get("height")
    slots = layout.get("photos")
    if not isinstance(slots, list) or not slots:
        raise ValueError(f"template {name!r} has no photo slots")

    preview = _load_image(background_path, size, "RGB")
    try:
        draw = ImageDraw.Draw(preview)
        for index, slot in enumerate(slots):
            try:
                x, y = slot["x"], slot["y"]
                rectangle = (x, y, x + photo_width - 1, y + photo_height - 1)
            except (KeyError, TypeError) as exc:
                raise ValueError(f"template {name!r} has invalid slot {index}") from exc
            if rectangle[2] >= size[0] or rectangle[3] >= size[1]:
                raise ValueError(f"template {name!r} slot {index} exceeds print size")
            draw.rectangle(rectangle, fill=PHOTO_SLOT_COLOR)
        _add_foreground(preview, foreground_path, size)
        if texts:
            draw_text_blocks(preview, texts, text_values, name)
        _save_png(preview, output_path)
    finally:
        preview.close()


def _write_trim(
    layout_path: Path,
    size: tuple[int, int],
    trim,
    output_path: Path,
) -> None:
    background = _load_image(layout_path, size, "RGBA")
    try:
        width, height = size
        left, top, right, bottom = trim
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        try:
            draw = ImageDraw.Draw(overlay)
            if left:
                draw.rectangle((0, 0, left - 1, height - 1), fill=TRIM_COLOR)
            if top:
                draw.rectangle((0, 0, width - 1, top - 1), fill=TRIM_COLOR)
            if right:
                draw.rectangle((width - right, 0, width - 1, height - 1), fill=TRIM_COLOR)
            if bottom:
                draw.rectangle((0, height - bottom, width - 1, height - 1), fill=TRIM_COLOR)
            result = Image.alpha_composite(background, overlay).convert("RGB")
        finally:
            overlay.close()
        try:
            _save_png(result, output_path)
        finally:
            result.close()
    finally:
        background.close()


def _write_strips(
    sheet_path: Path,
    output_dir: Path,
    template_name: str,
    check_type: str,
    rotation: object,
) -> list[Path]:
    if rotation not in ROTATION_TRANSPOSE:
        raise ValueError(f"unsupported preview_rotation {rotation!r}")
    outputs = []
    with Image.open(sheet_path) as sheet:
        half = sheet.height // 2
        boxes = (
            ("1", (0, 0, sheet.width, half)),
            ("2", (0, sheet.height - half, sheet.width, sheet.height)),
        )
        for label, box in boxes:
            strip = sheet.crop(box)
            try:
                transpose = ROTATION_TRANSPOSE[rotation]
                if transpose is not None:
                    rotated = strip.transpose(transpose)
                    strip.close()
                    strip = rotated
                output_path = output_dir / f"{check_type}_{template_name}_{label}.png"
                _save_png(strip, output_path)
                outputs.append(output_path)
            finally:
                strip.close()
    return outputs


def _load_packs(pack_names: list[str]):
    packs = []
    for config_path in _config_paths(pack_names):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        size = _print_size(config, config_path)
        output_dir = config_path.parent / CHECKS_DIR_NAME
        output_dir.mkdir(exist_ok=True)
        packs.append((config_path, size, _trim(config, config_path, size),
                      _template_items(config_path, config, size), output_dir))
    return packs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate manual layout checks first, then print-trim checks in "
            "each template pack's checks directory."
        )
    )
    parser.add_argument(
        "packs", nargs="*", help="template pack names; omit to process every pack"
    )
    args = parser.parse_args()

    packs = _load_packs(args.packs)
    text_values = date_values(datetime.now())
    layout_count = trim_count = strip_count = 0

    for config_path, size, _trim_values, items, output_dir in packs:
        for item in items:
            name, template = item[:2]
            output_path = output_dir / f"layout_{name}_full.png"
            _write_layout(item, size, text_values, output_path)
            layout_count += 1
            print(f"[layout] {config_path.parent.name}:{name} -> checks/{output_path.name}")
            if template.get("preview_split") == "horizontal":
                strips = _write_strips(
                    output_path,
                    output_dir,
                    name,
                    "layout",
                    template.get("preview_rotation"),
                )
                strip_count += len(strips)
                for strip in strips:
                    print(f"[layout] {config_path.parent.name}:{name} -> checks/{strip.name}")

    for config_path, size, trim, items, output_dir in packs:
        for item in items:
            name, template = item[:2]
            layout_path = output_dir / f"layout_{name}_full.png"
            output_path = output_dir / f"trim_{name}_full.png"
            _write_trim(layout_path, size, trim, output_path)
            trim_count += 1
            print(f"[trim]   {config_path.parent.name}:{name} -> checks/{output_path.name}")
            if template.get("preview_split") == "horizontal":
                strips = _write_strips(
                    output_path,
                    output_dir,
                    name,
                    "trim",
                    template.get("preview_rotation"),
                )
                strip_count += len(strips)
                for strip in strips:
                    print(f"[trim]   {config_path.parent.name}:{name} -> checks/{strip.name}")

    print(
        f"Generated {layout_count} layout check(s), {trim_count} trim check(s) "
        f"and {strip_count} oriented strip check(s) in checks/"
    )


if __name__ == "__main__":
    main()
