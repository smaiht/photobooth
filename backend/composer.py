"""Compose photos onto native-resolution print templates.

Template folder contains config.json and image layers. Each template has one
print_layout shared by final composition and the on-screen preview. An optional
foreground layer is composited after the photos.
"""

from pathlib import Path
import logging
import os
from typing import NamedTuple

from PIL import Image, ImageOps


DEFAULT_PRINT_SIZE = (3688, 2480)
DEFAULT_PREVIEW_WIDTH = 720
PREVIEW_PHOTO_MAX_EDGE = 720
PREVIEW_CANVAS_COLOR = (51, 51, 51)
PREVIEW_SPLIT_HEIGHT_RATIO = 0.86
PREVIEW_SPLIT_Y_OFFSET_RATIO = 0.08
PREVIEW_SPLIT_GAP_RATIO = 0.035
ROTATION_TRANSPOSE = {
    "none": None,
    "cw": Image.Transpose.ROTATE_270,
    "ccw": Image.Transpose.ROTATE_90,
}
log = logging.getLogger(__name__)


class PhotoSlot(NamedTuple):
    photo_index: int
    x: int
    y: int
    width: int
    height: int
    rotation: str


class TemplateSpec(NamedTuple):
    background: str
    foreground: str | None
    slots: list[PhotoSlot]
    preview_rotation: str
    preview_split: str


def compose(template_dir: Path, template_name: str, photos: list[str | Path], config: dict) -> Image.Image:
    """Compose photos onto a template. Returns print-ready image."""
    print_size = _validated_print_size(config)
    spec = _validated_template(
        config["templates"][template_name], template_name)
    required_photos = _required_photo_count(spec.slots)
    if len(photos) < required_photos:
        raise ValueError(
            f"template {template_name!r} needs {required_photos} photos, "
            f"got {len(photos)}"
        )
    with Image.open(template_dir / spec.background) as background:
        canvas = background.convert("RGB")
    if canvas.size != print_size:
        actual_size = canvas.size
        canvas.close()
        raise ValueError(
            f"template {template_name!r} background must be {print_size}, "
            f"got {actual_size}"
        )

    rendered: dict[tuple[int, str, int, int], tuple[Image.Image, int, int]] = {}
    try:
        for slot_index, slot in enumerate(spec.slots):
            if (slot.x + slot.width > canvas.width
                    or slot.y + slot.height > canvas.height):
                raise ValueError(
                    f"photo slot {slot_index} exceeds {template_name!r} "
                    f"background {canvas.size}"
                )
            cache_key = (
                slot.photo_index, slot.rotation, slot.width, slot.height)
            prepared = rendered.get(cache_key)
            if prepared is None:
                with Image.open(photos[slot.photo_index]) as source:
                    source_image = _oriented_rgb(source)
                try:
                    prepared = _render_photo(
                        source_image, slot.rotation, slot.width, slot.height)
                finally:
                    source_image.close()
                rendered[cache_key] = prepared
            image, offset_x, offset_y = prepared
            canvas.paste(image, (slot.x + offset_x, slot.y + offset_y))
        if spec.foreground is not None:
            _composite_foreground(
                canvas,
                template_dir / spec.foreground,
                print_size,
                template_name,
            )
        return canvas
    except Exception:
        canvas.close()
        raise
    finally:
        for image, _, _ in rendered.values():
            image.close()


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
    required_photos = max(
        template_photo_count(template, name)
        for name, template in templates.items()
    )
    if len(photos) < required_photos:
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


