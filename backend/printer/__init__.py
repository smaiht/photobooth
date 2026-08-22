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
import threading
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
# Printing and administrative spooler operations must not overlap, otherwise
# the reported before/after counts could be sampled while the Windows image
# handler is still submitting a job.
_windows_spooler_lock = threading.Lock()
DEFAULT_CUSTOM_PRINT_SIZE = (3688, 2480)
MAX_CUSTOM_PRINT_PIXELS = 100_000_000
DNP_STATUS_DLL = (
    Path(__file__).resolve().parents[2]
    / "drivers"
    / "RX1-Information"
    / "CyStat64.dll"
)

_DNP_STATUS_LABELS = {
    0x00010001: "готов к печати",
    0x00010002: "печатает",
    0x00010008: "закончилась бумага",
    0x00010010: "закончилась лента",
    0x00010020: "охлаждается печатающая головка",
    0x00010040: "охлаждается двигатель",
    0x00020001: "открыта передняя крышка",
    0x00020002: "замята бумага",
    0x00020004: "ошибка ленты",
    0x00020008: "не совпадает размер бумаги",
    0x00020010: "ошибка данных",
    0x00020020: "ошибка контейнера обрезков",
    0x80000000: "не подключён",
}


def print_queue_busy() -> bool:
    """Return whether the application is waiting for or submitting a print."""
    return _printing or bool(_print_queue)


def _win32print():
    """Import pywin32 lazily so the booth can still run on development hosts."""
    try:
        import win32print
    except ImportError as exc:
        raise RuntimeError("Windows printing requires pywin32") from exc
    return win32print


def _resolved_queue_names(config: dict, win32print) -> list[tuple[str, str]]:
    """Return the concrete Windows queue for each logical print target."""
    default_name: str | None = None
    result: list[tuple[str, str]] = []
    for target in ("grid", "strips"):
        name = _printer_name(config, target)
        if not name:
            if default_name is None:
                default_name = str(win32print.GetDefaultPrinter() or "").strip()
            name = default_name
        if not name:
            raise RuntimeError(
                f"Не задано имя Windows-принтера для очереди {target}"
            )
        result.append((target, name))
    return result


def _queue_job_count(win32print, handle) -> int:
    """Count the jobs Windows currently exposes in the queue."""
    # DNP's level-2 ``cJobs`` counter can remain stale after the visible job
    # has disappeared.  EnumJobs is also what the queue UI is based on, so the
    # administrator sees the same count here and in Windows.
    jobs = win32print.EnumJobs(handle, 0, 0x7FFFFFFF, 1)
    return len(jobs)


def _open_for_clear(win32print, printer_name):
    """Open a queue with administer access, falling back to normal access.

    A kiosk account may be allowed to delete its own jobs without the
    administrator right.  The fallback lets the per-job deletion path work in
    that configuration while still allowing a true queue-wide purge whenever
    Windows grants it.
    """
    desired_access = getattr(win32print, "PRINTER_ACCESS_ADMINISTER", None)
    if desired_access is not None:
        try:
            return win32print.OpenPrinter(
                printer_name,
                {"DesiredAccess": desired_access},
            )
        except Exception as exc:
            log.info(
                "Could not open printer %s with administer access; "
                "trying normal access: %s",
                printer_name,
                exc,
            )
    return win32print.OpenPrinter(printer_name)


def _delete_jobs_individually(win32print, handle) -> tuple[int, list[str]]:
    """Delete jobs one by one for queues where purge access is unavailable."""
    try:
        jobs = win32print.EnumJobs(handle, 0, 0x7FFFFFFF, 1)
    except Exception as exc:
        return 0, [str(exc)]
    deleted = 0
    errors: list[str] = []
    command = getattr(win32print, "JOB_CONTROL_DELETE", 5)
    for job in jobs:
        job_id = job.get("JobId") if isinstance(job, dict) else None
        if type(job_id) is not int:
            errors.append("Windows returned a job without JobId")
            continue
        try:
            win32print.SetJob(handle, job_id, 0, None, command)
            deleted += 1
        except Exception as exc:
            errors.append(f"job {job_id}: {exc}")
    return deleted, errors


