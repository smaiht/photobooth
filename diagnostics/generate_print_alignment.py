"""Generate a native DS-RX1HS 6x4 alignment sheet."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 3688
HEIGHT = 2480
DPI = 600
OUTPUT = Path(__file__).with_name("print_alignment_3688x2480.png")


def font(size: int, bold: bool = False):
    names = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        r"C:\Windows\Fonts\arialbd.ttf"
        if bold else r"C:\Windows\Fonts\arial.ttf",
    )
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def centered_text(draw, y: int, text: str, selected_font, fill="black") -> None:
    box = draw.textbbox((0, 0), text, font=selected_font)
    draw.text(
        ((WIDTH - (box[2] - box[0])) / 2, y),
        text,
        font=selected_font,
        fill=fill,
    )


def dashed_rectangle(draw, inset: int, color, width: int = 5, dash: int = 28) -> None:
    left, top = inset, inset
    right, bottom = WIDTH - 1 - inset, HEIGHT - 1 - inset
    for start in range(left, right, dash * 2):
        draw.line((start, top, min(start + dash, right), top), fill=color, width=width)
        draw.line((start, bottom, min(start + dash, right), bottom), fill=color, width=width)
    for start in range(top, bottom, dash * 2):
        draw.line((left, start, left, min(start + dash, bottom)), fill=color, width=width)
        draw.line((right, start, right, min(start + dash, bottom)), fill=color, width=width)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)

    # Six 20 px bands make edge loss immediately measurable.
    rings = (
        (0, "#e60012"),
        (20, "#ff7a00"),
        (40, "#ffd900"),
        (60, "#00a650"),
        (80, "#0877d1"),
        (100, "#8a2be2"),
    )
    for inset, color in rings:
        draw.rectangle(
            (inset, inset, WIDTH - 1 - inset, HEIGHT - 1 - inset),
            outline=color,
            width=20,
        )

    # Current grid uses 61 px outer margins. Driver Border=Enable uses 120 px.
    dashed_rectangle(draw, 61, "white", width=5, dash=24)
    dashed_rectangle(draw, 120, "black", width=5, dash=28)

    for x in range(344, WIDTH - 120, DPI):
        draw.line((x, 140, x, HEIGHT - 141), fill="#c8ccd2", width=3)
        draw.text((x + 8, 148), f"x={x}", font=font(24), fill="#525860")
    for y in range(340, HEIGHT - 120, DPI):
        draw.line((140, y, WIDTH - 141, y), fill="#c8ccd2", width=3)
        draw.text((148, y + 8), f"y={y}", font=font(24), fill="#525860")

    title_font = font(52, bold=True)
    text_font = font(34)
    small_font = font(26)
    centered_text(draw, 175, "DNP DS-RX1HS ALIGNMENT TEST", title_font)
    centered_text(draw, 240, "3688 x 2480 px   |   600 x 600 DPI   |   (6x4) Portrait", text_font)

    center_x, center_y = WIDTH // 2, HEIGHT // 2
    half = DPI // 2
    draw.rectangle(
        (center_x - half, center_y - half, center_x + half, center_y + half),
        outline="black",
        width=7,
    )
    draw.ellipse(
        (center_x - half, center_y - half, center_x + half, center_y + half),
        outline="#e60012",
        width=7,
    )
    draw.line((center_x - half, center_y, center_x + half, center_y), fill="black", width=4)
    draw.line((center_x, center_y - half, center_x, center_y + half), fill="black", width=4)
    centered_text(draw, center_y + half + 24, "600 x 600 px = 1 x 1 inch", text_font)

    legend_x = 310
    legend_y = 1940
    draw.rounded_rectangle(
        (legend_x - 35, legend_y - 35, legend_x + 1320, legend_y + 330),
        radius=24,
        fill="#f3f4f6",
        outline="#20242a",
        width=4,
    )
    draw.text((legend_x, legend_y), "EDGE BANDS (20 px each)", font=font(32, bold=True), fill="black")
    for index, (inset, color) in enumerate(rings):
        x = legend_x + (index % 3) * 420
        y = legend_y + 65 + (index // 3) * 105
        draw.rectangle((x, y, x + 85, y + 58), fill=color, outline="black", width=2)
        draw.text(
            (x + 100, y + 9),
            f"{inset}-{inset + 20} px",
            font=small_font,
            fill="black",
        )
    draw.text(
        (1900, 1970),
        "WHITE DASH = current template margin: 61 px\n"
        "BLACK DASH = driver Border=Enable inset: 120 px\n"
        "With Border=Disable the full colored edge should be addressable.",
        font=small_font,
        fill="black",
        spacing=16,
    )

    corner_font = font(34, bold=True)
    draw.text((145, 145), "TOP LEFT", font=corner_font, fill="black")
    right_box = draw.textbbox((0, 0), "TOP RIGHT", font=corner_font)
    draw.text((WIDTH - 145 - (right_box[2] - right_box[0]), 145), "TOP RIGHT", font=corner_font, fill="black")
    draw.text((145, HEIGHT - 190), "BOTTOM LEFT", font=corner_font, fill="black")
    right_box = draw.textbbox((0, 0), "BOTTOM RIGHT", font=corner_font)
    draw.text(
        (WIDTH - 145 - (right_box[2] - right_box[0]), HEIGHT - 190),
        "BOTTOM RIGHT",
        font=corner_font,
        fill="black",
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, "PNG", dpi=(DPI, DPI), optimize=True)
    image.close()
    print(OUTPUT)


if __name__ == "__main__":
    main()
