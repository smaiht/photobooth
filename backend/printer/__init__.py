"""Direct Windows printing for the DNP DS-RX1HS.

The DNP driver receives a print-ready bitmap through a Windows printer device
context.  No shell association or hot-folder watcher is involved.
"""

import asyncio
import io
import logging
from collections import deque
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

_print_queue: deque[dict] = deque()
_printing = False
DEFAULT_CUSTOM_PRINT_SIZE = (3688, 2480)
MAX_CUSTOM_PRINT_PIXELS = 100_000_000


def prepare_custom_print(
    payload: bytes,
    output_path: str | Path,
    print_size: tuple[int, int] = DEFAULT_CUSTOM_PRINT_SIZE,
    dpi: int = 600,
) -> str:
    """Render one arbitrary image onto a horizontal 4x6 page without cropping."""
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("empty print image")
    if (len(print_size) != 2
            or not all(isinstance(value, int) and value > 0 for value in print_size)):
        raise ValueError("invalid custom print size")

    with Image.open(io.BytesIO(payload)) as source:
        if source.width * source.height > MAX_CUSTOM_PRINT_PIXELS:
            raise ValueError("изображение слишком большое: максимум 100 Мп")
        oriented = ImageOps.exif_transpose(source)
        try:
            if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
                rgba.close()
            else:
                image = oriented.convert("RGB")
        finally:
            if oriented is not source:
                oriented.close()

    source_size = image.size
    landscape = image.width > image.height
    if not landscape:
        rotated = image.transpose(Image.Transpose.ROTATE_90)
        image.close()
        image = rotated

    long_side = max(print_size)
    short_side = min(print_size)
    canvas_size = (long_side, short_side)
    canvas = Image.new("RGB", canvas_size, "white")
    try:
        scale = min(canvas.width / image.width, canvas.height / image.height)
        fitted_size = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        if fitted_size != image.size:
            fitted = image.resize(fitted_size, Image.Resampling.LANCZOS)
            image.close()
            image = fitted
        x = (canvas.width - image.width) // 2
        y = (canvas.height - image.height) // 2
        canvas.paste(image, (x, y))

        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        canvas.save(
            temporary,
            "JPEG",
            quality=95,
            subsampling=0,
            dpi=(int(dpi), int(dpi)),
        )
        temporary.replace(destination)
        log.info(
            "Custom print prepared: source=%sx%s orientation=%s rotated_ccw=%s "
            "output=%sx%s path=%s",
            source_size[0], source_size[1],
            "landscape" if landscape else "portrait",
            not landscape,
            canvas.width, canvas.height,
            destination,
        )
    finally:
        image.close()
        canvas.close()
    return "горизонтальная" if landscape else "вертикальная"


async def enqueue_print(
    image_path: str,
    config: dict,
    template_name: str = "",
    delete_after: bool = False,
):
    """Add one print job to the serial printer queue."""
    _print_queue.append({
        "path": image_path,
        "config": dict(config),
        "template": template_name,
        "delete_after": bool(delete_after),
    })
    asyncio.create_task(_process_queue())


async def _process_queue():
    global _printing
    if _printing:
        return

    while _print_queue:
        _printing = True
        job = _print_queue.popleft()
        try:
            await asyncio.to_thread(
                _do_print,
                job["path"],
                job["config"],
                job["template"],
            )
            log.info(f"Printed: {job['path']}")
        except Exception as exc:
            log.error(f"Print failed: {exc}")
        finally:
            if job["delete_after"]:
                try:
                    Path(job["path"]).unlink(missing_ok=True)
                except OSError as exc:
                    log.warning("Could not remove custom print cache %s: %s", job["path"], exc)
        _printing = False


def _printer_name(config: dict, template_name: str) -> str:
    """Select an optional second queue for DNP's 2-inch cutter setting."""
    if template_name == "strips":
        strips_name = str(config.get("printer_name_strips", "")).strip()
        if strips_name:
            return strips_name
    return str(config.get("printer_name", "")).strip()


