"""Compose 4 photos into print-ready templates.

DNP RX1HS prints 4x6" (10x15cm) at 300dpi = 1800x1200px.
Strip template: two 2x6" strips side by side on one 4x6" sheet (printer cuts in half).
Grid template: 2x2 grid on one 4x6" sheet.
"""

from pathlib import Path
from PIL import Image, ImageDraw

# Print dimensions at 300dpi
PRINT_W, PRINT_H = 1800, 1200  # 4x6" landscape
STRIP_W, STRIP_H = 600, 1800   # 2x6" single strip (portrait)


def compose_strip(photos: list[str | Path], overlay: str | Path | None = None) -> Image.Image:
    """Two 2x6 strips side by side on 4x6 sheet. Each strip has 4 photos stacked vertically.
    
    Layout per strip (600x1800):
      Photo area per image: 600 x ~400px with gaps
      Total: 4 photos + optional overlay (border, logo, text)
    """
    sheet = Image.new("RGB", (PRINT_W, PRINT_H), "white")

    photo_w, photo_h = 540, 380
    margin_x, margin_y = 30, 30
    gap = (STRIP_H - margin_y * 2 - photo_h * 4) // 3

    for strip_idx in range(2):
        x_offset = strip_idx * (PRINT_W // 2)
        for i, photo_path in enumerate(photos[:4]):
            img = Image.open(photo_path)
            img = _fit_crop(img, photo_w, photo_h)
            y = margin_y + i * (photo_h + gap)
            sheet.paste(img, (x_offset + margin_x, y))

    if overlay and Path(overlay).exists():
        ov = Image.open(overlay).convert("RGBA").resize((PRINT_W, PRINT_H))
        sheet.paste(ov, (0, 0), ov)

    return sheet


def compose_grid(photos: list[str | Path], overlay: str | Path | None = None) -> Image.Image:
    """2x2 grid on 4x6 sheet.
    
    Layout (1800x1200):
      4 photos in 2 columns x 2 rows
    """
    sheet = Image.new("RGB", (PRINT_W, PRINT_H), "white")

    margin = 30
    gap = 20
    photo_w = (PRINT_W - margin * 2 - gap) // 2
    photo_h = (PRINT_H - margin * 2 - gap) // 2

    positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
    for idx, (col, row) in enumerate(positions):
        if idx >= len(photos):
            break
        img = Image.open(photos[idx])
        img = _fit_crop(img, photo_w, photo_h)
        x = margin + col * (photo_w + gap)
        y = margin + row * (photo_h + gap)
        sheet.paste(img, (x, y))

    if overlay and Path(overlay).exists():
        ov = Image.open(overlay).convert("RGBA").resize((PRINT_W, PRINT_H))
        sheet.paste(ov, (0, 0), ov)

    return sheet


def _fit_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Crop to aspect ratio then resize. Center crop."""
    src_ratio = img.width / img.height
    dst_ratio = target_w / target_h

    if src_ratio > dst_ratio:
        # Source wider — crop sides
        new_w = int(img.height * dst_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        # Source taller — crop top/bottom
        new_h = int(img.width / dst_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)