def _validated_template(
    template: dict,
    template_name: str,
) -> TemplateSpec:
    """Validate one template and return its layers, slots and preview settings."""
    if not isinstance(template, dict):
        raise ValueError(f"invalid template {template_name!r}")
    photo_width, photo_height = _validated_photo_size(template, template_name)
    layout = template.get("print_layout")
    if not isinstance(layout, dict):
        raise ValueError(f"template {template_name!r} print_layout must be an object")
    background = layout.get("background")
    if not isinstance(background, str) or not background:
        raise ValueError(f"template {template_name!r} needs a background")
    foreground = layout.get("foreground")
    if foreground is not None and (
        not isinstance(foreground, str) or not foreground
    ):
        raise ValueError(
            f"template {template_name!r} foreground must be a non-empty string"
        )
    raw_slots = layout.get("photos")
    if not isinstance(raw_slots, list) or not raw_slots:
        raise ValueError(f"template {template_name!r} has no photo slots")

    slots = []
    for slot_index, raw in enumerate(raw_slots):
        if not isinstance(raw, dict):
            raise ValueError(
                f"invalid photo slot {slot_index} in template {template_name!r}"
            )
        try:
            photo_index = raw["photo_index"]
            x = raw["x"]
            y = raw["y"]
            rotation = raw["rotate"]
        except KeyError as exc:
            raise ValueError(
                f"incomplete photo slot {slot_index} in template {template_name!r}"
            ) from exc
        if (not isinstance(photo_index, int) or isinstance(photo_index, bool)
                or photo_index < 0):
            raise ValueError(
                f"invalid photo_index in slot {slot_index} "
                f"of template {template_name!r}"
            )
        if (not isinstance(x, int) or isinstance(x, bool) or x < 0
                or not isinstance(y, int) or isinstance(y, bool) or y < 0):
            raise ValueError(
                f"invalid coordinates in slot {slot_index} "
                f"of template {template_name!r}"
            )
        _rotation_transpose(
            rotation,
            f"photo slot {slot_index} of template {template_name!r}",
        )
        slots.append(PhotoSlot(
            photo_index,
            x,
            y,
            photo_width,
            photo_height,
            rotation,
        ))

    required = _required_photo_count(slots)
    if {slot.photo_index for slot in slots} != set(range(required)):
        raise ValueError(
            f"template {template_name!r} must reference consecutive photos"
        )
    preview_rotation = template.get("preview_rotation")
    _rotation_transpose(
        preview_rotation,
        f"preview of template {template_name!r}",
    )
    preview_split = template.get("preview_split")
    if preview_split not in ("none", "horizontal"):
        raise ValueError(
            f"unsupported preview_split {preview_split!r} "
            f"in template {template_name!r}"
        )
    return TemplateSpec(
        background,
        foreground,
        slots,
        preview_rotation,
        preview_split,
    )


def _required_photo_count(slots: list[PhotoSlot]) -> int:
    return max(slot.photo_index for slot in slots) + 1


def template_photo_count(template: dict, template_name: str = "template") -> int:
    """Return how many distinct session photos a template references."""
    spec = _validated_template(template, template_name)
    return _required_photo_count(spec.slots)


def _composite_foreground(
    canvas: Image.Image,
    source_path: Path,
    print_size: tuple[int, int],
    template_name: str,
) -> None:
    with Image.open(source_path) as source:
        if source.size != print_size:
            raise ValueError(
                f"template {template_name!r} foreground must be {print_size}, "
                f"got {source.size}"
            )
        if "A" not in source.getbands():
            raise ValueError(
                f"template {template_name!r} foreground must have an alpha channel"
            )
        foreground = source.convert("RGBA")
    try:
        canvas.paste(foreground, (0, 0), foreground)
    finally:
        foreground.close()


def _validated_photo_size(
    template: dict,
    template_name: str,
) -> tuple[int, int]:
    raw = template.get("photo_size_px")
    if not isinstance(raw, dict):
        raise ValueError(f"template {template_name!r} photo_size_px must be an object")
    try:
        size = raw["width"], raw["height"]
    except KeyError as exc:
        raise ValueError(
            f"template {template_name!r} photo_size_px needs width and height"
        ) from exc
    if not all(isinstance(value, int) and value > 0 for value in size):
        raise ValueError(
            f"template {template_name!r} photo_size_px values must be positive integers"
        )
    return size


