#!/usr/bin/env python3
"""Build social-media samples from one real photobooth session.

Every sheet is composed by the production ``backend.composer``, so the samples
are pixel-identical to what the printer receives. Three views are produced:

* ``print/``   full ``print_size`` raster exactly as sent to the DNP driver;
* ``paper/``   the sheet cropped to ``print_trim.visible_size``, i.e. what the
               guest actually holds, plus strips cut and rotated upright;
* ``web/``     the ``paper/`` view downscaled for a social-media post.

The session's own photos and video are copied verbatim into ``source/``.

Usage:
    venv/bin/python marketing/generate_samples.py <session.zip|session_dir> \
        [--pack kvas01aug26] [--out marketing/samples]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.composer import (  # noqa: E402  (path setup must run first)
    ROTATION_TRANSPOSE,
    compose,
    compose_unframed_photo,
)
from backend.text_layer import date_values  # noqa: E402

TEMPLATES_DIR = PROJECT_ROOT / "templates"
VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v")
WEB_LONG_EDGE = 2048
JPEG_QUALITY_PRINT = 95
JPEG_QUALITY_WEB = 88


def _default_pack() -> str:
    config = json.loads((PROJECT_ROOT / "config_app.json").read_text("utf-8"))
    pack = config.get("template_pack")
    if not isinstance(pack, str) or not pack:
        raise SystemExit("config_app.json has no template_pack")
    return pack


def _session_media(source: Path, workdir: Path) -> tuple[str, list[Path], list[Path]]:
    """Return the session name, its photo_NN.jpg files and its videos.

    A .zip is unpacked into ``workdir`` first. Both photos and video are taken
    straight from the session as the guest received it; nothing is re-encoded.
    """
    if source.is_dir():
        media_dir = source
        name = source.name
    elif source.suffix.lower() == ".zip":
        name = source.stem
        media_dir = workdir / name
        media_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                filename = Path(entry.filename).name
                lowered = filename.lower()
                is_photo = filename.startswith("photo_") and lowered.endswith(".jpg")
                is_video = lowered.endswith(VIDEO_SUFFIXES)
                if not (is_photo or is_video):
                    continue
                with archive.open(entry) as src, \
                        open(media_dir / filename, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    else:
        raise SystemExit(f"expected a session folder or .zip, got {source}")

    photos = sorted(media_dir.glob("photo_*.jpg"))
    if not photos:
        raise SystemExit(f"no photo_*.jpg found in {media_dir}")
    videos = sorted(
        path for path in media_dir.iterdir()
        if path.is_file() and path.name.lower().endswith(VIDEO_SUFFIXES)
    )
    return name, photos, videos


def _trim_box(config: dict) -> tuple[int, int, int, int] | None:
    trim = config.get("print_trim")
    if not isinstance(trim, dict):
        return None
    width, height = config["print_size"]
    left = int(trim.get("left", 0))
    top = int(trim.get("top", 0))
    right = int(trim.get("right", 0))
    bottom = int(trim.get("bottom", 0))
    return left, top, width - right, height - bottom


def _save(image: Image.Image, path: Path, quality: int, dpi: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    options = {"quality": quality, "subsampling": 0, "optimize": True}
    if dpi is not None:
        options["dpi"] = (dpi, dpi)
    image.save(path, "JPEG", **options)


def _web_copy(image: Image.Image) -> Image.Image:
    scale = WEB_LONG_EDGE / max(image.size)
    if scale >= 1:
        return image.copy()
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _emit(
    sheet: Image.Image,
    name: str,
    out_dir: Path,
    trim: tuple[int, int, int, int] | None,
    print_dpi: int,
    split: str,
    rotation: str,
) -> list[Path]:
    """Write print, paper and web views of one composed sheet."""
    written: list[Path] = []
    print_path = out_dir / "print" / f"{name}.jpg"
    _save(sheet, print_path, JPEG_QUALITY_PRINT, print_dpi)
    written.append(print_path)

    paper = sheet.crop(trim) if trim else sheet.copy()
    try:
        pieces: list[tuple[str, Image.Image]] = []
        if split == "horizontal":
            half = paper.height // 2
            for index, box in enumerate(
                ((0, 0, paper.width, half), (0, half, paper.width, paper.height)),
                start=1,
            ):
                piece = paper.crop(box)
                transpose = ROTATION_TRANSPOSE.get(rotation)
                if transpose is not None:
                    rotated = piece.transpose(transpose)
                    piece.close()
                    piece = rotated
                pieces.append((f"{name}_cut_{index:02d}", piece))
        else:
            pieces.append((name, paper.copy()))

        for piece_name, piece in pieces:
            paper_path = out_dir / "paper" / f"{piece_name}.jpg"
            _save(piece, paper_path, JPEG_QUALITY_PRINT, print_dpi)
            written.append(paper_path)
            web = _web_copy(piece)
            try:
                web_path = out_dir / "web" / f"{piece_name}.jpg"
                _save(web, web_path, JPEG_QUALITY_WEB, None)
                written.append(web_path)
            finally:
                web.close()
            piece.close()
    finally:
        paper.close()
    return written


def _session_date(session_name: str) -> datetime:
    """Date of the session itself, so samples match the printed sheet.

    Session folders are named ``2026-08-08_09-20-43_<id>``. Without that prefix
    there is nothing to recover, and today's date is the honest fallback.
    """
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})", session_name)
    if not match:
        print(
            f"note: {session_name} has no date prefix; using today",
            file=sys.stderr,
        )
        return datetime.now()
    return datetime(*(int(value) for value in match.groups()))


def build(source: Path, pack: str, out_root: Path) -> Path:
    template_dir = TEMPLATES_DIR / pack
    config_path = template_dir / "config.json"
    if not config_path.is_file():
        raise SystemExit(f"template pack {pack!r} has no config.json")
    config = json.loads(config_path.read_text("utf-8"))
    config.setdefault("print_size", [3688, 2480])
    app_config = json.loads((PROJECT_ROOT / "config_app.json").read_text("utf-8"))
    print_dpi = int(app_config.get("print_dpi", 600))
    trim = _trim_box(config)

    with tempfile.TemporaryDirectory(prefix="marketing_session_") as tmp:
        session_name, photos, videos = _session_media(source, Path(tmp))
        session_dir = out_root / session_name
        out_dir = session_dir / pack
        shutil.rmtree(out_dir, ignore_errors=True)
        source_dir = session_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        for media in (*photos, *videos):
            shutil.copy2(media, source_dir / media.name)
        if not videos:
            print(f"note: {session_name} has no video", file=sys.stderr)

        written: list[Path] = []
        text_values = date_values(_session_date(session_name))
        for template_name, template in config["templates"].items():
            split = template.get("preview_split", "none")
            rotation = template.get("preview_rotation", "none")
            if template.get("photo_choice"):
                for index, photo in enumerate(photos, start=1):
                    framed = compose(
                        template_dir, template_name, [photo], config,
                        text_values=text_values)
                    try:
                        written += _emit(
                            framed,
                            f"{template_name}_{index:02d}_frame",
                            out_dir,
                            trim,
                            print_dpi,
                            split,
                            rotation,
                        )
                    finally:
                        framed.close()
                    plain = compose_unframed_photo(photo, config)
                    try:
                        written += _emit(
                            plain,
                            f"{template_name}_{index:02d}_plain",
                            out_dir,
                            trim,
                            print_dpi,
                            split,
                            rotation,
                        )
                    finally:
                        plain.close()
                continue
            sheet = compose(
                template_dir, template_name, photos, config,
                text_values=text_values)
            try:
                written += _emit(
                    sheet, template_name, out_dir, trim, print_dpi, split, rotation
                )
            finally:
                sheet.close()

    for path in sorted(written):
        print(path.relative_to(PROJECT_ROOT))
    print(f"\n{len(written)} files in {out_dir.relative_to(PROJECT_ROOT)}")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="session .zip or unpacked folder")
    parser.add_argument("--pack", default=None, help="template pack name")
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "marketing" / "samples",
        help="output root",
    )
    args = parser.parse_args()
    build(args.session.resolve(), args.pack or _default_pack(), args.out.resolve())


if __name__ == "__main__":
    main()
