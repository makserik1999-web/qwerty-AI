"""Running ffmpeg, and the two things that make it safe to run on user input.

**Filtergraph injection.** A filtergraph is parsed, not passed as data: a
caption containing `,` or `'` or `[` changes what filters run. So caption text
is never interpolated into the graph - it is written to a file and read back
with drawtext's `textfile=`, which takes the bytes as they are. Kazakh
captions need this doubly: no escaping table has to be right.

**Runaway encodes.** Every call has a timeout and every process is killed on
the way out. A GIF of a badly chosen range can otherwise pin a core for as
long as the container lives.
"""

import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Bundled with the agent image and installed here too; it carries Cyrillic,
# the Kazakh-specific letters and the subscripts used in formulas.
CAPTION_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


class FfmpegError(RuntimeError):
    """ffmpeg exited non-zero. Carries the tail of stderr, which is the reason."""


def _run(args: List[str], timeout: int) -> str:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise FfmpegError(f"ffmpeg timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise FfmpegError("ffmpeg is not installed in this image") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-400:]
        raise FfmpegError(tail or f"ffmpeg exited {proc.returncode}")
    return proc.stdout


def probe_duration(path: Path, timeout: int = 30) -> float:
    out = _run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        timeout,
    )
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def _caption_filter(text: str, tmpdir: Path) -> Optional[str]:
    """A drawtext filter whose text lives in a file, not in the graph."""
    if not text.strip():
        return None
    caption_file = tmpdir / "caption.txt"
    caption_file.write_text(text.strip(), encoding="utf-8")
    if not Path(CAPTION_FONT).is_file():
        # No font, no caption. Losing the subtitle is better than losing the
        # export, and better than rendering it as boxes.
        print(f"[ffmpeg] caption skipped: {CAPTION_FONT} is missing")
        return None
    return (
        f"drawtext=fontfile={CAPTION_FONT}:textfile={caption_file}"
        ":fontcolor=white:fontsize=h/18:box=1:boxcolor=black@0.55:boxborderw=10"
        ":x=(w-text_w)/2:y=h-text_h-20"
    )


def render_gif(
    source: Path, destination: Path, start: float, duration: float,
    fps: int, width: int, loop: bool, caption: str = "", timeout: int = 300,
) -> None:
    """Two-pass palette. A single pass quantises to a fixed 216-colour palette
    and the result looks like 1998; palettegen builds one from these frames.
    """
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmpdir = Path(raw_tmp)
        steps = [f"fps={fps}", f"scale={width}:-1:flags=lanczos"]
        caption_filter = _caption_filter(caption, tmpdir)
        if caption_filter:
            steps.append(caption_filter)
        chain = ",".join(steps)

        graph = (
            f"{chain},split[a][b];"
            "[a]palettegen=max_colors=128[p];"
            "[b][p]paletteuse=dither=bayer"
        )
        _run(
            [FFMPEG, "-y", "-v", "error",
             "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
             "-vf", graph,
             "-loop", "0" if loop else "-1",
             str(destination)],
            timeout,
        )


def render_clip(
    source: Path, destination: Path, start: float, duration: float,
    fps: int, width: int, caption: str = "", timeout: int = 300,
) -> None:
    """An mp4 of the same selection: ten to twenty times smaller than the GIF."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmpdir = Path(raw_tmp)
        # -2 rather than -1: h264 needs even dimensions, and an odd height
        # from an arbitrary aspect ratio fails the encode outright.
        steps = [f"fps={fps}", f"scale={width}:-2:flags=lanczos"]
        caption_filter = _caption_filter(caption, tmpdir)
        if caption_filter:
            steps.append(caption_filter)

        _run(
            [FFMPEG, "-y", "-v", "error",
             "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
             "-vf", ",".join(steps),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             # The animations are silent; carrying an empty audio track only
             # makes the file bigger and some players unhappy.
             "-an",
             str(destination)],
            timeout,
        )


def extract_frame(source: Path, destination: Path, at: float, timeout: int = 60) -> None:
    _run(
        [FFMPEG, "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(source),
         "-frames:v", "1", str(destination)],
        timeout,
    )


def describe(args: List[str]) -> str:
    """The command as a copy-pasteable line, for logs."""
    return " ".join(shlex.quote(a) for a in args)


def shrink_step(fps: int, width: int) -> Tuple[int, int]:
    """The next size down, for a result that came out over budget.

    Width first: halving the pixel count cuts far more than dropping frames,
    and a smaller still-smooth clip reads better than a full-size stuttering
    one.
    """
    widths = [320, 480, 640, 800]
    rates = [10, 15, 20]
    if width in widths and widths.index(width) > 0:
        return fps, widths[widths.index(width) - 1]
    if fps in rates and rates.index(fps) > 0:
        return rates[rates.index(fps) - 1], width
    return fps, width


def scene_change_times(source: Path, threshold: float, timeout: int = 180) -> List[float]:
    """Timestamps where the picture changes substantially.

    Used to pick slide frames: a Manim animation is a sequence of distinct
    states, and its transitions are exactly what this filter reports. Fixed
    intervals would land mid-transition and give a deck of half-drawn shapes.

    The timestamps come from `showinfo` on stderr, which is where ffmpeg puts
    filter diagnostics; `-f null` means nothing is encoded, only analysed.
    """
    proc = subprocess.run(
        [FFMPEG, "-v", "info", "-i", str(source),
         "-vf", f"select='gt(scene,{threshold})',showinfo",
         "-vsync", "vfr", "-f", "null", "-"],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    # A video with no detected change exits 0 with no matches; that is a valid
    # answer, not a failure, so the return code is not treated as one.
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", proc.stderr or "")]
