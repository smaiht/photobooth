"""Render configured text blocks onto print sheets and their previews.

A template's ``print_layout.texts`` describes text drawn as the last layer,
after ``background``, the photos and the optional ``foreground``. Nothing is
baked into the static image layers, so their reduced preview caches stay
untouched and a date never has to be redrawn by hand for a new event.

The same block is used for the full print raster and for the on-screen preview:
every coordinate and font size is multiplied by one scale factor, exactly like
the photo slots are.

Text is decoration, not the product the guest paid for. A missing font, an
unparsable colour or an unknown token is logged and that block is skipped, so a
sheet is still printed without its caption.
"""

from datetime import datetime
from pathlib import Path
import logging
from typing import NamedTuple

from PIL import Image, ImageDraw, ImageFont


ALIGN_OPTIONS = ("left", "center", "right")
VALIGN_OPTIONS = ("top", "middle", "bottom")
# One rotation vocabulary for photo slots, previews and text blocks. It lives
# here so this module needs no import from composer, which imports it.
ROTATION_TRANSPOSE = {
    "none": None,
    "cw": Image.Transpose.ROTATE_270,
    "ccw": Image.Transpose.ROTATE_90,
}
DEFAULT_LINE_SPACING = 1.2
DEFAULT_COLOR = "#000000"
MIN_FONT_SIZE = 4
MAX_FONT_SIZE = 2000
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Cyrillic month names: an embedded Windows Python runs under the "C" locale,
# where strftime("%B") returns English names. Nominative and genitive forms
# differ in Russian, and a date reads "8 августа 2026", not "8 август 2026".
MONTHS_RU_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
DATE_TOKENS = ("{dd}.{mm}.{yyyy}", "{dd} {month_ru} {yyyy}")

log = logging.getLogger(__name__)


class TextLine(NamedTuple):
    text: str
    font: str
    size: int
    weight: int | None
    color: str


class TextBlock(NamedTuple):
    x: int
    y: int
    width: int
    height: int
    align: str
    valign: str
    rotation: str
    line_spacing: float
    lines: list[TextLine]


def date_values(moment: datetime) -> dict[str, str]:
    """Values for every supported token of one session date."""
    return {
        "{dd}.{mm}.{yyyy}": f"{moment.day:02d}.{moment.month:02d}.{moment.year:04d}",
        "{dd} {month_ru} {yyyy}": (
            f"{moment.day} {MONTHS_RU_GENITIVE[moment.month - 1]} {moment.year}"
        ),
    }


def validated_text_blocks(
    layout: dict,
    template_name: str,
    print_size: tuple[int, int],
) -> list[TextBlock]:
    """Validate ``print_layout.texts``; an absent key means no text at all.

    Only a structural mistake in the pack raises. Everything that can fail at
    render time is handled there, so a live session never loses its print over
    a caption.
    """
    raw_blocks = layout.get("texts")
    if raw_blocks is None:
        return []
    if not isinstance(raw_blocks, list):
        raise ValueError(f"template {template_name!r} texts must be a list")

    blocks = []
    for index, raw in enumerate(raw_blocks):
        context = f"text block {index} of template {template_name!r}"
        if not isinstance(raw, dict):
            raise ValueError(f"invalid {context}")
        blocks.append(_validated_block(raw, context, print_size))
    return blocks


def _validated_block(
    raw: dict,
    context: str,
    print_size: tuple[int, int],
) -> TextBlock:
    box = raw.get("box")
    if not isinstance(box, dict):
        raise ValueError(f"{context} needs a box object")
    try:
        values = tuple(box[name] for name in ("x", "y", "width", "height"))
    except KeyError as exc:
        raise ValueError(f"{context} box needs x, y, width and height") from exc
    if not all(isinstance(value, int) and not isinstance(value, bool)
               for value in values):
        raise ValueError(f"{context} box values must be integers")
    x, y, width, height = values
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"{context} box must be positive and on the sheet")
    if x + width > print_size[0] or y + height > print_size[1]:
        raise ValueError(f"{context} box exceeds the print size {print_size}")

    align = raw.get("align", "center")
    if align not in ALIGN_OPTIONS:
        raise ValueError(f"{context} has unsupported align {align!r}")
    valign = raw.get("valign", "middle")
    if valign not in VALIGN_OPTIONS:
        raise ValueError(f"{context} has unsupported valign {valign!r}")
    rotation = raw.get("rotate", "none")
    if rotation not in ROTATION_TRANSPOSE:
        raise ValueError(f"{context} has unsupported rotate {rotation!r}")

    line_spacing = raw.get("line_spacing", DEFAULT_LINE_SPACING)
    if (isinstance(line_spacing, bool)
            or not isinstance(line_spacing, (int, float))
            or not 0.5 <= float(line_spacing) <= 4):
        raise ValueError(f"{context} line_spacing must be between 0.5 and 4")

    block_font = raw.get("font")
    block_size = raw.get("size")
    block_weight = raw.get("weight")
    block_color = raw.get("color", DEFAULT_COLOR)

    raw_lines = raw.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError(f"{context} needs a non-empty lines list")

    lines = []
    for line_index, raw_line in enumerate(raw_lines):
        line_context = f"line {line_index} of {context}"
        if not isinstance(raw_line, dict):
            raise ValueError(f"invalid {line_context}")
        text = raw_line.get("text")
        if not isinstance(text, str):
            raise ValueError(f"{line_context} text must be a string")
        # A block-level value is the default; a line overrides only what it
        # needs, so a pack cannot drift by repeating the font on every line.
        font = raw_line.get("font", block_font)
        if not isinstance(font, str) or not font or Path(font).name != font:
            raise ValueError(f"{line_context} needs a font file name")
        size = raw_line.get("size", block_size)
        if (not isinstance(size, int) or isinstance(size, bool)
                or not MIN_FONT_SIZE <= size <= MAX_FONT_SIZE):
            raise ValueError(
                f"{line_context} size must be an integer between "
                f"{MIN_FONT_SIZE} and {MAX_FONT_SIZE}"
            )
        weight = raw_line.get("weight", block_weight)
        if weight is not None and (
            not isinstance(weight, int) or isinstance(weight, bool)
        ):
            raise ValueError(f"{line_context} weight must be an integer")
        color = raw_line.get("color", block_color)
        if not isinstance(color, str) or not color:
            raise ValueError(f"{line_context} color must be a string")
        lines.append(TextLine(text, font, size, weight, color))

    return TextBlock(
        x, y, width, height,
        align, valign, rotation, float(line_spacing), lines,
    )


