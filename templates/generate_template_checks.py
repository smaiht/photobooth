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
from backend.composer import _oriented_rgb, _render_photo  # noqa: E402
from generate_grid_background import build_background as build_grid_background
from generate_strip_background import build_background as build_strip_background


TEMPLATES_DIR = Path(__file__).resolve().parent
CHECKS_DIR_NAME = "checks"
PHOTO_SLOT_COLOR = (189, 189, 189)
TRIM_OPACITY = 0.75
TRIM_COLOR = (255, 0, 0, round(255 * TRIM_OPACITY))
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


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
    resize: bool = False,
) -> Image.Image:
    with Image.open(path) as source:
        if require_alpha and "A" not in source.getbands():
            raise ValueError(f"{path}: foreground must have an alpha channel")
        if source.size != size:
            if not resize:
                raise ValueError(f"{path}: expected {size}, got {source.size}")
            converted = source.convert(mode)
            try:
                return converted.resize(size, Image.Resampling.LANCZOS)
            finally:
                converted.close()
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
    *,
    background_path: Path | None = None,
    resize_background: bool = False,
    photo_paths: list[Path] | None = None,
) -> None:
    name, template, layout, configured_background, foreground_path, texts = item
    background_path = background_path or configured_background
    photo_size = template.get("photo_size_px")
    if not isinstance(photo_size, dict):
        raise ValueError(f"template {name!r} has no photo_size_px")
    photo_width = photo_size.get("width")
    photo_height = photo_size.get("height")
    slots = layout.get("photos")
    if not isinstance(slots, list) or not slots:
        raise ValueError(f"template {name!r} has no photo slots")

    preview = _load_image(background_path, size, "RGB", resize=resize_background)
    rendered = {}
    try:
        draw = ImageDraw.Draw(preview)
        for index, slot in enumerate(slots):
            try:
                x, y = slot["x"], slot["y"]
                width = slot.get("width", photo_width)
                height = slot.get("height", photo_height)
                rectangle = (x, y, x + width - 1, y + height - 1)
            except (KeyError, TypeError) as exc:
                raise ValueError(f"template {name!r} has invalid slot {index}") from exc
            if rectangle[2] >= size[0] or rectangle[3] >= size[1]:
                raise ValueError(f"template {name!r} slot {index} exceeds print size")
            if not photo_paths:
                draw.rectangle(rectangle, fill=PHOTO_SLOT_COLOR)
                continue

            try:
                photo_index = slot["photo_index"]
                rotation = slot["rotate"]
                photo_path = photo_paths[photo_index % len(photo_paths)]
            except (KeyError, TypeError) as exc:
                raise ValueError(f"template {name!r} has invalid slot {index}") from exc
            cache_key = (photo_path, rotation, width, height)
            prepared = rendered.get(cache_key)
            if prepared is None:
                with Image.open(photo_path) as source:
                    source_image = _oriented_rgb(source)
                try:
                    prepared = _render_photo(
                        source_image, rotation, width, height
                    )
                finally:
                    source_image.close()
                rendered[cache_key] = prepared
            photo, offset_x, offset_y = prepared
            preview.paste(photo, (x + offset_x, y + offset_y))
        _add_foreground(preview, foreground_path, size)
        if texts:
            draw_text_blocks(
                preview,
                texts,
                text_values,
                name,
                template_dir=configured_background.parent,
            )
        _save_png(preview, output_path)
    finally:
        for photo, _, _ in rendered.values():
            photo.close()
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


def _write_cut(trim_path: Path, trim, output_path: Path) -> None:
    with Image.open(trim_path) as trim_image:
        left, top, right, bottom = trim
        width, height = trim_image.size
        cut = trim_image.crop((left, top, width - right, height - bottom))
    try:
        _save_png(cut, output_path)
    finally:
        cut.close()


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


def _photos(directory: Path | None) -> list[Path] | None:
    if directory is None:
        return None
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    paths = sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in PHOTO_SUFFIXES
    )
    if not paths:
        raise ValueError(f"no photos found in {directory}")
    return paths


def _item(items, name: str, config_path: Path):
    try:
        return next(item for item in items if item[0] == name)
    except StopIteration as exc:
        raise ValueError(f"{config_path}: template {name!r} not found") from exc


