"""Windows image printing for the DNP DS-RX1HS.

Ready JPEGs are submitted through Windows' built-in image print handler.  The
DNP driver receives the saved defaults of the selected printer queue, including
its private options such as 2-inch cutting.
"""

import asyncio
import io
import locale
import logging
import os
import subprocess
from collections import deque
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception as exc:
    log.warning("HEIC/HEIF image decoder is unavailable: %s", exc)

_print_queue: deque[dict] = deque()
_printing = False
DEFAULT_CUSTOM_PRINT_SIZE = (3688, 2480)
MAX_CUSTOM_PRINT_PIXELS = 100_000_000


def prepare_custom_print(
    payload: bytes,
    output_path: str | Path,
    print_size: tuple[int, int] = DEFAULT_CUSTOM_PRINT_SIZE,
    dpi: int = 600,
    mode: str = "fit",
) -> str:
    """Render one arbitrary image onto a horizontal 4x6 print page."""
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("empty print image")
    if (len(print_size) != 2
            or not all(isinstance(value, int) and value > 0 for value in print_size)):
        raise ValueError("invalid custom print size")
    if mode not in ("fit", "fill"):
        raise ValueError("invalid custom print mode")

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
        scales = (canvas.width / image.width, canvas.height / image.height)
        scale = min(scales) if mode == "fit" else max(scales)
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
        output_bytes = destination.stat().st_size
        log.info(
            "Custom print prepared: source=%sx%s orientation=%s rotated_ccw=%s mode=%s "
            "scale=%.3fx fitted=%sx%s margins=%s,%s,%s,%s "
            "output=%sx%s jpeg=%s bytes path=%s",
            source_size[0], source_size[1],
            "landscape" if landscape else "portrait",
            not landscape,
            mode,
            scale,
            image.width, image.height,
            x, canvas.width - image.width - x,
            y, canvas.height - image.height - y,
            canvas.width, canvas.height,
            output_bytes,
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
    delete_paths: list[str] | None = None,
):
    """Add one print job to the serial printer queue."""
    _print_queue.append({
        "path": image_path,
        "config": dict(config),
        "template": template_name,
        "delete_after": bool(delete_after),
        "delete_paths": list(delete_paths or []),
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
            log.info("Print submitted to Windows: %s", job["path"])
        except Exception as exc:
            log.error(f"Print failed: {exc}")
        finally:
            cleanup_paths = list(job["delete_paths"])
            if job["delete_after"]:
                cleanup_paths.insert(0, job["path"])
            cleanup_parents: set[Path] = set()
            for cleanup_path in dict.fromkeys(cleanup_paths):
                try:
                    path = Path(cleanup_path)
                    path.unlink(missing_ok=True)
                    cleanup_parents.add(path.parent)
                except OSError as exc:
                    log.warning(
                        "Could not remove custom print file %s: %s",
                        cleanup_path, exc,
                    )
            for parent in cleanup_parents:
                try:
                    parent.rmdir()
                except OSError:
                    pass
        _printing = False


def _printer_name(config: dict, template_name: str) -> str:
    """Select an optional second queue for DNP's 2-inch cutter setting."""
    if template_name == "strips":
        strips_name = str(config.get("printer_name_strips", "")).strip()
        if strips_name:
            return strips_name
    return str(config.get("printer_name", "")).strip()


def _print_driver(image_path: str, config: dict, template_name: str = ""):
    """Submit one image through Windows' built-in silent PrintTo handler."""
    source = Path(image_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"print image not found: {source}")

    with Image.open(source) as print_image:
        page_width, page_height = print_image.size
        raw_dpi = print_image.info.get("dpi") or (0, 0)
        if isinstance(raw_dpi, (tuple, list)) and len(raw_dpi) >= 2:
            page_dpi = (
                round(float(raw_dpi[0])),
                round(float(raw_dpi[1])),
            )
        else:
            page_dpi = (0, 0)
    log.info(
        "Print raster: source=%s page=%sx%s dpi=%sx%s template=%s",
        source.name,
        page_width,
        page_height,
        page_dpi[0],
        page_dpi[1],
        template_name or "custom",
    )
    if (page_width, page_height) != DEFAULT_CUSTOM_PRINT_SIZE:
        log.warning(
            "Print raster differs from DNP (6x4) Portrait 600 DPI page: "
            "source=%s actual=%sx%s expected=%sx%s",
            source.name,
            page_width,
            page_height,
            DEFAULT_CUSTOM_PRINT_SIZE[0],
            DEFAULT_CUSTOM_PRINT_SIZE[1],
        )

    try:
        import win32print
    except ImportError as exc:
        raise RuntimeError("Windows printing requires pywin32") from exc

    selected_printer = _printer_name(config, template_name) or win32print.GetDefaultPrinter()
    handle = win32print.OpenPrinter(selected_printer)
    try:
        printer_info = win32print.GetPrinter(handle, 2)
        driver_name = str(printer_info.get("pDriverName") or "")
        port_name = str(printer_info.get("pPortName") or "")
        devmode = printer_info.get("pDevMode")
    finally:
        win32print.ClosePrinter(handle)

    if not driver_name or not port_name:
        raise RuntimeError(
            f"printer driver or port is missing: {selected_printer}"
        )

    if devmode is not None:
        paper_size = int(getattr(devmode, "PaperSize", 0))
        orientation = int(getattr(devmode, "Orientation", 0))
        quality = int(getattr(devmode, "PrintQuality", 0))
        y_resolution = int(getattr(devmode, "YResolution", 0))
        copies = int(getattr(devmode, "Copies", 0))
        log.info(
            "Printer queue defaults: printer=%s paper_size=%s orientation=%s "
            "quality=%sx%s copies=%s",
            selected_printer,
            paper_size,
            {1: "portrait", 2: "landscape"}.get(orientation, orientation),
            quality,
            y_resolution,
            copies,
        )
        # DNP's official V1.13 table maps a 3688x2480 raster to the (6x4)
        # paper form (ID 202) with the seemingly counter-intuitive Portrait
        # orientation.  PR(4x6) is a different, vertical 2480x3688 form.
        if paper_size != 202 or orientation != 1:
            log.warning(
                "DNP queue defaults do not match horizontal 3688x2480 output: "
                "printer=%s expected paper_size=202 ((6x4)) and "
                "orientation=portrait",
                selected_printer,
            )

    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    rundll32 = Path(system_root) / "System32" / "rundll32.exe"
    image_print_dll = Path(system_root) / "System32" / "shimgvw.dll"
    if not rundll32.is_file() or not image_print_dll.is_file():
        raise RuntimeError("Windows image print handler is unavailable")

    command = [
        str(rundll32),
        f"{image_print_dll},ImageView_PrintTo",
        "/pt",
        str(source),
        selected_printer,
        driver_name,
        port_name,
    ]
    log.info(
        "Submitting print through Windows image handler: printer=%s "
        "driver=%s port=%s source=%s bytes=%s",
        selected_printer, driver_name, port_name, source.name, source.stat().st_size,
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            timeout=60,
            creationflags=creation_flags,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Windows image print handler timed out: {selected_printer}"
        ) from exc
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        suffix = f": {details}" if details else ""
        raise RuntimeError(
            f"Windows image print handler failed with code "
            f"{completed.returncode}{suffix}"
        )


def _do_print(image_path: str, config: dict, template_name: str = ""):
    """Submit one print in a worker thread."""
    _print_driver(image_path, config, template_name)