def get_windows_print_queues(
    config: dict,
) -> list[dict]:
    """Return Windows spooler counts for the grid and strips queues.

    The returned records intentionally contain both the logical target and the
    resolved Windows queue name.  This makes a fallback to the default printer
    visible to an administrator instead of silently reporting an ambiguous
    number.
    """
    win32print = _win32print()
    queue_names = _resolved_queue_names(dict(config or {}), win32print)
    records: list[dict] = []
    with _windows_spooler_lock:
        for logical_target, printer_name in queue_names:
            handle = None
            record = {
                "target": logical_target,
                "printer_name": printer_name,
                "jobs": None,
                "error": None,
            }
            try:
                handle = win32print.OpenPrinter(printer_name)
                record["jobs"] = _queue_job_count(win32print, handle)
            except Exception as exc:
                record["error"] = str(exc)
                log.warning(
                    "Could not inspect Windows printer queue %s (%s): %s",
                    logical_target,
                    printer_name,
                    exc,
                )
            finally:
                if handle is not None:
                    try:
                        win32print.ClosePrinter(handle)
                    except Exception:
                        log.exception("Could not close printer handle %s", printer_name)
            records.append(record)
    return records


def _load_dnp_status_library():
    """Load the official 64-bit DS-RX1 status library."""
    if os.name != "nt":
        raise RuntimeError("Состояние DNP доступно только на Windows")
    if not DNP_STATUS_DLL.is_file():
        raise RuntimeError(f"Не найдена библиотека DNP: {DNP_STATUS_DLL}")

    import ctypes

    try:
        library = ctypes.WinDLL(str(DNP_STATUS_DLL), use_last_error=True)
        library.CvInitialize.argtypes = (ctypes.c_wchar_p,)
        library.CvInitialize.restype = ctypes.c_int
        for name in (
            "CvGetStatus",
            "GetCounterL",
            "GetMediaCountOffset",
            "GetMediaCounter",
            "GetInitialMediaCount",
        ):
            function = getattr(library, name)
            function.argtypes = (ctypes.c_int,)
            function.restype = ctypes.c_int
        return library
    except (AttributeError, OSError) as exc:
        raise RuntimeError(f"Не удалось загрузить библиотеку DNP: {exc}") from exc


def _dnp_status_label(status: int) -> str:
    status &= 0xFFFFFFFF
    known = _DNP_STATUS_LABELS.get(status)
    if known:
        return known
    if status & 0x00040000:
        return f"аппаратная ошибка (0x{status:08X})"
    if status & 0x00080000:
        return f"системная ошибка (0x{status:08X})"
    return f"неизвестное состояние (0x{status:08X})"


def get_dnp_printer_info(config: dict) -> dict:
    """Read the DS-RX1 hardware counter and loaded-media balance."""
    win32print = _win32print()
    _target, printer_name = _resolved_queue_names(
        dict(config or {}),
        win32print,
    )[0]

    with _windows_spooler_lock:
        handle = None
        try:
            handle = win32print.OpenPrinter(printer_name)
            printer = win32print.GetPrinter(handle, 2)
            if not isinstance(printer, dict):
                raise RuntimeError("Windows не вернул сведения о принтере")
            if _queue_job_count(win32print, handle):
                raise RuntimeError(
                    "принтер сейчас печатает; повторите команду после завершения"
                )
            port_name = str(printer.get("pPortName") or "").strip()
            if not port_name:
                raise RuntimeError("Windows не вернул порт принтера")
        finally:
            if handle is not None:
                try:
                    win32print.ClosePrinter(handle)
                except Exception:
                    log.exception("Could not close printer handle %s", printer_name)

        library = _load_dnp_status_library()
        port_number = int(library.CvInitialize(port_name))
        if port_number <= 0:
            raise RuntimeError(f"DNP не открыл порт {port_name}")

        status_code = int(library.CvGetStatus(port_number)) & 0xFFFFFFFF
        total_count = int(library.GetCounterL(port_number))
        if total_count < 0:
            raise RuntimeError(
                "счётчики недоступны — "
                + _dnp_status_label(status_code)
            )

        # This is the same correction used by DNP's RX1-Information utility.
        media_offset = int(library.GetMediaCountOffset(port_number))
        if media_offset < 0:
            media_offset = 50
        media_count = int(library.GetMediaCounter(port_number))
        initial_media_count = int(library.GetInitialMediaCount(port_number))

    return {
        "printer_name": printer_name,
        "port_name": port_name,
        "status": _dnp_status_label(status_code),
        "status_code": status_code,
        "total_count": total_count,
        "media_remaining": (
            max(0, media_count - media_offset)
            if media_count >= 0 else None
        ),
        "media_capacity": (
            initial_media_count - media_offset
            if initial_media_count >= media_offset else None
        ),
    }


