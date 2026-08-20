"""Generate a blank speech-bubble prop.

Run from the project root:
    venv/bin/python event_props/generate_speech_bubble.py
"""

from pathlib import Path

from shapely.affinity import translate
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient


PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_DIR / "assets/speech_bubble.svg"

# Main settings you can change, in millimetres.
BUBBLE_WIDTH = 150
BUBBLE_HEIGHT = 116
BORDER_WIDTH = 1.5
CORNER_RADIUS = 22
TAIL_BLEND_RADIUS = 5.0

# Tail dimensions. Positive TAIL_BEND moves the tip to the left.
TAIL_FROM_LEFT = 71
TAIL_WIDTH = 26
TAIL_HEIGHT = 16
TAIL_BEND = 16

RED = "#d71920"
WHITE = "#ffffff"


def svg_path(coordinates):
    points = list(coordinates)
    return "M" + "L".join(f"{x:.3f} {y:.3f}" for x, y in points[:-1]) + "Z"


def cubic_points(p0, p1, p2, p3, steps=24):
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        mt = 1 - t
        points.append(
            (
                mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
                mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1],
            )
        )
    return points


rounded_rectangle = box(
    CORNER_RADIUS,
    CORNER_RADIUS,
    BUBBLE_WIDTH - CORNER_RADIUS,
    BUBBLE_HEIGHT - CORNER_RADIUS,
).buffer(CORNER_RADIUS, quad_segs=16)

tail_start = (TAIL_FROM_LEFT, BUBBLE_HEIGHT - 0.5)
tail_end = (TAIL_FROM_LEFT + TAIL_WIDTH, BUBBLE_HEIGHT - 0.5)
tail_tip = (TAIL_FROM_LEFT - TAIL_BEND, BUBBLE_HEIGHT + TAIL_HEIGHT)

tail_left_control_1 = (TAIL_FROM_LEFT - 1, BUBBLE_HEIGHT + TAIL_HEIGHT * 0.3)
tail_left_control_2 = (tail_tip[0] + TAIL_WIDTH * 0.26, BUBBLE_HEIGHT + TAIL_HEIGHT * 0.63)
tail_before_tip = (tail_tip[0] + TAIL_WIDTH * 0.12, BUBBLE_HEIGHT + TAIL_HEIGHT * 0.84)

tail_right_control_1 = (tail_tip[0] + TAIL_WIDTH * 0.38, BUBBLE_HEIGHT + TAIL_HEIGHT * 0.84)
tail_right_control_2 = (tail_end[0] - TAIL_WIDTH * 0.3, BUBBLE_HEIGHT + TAIL_HEIGHT * 0.42)

tail_points = [tail_start]
tail_points.extend(
    cubic_points(
        tail_start,
        tail_left_control_1,
        tail_left_control_2,
        tail_before_tip,
    )
)
tail_points.append(tail_tip)
tail_points.extend(
    cubic_points(
        tail_tip,
        tail_right_control_1,
        tail_right_control_2,
        tail_end,
    )
)
tail = Polygon(tail_points)

inner = rounded_rectangle.union(tail)
# Round the two inner transitions where the tail joins the bubble.
inner = inner.buffer(TAIL_BLEND_RADIUS, join_style="round").buffer(
    -TAIL_BLEND_RADIUS, join_style="round"
)
inner = orient(inner, sign=1.0)
outer = orient(inner.buffer(BORDER_WIDTH, join_style="mitre"), sign=1.0)

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
  <title>Speech bubble prop</title>
  <path id="red-border" fill="{RED}" fill-rule="evenodd" d="{outer_path}{inner_reversed_path}"/>
  <path id="white-center" fill="{WHITE}" d="{inner_path}"/>
</svg>
''',
    encoding="utf-8",
)

print(f"Generated {OUTPUT_PATH}")
