"""Generate the heart SVG.

Run from the project root:
    venv/bin/python event_props/generate_heart.py
"""

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_DIR / "assets/egor_elizaveta_heart.svg"

# Main settings you can change.
FONT_PATH = PROJECT_DIR / "assets/fonts/Comfortaa-VariableFont_wght.ttf"
FONT_WEIGHT = 700  # Comfortaa supports 300–700.
FONT_SIZE_MM = 15.0
BORDER_WIDTH_MM = 1.4
LINES = (
)

HEART_PATH = "M60 104C56 100 12 72 6 39C2 16 18 4 35 4C47 4 55 10 60 20C65 10 73 4 85 4C102 4 118 16 114 39C108 72 64 100 60 104Z"
HEART_REVERSED_PATH = "M60 104C64 100 108 72 114 39C118 16 102 4 85 4C73 4 65 10 60 20C55 10 47 4 35 4C18 4 2 16 6 39C12 72 56 100 60 104Z"
HEART_SEGMENTS = (
    ((60, 104), (56, 100), (12, 72), (6, 39)),
    ((6, 39), (2, 16), (18, 4), (35, 4)),
    ((35, 4), (47, 4), (55, 10), (60, 20)),
    ((60, 20), (65, 10), (73, 4), (85, 4)),
    ((85, 4), (102, 4), (118, 16), (114, 39)),
    ((114, 39), (108, 72), (64, 100), (60, 104)),
)


def cubic_point(segment, t):
    p0, p1, p2, p3 = segment
    mt = 1 - t
    return (
        mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
        mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1],
    )


def make_border_path():
    points = []
    for segment in HEART_SEGMENTS:
        points.extend(cubic_point(segment, step / 48) for step in range(48))

    heart = Polygon(points)
    outer = orient(heart.buffer(BORDER_WIDTH_MM, join_style="mitre"), sign=1.0)
    coordinates = "L".join(f"{x:.3f} {y:.3f}" for x, y in outer.exterior.coords[:-1])
    return f"M{coordinates}Z"


def make_text_paths(font, text, baseline):
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    metrics = font["hmtx"].metrics
    scale = FONT_SIZE_MM / font["head"].unitsPerEm
    glyphs = [cmap[ord(character)] for character in text]
    width = sum(metrics[glyph][0] for glyph in glyphs) * scale
    x = (120 - width) / 2

    paths = []
    for glyph_name in glyphs:
        path_pen = SVGPathPen(glyph_set)
        transform_pen = TransformPen(path_pen, (scale, 0, 0, -scale, x, baseline))
        glyph_set[glyph_name].draw(transform_pen)
        if path_pen.getCommands():
            paths.append(f'    <path d="{path_pen.getCommands()}"/>')
        x += metrics[glyph_name][0] * scale
    return "\n".join(paths)


font = TTFont(FONT_PATH)
if "fvar" in font:
    font = instantiateVariableFont(font, {"wght": FONT_WEIGHT})

lettering = "\n".join(make_text_paths(font, text, baseline) for text, baseline in LINES)
border_path = make_border_path()

OUTPUT_PATH.write_text(
    f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="108mm" viewBox="0 0 120 108">
  <title>Елизавета и Егор — сердце</title>
  <path id="white-border" fill="#ffffff" fill-rule="evenodd" d="{border_path}{HEART_REVERSED_PATH}"/>
  <path id="red-heart" fill="#d71920" d="{HEART_PATH}"/>
  <g id="lettering" fill="#ffffff" aria-label="Елизавета и Егор">
{lettering}
  </g>
</svg>
''',
    encoding="utf-8",
)

print(f"Generated {OUTPUT_PATH}")
