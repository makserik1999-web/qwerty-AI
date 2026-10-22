"""How much of a finished video stands still.

ffmpeg's freezedetect, run over the rendered file and summed: a stretch counts
as static when for at least FREEZE_MIN_SEC the picture changes by less than
FREEZE_NOISE_DB - about a seventh of one grey level on average, so anything a
viewer could see move counts as motion. static_share is the static seconds
over the video's length; the motion layer (MOTION_LAYER=1) aims for under 5%.

Measured, not inferred from the script, for the same reason media_info probes
the file: what matters is what was delivered.

Never raises. A video whose stillness could not be measured is reported as
unmeasured (an empty dict), not as perfectly still or perfectly alive.
"""

from __future__ import annotations

import re
import subprocess
from typing import Dict, Optional

FREEZE_NOISE_DB = -66
FREEZE_MIN_SEC = 0.3
TIMEOUT_SEC = 180

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_EVENT_RE = re.compile(r"lavfi\.freezedetect\.freeze_(start|end):\s*(-?\d+(?:\.\d+)?)")


def command(path: str) -> list:
    return [
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-map", "0:v:0",
        "-vf", f"freezedetect=n={FREEZE_NOISE_DB}dB:d={FREEZE_MIN_SEC}",
        "-f", "null", "-",
    ]


def parse(log: str, duration: Optional[float] = None) -> Dict[str, float]:
    """static_seconds and static_share out of ffmpeg's log.

    A freeze still running when the video ends has a start and no end;
    it lasts to the end of the video.
    """
    if duration is None:
        match = _DURATION_RE.search(log or "")
        if match:
            h, m, s = match.groups()
            duration = int(h) * 3600 + int(m) * 60 + float(s)
    if not duration or duration <= 0:
        return {}

    static, start = 0.0, None
    for kind, value in _EVENT_RE.findall(log or ""):
        t = float(value)
        if kind == "start":
            start = t
        elif start is not None:
            static += max(0.0, t - start)
            start = None
    if start is not None:
        static += max(0.0, duration - start)

    static = min(static, duration)
    return {
        "static_seconds": round(static, 2),
        "static_share": round(static / duration, 4),
        "duration": round(duration, 2),
    }


def measure(path: str) -> Dict[str, float]:
    """{"static_seconds", "static_share", "duration"}, or {} if unmeasured."""
    if not path:
        return {}
    try:
        proc = subprocess.run(command(path), capture_output=True, text=True,
                              timeout=TIMEOUT_SEC)
    except Exception as exc:  # noqa: BLE001 - a metric must never break a request
        print(f"[motion] freezedetect failed: {type(exc).__name__}", flush=True)
        return {}
    if proc.returncode != 0:
        print(f"[motion] freezedetect failed: {(proc.stderr or '')[-200:]}", flush=True)
        return {}
    return parse(proc.stderr)
