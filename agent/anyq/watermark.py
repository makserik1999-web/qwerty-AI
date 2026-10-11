"""Burn the trial mark into a finished video, keeping the clean render too.

The clean file is what the shared library keeps: the next teacher who asks
the same question gets the video without a trial's mark on it. The marked
copy is the one the trial account is shown.

ffmpeg runs here, in the agent, never in the render sandbox - this is the
agent's own file handling, the same as the narration merge.

If marking fails the clean video is returned: a trial teacher getting one
unmarked video is a smaller loss than a teacher getting no video.
"""

import asyncio
import os
import subprocess
import tempfile
from typing import Optional, Tuple

FONT = os.getenv("WATERMARK_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
TIMEOUT_SEC = 300


def _height(path: str) -> int:
    """The video's height in pixels, for sizing the mark; 720 if unknown."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=height", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        return int(out.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001 - a guess is good enough for a font size
        return 720


def marked_path(src: str) -> str:
    stem, ext = os.path.splitext(src)
    return f"{stem}_trial{ext or '.mp4'}"


def command(src: str, dst: str, textfile: str, height: int) -> list:
    size = max(14, round(height * 0.045))
    margin = max(8, round(height * 0.03))
    drawtext = (
        f"drawtext=fontfile={FONT}:textfile={textfile}:fontsize={size}"
        f":fontcolor=white@0.85:borderw=2:bordercolor=black@0.45"
        f":x=w-tw-{margin}:y=h-th-{margin}"
    )
    return [
        "ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf", drawtext,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", dst,
    ]


def watermark_sync(src: str, text: str) -> Optional[str]:
    """The marked copy's path, or None if ffmpeg could not make it."""
    dst = marked_path(src)
    # The text goes through a file: drawtext's own escaping of ':' and quotes
    # is a trap, and the text has a middle dot and Kazakh letters in it.
    fd, textfile = tempfile.mkstemp(prefix="wm_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        proc = subprocess.run(command(src, dst, textfile, _height(src)),
                              capture_output=True, text=True, timeout=TIMEOUT_SEC)
        if proc.returncode != 0 or not os.path.exists(dst):
            print(f"[watermark] ffmpeg failed: {(proc.stderr or '')[-300:]}", flush=True)
            return None
        return dst
    except Exception as e:  # noqa: BLE001 - fall back to the clean video
        print(f"[watermark] failed: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        try:
            os.remove(textfile)
        except OSError:
            pass


async def apply(video_path: str, text: Optional[str]) -> Tuple[str, str]:
    """(path to show, clean path for the library)."""
    if not video_path or not text:
        return video_path, video_path
    marked = await asyncio.to_thread(watermark_sync, video_path, str(text)[:40])
    return (marked or video_path), video_path