def _rotation_transpose(rotation: str, context: str):
    try:
        return ROTATION_TRANSPOSE[rotation]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"unsupported rotation {rotation!r} in {context}"
        ) from exc


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
    spec = _validated_template(
        config["templates"][template_name], template_name)
    required_photos = _required_photo_count(spec.slots)
    if len(photos) < required_photos:
        raise ValueError(
            f"template {template_name!r} needs {required_photos} photos"
        )

    source_path = template_dir / spec.background
    with Image.open(source_path) as source:
        source_size = source.size
    if source_size != print_size:
        raise ValueError(
            f"template {template_name!r} background must be {print_size}, "
            f"got {source_size}"
        )
    target_size = (
        preview_width,
        max(1, round(print_size[1] * preview_width / print_size[0])),
    )
    scale = preview_width / print_size[0]
    background_size = (
        max(1, round(source_size[0] * scale)),
        max(1, round(source_size[1] * scale)),
    )
    cache_path = source_path.with_name(f"{source_path.stem}_preview.jpg")
    _ensure_background_preview(source_path, cache_path, background_size)
    with Image.open(cache_path) as cached:
        background = cached.convert("RGB")

    rendered: dict[tuple[int, str, int, int], tuple[Image.Image, int, int]] = {}
    try:
        for slot_index, slot in enumerate(spec.slots):
            x = round(slot.x * scale)
            y = round(slot.y * scale)
            width = max(1, round((slot.x + slot.width) * scale) - x)
            height = max(1, round((slot.y + slot.height) * scale) - y)
            if (x < 0 or y < 0 or x + width > background.width
                    or y + height > background.height):
                raise ValueError(
                    f"preview slot {slot_index} exceeds "
                    f"{template_name!r} background"
                )
            cache_key = (slot.photo_index, slot.rotation, width, height)
            prepared = rendered.get(cache_key)
            if prepared is None:
                prepared = _render_photo(
                    photos[slot.photo_index], slot.rotation, width, height)
                rendered[cache_key] = prepared
            image, offset_x, offset_y = prepared
            background.paste(image, (x + offset_x, y + offset_y))
        if spec.foreground is not None:
            _composite_preview_foreground(
                background,
                template_dir / spec.foreground,
                print_size,
                background_size,
                template_name,
            )
    except Exception:
        background.close()
        raise
    finally:
        for image, _, _ in rendered.values():
            image.close()

    if spec.preview_split == "horizontal":
        try:
            return _present_split_preview(
                background,
                target_size,
                spec.preview_rotation,
                template_name,
            )
        finally:
            background.close()

    transpose = _rotation_transpose(
        spec.preview_rotation, f"preview of template {template_name!r}")
    if transpose is not None:
        rotated = background.transpose(transpose)
        background.close()
        background = rotated

    if background.size == target_size:
        return background
    try:
        return _fit_on_canvas(background, target_size, PREVIEW_CANVAS_COLOR)
    finally:
        background.close()


def _present_split_preview(
    sheet: Image.Image,
    target_size: tuple[int, int],
    rotation: str,
    template_name: str,
) -> Image.Image:
    """Show the two physical half-sheet strips separately on one canvas."""
    half_height = sheet.height // 2
    if half_height < 1:
        raise ValueError(f"template {template_name!r} preview is too short to split")
    pieces = [
        sheet.crop((0, 0, sheet.width, half_height)),
        sheet.crop((0, sheet.height - half_height, sheet.width, sheet.height)),
    ]
    transpose = _rotation_transpose(
        rotation, f"split preview of template {template_name!r}")
    if transpose is not None:
        rotated_pieces = []
        try:
            for piece in pieces:
                rotated_pieces.append(piece.transpose(transpose))
        except Exception:
            for piece in rotated_pieces:
                piece.close()
            raise
        finally:
            for piece in pieces:
                piece.close()
        pieces = rotated_pieces

    target_width, target_height = target_size
    gap = max(1, round(target_width * PREVIEW_SPLIT_GAP_RATIO))
    y_offset = max(0, round(target_height * PREVIEW_SPLIT_Y_OFFSET_RATIO))
    width_ratios = sum(piece.width / piece.height for piece in pieces)
    display_height = min(
        max(1, round(target_height * PREVIEW_SPLIT_HEIGHT_RATIO)),
        max(1, target_height - y_offset),
        max(1, int((target_width - gap) / width_ratios)),
    )

    resized = []
    try:
        for piece in pieces:
            width = max(1, round(piece.width * display_height / piece.height))
            resized.append(piece.resize(
                (width, display_height), Image.Resampling.LANCZOS))
    except Exception:
        for piece in resized:
            piece.close()
        raise
    finally:
        for piece in pieces:
            piece.close()

    group_width = sum(piece.width for piece in resized) + gap
    group_height = display_height + y_offset
    x = (target_width - group_width) // 2
    y = (target_height - group_height) // 2
    preview = Image.new("RGB", target_size, PREVIEW_CANVAS_COLOR)
    try:
        preview.paste(resized[0], (x, y))
        preview.paste(resized[1], (x + resized[0].width + gap, y + y_offset))
    finally:
        for piece in resized:
            piece.close()
    return preview