def draw_text_blocks(
    canvas: Image.Image,
    blocks: list[TextBlock],
    values: dict[str, str],
    template_name: str,
    scale: float = 1.0,
) -> None:
    """Draw every block onto ``canvas``; log and skip the ones that fail."""
    for index, block in enumerate(blocks):
        try:
            _draw_block(canvas, block, values, scale)
        except Exception as exc:
            # The sheet is worth more than its caption.
            log.error(
                "Text block %d of template %r was skipped: %s",
                index, template_name, exc,
            )


def _draw_block(
    canvas: Image.Image,
    block: TextBlock,
    values: dict[str, str],
    scale: float,
) -> None:
    x = round(block.x * scale)
    y = round(block.y * scale)
    width = max(1, round((block.x + block.width) * scale) - x)
    height = max(1, round((block.y + block.height) * scale) - y)
    if x < 0 or y < 0 or x + width > canvas.width or y + height > canvas.height:
        raise ValueError("box does not fit the canvas")

    # A rotated block is laid out in its own upright space, then turned as a
    # whole, so the box describes the area the text occupies on the sheet.
    transpose = ROTATION_TRANSPOSE[block.rotation]
    layout_size = (height, width) if transpose is not None else (width, height)

    prepared = []
    for line in block.lines:
        text = _resolve_text(line.text, values)
        font = _load_font(line.font, max(1, round(line.size * scale)), line.weight)
        color = _parse_color(line.color)
        ascent, descent = font.getmetrics()
        prepared.append((text, font, color, ascent + descent))

    total_height = sum(
        round(line_height * block.line_spacing) for *_, line_height in prepared
    )
    layer = Image.new("RGBA", layout_size, (0, 0, 0, 0))
    try:
        draw = ImageDraw.Draw(layer)
        if block.valign == "top":
            cursor = 0
        elif block.valign == "bottom":
            cursor = layout_size[1] - total_height
        else:
            cursor = (layout_size[1] - total_height) // 2

        for text, font, color, line_height in prepared:
            slot_height = round(line_height * block.line_spacing)
            if text:
                # anchor "ma" places the glyph by its ascender, so lines with
                # different sizes still sit on a common visual baseline.
                if block.align == "left":
                    anchor_x, anchor = 0, "la"
                elif block.align == "right":
                    anchor_x, anchor = layout_size[0], "ra"
                else:
                    anchor_x, anchor = layout_size[0] // 2, "ma"
                offset = (slot_height - line_height) // 2
                draw.text(
                    (anchor_x, cursor + offset),
                    text,
                    font=font,
                    fill=color,
                    anchor=anchor,
                )
            cursor += slot_height

        if transpose is not None:
            rotated = layer.transpose(transpose)
            layer.close()
            layer = rotated
        canvas.paste(layer, (x, y), layer)
    finally:
        layer.close()


def _resolve_text(text: str, values: dict[str, str]) -> str:
    """Substitute known tokens; an unknown placeholder is an error."""
    resolved = text
    for token, value in values.items():
        resolved = resolved.replace(token, value)
    if "{" in resolved or "}" in resolved:
        raise ValueError(
            f"unknown token in {text!r}; available: {', '.join(values)}"
        )
    return resolved


def _load_font(
    name: str,
    size: int,
    weight: int | None,
) -> ImageFont.FreeTypeFont:
    path = FONTS_DIR / name
    if not path.is_file():
        raise ValueError(f"font not found: {name}")
    font = ImageFont.truetype(str(path), size)
    if weight is None:
        return font
    try:
        axes = font.get_variation_axes()
    except OSError:
        # A static TTF has no variation axes; the configured weight is moot.
        log.info("Font %s is not variable; weight %d ignored", name, weight)
        return font
    for axis in axes:
        if axis.get("name") in (b"Weight", "Weight"):
            minimum = axis["minimum"]
            maximum = axis["maximum"]
            clamped = max(minimum, min(maximum, weight))
            if clamped != weight:
                log.error(
                    "Out-of-range weight=%d for %s; using %d (%d..%d)",
                    weight, name, clamped, minimum, maximum,
                )
            font.set_variation_by_axes([clamped])
            return font
    log.info("Font %s has no weight axis; weight %d ignored", name, weight)
    return font


def _parse_color(value: str) -> tuple[int, int, int, int]:
    text = value.strip()
    if not text.startswith("#"):
        raise ValueError(f"color must be #rrggbb or #rrggbbaa, got {value!r}")
    digits = text[1:]
    if len(digits) not in (6, 8):
        raise ValueError(f"color must be #rrggbb or #rrggbbaa, got {value!r}")
    try:
        numbers = [int(digits[i:i + 2], 16) for i in range(0, len(digits), 2)]
    except ValueError as exc:
        raise ValueError(f"invalid color {value!r}") from exc
    if len(numbers) == 3:
        numbers.append(255)
    return tuple(numbers)