def _clear_one_windows_queue(win32print, printer_name: str) -> dict:
    handle = None
    record = {
        "printer_name": printer_name,
        "jobs_before": None,
        "jobs_after": None,
        "cleared": 0,
        "error": None,
    }
    try:
        handle = _open_for_clear(win32print, printer_name)
        record["jobs_before"] = _queue_job_count(win32print, handle)
        failure_detail = None
        if record["jobs_before"]:
            purge_command = getattr(win32print, "PRINTER_CONTROL_PURGE", 3)
            purge_error = None
            try:
                win32print.SetPrinter(handle, 0, None, purge_command)
            except Exception as exc:
                purge_error = exc

            # Some Windows accounts can manage their own jobs but cannot use
            # PRINTER_CONTROL_PURGE.  Fall back to deleting every enumerated
            # job, then report any jobs which remained inaccessible.
            if purge_error is not None:
                log.info(
                    "Printer-wide purge failed for %s; deleting jobs one by one: %s",
                    printer_name,
                    purge_error,
                )
                deleted, deletion_errors = _delete_jobs_individually(
                    win32print,
                    handle,
                )
                log.info(
                    "Individual Windows job deletion for %s: deleted=%d errors=%d",
                    printer_name,
                    deleted,
                    len(deletion_errors),
                )
                if deletion_errors:
                    failure_detail = deletion_errors[0]

        record["jobs_after"] = _queue_job_count(win32print, handle)
        before = record["jobs_before"] or 0
        after = record["jobs_after"] or 0
        record["cleared"] = max(0, before - after)
        if after:
            suffix = f"; {failure_detail}" if failure_detail else ""
            record["error"] = (
                f"после очистки осталось заданий: {after}{suffix}"
            )
    except Exception as exc:
        record["error"] = str(exc)
        log.warning(
            "Could not clear Windows printer queue %s: %s",
            printer_name,
            exc,
        )
    finally:
        if handle is not None:
            try:
                win32print.ClosePrinter(handle)
            except Exception:
                log.exception("Could not close printer handle %s", printer_name)
    return record


def clear_windows_print_queues(
    config: dict,
) -> list[dict]:
    """Clear both Windows spooler queues and return before/after counts."""
    win32print = _win32print()
    queue_names = _resolved_queue_names(dict(config or {}), win32print)
    selected: list[str] = []
    for _logical_target, printer_name in queue_names:
        if printer_name not in selected:
            selected.append(printer_name)

    by_name: dict[str, dict] = {}
    with _windows_spooler_lock:
        for printer_name in selected:
            by_name[printer_name] = _clear_one_windows_queue(
                win32print,
                printer_name,
            )

    records = []
    first_target_by_name: dict[str, str] = {}
    for logical_target, printer_name in queue_names:
        record = dict(by_name[printer_name])
        record["target"] = logical_target
        if printer_name in first_target_by_name:
            record["shared_with"] = first_target_by_name[printer_name]
        else:
            first_target_by_name[printer_name] = logical_target
        records.append(record)
    return records


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
        form_name = str(getattr(devmode, "FormName", "") or "")
        orientation = int(getattr(devmode, "Orientation", 0))
        quality = int(getattr(devmode, "PrintQuality", 0))
        y_resolution = int(getattr(devmode, "YResolution", 0))
        copies = int(getattr(devmode, "Copies", 0))
        log.info(
            "Printer level-2 defaults (diagnostic only): printer=%s "
            "paper_size=%s form=%r orientation=%s quality=%sx%s copies=%s",
            selected_printer,
            paper_size,
            form_name,
            {1: "portrait", 2: "landscape"}.get(orientation, orientation),
            quality,
            y_resolution,
            copies,
        )
        # PRINTER_INFO_2 contains generic queue defaults, not necessarily the
        # effective per-user settings consumed by Windows' image handler for
        # this job.  Keep these values for diagnostics, but do not validate a
        # working print path against driver-specific PaperSize numeric IDs.


        # # PREV THOUGHT LOGIC:
        # # DNP's official V1.13 table maps a 3688x2480 raster to the (6x4)
        # # paper form (ID 202) with the seemingly counter-intuitive Portrait
        # # orientation.  PR(4x6) is a different, vertical 2480x3688 form.
        # if paper_size != 202 or orientation != 1:
        #     log.warning(
        #         "DNP queue defaults do not match horizontal 3688x2480 output: "
        #         "printer=%s expected paper_size=202 ((6x4)) and "
        #         "orientation=portrait",
        #         selected_printer,
        #     )


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
    with _windows_spooler_lock:
        _print_driver(image_path, config, template_name)
