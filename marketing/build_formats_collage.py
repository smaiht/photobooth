#!/usr/bin/env python3
"""Build "three print formats" collages on a neutral studio background.

Every print keeps its real proportions and its real relative size: the postcard
and the strip both come from the same 4x6 sheet, so a strip is exactly as long as
the postcard is wide. Nothing is cropped or stretched.

Three arrangements are produced on every run — mosaic, row and column — so the
one that fits a given post can simply be picked:

    venv/bin/python marketing/build_formats_collage.py \
        --session <name> --pack <name> [--single 3] [--variant frame|plain]

``--single`` picks which captured frame is shown as the one-photo sheet, and
``--variant`` switches between the framed and full-bleed version of it. Output
files carry the pack name, so several events can live in one folder.

Everything is rendered at double size and downscaled once at the end, which is
what keeps the rotated edges and the captions smooth.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = PROJECT_ROOT / "marketing" / "samples"
FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "Comfortaa-VariableFont_wght.ttf"
DEFAULT_SESSION = "2026-08-08_16-06-26_b9e1d30665888c9ed50d7"
DEFAULT_PACK = "park08082026"
DEFAULT_SINGLE = 3          # which captured frame the "one photo" sheet shows
DEFAULT_VARIANT = "frame"   # frame = template border, plain = full-bleed photo
LAYOUTS = ("mosaic", "row", "column")

# Working resolution. The finished collage is downscaled to FINAL_LONG_EDGE, so
# rotation and text are supersampled rather than aliased.
PRINT_WIDTH = 2200          # postcard width while compositing
FINAL_LONG_EDGE = 2400
JPEG_QUALITY = 92

MARGIN = 210
GAP = 150                   # between neighbouring blocks

# Warm neutral grey, like a photo-studio surface: dark enough to separate the
# beige templates, far from the flat near-black that reads as a mistake.
BACKGROUND_TOP = (88, 86, 82)
BACKGROUND_BOTTOM = (54, 53, 50)
VIGNETTE_ALPHA = 95
SHADOW_BLUR = 60
SHADOW_OFFSET = (24, 44)
SHADOW_ALPHA = 190

CAPTION_RATIO = 0.042       # of PRINT_WIDTH
CAPTION_GAP = 78            # between a print edge and its caption
CAPTION_COLOR = (240, 238, 234)
CAPTIONS = {
    "postcard": "ОТКРЫТКА",
    "single": "ОДНО ФОТО",
    "strips": "ДВЕ ПОЛОСКИ",
}

# Small tilts only: enough to feel like loose prints, not a scrapbook.
POSTCARD_ANGLE = 2.0
SINGLE_ANGLE = -1.6
STRIP_BACK_ANGLE = 9.0
STRIP_FRONT_ANGLE = -3.5
STRIP_OVERLAP = 0.26        # how much of the back strip the front one covers


def _load(path: Path) -> Image.Image:
    if not path.is_file():
        raise SystemExit(f"missing image: {path}")
    with Image.open(path) as raw:
        return raw.convert("RGBA")


def _resized(image: Image.Image, width: int | None = None,
             height: int | None = None) -> Image.Image:
    if width is None:
        width = max(1, round(image.width * height / image.height))
    if height is None:
        height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _rotated(image: Image.Image, angle: float) -> Image.Image:
    """Rotate with a transparent margin so the edge stays antialiased."""
    padding = 4
    padded = Image.new(
        "RGBA",
        (image.width + padding * 2, image.height + padding * 2),
        (0, 0, 0, 0),
    )
    padded.paste(image, (padding, padding))
    rotated = padded.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=True
    )
    padded.close()
    return rotated


def _with_shadow(prints: list[tuple[Image.Image, tuple[int, int]]],
                 size: tuple[int, int]) -> Image.Image:
    """Composite already-rotated prints onto one layer, each with a drop shadow.

    Shadows are drawn per print in stacking order, so an overlapping print casts
    its shadow onto the one below it.
    """
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    for image, position in prints:
        shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow.putalpha(
            image.getchannel("A").point(lambda a: round(a * SHADOW_ALPHA / 255))
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
        layer.alpha_composite(
            shadow,
            (position[0] + SHADOW_OFFSET[0], position[1] + SHADOW_OFFSET[1]),
        )
        layer.alpha_composite(image, position)
        shadow.close()
    return layer


def _block(prints: list[tuple[Image.Image, tuple[int, int]]]) -> Image.Image:
    """Lay prints out on a generous canvas, then trim to what was drawn."""
    width = max(x + image.width for image, (x, _) in prints)
    height = max(y + image.height for image, (_, y) in prints)
    slack = SHADOW_BLUR * 3
    layer = _with_shadow(
        [(image, (x + slack, y + slack)) for image, (x, y) in prints],
        (width + slack * 2, height + slack * 2),
    )
    bounds = layer.getbbox()
    trimmed = layer.crop(bounds) if bounds else layer.copy()
    layer.close()
    return trimmed


def _font() -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_PATH), round(PRINT_WIDTH * CAPTION_RATIO))
    try:
        font.set_variation_by_name("Bold")
    except (OSError, ValueError):
        pass  # Static build of the font: the default weight is fine.
    return font


def _labeled(block: Image.Image, caption: str,
             font: ImageFont.FreeTypeFont) -> Image.Image:
    """Put a caption under one block and return them as a single image."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), caption, font=font)
    text_size = (right - left, bottom - top)
    width = max(block.width, text_size[0])
    height = block.height + CAPTION_GAP + text_size[1]
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(block, ((width - block.width) // 2, 0))
    ImageDraw.Draw(canvas).text(
        (width // 2, block.height + CAPTION_GAP - top),
        caption, font=font, fill=CAPTION_COLOR, anchor="ma",
    )
    return canvas


def _blocks(paper: Path, single_name: str,
            font: ImageFont.FreeTypeFont) -> dict[str, Image.Image]:
    """Render the three format blocks at a single shared physical scale."""
    postcard = _resized(_load(paper / "grid.jpg"), width=PRINT_WIDTH)
    single = _resized(_load(paper / single_name), width=PRINT_WIDTH)
    # A strip and the postcard share the same 4x6 sheet, so the strip's long edge
    # equals the postcard's width. Scaling by height keeps that relationship.
    strip = _resized(_load(paper / "strips_cut_01.jpg"), height=PRINT_WIDTH)

    rotated_postcard = _rotated(postcard, POSTCARD_ANGLE)
    rotated_single = _rotated(single, SINGLE_ANGLE)
    strip_back = _rotated(strip, STRIP_BACK_ANGLE)
    strip_front = _rotated(strip, STRIP_FRONT_ANGLE)
    fan_step = round(strip.width * (1 - STRIP_OVERLAP))

    blocks = {
        "postcard": _labeled(
            _block([(rotated_postcard, (0, 0))]), CAPTIONS["postcard"], font),
        "single": _labeled(
            _block([(rotated_single, (0, 0))]), CAPTIONS["single"], font),
        "strips": _labeled(
            _block([
                (strip_back, (0, 0)),
                (strip_front, (fan_step, 0)),
            ]),
            CAPTIONS["strips"], font,
        ),
    }
    for image in (postcard, single, strip, rotated_postcard, rotated_single,
                  strip_back, strip_front):
        image.close()
    return blocks


def _background(size: tuple[int, int]) -> Image.Image:
    """Vertical gradient plus a gentle vignette."""
    width, height = size
    background = Image.new("RGB", size, BACKGROUND_TOP)
    draw = ImageDraw.Draw(background)
    for row in range(height):
        blend = row / max(1, height - 1)
        draw.line(
            [(0, row), (width, row)],
            fill=tuple(
                round(top + (bottom - top) * blend)
                for top, bottom in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM)
            ),
        )
    vignette = Image.new("L", (width, height), 0)
    ImageDraw.Draw(vignette).ellipse(
        (-width * 0.28, -height * 0.28, width * 1.28, height * 1.28), fill=255
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(min(width, height) * 0.12))
    mask = vignette.point(lambda value: round((255 - value) * VIGNETTE_ALPHA / 255))
    background.paste(Image.new("RGB", (width, height), (0, 0, 0)), (0, 0), mask)
    vignette.close()
    mask.close()
    return background


def _compose(placed: list[tuple[Image.Image, tuple[int, int]]]) -> Image.Image:
    """Draw placed blocks over the background and scale down to final size."""
    width = max(x + block.width for block, (x, _) in placed) + MARGIN * 2
    height = max(y + block.height for block, (_, y) in placed) + MARGIN * 2
    canvas = _background((width, height))
    for block, (x, y) in placed:
        canvas.paste(block, (x + MARGIN, y + MARGIN), block)
    scale = FINAL_LONG_EDGE / max(canvas.size)
    if scale < 1:
        final = canvas.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.LANCZOS,
        )
        canvas.close()
        return final
    return canvas


def _layout(blocks: dict[str, Image.Image], name: str) -> Image.Image:
    postcard, single, strips = blocks["postcard"], blocks["single"], blocks["strips"]
    if name == "row":
        # Bottom-aligned, as if the prints were laid out on a table edge.
        height = max(block.height for block in (postcard, single, strips))
        x = 0
        placed = []
        for block in (postcard, single, strips):
            placed.append((block, (x, height - block.height)))
            x += block.width + GAP
        return _compose(placed)
    if name == "column":
        width = max(block.width for block in (postcard, single, strips))
        y = 0
        placed = []
        for block in (postcard, single, strips):
            placed.append((block, ((width - block.width) // 2, y)))
            y += block.height + GAP
        return _compose(placed)
    # mosaic: postcard over single on the left, strips beside them
    left_width = max(postcard.width, single.width)
    left_height = postcard.height + GAP + single.height
    return _compose([
        (postcard, ((left_width - postcard.width) // 2, 0)),
        (single, ((left_width - single.width) // 2, postcard.height + GAP)),
        (strips, (left_width + GAP, max(0, (left_height - strips.height) // 2))),
    ])


def build(session: str, pack: str, single: int, variant: str,
          out_dir: Path) -> None:
    paper = SAMPLES / session / pack / "paper"
    single_name = f"single_{single:02d}_{variant}.jpg"
    font = _font()
    blocks = _blocks(paper, single_name, font)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in LAYOUTS:
        collage = _layout(blocks, name)
        path = out_dir / f"formats_{pack}_{name}.jpg"
        collage.save(path, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True)
        print(f"{path.relative_to(PROJECT_ROOT)}  {collage.size[0]}x{collage.size[1]}")
        collage.close()
    for block in blocks.values():
        block.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--pack", default=DEFAULT_PACK)
    parser.add_argument(
        "--single", type=int, default=DEFAULT_SINGLE,
        help="captured frame shown as the one-photo sheet (1..4)",
    )
    parser.add_argument(
        "--variant", choices=("frame", "plain"), default=DEFAULT_VARIANT,
        help="frame keeps the template border, plain fills the whole sheet",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "marketing" / "collages",
    )
    args = parser.parse_args()
    build(
        args.session, args.pack, args.single, args.variant, args.out.resolve()
    )


if __name__ == "__main__":
    main()
