"""Compose photos onto print templates.

Template folder contains config.json + background images.
config.json["templates"]["strips"] / ["grid"] define background file and photo positions.
"""

from pathlib import Path
from PIL import Image


def compose(template_dir: Path, template_name: str, photos: list[str | Path], config: dict) -> Image.Image:
    """Compose photos onto a template. Returns print-ready image."""
    tpl = config["templates"][template_name]
    bg = Image.open(template_dir / tpl["background"]).convert("RGB")

    for i, slot in enumerate(tpl["photos"]):
        if i >= len(photos):
            break
        img = Image.open(photos[i])
        img = _fit_crop(img, slot["w"], slot["h"])
        bg.paste(img, (slot["x"], slot["y"]))

    if tpl.get("duplicate"):
        sheet = Image.new("RGB", (bg.width * 2, bg.height), "white")
        sheet.paste(bg, (0, 0))
        sheet.paste(bg, (bg.width, 0))
        return sheet

    return bg


def _fit_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Center crop to aspect ratio, then resize."""
    src_ratio = img.width / img.height
    dst_ratio = target_w / target_h

    if src_ratio > dst_ratio:
        new_w = int(img.height * dst_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / dst_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)
