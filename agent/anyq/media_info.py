"""What a finished video actually is: how long, and whether it has sound.

Read from the file with ffprobe rather than taken from the graph's intent:
narration can fail and leave a silent video behind, and the admin panel's
"silent videos" filter is only useful if it reports what was delivered.
"""

import json
import subprocess
from typing import Any, Dict


def probe(path: str) -> Dict[str, Any]:
    """{"duration": seconds or None, "has_audio": bool or None}."""
    if not path:
        return {"duration": None, "has_audio": None}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout or "{}")
        duration = float((data.get("format") or {}).get("duration") or 0) or None
        has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams") or [])
        return {"duration": round(duration, 1) if duration else None, "has_audio": has_audio}
    except Exception:  # noqa: BLE001 - unknown is an honest answer
        return {"duration": None, "has_audio": None}
