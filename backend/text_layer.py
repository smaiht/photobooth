"""Render configured text objects onto print sheets and previews.

Each item in ``print_layout.texts`` is one text object. Its properties apply to
the complete string; explicit ``\n`` characters are the only line breaks.
Text is drawn last, over the background, photos and optional foreground.

Rendering errors are logged per object and never block the guest's print.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import math

from PIL import Image, ImageDraw, ImageFont


# Photo slots and previews still use this compact rotation vocabulary.
ROTATION_TRANSPOSE = {
    "none": None,
    "cw": Image.Transpose.ROTATE_270,
    "ccw": Image.Transpose.ROTATE_90,
}
DEFAULT_LINE_SPACING = 1.2
DEFAULT_COLOR = "#000000"
FABRIC_FONT_SIZE_MULTIPLIER = 1.13
MIN_FONT_SIZE = 4
MAX_FONT_SIZE = 2000
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Cyrillic month names cannot depend on the host's locale.
MONTHS_RU_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
DATE_TOKENS = ("{dd}.{mm}.{yyyy}", "{dd} {month_ru} {yyyy}")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextBlock:
    x: int
    y: int
    text: str
    align: str
    angle: float
    skew_x: float
    skew_y: float
    flip_x: bool
    flip_y: bool
    font: str
    size: int
    weight: int | None
    color: str
    stroke_width: float
    stroke_color: str
    line_spacing: float
    char_spacing: float
    underline: bool
    linethrough: bool


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
    """Validate ``print_layout.texts``; an absent key means no text."""
    raw_blocks = layout.get("texts")
    if raw_blocks is None:
        return []
    if not isinstance(raw_blocks, list):
        raise ValueError(f"template {template_name!r} texts must be a list")

    blocks = []
    for index, raw in enumerate(raw_blocks):
        context = f"text object {index} of template {template_name!r}"
        if not isinstance(raw, dict):
            raise ValueError(f"invalid {context}")
        blocks.append(_validated_block(raw, context, print_size))
    return blocks


def _validated_block(
    raw: dict,
    context: str,
    print_size: tuple[int, int],
) -> TextBlock:
    text = raw.get("text")
    if not isinstance(text, str):
        raise ValueError(f"{context} text must be a string")

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

    align = raw.get("align", "center")
    if align not in ("left", "center", "right"):
        raise ValueError(f"{context} align must be left, center or right")

    angle = _finite_number(raw.get("angle", 0), f"{context} angle")

    skew = raw.get("skew", {"x": 0, "y": 0})
    if not isinstance(skew, dict):
        raise ValueError(f"{context} skew must be an object")
    skew_x = _finite_number(skew.get("x", 0), f"{context} skew.x")
    skew_y = _finite_number(skew.get("y", 0), f"{context} skew.y")
    if not -89 <= skew_x <= 89 or not -89 <= skew_y <= 89:
        raise ValueError(f"{context} skew values must be between -89 and 89")

    flip = raw.get("flip", {"x": False, "y": False})
    if not isinstance(flip, dict):
        raise ValueError(f"{context} flip must be an object")
    flip_x = flip.get("x", False)
    flip_y = flip.get("y", False)
    if not isinstance(flip_x, bool) or not isinstance(flip_y, bool):
        raise ValueError(f"{context} flip values must be booleans")

    font = raw.get("font")
    if not isinstance(font, str) or not font or Path(font).name != font:
        raise ValueError(f"{context} needs a font file name")

    size = raw.get("size")
    if (not isinstance(size, int) or isinstance(size, bool)
            or not MIN_FONT_SIZE <= size <= MAX_FONT_SIZE):
        raise ValueError(
            f"{context} size must be an integer between "
            f"{MIN_FONT_SIZE} and {MAX_FONT_SIZE}"
        )

    weight = raw.get("weight")
    if weight is not None and (
        not isinstance(weight, int) or isinstance(weight, bool)
    ):
        raise ValueError(f"{context} weight must be an integer")

    color = raw.get("color", DEFAULT_COLOR)
    if not isinstance(color, str) or not color:
        raise ValueError(f"{context} color must be a string")

    stroke_width = _finite_number(
        raw.get("stroke_width", 0), f"{context} stroke_width"
    )
    if stroke_width < 0:
        raise ValueError(f"{context} stroke_width must be non-negative")
    stroke_color = raw.get("stroke_color", color)
    if not isinstance(stroke_color, str) or not stroke_color:
        raise ValueError(f"{context} stroke_color must be a string")

    line_spacing = _finite_number(
        raw.get("line_spacing", DEFAULT_LINE_SPACING),
        f"{context} line_spacing",
    )
    if not 0.5 <= line_spacing <= 4:
        raise ValueError(f"{context} line_spacing must be between 0.5 and 4")

    char_spacing = _finite_number(
        raw.get("char_spacing", 0), f"{context} char_spacing"
    )
    if not -2000 <= char_spacing <= 2000:
        raise ValueError(f"{context} char_spacing must be between -2000 and 2000")

    underline = raw.get("underline", False)
    linethrough = raw.get("linethrough", False)
    if not isinstance(underline, bool) or not isinstance(linethrough, bool):
        raise ValueError(f"{context} text decorations must be booleans")

    return TextBlock(
        x=x,
        y=y,
        text=text,
        align=align,
        angle=angle,
        skew_x=skew_x,
        skew_y=skew_y,
        flip_x=flip_x,
        flip_y=flip_y,
        font=font,
        size=size,
        weight=weight,
        color=color,
        stroke_width=stroke_width,
        stroke_color=stroke_color,
        line_spacing=line_spacing,
        char_spacing=char_spacing,
        underline=underline,
        linethrough=linethrough,
    )


def _finite_number(value: object, label: str) -> float:
    if (isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def draw_text_blocks(
    canvas: Image.Image,
    blocks: list[TextBlock],
    values: dict[str, str],
    template_name: str,
    scale: float = 1.0,
    template_dir: Path | None = None,
) -> None:
    """Draw every object; log and skip any object that fails at runtime."""
    for index, block in enumerate(blocks):
        try:
            _draw_block(canvas, block, values, scale, template_dir)
        except Exception as exc:
            log.error(
                "Text object %d of template %r was skipped: %s",
                index, template_name, exc,
            )


def _draw_block(
    canvas: Image.Image,
    block: TextBlock,
    values: dict[str, str],
    scale: float,
    template_dir: Path | None,
) -> None:
    x = round(block.x * scale)
    y = round(block.y * scale)
    if not 0 <= x <= canvas.width or not 0 <= y <= canvas.height:
        raise ValueError("position does not fit the canvas")

    text = _resolve_text(block.text, values)
    font_size = max(1, round(block.size * scale))
    font = _load_font(block.font, font_size, block.weight, template_dir)
    color = _parse_color(block.color)
    stroke_color = _parse_color(block.stroke_color)
    stroke_width = max(0, round(block.stroke_width * scale))
    char_spacing = font_size * block.char_spacing / 1000
    ascent, descent = font.getmetrics()
    lines = text.split("\n")
    line_step = font_size * block.line_spacing * FABRIC_FONT_SIZE_MULTIPLIER

    positioned = []
    bounds = []
    decoration_thickness = max(1, round(font_size / 15))
    for index, line in enumerate(lines):
        baseline_y = (
            (index - (len(lines) - 1) / 2) * line_step
            + (ascent - descent) / 2
        )
        runs, line_left, line_right = _line_runs(
            line, font, char_spacing, block.align
        )
        for value, run_x, anchor in runs:
            bbox = font.getbbox(value, anchor=anchor, stroke_width=stroke_width)
            bounds.append((
                run_x + bbox[0],
                baseline_y + bbox[1],
                run_x + bbox[2],
                baseline_y + bbox[3],
            ))

        decorations = []
        if line_right > line_left:
            if block.underline:
                decorations.append(
                    baseline_y + max(1, round(descent * 0.35))
                )
            if block.linethrough:
                decorations.append(baseline_y - round(ascent * 0.3))
            bounds.extend(
                (
                    line_left,
                    line_y - decoration_thickness / 2,
                    line_right,
                    line_y + decoration_thickness / 2,
                )
                for line_y in decorations
            )
        positioned.append((runs, baseline_y, line_left, line_right, decorations))

    if not bounds:
        return

    half_width = math.ceil(max(
        1,
        max(abs(left) for left, _, _, _ in bounds),
        max(abs(right) for _, _, right, _ in bounds),
    )) + 2
    half_height = math.ceil(max(
        1,
        max(abs(top) for _, top, _, _ in bounds),
        max(abs(bottom) for _, _, _, bottom in bounds),
    )) + 2
    layer = Image.new(
        "RGBA", (half_width * 2, half_height * 2), (0, 0, 0, 0)
    )

    try:
        draw = ImageDraw.Draw(layer)
        for runs, baseline_y, _, _, _ in positioned:
            if not stroke_width:
                continue
            for value, run_x, anchor in runs:
                draw.text(
                    (half_width + run_x, half_height + baseline_y),
                    value,
                    font=font,
                    fill=stroke_color,
                    anchor=anchor,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_color,
                )

        for runs, baseline_y, line_left, line_right, decorations in positioned:
            for value, run_x, anchor in runs:
                draw.text(
                    (half_width + run_x, half_height + baseline_y),
                    value,
                    font=font,
                    fill=color,
                    anchor=anchor,
                )
            for line_y in decorations:
                draw.line(
                    (
                        half_width + line_left,
                        half_height + line_y,
                        half_width + line_right,
                        half_height + line_y,
                    ),
                    fill=color,
                    width=decoration_thickness,
                )

        transformed = _transform_layer(layer, block)
        if transformed is not layer:
            layer.close()
            layer = transformed
        canvas.paste(
            layer,
            (round(x - layer.width / 2), round(y - layer.height / 2)),
            layer,
        )
    finally:
        layer.close()


def _line_runs(
    text: str,
    font: ImageFont.FreeTypeFont,
    char_spacing: float,
    align: str,
) -> tuple[list[tuple[str, float, str]], float, float]:
    if not text:
        return [], 0, 0

    if abs(char_spacing) < 0.001:
        width = float(font.getlength(text))
        left = {"left": 0, "center": -width / 2, "right": -width}[align]
        anchor = {"left": "ls", "center": "ms", "right": "rs"}[align]
        return [(text, 0, anchor)], left, left + width

    characters = list(text)
    advances = [float(font.getlength(character)) for character in characters]
    width = sum(advances) + char_spacing * (len(characters) - 1)
    left = {"left": 0, "center": -width / 2, "right": -width}[align]
    cursor = left
    runs = []
    for character, advance in zip(characters, advances):
        runs.append((character, cursor, "ls"))
        cursor += advance + char_spacing
    return runs, left, left + width


def _transform_layer(layer: Image.Image, block: TextBlock) -> Image.Image:
    skew_x = math.tan(math.radians(block.skew_x))
    skew_y = math.tan(math.radians(block.skew_y))
    flip_x = -1 if block.flip_x else 1
    flip_y = -1 if block.flip_y else 1

    # Fabric composes dimensions as flip/scale * skewX * skewY.
    matrix = (
        flip_x * (1 + skew_x * skew_y),
        flip_x * skew_x,
        flip_y * skew_y,
        flip_y,
    )
    transformed = layer
    if matrix != (1, 0, 0, 1):
        transformed = _affine_about_center(layer, matrix)

    if abs(block.angle) >= 0.001:
        rotated = transformed.rotate(
            -block.angle,
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )
        if transformed is not layer:
            transformed.close()
        transformed = rotated
    return transformed


def _affine_about_center(
    image: Image.Image,
    matrix: tuple[float, float, float, float],
) -> Image.Image:
    a, b, c, d = matrix
    determinant = a * d - b * c
    if abs(determinant) < 1e-9:
        raise ValueError("text transform is singular")

    half_width = image.width / 2
    half_height = image.height / 2
    corners = (
        (-half_width, -half_height),
        (half_width, -half_height),
        (-half_width, half_height),
        (half_width, half_height),
    )
    points = tuple(
        (a * x + b * y, c * x + d * y) for x, y in corners
    )
    output_half_width = math.ceil(max(abs(x) for x, _ in points)) + 2
    output_half_height = math.ceil(max(abs(y) for _, y in points)) + 2
    output_size = (output_half_width * 2, output_half_height * 2)

    ia, ib, ic, id_ = (
        d / determinant,
        -b / determinant,
        -c / determinant,
        a / determinant,
    )
    data = (
        ia,
        ib,
        half_width - ia * output_half_width - ib * output_half_height,
        ic,
        id_,
        half_height - ic * output_half_width - id_ * output_half_height,
    )
    return image.transform(
        output_size,
        Image.Transform.AFFINE,
        data,
        resample=Image.Resampling.BICUBIC,
    )


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
    template_dir: Path | None = None,
) -> ImageFont.FreeTypeFont:
    path = template_dir / name if template_dir is not None else None
    if path is None or not path.is_file():
        path = FONTS_DIR / name
    if not path.is_file():
        raise ValueError(f"font not found: {name}")
    font = ImageFont.truetype(str(path), size)
    if weight is None:
        return font
    try:
        axes = font.get_variation_axes()
    except OSError:
        log.info("Font %s is not variable; weight %d ignored", name, weight)
        return font

    values = [axis["default"] for axis in axes]
    for index, axis in enumerate(axes):
        if axis.get("name") in (b"Weight", "Weight"):
            minimum = axis["minimum"]
            maximum = axis["maximum"]
            clamped = max(minimum, min(maximum, weight))
            if clamped != weight:
                log.error(
                    "Out-of-range weight=%d for %s; using %d (%d..%d)",
                    weight, name, clamped, minimum, maximum,
                )
            values[index] = clamped
            font.set_variation_by_axes(values)
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
