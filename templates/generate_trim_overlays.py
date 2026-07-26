#!/usr/bin/env python3
"""Generate visual copies of template backgrounds with print trim in red."""

import json
from pathlib import Path

from PIL import Image, ImageDraw


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


def _background_paths(config_path: Path, config: dict) -> list[Path]:
    templates = config.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ValueError(f"{config_path}: templates must be a non-empty object")

    pack_dir = config_path.parent.resolve()
    backgrounds = set()
    for template_name, template in templates.items():
        layout = template.get("print_layout") if isinstance(template, dict) else None
        background = layout.get("background") if isinstance(layout, dict) else None
        if not isinstance(background, str) or not background:
            raise ValueError(
                f"{config_path}: template {template_name!r} has no background"
            )
        source_path = (pack_dir / background).resolve()
        if pack_dir not in source_path.parents:
            raise ValueError(
                f"{config_path}: background escapes template pack: {background}"
            )
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        backgrounds.add(source_path)
    return sorted(backgrounds)


def _write_overlay(
    source_path: Path,
    print_size: tuple[int, int],
    trim: tuple[int, int, int, int],
) -> Path:
    with Image.open(source_path) as source:
        background = source.convert("RGBA")
    if background.size != print_size:
        actual_size = background.size
        background.close()
        raise ValueError(
            f"{source_path}: expected {print_size}, got {actual_size}"
        )

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

    output_path = source_path.with_name(f"{source_path.stem}_trim.png")
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
        for source_path in _background_paths(config_path, config):
            output_path = _write_overlay(source_path, print_size, trim)
            generated += 1
            print(f"{config_path.parent.name}: {source_path.name} -> {output_path.name}")

    print(f"Generated {generated} trim overlay(s) at {TRIM_OPACITY:.0%} opacity")


if __name__ == "__main__":
    main()
