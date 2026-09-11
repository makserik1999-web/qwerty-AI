"""Run telemetry: one JSON line per processed websocket request.

Standard library only. `agent_ws_client.process_request` calls new_run() when
a request comes in and write() once, in its own finally, to flush the line
and clear the slot. `anyq.nodes.generate_manim_script` calls record() and
note_guard_rewrite() along the way to add the fields it alone can see.

The record is a plain module-level dict, not part of ScienceVideoState - its
fields must never become part of the graph's state schema. agent_ws_client
processes one websocket message at a time (each loop iteration awaits
process_request fully before receiving the next), so a single module-level
slot is enough - there is no cross-request concurrency to guard against here.
Within one request, generate_manim_script and educator_answer do run
concurrently (the educate_and_script parallel group), but both only ever
touch their own keys of the same dict and never await between reading and
writing them, so plain dict mutation is safe.

Any failure while writing the log must never break the pipeline: every
exception is caught and only printed as a warning.
"""

import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from anyq.config import ANYQ_TELEMETRY_PATH

_write_lock = threading.Lock()

_current: Optional[dict] = None


def new_run(request_id: Any, user_message: str) -> None:
    """Start a new run record. Called once, at the top of process_request."""
    global _current
    # Privacy: never store raw user content - only a sha256 and the length.
    user_text = user_message or ""
    _current = {
        "run_id": str(uuid.uuid4()),
        "request_id": request_id,
        "user_message_sha256": hashlib.sha256(user_text.encode("utf-8")).hexdigest(),
        "user_message_len": len(user_text),
        "language": "",
        "is_science": False,
        "subject": "",
        "video_needed": False,
        "educator_text_len": 0,
        "script_len": 0,
        "guard_rewrites": [],
        "render_attempt": None,
        "render_ok": False,
        "render_error_tail": "",
        "status": "error",
        "error_type": "",
        "_started": time.monotonic(),
    }


def record(**fields: Any) -> None:
    """Add/overwrite fields on the current run. No-op if there is no run."""
    if _current is not None:
        _current.update(fields)


def note_guard_rewrite(name: str, fixed: bool) -> None:
    """Record that a guard fired, and whether its rewrite was accepted.

    `fixed` is True only when the rewritten script passed the guard's own
    re-check and replaced the script generate_manim_script goes on to use.
    """
    if _current is not None:
        _current["guard_rewrites"].append({"guard": name, "fired": True, "fixed": fixed})


def write() -> None:
    """Write the current run as one JSON line and clear the slot.

    Never raises - a telemetry failure must not take the pipeline down with it.
    """
    global _current
    run = _current
    _current = None
    if run is None:
        return
    try:
        entry = {
            "run_id": run["run_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": run["request_id"],
            "user_message_sha256": run["user_message_sha256"],
            "user_message_len": run["user_message_len"],
            "language": run["language"],
            "is_science": run["is_science"],
            "subject": run["subject"],
            "video_needed": run["video_needed"],
            "educator_text_len": run["educator_text_len"],
            "script_len": run["script_len"],
            "guard_rewrites": run["guard_rewrites"],
            "render_attempt": run["render_attempt"],
            "render_ok": run["render_ok"],
            "render_error_tail": run["render_error_tail"],
            "duration_ms": int((time.monotonic() - run["_started"]) * 1000),
            "status": run["status"],
            "error_type": run["error_type"],
        }

        path = ANYQ_TELEMETRY_PATH
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        line = json.dumps(entry, ensure_ascii=False)
        # Two sinks, and the file is the one that lasts. Stdout is bounded by
        # docker's log rotation and is per-container, so recreating the
        # container starts an empty log - which is how a day of runs came to
        # be unaccounted for. The file lives on its own volume and survives
        # both. Stdout stays because it is what `docker compose logs` shows
        # while something is being watched live.
        print(f"TELEMETRY {line}", flush=True)
        with _write_lock, open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception as e:
        print(f"[telemetry] failed to write run log: {type(e).__name__}: {e}", flush=True)
