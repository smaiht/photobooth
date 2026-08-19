#!/usr/bin/env python3
"""Scale one source image to grid_bg.png at the full print size."""

import argparse
from pathlib import Path

from PIL import Image


PRINT_SIZE = (3688, 2480)
OUTPUT_NAME = "grid_bg.png"


def build_background(source_path: Path, output_path: Path) -> None:
    source_path = source_path.resolve()
    output_path = output_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path == output_path:
        raise ValueError(f"source must not be {OUTPUT_NAME}")

    with Image.open(source_path) as source:
        result = source.convert("RGB").resize(PRINT_SIZE, Image.Resampling.LANCZOS)

    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        result.save(temporary, "PNG", optimize=True)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
        result.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scale an image to 3688x2480 and save it as grid_bg.png "
            "beside the source."
        )
    )
    parser.add_argument("source", type=Path, help="path to the source image")
    args = parser.parse_args()

    source_path = args.source.resolve()
    output_path = source_path.parent / OUTPUT_NAME
    build_background(source_path, output_path)
    print(f"{source_path} -> {output_path} ({PRINT_SIZE[0]}x{PRINT_SIZE[1]})")


if __name__ == "__main__":
    main()
