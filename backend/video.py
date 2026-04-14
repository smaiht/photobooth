"""Record session video from live view JPEG frames.

Saves frames during session, stitches into mp4 via ffmpeg after session ends.
Finds capture gaps by timestamps and inserts photos there.
"""

import subprocess
import logging
import shutil
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
        self._frames_dir: Path | None = None
        self._frame_count = 0
        self._recording = False
        self._timestamps: list[float] = []
        self._frame_size: tuple[int, int] | None = None

    def start(self, session_dir: Path):
        self._frames_dir = session_dir / "_frames"
        self._frames_dir.mkdir(exist_ok=True)
        self._frame_count = 0
        self._timestamps = []
        self._frame_size = None
        self._recording = True
        log.info(f"Video recording started: {self._frames_dir}")

    def add_frame(self, jpeg_bytes: bytes):
        if not self._recording or not self._frames_dir:
            return
        self._timestamps.append(time.monotonic())
        frame_path = self._frames_dir / f"frame_{self._frame_count:05d}.jpg"
        frame_path.write_bytes(jpeg_bytes)
        if not self._frame_size:
            img = Image.open(io.BytesIO(jpeg_bytes))
            self._frame_size = img.size
        self._frame_count += 1

    def stop_and_encode(self, output_path: Path, photos: list[str] = None, fps: int = 30) -> str | None:
        self._recording = False

        if not self._frames_dir or self._frame_count == 0:
            return None

        if photos and self._frame_size:
            marks = self._find_gaps(len(photos))
            if marks:
                self._insert_photos(photos, marks, fps)

        log.info(f"Encoding {self._frame_count} frames to video...")

        try:
            kwargs = {"capture_output": True, "timeout": 60}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run([
                _FFMPEG, "-y",
                "-framerate", str(fps),
                "-i", str(self._frames_dir / "frame_%05d.jpg"),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "23",
                str(output_path),
            ], **kwargs)

            if result.returncode != 0:
                log.error(f"ffmpeg error: {result.stderr.decode()}")
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
            if self._frames_dir and self._frames_dir.exists():
                shutil.rmtree(self._frames_dir, ignore_errors=True)

    def _find_gaps(self, num_photos: int) -> list[int]:
        """Find N largest gaps in frame timestamps. Returns frame indices sorted ascending."""
        if len(self._timestamps) < 2:
            return []

        # Calculate all gaps
        gaps = [(self._timestamps[i] - self._timestamps[i - 1], i) for i in range(1, len(self._timestamps))]
        avg = sum(g[0] for g in gaps) / len(gaps)
        log.info(f"Video: {len(self._timestamps)} frames, avg interval {avg*1000:.1f}ms")

        # Log top 10 gaps
        gaps.sort(reverse=True)
        log.info(f"Video: top 10 gaps:")
        for dur, idx in gaps[:10]:
            log.info(f"  frame {idx}: {dur*1000:.0f}ms")

        # Take top N
        top = gaps[:num_photos]
        marks = sorted(g[1] for g in top)
        return marks

    def _insert_photos(self, photos: list[str], marks: list[int], fps: int):
        """Insert photos at gap positions."""
        freeze_frames = int(FREEZE_SECONDS * fps)
        w, h = self._frame_size

        for mark, photo_path in sorted(zip(marks, photos), reverse=True):
            if not Path(photo_path).exists():
                continue

            img = Image.open(photo_path)
            img = img.resize((w, h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            photo_bytes = buf.getvalue()

            for i in range(self._frame_count - 1, mark - 1, -1):
                src = self._frames_dir / f"frame_{i:05d}.jpg"
                dst = self._frames_dir / f"frame_{i + freeze_frames:05d}.jpg"
                if src.exists():
                    src.rename(dst)

            for i in range(freeze_frames):
                (self._frames_dir / f"frame_{mark + i:05d}.jpg").write_bytes(photo_bytes)

            self._frame_count += freeze_frames

        log.info(f"Inserted {len(photos)} photos ({freeze_frames} frames each)")
