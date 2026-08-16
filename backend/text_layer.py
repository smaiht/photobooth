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
    stroke_width: int
    stroke_color: str


class TextBlock(NamedTuple):
    x: int
    y: int
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
    position = raw.get("position")
    if not isinstance(position, dict):
        raise ValueError(f"{context} needs a position object")
    try:
        x, y = (position[name] for name in ("x", "y"))
    except KeyError as exc:
        raise ValueError(f"{context} position needs x and y") from exc
    if not all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (x, y)
    ):
        raise ValueError(f"{context} position values must be integers")
    if not 0 <= x <= print_size[0] or not 0 <= y <= print_size[1]:
        raise ValueError(
            f"{context} position must be inside the print size {print_size}"
        )

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
    block_stroke_width = raw.get("stroke_width", 0)
    block_stroke_color = raw.get("stroke_color")

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
        stroke_width = raw_line.get("stroke_width", block_stroke_width)
        if (not isinstance(stroke_width, int) or isinstance(stroke_width, bool)
                or stroke_width < 0):
            raise ValueError(
                f"{line_context} stroke_width must be a non-negative integer"
            )
        stroke_color = raw_line.get("stroke_color", block_stroke_color)
        if stroke_color is None:
            stroke_color = color
        if not isinstance(stroke_color, str) or not stroke_color:
            raise ValueError(f"{line_context} stroke_color must be a string")
        lines.append(TextLine(
            text, font, size, weight, color, stroke_width, stroke_color,
        ))

    return TextBlock(x, y, rotation, float(line_spacing), lines)


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
    if not 0 <= x <= canvas.width or not 0 <= y <= canvas.height:
        raise ValueError("position does not fit the canvas")

    prepared = []
    for line in block.lines:
        text = _resolve_text(line.text, values)
        font = _load_font(line.font, max(1, round(line.size * scale)), line.weight)
        color = _parse_color(line.color)
        stroke_width = (
            max(1, round(line.stroke_width * scale))
            if line.stroke_width else 0
        )
        stroke_color = _parse_color(line.stroke_color)
        ascent, descent = font.getmetrics()
        line_height = ascent + descent + stroke_width * 2
        prepared.append((
            text, font, color, stroke_width, stroke_color, line_height,
        ))

    total_height = sum(
        round(line_height * block.line_spacing) for *_, line_height in prepared
    )
    cursor = -total_height // 2
    positioned = []
    bounds = []
    for text, font, color, stroke_width, stroke_color, line_height in prepared:
        slot_height = round(line_height * block.line_spacing)
        offset = (slot_height - line_height) // 2
        anchor_y = cursor + offset + stroke_width
        if text:
            bbox = font.getbbox(
                text,
                anchor="ma",
                stroke_width=stroke_width,
            )
            positioned.append((
                text, font, color, stroke_width, stroke_color, anchor_y,
            ))
            bounds.append((
                bbox[0],
                anchor_y + bbox[1],
                bbox[2],
                anchor_y + bbox[3],
            ))
        cursor += slot_height

    if not positioned:
        return

    left = min(bbox[0] for bbox in bounds)
    top = min(bbox[1] for bbox in bounds)
    right = max(bbox[2] for bbox in bounds)
    bottom = max(bbox[3] for bbox in bounds)
    half_width = max(1, -left, right) + 1
    half_height = max(1, -top, bottom) + 1

    layer = Image.new(
        "RGBA",
        (half_width * 2, half_height * 2),
        (0, 0, 0, 0),
    )
    try:
        draw = ImageDraw.Draw(layer)

        # Paint every outline first, so a later line's thick stroke can never
        # cover the face of an earlier line.
        for text, font, _, stroke_width, stroke_color, anchor_y in positioned:
            if stroke_width:
                draw.text(
                    (half_width, half_height + anchor_y),
                    text,
                    font=font,
                    fill=stroke_color,
                    anchor="ma",
                    stroke_width=stroke_width,
                    stroke_fill=stroke_color,
                )

        for text, font, color, _, _, anchor_y in positioned:
            draw.text(
                (half_width, half_height + anchor_y),
                text,
                font=font,
                fill=color,
                anchor="ma",
            )

        transpose = ROTATION_TRANSPOSE[block.rotation]
        if transpose is not None:
            rotated = layer.transpose(transpose)
            layer.close()
            layer = rotated
        canvas.paste(
            layer,
            (x - layer.width // 2, y - layer.height // 2),
            layer,
        )
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
