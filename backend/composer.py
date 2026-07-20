"""Compose photos onto native-resolution print templates.

Template folder contains config.json + background images.
config.json["templates"]["strips"] / ["grid"] define background file and photo positions.
"""

from pathlib import Path
import logging

from PIL import Image, ImageOps


DEFAULT_PRINT_SIZE = (3688, 2480)
log = logging.getLogger(__name__)


def compose(template_dir: Path, template_name: str, photos: list[str | Path], config: dict) -> Image.Image:
    """Compose photos onto a template. Returns print-ready image."""
    tpl = config["templates"][template_name]
    slots = tpl["photos"]
    if len(photos) < len(slots):
        raise ValueError(
            f"template {template_name!r} needs {len(slots)} photos, got {len(photos)}"
        )
    with Image.open(template_dir / tpl["background"]) as background:
        bg = background.convert("RGB")

    for i, slot in enumerate(slots):
        try:
            x, y, slot_w, slot_h = (
                int(slot["x"]), int(slot["y"]), int(slot["w"]), int(slot["h"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid photo slot {i} in template {template_name!r}") from exc
        if x < 0 or y < 0 or slot_w <= 0 or slot_h <= 0:
            raise ValueError(f"invalid photo slot {i} in template {template_name!r}")
        if x + slot_w > bg.width or y + slot_h > bg.height:
            raise ValueError(
                f"photo slot {i} exceeds {template_name!r} background {bg.size}"
            )
        with Image.open(photos[i]) as source:
            img = _fit_crop(
                ImageOps.exif_transpose(source).convert("RGB"), slot_w, slot_h
            )
        bg.paste(img, (x, y))

    if tpl.get("duplicate"):
        sheet = Image.new("RGB", (bg.width * 2, bg.height), "white")
        sheet.paste(bg, (0, 0))
        sheet.paste(bg, (bg.width, 0))
    else:
        sheet = bg

    print_size = tuple(config.get("print_size", DEFAULT_PRINT_SIZE))
    if len(print_size) != 2 or not all(isinstance(value, int) and value > 0 for value in print_size):
        raise ValueError("template print_size must contain two positive integers")
    if sheet.size == print_size:
        return sheet
    if sheet.size[::-1] == print_size:
        sheet = sheet.transpose(Image.Transpose.ROTATE_90)
    if sheet.size == print_size:
        return sheet
    log.warning(
        "Template %s produced %sx%s; fitting to %sx%s",
        template_name,
        sheet.width,
        sheet.height,
        print_size[0],
        print_size[1],
    )
    return ImageOps.fit(
        sheet,
        print_size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


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

    return img.resize((target_w, target_h), Image.Resampling.LANCZOS)
