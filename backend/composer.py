"""Compose photos onto native-resolution print templates.

Template folder contains config.json + background images.
config.json["templates"]["strips"] / ["grid"] define background file and photo positions.
"""

from pathlib import Path
import logging
import os

from PIL import Image, ImageOps


DEFAULT_PRINT_SIZE = (3688, 2480)
DEFAULT_PREVIEW_WIDTH = 720
PREVIEW_PHOTO_MAX_EDGE = 720
PREVIEW_CANVAS_COLOR = (51, 51, 51)
DUPLICATE_PREVIEW_HEIGHT_RATIO = 0.86
DUPLICATE_PREVIEW_Y_OFFSET_RATIO = 0.08
DUPLICATE_PREVIEW_GAP_RATIO = 0.035
log = logging.getLogger(__name__)


def compose(template_dir: Path, template_name: str, photos: list[str | Path], config: dict) -> Image.Image:
    """Compose photos onto a template. Returns print-ready image."""
    print_size = _validated_print_size(config)
    tpl = config["templates"][template_name]
    slots = tpl["photos"]
    if len(photos) < len(slots):
        raise ValueError(
            f"template {template_name!r} needs {len(slots)} photos, got {len(photos)}"
        )
    with Image.open(template_dir / tpl["background"]) as background:
        bg = background.convert("RGB")

    try:
        for i, slot in enumerate(slots):
            try:
                x, y, slot_w, slot_h = (
                    int(slot["x"]), int(slot["y"]),
                    int(slot["w"]), int(slot["h"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid photo slot {i} in template {template_name!r}"
                ) from exc
            if x < 0 or y < 0 or slot_w <= 0 or slot_h <= 0:
                raise ValueError(
                    f"invalid photo slot {i} in template {template_name!r}")
            if x + slot_w > bg.width or y + slot_h > bg.height:
                raise ValueError(
                    f"photo slot {i} exceeds {template_name!r} background {bg.size}"
                )
            with Image.open(photos[i]) as source:
                source_image = _oriented_rgb(source)
            try:
                img, offset_x, offset_y = _fit_inside(
                    source_image, slot_w, slot_h)
            finally:
                source_image.close()
            try:
                bg.paste(img, (x + offset_x, y + offset_y))
            finally:
                img.close()

        if tpl.get("duplicate"):
            sheet = Image.new("RGB", (bg.width * 2, bg.height), "white")
            sheet.paste(bg, (0, 0))
            sheet.paste(bg, (bg.width, 0))
        else:
            sheet = bg.copy()
    finally:
        bg.close()

    if sheet.size == print_size:
        return sheet
    if sheet.size[::-1] == print_size:
        rotated = sheet.transpose(Image.Transpose.ROTATE_90)
        sheet.close()
        sheet = rotated
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
    try:
        return _fit_on_canvas(sheet, print_size, "white")
    finally:
        sheet.close()


def generate_template_previews(
    template_dir: Path,
    photos: list[str | Path],
    config: dict,
    output_dir: Path,
    preview_width: int = DEFAULT_PREVIEW_WIDTH,
) -> dict[str, Path]:
    """Compose every configured template at screen resolution.

    Source photos are decoded and reduced once, kept in memory only for this
    batch, and explicitly closed before returning. Static reduced backgrounds
    are cached beside their full-size source images.
    """
    templates = config.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ValueError("no templates configured")
    print_size = _validated_print_size(config)
    if not isinstance(preview_width, int) or preview_width < 100:
        raise ValueError("preview_width must be at least 100")
    if len(photos) < max(len(template.get("photos", []))
                         for template in templates.values()):
        raise ValueError("not enough photos for template previews")

    output_dir.mkdir(parents=True, exist_ok=True)
    reduced_photos = _load_reduced_photos(photos)
    results: dict[str, Path] = {}
    try:
        for index, template_name in enumerate(templates, start=1):
            try:
                preview = _compose_preview(
                    template_dir,
                    template_name,
                    reduced_photos,
                    config,
                    print_size,
                    preview_width,
                )
                output_path = output_dir / f"preview_{index:02d}.jpg"
                try:
                    _save_jpeg_atomic(preview, output_path)
                finally:
                    preview.close()
                results[template_name] = output_path
            except Exception:
                log.exception("Template preview failed: %s", template_name)
        if not results:
            raise RuntimeError("all template previews failed")
        return results
    finally:
        for image in reduced_photos:
            image.close()


def _validated_print_size(config: dict) -> tuple[int, int]:
    print_size = tuple(config.get("print_size", DEFAULT_PRINT_SIZE))
    if (len(print_size) != 2
            or not all(isinstance(value, int) and value > 0 for value in print_size)):
        raise ValueError("template print_size must contain two positive integers")
    return print_size


def _load_reduced_photos(photos: list[str | Path]) -> list[Image.Image]:
    reduced = []
    try:
        for photo in photos:
            with Image.open(photo) as source:
                # Preserve the source aspect ratio in the JPEG decoder hint.
                # For a 6000x4000 Canon JPEG, 720x480 unlocks 1/8 decoding
                # instead of first expanding it to 1500x1000 or larger.
                source_width, source_height = source.size
                draft_scale = min(
                    1.0,
                    PREVIEW_PHOTO_MAX_EDGE / max(source_width, source_height),
                )
                draft_size = (
                    max(1, round(source_width * draft_scale)),
                    max(1, round(source_height * draft_scale)),
                )
                source.draft("RGB", draft_size)
                image = _oriented_rgb(source)
            try:
                image.thumbnail(
                    (PREVIEW_PHOTO_MAX_EDGE, PREVIEW_PHOTO_MAX_EDGE),
                    Image.Resampling.LANCZOS,
                )
            except Exception:
                image.close()
                raise
            reduced.append(image)
        return reduced
    except Exception:
        for image in reduced:
            image.close()
        raise


def _compose_preview(
    template_dir: Path,
    template_name: str,
    photos: list[Image.Image],
    config: dict,
    print_size: tuple[int, int],
    preview_width: int,
) -> Image.Image:
    template = config["templates"][template_name]
    slots = template["photos"]
    if len(photos) < len(slots):
        raise ValueError(f"template {template_name!r} needs {len(slots)} photos")

    source_path = template_dir / template["background"]
    with Image.open(source_path) as source:
        source_size = source.size
    target_size = (
        preview_width,
        max(1, round(print_size[1] * preview_width / print_size[0])),
    )
    if template.get("duplicate"):
        # The print compositor duplicates the strip and rotates the resulting
        # sheet to match the printer page.  That technical layout is confusing
        # on the choice screen, so keep the real strip upright and present two
        # copies as separate physical strips instead.
        display_height = max(
            1, round(target_size[1] * DUPLICATE_PREVIEW_HEIGHT_RATIO))
        scale = display_height / source_size[1]
    else:
        scale = preview_width / print_size[0]
    background_size = (
        max(1, round(source_size[0] * scale)),
        max(1, round(source_size[1] * scale)),
    )
    cache_path = source_path.with_name(f"{source_path.stem}_preview.jpg")
    _ensure_background_preview(source_path, cache_path, background_size)
    with Image.open(cache_path) as cached:
        background = cached.convert("RGB")

    try:
        for index, slot in enumerate(slots):
            try:
                source_x = int(slot["x"])
                source_y = int(slot["y"])
                source_width = int(slot["w"])
                source_height = int(slot["h"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid preview slot {index} in template {template_name!r}"
                ) from exc
            if (source_x < 0 or source_y < 0
                    or source_width <= 0 or source_height <= 0):
                raise ValueError(
                    f"invalid preview slot {index} in template {template_name!r}")
            x = round(source_x * scale)
            y = round(source_y * scale)
            width = max(1, round((source_x + source_width) * scale) - x)
            height = max(1, round((source_y + source_height) * scale) - y)
            if (x < 0 or y < 0 or x + width > background.width
                    or y + height > background.height):
                raise ValueError(
                    f"preview slot {index} exceeds {template_name!r} background"
                )
            fitted, offset_x, offset_y = _fit_inside(
                photos[index], width, height)
            try:
                background.paste(fitted, (x + offset_x, y + offset_y))
            finally:
                fitted.close()

        if template.get("duplicate"):
            sheet = _present_duplicate_preview(background, target_size)
        else:
            sheet = background.copy()
    finally:
        background.close()

    if sheet.size == target_size:
        return sheet
    if sheet.size[::-1] == target_size:
        rotated = sheet.transpose(Image.Transpose.ROTATE_90)
        sheet.close()
        return rotated
    try:
        return _fit_on_canvas(sheet, target_size, PREVIEW_CANVAS_COLOR)
    finally:
        sheet.close()


def _present_duplicate_preview(
    strip: Image.Image,
    target_size: tuple[int, int],
) -> Image.Image:
    """Place two upright strip copies with a small gap and vertical offset."""
    target_width, target_height = target_size
    gap = max(1, round(target_width * DUPLICATE_PREVIEW_GAP_RATIO))
    y_offset = max(1, round(target_height * DUPLICATE_PREVIEW_Y_OFFSET_RATIO))
    group_width = strip.width * 2 + gap
    group_height = strip.height + y_offset
    if group_width > target_width or group_height > target_height:
        raise ValueError(
            f"duplicate preview does not fit {target_size}: "
            f"group={group_width}x{group_height}"
        )

    x = (target_width - group_width) // 2
    y = (target_height - group_height) // 2
    preview = Image.new("RGB", target_size, PREVIEW_CANVAS_COLOR)
    preview.paste(strip, (x, y))
    preview.paste(strip, (x + strip.width + gap, y + y_offset))
    return preview


def _ensure_background_preview(
    source_path: Path,
    cache_path: Path,
    expected_size: tuple[int, int],
) -> None:
    if cache_path.is_file():
        try:
            fresh = cache_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns
            if fresh:
                with Image.open(cache_path) as cached:
                    if cached.size == expected_size:
                        return
        except (OSError, ValueError):
            pass

    with Image.open(source_path) as source:
        source_image = source.convert("RGB")
    try:
        reduced = source_image.resize(expected_size, Image.Resampling.LANCZOS)
    finally:
        source_image.close()
    try:
        _save_jpeg_atomic(reduced, cache_path)
    finally:
        reduced.close()
    log.info("Template preview background cached: %s", cache_path)


def _save_jpeg_atomic(image: Image.Image, output_path: Path) -> None:
    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        image.save(
            temporary,
            "JPEG",
            quality=88,
            optimize=True,
            subsampling=0,
        )
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _fit_inside(
    image: Image.Image,
    target_width: int,
    target_height: int,
) -> tuple[Image.Image, int, int]:
    """Resize the whole image into a box without cropping or distortion."""
    scale = min(target_width / image.width, target_height / image.height)
    fitted_size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    fitted = image.resize(fitted_size, Image.Resampling.LANCZOS)
    return (
        fitted,
        (target_width - fitted.width) // 2,
        (target_height - fitted.height) // 2,
    )


def _fit_on_canvas(
    image: Image.Image,
    target_size: tuple[int, int],
    background,
) -> Image.Image:
    """Fit a whole image onto a centered canvas, preserving every pixel."""
    result = Image.new("RGB", target_size, background)
    fitted, offset_x, offset_y = _fit_inside(
        image, target_size[0], target_size[1])
    try:
        result.paste(fitted, (offset_x, offset_y))
    finally:
        fitted.close()
    return result


def _oriented_rgb(source: Image.Image) -> Image.Image:
    oriented = ImageOps.exif_transpose(source)
    try:
        return oriented.convert("RGB")
    finally:
        if oriented is not source:
            oriented.close()