def _custom_grid_checks(
    sources: list[Path],
    item,
    size: tuple[int, int],
    trim,
    checks_dir: Path,
    text_values: dict[str, str],
    photo_paths: list[Path] | None,
) -> int:
    for raw_path in sources:
        source_path = raw_path.expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        output_dir = checks_dir / source_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        background_path = output_dir / "grid_bg.png"
        layout_path = output_dir / "layout_grid_full.png"
        trim_path = output_dir / "trim_grid_full.png"
        cut_path = output_dir / "cut_grid_full.png"

        build_grid_background(source_path, background_path)
        _write_layout(
            item, size, text_values, layout_path,
            background_path=background_path, photo_paths=photo_paths,
        )
        _write_trim(layout_path, size, trim, trim_path)
        _write_cut(trim_path, trim, cut_path)
        print(f"{source_path} -> {output_dir / layout_path.name}")
        print(f"{source_path} -> {output_dir / trim_path.name}")
        print(f"{source_path} -> {output_dir / cut_path.name}")
    return len(sources)


def _custom_strip_checks(
    sources: list[Path],
    item,
    size: tuple[int, int],
    trim,
    checks_dir: Path,
    text_values: dict[str, str],
    photo_paths: list[Path] | None,
) -> int:
    _, template, _, _, _, _ = item
    for raw_path in sources:
        source_path = raw_path.expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        output_dir = checks_dir / source_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        background_path = output_dir / "strip_bg.png"
        layout_path = output_dir / "layout_strips_full.png"
        trim_path = output_dir / "trim_strips_full.png"
        cut_path = output_dir / "cut_strips_full.png"

        build_strip_background(source_path, background_path)
        _write_layout(
            item, size, text_values, layout_path,
            background_path=background_path, photo_paths=photo_paths,
        )
        _write_trim(layout_path, size, trim, trim_path)
        _write_cut(trim_path, trim, cut_path)
        layout_strips = _write_strips(
            layout_path, output_dir, "strips", "layout", template.get("preview_rotation")
        )
        trim_strips = _write_strips(
            trim_path, output_dir, "strips", "trim", template.get("preview_rotation")
        )
        cut_strips = _write_strips(
            cut_path, output_dir, "strips", "cut", template.get("preview_rotation")
        )
        for output_path in (
            layout_path, trim_path, cut_path, *layout_strips, *trim_strips, *cut_strips
        ):
            print(f"{source_path} -> {output_dir / output_path.name}")
    return len(sources)


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
    parser.add_argument(
        "--photos", type=Path, metavar="DIR", help="fill custom checks with photos"
    )
    parser.add_argument(
        "--grid", nargs="+", type=Path, metavar="PATH", help="grid background source(s)"
    )
    parser.add_argument(
        "--strip", nargs="+", type=Path, metavar="PATH", help="vertical strip source(s)"
    )
    args = parser.parse_args()

    packs = _load_packs(args.packs)
    if args.grid or args.strip:
        if len(packs) != 1:
            parser.error("--grid and --strip require exactly one pack")
        config_path, size, trim, items, checks_dir = packs[0]
        text_values = date_values(datetime.now())
        photo_paths = _photos(args.photos)
        grid_count = _custom_grid_checks(
            args.grid or [], _item(items, "grid", config_path), size, trim,
            checks_dir, text_values, photo_paths,
        ) if args.grid else 0
        strip_count = _custom_strip_checks(
            args.strip or [], _item(items, "strips", config_path), size, trim,
            checks_dir, text_values, photo_paths,
        ) if args.strip else 0
        print(f"Generated checks for {grid_count} grid and {strip_count} strip background(s)")
        return
    text_values = date_values(datetime.now())
    photo_paths = _photos(args.photos)
    layout_count = trim_count = cut_count = strip_count = 0

    for config_path, size, _trim_values, items, output_dir in packs:
        for item in items:
            name, template = item[:2]
            output_path = output_dir / f"layout_{name}_full.png"
            _write_layout(item, size, text_values, output_path, photo_paths=photo_paths)
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

            cut_path = output_dir / f"cut_{name}_full.png"
            _write_cut(output_path, trim, cut_path)
            cut_count += 1
            print(f"[cut]    {config_path.parent.name}:{name} -> checks/{cut_path.name}")
            if template.get("preview_split") == "horizontal":
                strips = _write_strips(
                    cut_path,
                    output_dir,
                    name,
                    "cut",
                    template.get("preview_rotation"),
                )
                strip_count += len(strips)
                for strip in strips:
                    print(f"[cut]    {config_path.parent.name}:{name} -> checks/{strip.name}")

    print(
        f"Generated {layout_count} layout check(s), {trim_count} trim check(s), "
        f"{cut_count} cut check(s) "
        f"and {strip_count} oriented strip check(s) in checks/"
    )


if __name__ == "__main__":
    main()
