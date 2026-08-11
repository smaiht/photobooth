#!/usr/bin/env python3
"""Generate visual copies of template backgrounds with print trim in red."""

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
TRIM_OPACITY = 0.75
TRIM_COLOR = (255, 0, 0, round(255 * TRIM_OPACITY))


def _positive_size(raw, label: str) -> tuple[int, int]:
    if (not isinstance(raw, list) or len(raw) != 2
            or not all(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in raw
            )):
        raise ValueError(f"{label} must contain two positive integers")
    return raw[0], raw[1]


def _trim_values(raw, print_size: tuple[int, int], label: str) -> tuple[int, int, int, int]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    try:
        values = tuple(raw[name] for name in ("left", "top", "right", "bottom"))
    except KeyError as exc:
        raise ValueError(
            f"{label} needs left, top, right and bottom"
        ) from exc
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in values
    ):
        raise ValueError(f"{label} values must be non-negative integers")
    left, top, right, bottom = values
    if left + right >= print_size[0] or top + bottom >= print_size[1]:
        raise ValueError(f"{label} leaves no visible print area")
    visible_size = _positive_size(raw.get("visible_size"), f"{label}.visible_size")
    expected_size = (
        print_size[0] - left - right,
        print_size[1] - top - bottom,
    )
    if visible_size != expected_size:
        raise ValueError(
            f"{label}.visible_size must be {expected_size}, got {visible_size}"
        )
    return left, top, right, bottom


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


def _template_layers(
    config_path: Path,
    config: dict,
    print_size: tuple[int, int],
) -> list[tuple[Path, Path | None, str, list]]:
    templates = config.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ValueError(f"{config_path}: templates must be a non-empty object")

    layers = []
    seen = set()
    for template_name, template in templates.items():
        layout = template.get("print_layout") if isinstance(template, dict) else None
        if not isinstance(layout, dict):
            raise ValueError(
                f"{config_path}: template {template_name!r} has no print_layout"
            )
        background_path = _layer_path(
            config_path,
            layout.get("background"),
            template_name,
            "background",
            required=True,
        )
        assert background_path is not None
        foreground_path = _layer_path(
            config_path,
            layout.get("foreground"),
            template_name,
            "foreground",
            required=False,
        )
        text_blocks = validated_text_blocks(layout, template_name, print_size)
        # Text is part of the identity here: two templates may share one
        # background yet carry different captions, and each needs its own file.
        key = (
            background_path,
            foreground_path,
            json.dumps(layout.get("texts"), sort_keys=True, ensure_ascii=False),
        )
        if key not in seen:
            seen.add(key)
            layers.append(
                (background_path, foreground_path, template_name, text_blocks))
    return layers


def _write_overlay(
    source_path: Path,
    foreground_path: Path | None,
    print_size: tuple[int, int],
    trim: tuple[int, int, int, int],
    template_name: str,
    text_blocks: list,
) -> Path:
    with Image.open(source_path) as source:
        background = source.convert("RGBA")
    if background.size != print_size:
        actual_size = background.size
        background.close()
        raise ValueError(
            f"{source_path}: expected {print_size}, got {actual_size}"
        )

    if foreground_path is not None:
        with Image.open(foreground_path) as source:
            if source.size != print_size:
                background.close()
                raise ValueError(
                    f"{foreground_path}: expected {print_size}, got {source.size}"
                )
            if "A" not in source.getbands():
                background.close()
                raise ValueError(
                    f"{foreground_path}: foreground must have an alpha channel"
                )
            foreground = source.convert("RGBA")
        try:
            composed = Image.alpha_composite(background, foreground)
        finally:
            foreground.close()
            background.close()
        background = composed

    if text_blocks:
        # Drawn before the trim marks so the overlay shows whether a caption
        # survives the physical cut.
        draw_text_blocks(
            background, text_blocks, date_values(datetime.now()), template_name)

    width, height = print_size
    left, top, right, bottom = trim
    overlay = Image.new("RGBA", print_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if left:
        draw.rectangle((0, 0, left - 1, height - 1), fill=TRIM_COLOR)
    if top:
        draw.rectangle((0, 0, width - 1, top - 1), fill=TRIM_COLOR)
    if right:
        draw.rectangle((width - right, 0, width - 1, height - 1), fill=TRIM_COLOR)
    if bottom:
        draw.rectangle((0, height - bottom, width - 1, height - 1), fill=TRIM_COLOR)

    try:
        result = Image.alpha_composite(background, overlay).convert("RGB")
    finally:
        overlay.close()
        background.close()

    # Without text one file per background is unambiguous, and the existing
    # names stay put. With text two templates may share a background and need
    # distinct files.
    suffix = f"_{template_name}_trim" if text_blocks else "_trim"
    output_path = source_path.with_name(f"{source_path.stem}{suffix}.png")
    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        result.save(temporary, "PNG", optimize=True)
        temporary.replace(output_path)
    finally:
        result.close()
        temporary.unlink(missing_ok=True)
    return output_path


def main() -> None:
    config_paths = sorted(TEMPLATES_DIR.rglob("config.json"))
    if not config_paths:
        raise RuntimeError(f"No template packs found under {TEMPLATES_DIR}")

    generated = 0
    for config_path in config_paths:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        print_size = _positive_size(config.get("print_size"), f"{config_path}: print_size")
        trim = _trim_values(
            config.get("print_trim"),
            print_size,
            f"{config_path}: print_trim",
        )
        for source_path, foreground_path, template_name, text_blocks in \
                _template_layers(config_path, config, print_size):
            output_path = _write_overlay(
                source_path,
                foreground_path,
                print_size,
                trim,
                template_name,
                text_blocks,
            )
            generated += 1
            print(f"{config_path.parent.name}: {source_path.name} -> {output_path.name}")

    print(f"Generated {generated} trim overlay(s) at {TRIM_OPACITY:.0%} opacity")


if __name__ == "__main__":
    main()