def _ensure_background_preview(
    source_path: Path,
    cache_path: Path,
    expected_size: tuple[int, int],
) -> None:
    if _preview_cache_is_fresh(source_path, cache_path, expected_size):
        return

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


def _composite_preview_foreground(
    canvas: Image.Image,
    source_path: Path,
    print_size: tuple[int, int],
    preview_size: tuple[int, int],
    template_name: str,
) -> None:
    cache_path = source_path.with_name(f"{source_path.stem}_preview.png")
    _ensure_foreground_preview(
        source_path,
        cache_path,
        print_size,
        preview_size,
        template_name,
    )
    with Image.open(cache_path) as cached:
        foreground = cached.convert("RGBA")
    try:
        canvas.paste(foreground, (0, 0), foreground)
    finally:
        foreground.close()


def _ensure_foreground_preview(
    source_path: Path,
    cache_path: Path,
    print_size: tuple[int, int],
    expected_size: tuple[int, int],
    template_name: str,
) -> None:
    with Image.open(source_path) as source:
        if source.size != print_size:
            raise ValueError(
                f"template {template_name!r} foreground must be {print_size}, "
                f"got {source.size}"
            )
        if "A" not in source.getbands():
            raise ValueError(
                f"template {template_name!r} foreground must have an alpha channel"
            )
        if _preview_cache_is_fresh(
            source_path,
            cache_path,
            expected_size,
            require_alpha=True,
        ):
            return
        source_image = source.convert("RGBA")

    try:
        reduced = _resize_rgba(source_image, expected_size)
    finally:
        source_image.close()
    try:
        _save_png_atomic(reduced, cache_path)
    finally:
        reduced.close()
    log.info("Template preview foreground cached: %s", cache_path)


def _preview_cache_is_fresh(
    source_path: Path,
    cache_path: Path,
    expected_size: tuple[int, int],
    require_alpha: bool = False,
) -> bool:
    if not cache_path.is_file():
        return False
    try:
        if cache_path.stat().st_mtime_ns < source_path.stat().st_mtime_ns:
            return False
        with Image.open(cache_path) as cached:
            return (
                cached.size == expected_size
                and (not require_alpha or "A" in cached.getbands())
            )
    except (OSError, ValueError):
        return False


def _resize_rgba(
    image: Image.Image,
    target_size: tuple[int, int],
) -> Image.Image:
    """Resize RGBA without dark fringes around translucent edges."""
    premultiplied = image.convert("RGBa")
    try:
        resized = premultiplied.resize(target_size, Image.Resampling.LANCZOS)
    finally:
        premultiplied.close()
    try:
        return resized.convert("RGBA")
    finally:
        resized.close()


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


def _save_png_atomic(image: Image.Image, output_path: Path) -> None:
    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        image.save(temporary, "PNG", optimize=True)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _render_photo(
    source: Image.Image,
    rotation: str,
    target_width: int,
    target_height: int,
) -> tuple[Image.Image, int, int]:
    """Apply a configured turn, then fit the whole photo into one slot."""
    transpose = _rotation_transpose(rotation, "photo slot")
    rotated = None
    image = source
    if transpose is not None:
        rotated = source.transpose(transpose)
        image = rotated
    try:
        return _fit_inside(image, target_width, target_height)
    finally:
        if rotated is not None:
            rotated.close()


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
