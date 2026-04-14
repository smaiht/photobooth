"""Record session video from live view JPEG frames.

Frames buffered in memory. At encode time piped directly to ffmpeg — no temp files.
Photos frozen for 1.5s at capture positions.
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
        self._frames: list[bytes] = []
        self._frame_size: tuple[int, int] | None = None
        self._recording = False
        self._skip_until = 0.0
        self._photo_marks: list[tuple[int, str]] = []

    def start(self, session_dir: Path):
        self._frames = []
        self._frame_size = None
        self._skip_until = 0.0
        self._photo_marks = []
        self._recording = True
        log.info("Video recording started")

    def add_frame(self, jpeg_bytes: bytes):
        if not self._recording:
            return
        if time.monotonic() < self._skip_until:
            return
        if not self._frame_size:
            img = Image.open(io.BytesIO(jpeg_bytes))
            self._frame_size = img.size
        self._frames.append(jpeg_bytes)

    def insert_photo(self, photo_path: str):
        """Lightweight marker. Called from EDSDK thread."""
        self._photo_marks.append((len(self._frames), photo_path))
        self._skip_until = time.monotonic() + FREEZE_SECONDS
        log.info(f"Video: photo mark at frame {len(self._frames)}")

    def stop_and_encode(self, output_path: Path, fps: int = 30) -> str | None:
        self._recording = False

        if not self._frames or not self._frame_size:
            return None

        freeze_frames = int(FREEZE_SECONDS * fps)
        w, h = self._frame_size

        # Prepare photo freeze bytes
        photo_data = {}
        for mark, photo_path in self._photo_marks:
            if not Path(photo_path).exists():
                continue
            img = Image.open(photo_path)
            img = img.resize((w, h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            photo_data[mark] = buf.getvalue()

        total = len(self._frames) + len(photo_data) * freeze_frames
        log.info(f"Encoding {total} frames ({len(self._frames)} live + {len(photo_data)} photos)...")

        try:
            cmd = [
                _FFMPEG, "-y",
                "-f", "image2pipe", "-framerate", str(fps),
                "-i", "-",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "23",
                str(output_path),
            ]
            popen_kw = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
            if sys.platform == "win32":
                popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW

            proc = subprocess.Popen(cmd, **popen_kw)

            for i, frame in enumerate(self._frames):
                if i in photo_data:
                    for _ in range(freeze_frames):
                        proc.stdin.write(photo_data[i])
                proc.stdin.write(frame)

            proc.stdin.close()
            _, stderr = proc.communicate(timeout=120)
            self._frames = []

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
            self._frames = []
            return None
