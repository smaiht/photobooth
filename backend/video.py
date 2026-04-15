"""Record session video from live view JPEG frames.

Collects frames in memory + photo placeholders. Assembles video at end via ffmpeg pipe.
"""

import subprocess
import logging
import sys
import time
from pathlib import Path
from PIL import Image
import io

log = logging.getLogger(__name__)

_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
_FFMPEG = str(_BIN_DIR / "ffmpeg.exe") if (_BIN_DIR / "ffmpeg.exe").exists() else "ffmpeg"

FREEZE_SECONDS = 1.5


class VideoRecorder:
    def __init__(self):
        self._items: list[bytes | str] = []  # bytes=frame, str=photo path
        self._frame_size: tuple[int, int] | None = None
        self._recording = False
        self._skip_until = 0.0
        self._session_dir: Path | None = None
        self._placeholders: list[int] = []  # indices in _items where photos go

    def start(self, session_dir: Path):
        self._items = []
        self._frame_size = None
        self._skip_until = 0.0
        self._session_dir = session_dir
        self._placeholders = []
        self._photo_idx = 0
        self._recording = True
        log.info("Video recording started")

    def add_frame(self, jpeg_bytes: bytes):
        if not self._recording or time.monotonic() < self._skip_until:
            return
        if not self._frame_size:
            img = Image.open(io.BytesIO(jpeg_bytes))
            self._frame_size = img.size
        self._items.append(jpeg_bytes)

    def mark_photo(self):
        """Placeholder for photo + skip 1.5s of frames. Called at take_picture time."""
        idx = len(self._items)
        self._items.append(None)  # placeholder
        self._placeholders.append(idx)
        self._skip_until = time.monotonic() + FREEZE_SECONDS
        log.info(f"Video: photo placeholder at index {idx}")

    def set_photo_path(self, photo_path: str):
        """Fill next placeholder with actual photo path. Called in order of capture."""
        idx = self._placeholders[self._photo_idx]
        self._items[idx] = photo_path
        self._photo_idx += 1
        log.info(f"Video: placeholder {idx} -> {photo_path}")

    def stop_and_encode(self, fps: int = 30) -> str | None:
        self._recording = False
        if not self._items or not self._frame_size:
            return None

        output_path = self._session_dir / "session.mp4"
        freeze_frames = int(FREEZE_SECONDS * fps)
        w, h = self._frame_size

        cmd = [
            _FFMPEG, "-y", "-loglevel", "warning",
            "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", "-crf", "23",
            str(output_path),
        ]
        popen_kw = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if sys.platform == "win32":
            popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            proc = subprocess.Popen(cmd, **popen_kw)
            for item in self._items:
                if item is None:
                    continue
                if isinstance(item, str):
                    data = self._photo_to_jpeg(item, w, h)
                    if data:
                        for _ in range(freeze_frames):
                            proc.stdin.write(data)
                else:
                    proc.stdin.write(item)

            proc.stdin.close()
            _, stderr = proc.communicate(timeout=120)
            self._items = []

            if proc.returncode != 0:
                log.error(f"ffmpeg error: {stderr.decode()}")
                return None

            log.info(f"Video saved: {output_path}")
            return str(output_path)

        except FileNotFoundError:
            log.error("ffmpeg not found")
            return None
        except Exception as e:
            log.error(f"Video encoding failed: {e}")
            return None
        finally:
            self._items = []

    @staticmethod
    def _photo_to_jpeg(photo_path: str, w: int, h: int) -> bytes | None:
        if not Path(photo_path).exists():
            return None
        img = Image.open(photo_path)
        img = img.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return buf.getvalue()
