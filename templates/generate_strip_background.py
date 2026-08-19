#!/usr/bin/env python3
"""Build strip_bg.png from one vertical source and its mirrored copy."""

import argparse
from pathlib import Path

from PIL import Image, ImageOps


STRIP_SIZE = (1240, 3688)
SHEET_SIZE = (2480, 3688)
PRINT_SIZE = (3688, 2480)
OUTPUT_NAME = "strip_bg.png"


def build_background(source_path: Path, output_path: Path) -> None:
    source_path = source_path.resolve()
    output_path = output_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path == output_path:
        raise ValueError(f"source must not be {OUTPUT_NAME}")

    with Image.open(source_path) as source:
        strip = source.convert("RGB").resize(STRIP_SIZE, Image.Resampling.LANCZOS)

    mirrored = ImageOps.mirror(strip)
    sheet = Image.new("RGB", SHEET_SIZE)
    sheet.paste(strip, (0, 0))
    sheet.paste(mirrored, (STRIP_SIZE[0], 0))
    result = sheet.transpose(Image.Transpose.ROTATE_90)

    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        result.save(temporary, "PNG", optimize=True)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
        strip.close()
        mirrored.close()
        sheet.close()
        result.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scale a vertical image, place its mirrored copy on the right, "
            "then rotate the pair 90 degrees counter-clockwise."
        )
    )
    parser.add_argument("source", type=Path, help="path to the vertical source image")
    args = parser.parse_args()

    source_path = args.source.resolve()
    output_path = source_path.parent / OUTPUT_NAME
    build_background(source_path, output_path)
    print(f"{source_path} -> {output_path} ({PRINT_SIZE[0]}x{PRINT_SIZE[1]})")


if __name__ == "__main__":
    main()
