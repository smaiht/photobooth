"""Generate a blank arrow-shaped prop.

Run from the project root:
    venv/bin/python event_props/generate_arrow_sign.py
"""

from pathlib import Path

from shapely.affinity import scale, translate
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_DIR / "assets/arrow_sign.svg"

# Main dimensions, in millimetres.
SHAFT_LENGTH = 120
SHAFT_HEIGHT = 50
HEAD_LENGTH = 70  # Set to 0 for a rectangular sign.
HEAD_HEIGHT = 80

CORNER_RADIUS = 1.5
BORDER_WIDTH = 1.5
DIRECTION = "right"  # "right" or "left"

RED = "#d71920"
WHITE = "#ffffff"


def svg_path(coordinates):
    points = list(coordinates)
    return "M" + "L".join(f"{x:.3f} {y:.3f}" for x, y in points[:-1]) + "Z"


if HEAD_LENGTH < 0:
    raise ValueError("HEAD_LENGTH must be non-negative")
if HEAD_LENGTH > 0 and HEAD_HEIGHT <= SHAFT_HEIGHT:
    raise ValueError("HEAD_HEIGHT must be greater than SHAFT_HEIGHT")
if DIRECTION not in {"left", "right"}:
    raise ValueError('DIRECTION must be either "left" or "right"')

total_width = SHAFT_LENGTH + HEAD_LENGTH
if HEAD_LENGTH == 0:
    raw_arrow = Polygon(
        ((0, 0), (SHAFT_LENGTH, 0), (SHAFT_LENGTH, SHAFT_HEIGHT), (0, SHAFT_HEIGHT))
    )
    prop_height = SHAFT_HEIGHT
else:
    shaft_top = (HEAD_HEIGHT - SHAFT_HEIGHT) / 2
    shaft_bottom = shaft_top + SHAFT_HEIGHT
    raw_arrow = Polygon(
        (
            (0, shaft_top),
            (SHAFT_LENGTH, shaft_top),
            (SHAFT_LENGTH, 0),
            (total_width, HEAD_HEIGHT / 2),
            (SHAFT_LENGTH, HEAD_HEIGHT),
            (SHAFT_LENGTH, shaft_bottom),
            (0, shaft_bottom),
        )
    )
    prop_height = HEAD_HEIGHT

arrow = raw_arrow
if CORNER_RADIUS > 0:
    # First round the inner shoulders, then the outer corners and the tip.
    arrow = arrow.buffer(CORNER_RADIUS, join_style="round").buffer(
        -CORNER_RADIUS, join_style="round"
    )
    arrow = arrow.buffer(-CORNER_RADIUS, join_style="round").buffer(
        CORNER_RADIUS, join_style="round"
    )

# Keep the configured width and height exact after corner rounding.
min_x, min_y, max_x, max_y = arrow.bounds
arrow = translate(arrow, xoff=-min_x, yoff=-min_y)
arrow = scale(
    arrow,
    xfact=total_width / (max_x - min_x),
    yfact=prop_height / (max_y - min_y),
    origin=(0, 0),
)

if DIRECTION == "left":
    arrow = scale(arrow, xfact=-1, yfact=1, origin=(total_width / 2, 0))

inner = orient(arrow, sign=1.0)
outer = orient(inner.buffer(BORDER_WIDTH, join_style="round"), sign=1.0)

# Fit the SVG canvas tightly around the finished prop, including its border.
min_x, min_y, max_x, max_y = outer.bounds
svg_width = max_x - min_x
svg_height = max_y - min_y
inner = translate(inner, xoff=-min_x, yoff=-min_y)
outer = translate(outer, xoff=-min_x, yoff=-min_y)

outer_path = svg_path(outer.exterior.coords)
inner_path = svg_path(inner.exterior.coords)
inner_reversed_path = svg_path(reversed(inner.exterior.coords))

OUTPUT_PATH.write_text(
    f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width:.3f}mm" height="{svg_height:.3f}mm" viewBox="0 0 {svg_width:.3f} {svg_height:.3f}">
  <title>Arrow sign prop</title>
  <path id="red-border" fill="{RED}" fill-rule="evenodd" d="{outer_path}{inner_reversed_path}"/>
  <path id="white-center" fill="{WHITE}" d="{inner_path}"/>
</svg>
''',
    encoding="utf-8",
)

print(f"Generated {OUTPUT_PATH}")