def _set_devmode(devmode, config: dict, win32con) -> None:
    """Set standard print fields; DNP private options stay in queue defaults."""
    quality = int(config.get("print_dpi", 600))
    if quality not in (300, 600):
        raise ValueError("print_dpi must be 300 or 600")
    copies = int(config.get("print_copies", 1))
    if copies != 1:
        raise ValueError("DS-RX1HS is configured for exactly one copy per job")

    fields = int(getattr(devmode, "Fields", 0))
    fields |= win32con.DM_PAPERSIZE | win32con.DM_ORIENTATION
    fields |= win32con.DM_COPIES | win32con.DM_PRINTQUALITY
    fields |= win32con.DM_YRESOLUTION | win32con.DM_COLOR | win32con.DM_SCALE
    fields |= win32con.DM_ICMMETHOD | win32con.DM_ICMINTENT
    devmode.Fields = fields

    # DNP's GPD names paper option PC (4x6) as option ID 202.
    devmode.PaperSize = int(config.get("print_paper_size", 202))
    # DNP's default portrait driver orientation produces a 6x4 landscape sheet.
    orientation = str(config.get("print_orientation", "portrait")).lower()
    if orientation not in ("portrait", "landscape"):
        raise ValueError("print_orientation must be portrait or landscape")
    devmode.Orientation = (
        win32con.DMORIENT_LANDSCAPE
        if orientation == "landscape"
        else win32con.DMORIENT_PORTRAIT
    )
    devmode.Copies = copies
    devmode.PrintQuality = quality
    devmode.YResolution = quality
    devmode.Color = win32con.DMCOLOR_COLOR
    devmode.Scale = 100
    # DNP's documented default is host ICM with Pictures intent (contrast).
    devmode.ICMMethod = win32con.DMICMMETHOD_SYSTEM
    devmode.ICMIntent = win32con.DMICM_CONTRAST


def _prepare_for_page(
    image_path: str,
    page_size: tuple[int, int],
    page_dpi: tuple[int, int] = (1, 1),
) -> Image.Image:
    """Orient/crop an image to a printer page, accounting for asymmetric DPI."""
    page_w, page_h = page_size
    dpi_x, dpi_y = page_dpi
    if page_w <= 0 or page_h <= 0 or dpi_x <= 0 or dpi_y <= 0:
        raise ValueError(f"invalid printer page: size={page_size}, dpi={page_dpi}")

    physical_w = page_w / dpi_x
    physical_h = page_h / dpi_y
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    if (image.width > image.height) != (physical_w > physical_h):
        image = image.transpose(Image.Transpose.ROTATE_90)

    target_ratio = physical_w / physical_h
    source_ratio = image.width / image.height
    if source_ratio > target_ratio:
        crop_w = max(1, int(image.height * target_ratio))
        left = (image.width - crop_w) // 2
        image = image.crop((left, 0, left + crop_w, image.height))
    elif source_ratio < target_ratio:
        crop_h = max(1, int(image.width / target_ratio))
        top = (image.height - crop_h) // 2
        image = image.crop((0, top, image.width, top + crop_h))
    return image.resize((page_w, page_h), Image.Resampling.LANCZOS)


def _print_driver(image_path: str, config: dict, template_name: str = ""):
    """Render one job directly into the configured Windows printer DC."""
    if not Path(image_path).is_file():
        raise FileNotFoundError(f"print image not found: {image_path}")

    try:
        import win32con
        import win32gui
        import win32print
        import win32ui
        from PIL import ImageWin
    except ImportError as exc:
        raise RuntimeError("Windows printing requires pywin32 and Pillow ImageWin") from exc

    selected_printer = _printer_name(config, template_name) or win32print.GetDefaultPrinter()
    handle = win32print.OpenPrinter(selected_printer)
    dc = None
    image = None
    document_started = False
    try:
        printer_info = win32print.GetPrinter(handle, 2)
        devmode = printer_info.get("pDevMode")
        if devmode is None:
            raise RuntimeError(f"printer has no DEVMODE: {selected_printer}")
        _set_devmode(devmode, config, win32con)
        result = win32print.DocumentProperties(
            0,
            handle,
            selected_printer,
            devmode,
            devmode,
            win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER,
        )
        if result < 0:
            raise RuntimeError(f"DNP driver rejected print settings: {result}")

        raw_handle = win32gui.CreateDC("WINSPOOL", selected_printer, devmode)
        dc = win32ui.CreateDCFromHandle(raw_handle)
        page_size = (
            dc.GetDeviceCaps(win32con.HORZRES),
            dc.GetDeviceCaps(win32con.VERTRES),
        )
        page_dpi = (
            dc.GetDeviceCaps(win32con.LOGPIXELSX),
            dc.GetDeviceCaps(win32con.LOGPIXELSY),
        )
        image = _prepare_for_page(image_path, page_size, page_dpi)
        dib = ImageWin.Dib(image)

        log.info(
            f"Printing to {selected_printer}: source={Path(image_path).name}, "
            f"page={page_size[0]}x{page_size[1]} dpi={page_dpi[0]}x{page_dpi[1]}"
        )
        dc.StartDoc(Path(image_path).name)
        document_started = True
        dc.StartPage()
        dib.draw(dc.GetHandleOutput(), (0, 0, page_size[0], page_size[1]))
        dc.EndPage()
        dc.EndDoc()
        document_started = False
    except Exception:
        if document_started and dc is not None:
            try:
                dc.AbortDoc()
            except Exception:
                pass
        raise
    finally:
        if image is not None:
            image.close()
        if dc is not None:
            dc.DeleteDC()
        win32print.ClosePrinter(handle)


def _do_print(image_path: str, config: dict, template_name: str = ""):
    """Execute one direct-driver print in a worker thread."""
    _print_driver(image_path, config, template_name)
