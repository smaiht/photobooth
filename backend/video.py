"""Record session video from live view JPEG frames.

Saves frames during session, stitches into mp4 via ffmpeg after session ends.
~30fps × 30sec = ~900 frames × ~50KB = ~45MB temp disk usage.
"""

import subprocess
import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# ffmpeg: check bundled bin/ first, then system PATH
if getattr(sys, 'frozen', False):
    _BIN_DIR = Path(sys._MEIPASS) / "bin"
else:
    _BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
_FFMPEG = str(_BIN_DIR / "ffmpeg.exe") if (_BIN_DIR / "ffmpeg.exe").exists() else "ffmpeg"


class VideoRecorder:
    def __init__(self):
        self._frames_dir: Path | None = None
        self._frame_count = 0
        self._recording = False

    def start(self, session_dir: Path):
        self._frames_dir = session_dir / "_frames"
        self._frames_dir.mkdir(exist_ok=True)
        self._frame_count = 0
        self._recording = True
        log.info(f"Video recording started: {self._frames_dir}")

    def add_frame(self, jpeg_bytes: bytes):
        if not self._recording or not self._frames_dir:
            return
        frame_path = self._frames_dir / f"frame_{self._frame_count:05d}.jpg"
        frame_path.write_bytes(jpeg_bytes)
        self._frame_count += 1

    def stop_and_encode(self, output_path: Path, fps: int = 30) -> str | None:
        """Stop recording and encode frames to mp4. Returns path or None on failure."""
        self._recording = False

        if not self._frames_dir or self._frame_count == 0:
            return None

        log.info(f"Encoding {self._frame_count} frames to video...")

        try:
            result = subprocess.run([
                _FFMPEG, "-y",
                "-framerate", str(fps),
                "-i", str(self._frames_dir / "frame_%05d.jpg"),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "23",
                str(output_path),
            ], capture_output=True, timeout=60)

            if result.returncode != 0:
                log.error(f"ffmpeg error: {result.stderr.decode()}")
                return None

            log.info(f"Video saved: {output_path}")
            return str(output_path)

        except FileNotFoundError:
            log.error("ffmpeg not found — install ffmpeg to enable video recording")
            return None
        except Exception as e:
            log.error(f"Video encoding failed: {e}")
            return None
        finally:
            # Cleanup temp frames
            if self._frames_dir and self._frames_dir.exists():
                shutil.rmtree(self._frames_dir, ignore_errors=True)
