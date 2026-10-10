"""GIF and mp4 from a selected range.

Both formats come from one module because they differ only in the encoder:
the same selection, the same size budget, the same shrink-and-retry. Keeping
them together is what stops the two drifting into different behaviour for the
same request.

The budget matters more than it looks. A 15-second 800px GIF at 20fps is
comfortably 60MB - large enough to fail an upload, fill a phone, or simply
never finish downloading on a school connection. So the result is measured,
and if it is over, it is rebuilt smaller (twice at most) rather than handed
over.
"""

from pathlib import Path
from typing import Any, Callable, Dict

from app import ffmpeg

MAX_SHRINK_ATTEMPTS = 2


def _build(
    render: Callable[..., None],
    source: Path,
    destination: Path,
    params: Dict[str, Any],
    max_bytes: int,
    on_progress: Callable[[int], None],
    **extra,
) -> Dict[str, Any]:
    start = float(params["start"])
    duration = float(params["end"]) - start
    fps = int(params["fps"])
    width = int(params["width"])
    caption = str(params.get("caption", ""))

    attempts = []
    for attempt in range(MAX_SHRINK_ATTEMPTS + 1):
        on_progress(20 + attempt * 25)
        render(
            source=source, destination=destination, start=start, duration=duration,
            fps=fps, width=width, caption=caption, **extra,
        )
        size = destination.stat().st_size
        attempts.append({"fps": fps, "width": width, "bytes": size})

        if size <= max_bytes:
            break

        next_fps, next_width = ffmpeg.shrink_step(fps, width)
        if (next_fps, next_width) == (fps, width):
            # Already at the smallest setting. Hand over what we have with the
            # measurement attached, rather than failing outright - the caller
            # decides whether to offer the mp4 instead.
            break
        print(
            f"[clip] {size / 1e6:.1f}MB over the {max_bytes / 1e6:.0f}MB budget, "
            f"retrying at {next_width}px/{next_fps}fps"
        )
        fps, width = next_fps, next_width

    final = destination.stat().st_size
    return {
        "bytes": final,
        "fps": fps,
        "width": width,
        "over_budget": final > max_bytes,
        "attempts": attempts,
    }


def run_gif(source: Path, destination: Path, params: Dict[str, Any],
            max_bytes: int, on_progress: Callable[[int], None]) -> Dict[str, Any]:
    return _build(
        ffmpeg.render_gif, source, destination, params, max_bytes, on_progress,
        loop=bool(params.get("loop", True)),
    )


def run_clip(source: Path, destination: Path, params: Dict[str, Any],
             max_bytes: int, on_progress: Callable[[int], None]) -> Dict[str, Any]:
    return _build(
        ffmpeg.render_clip, source, destination, params, max_bytes, on_progress,
    )


def run_frame(source: Path, destination: Path, params: Dict[str, Any],
              max_bytes: int, on_progress: Callable[[int], None]) -> Dict[str, Any]:
    on_progress(50)
    ffmpeg.extract_frame(source, destination, at=float(params.get("at", 0)))
    return {"bytes": destination.stat().st_size, "over_budget": False}
