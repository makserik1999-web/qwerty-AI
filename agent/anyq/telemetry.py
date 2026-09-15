"""Run telemetry: one JSON line per processed websocket request.

Standard library only. `agent_ws_client.process_request` calls new_run() when
a request comes in and write() once, in its own finally, to flush the line
and clear the slot. `anyq.nodes.generate_manim_script` calls record() and
note_guard_rewrite() along the way to add the fields it alone can see.

The record is a dict held in a ContextVar, not part of ScienceVideoState -
its fields must never become part of the graph's state schema.

It used to be a plain module-level slot, on the reasoning that agent_ws_client
processes one websocket message at a time. That stopped being true when the
agent was split into a reader and a worker: an assessment or an embedding now
runs as its own task alongside a generation, so a second new_run() would have
overwritten the video's record, every record() from the graph would have
landed on the wrong one, and write() would have flushed a mixture. A ContextVar
gives each task its own binding, which is exactly the shape of the problem.

Within one request, generate_manim_script and educator_answer still run
concurrently (the educate_and_script parallel group). That is safe and stays
safe: a task inherits the BINDING, so both see the same dict, and both only
ever touch their own keys of it and never await between reading and writing
them.

Any failure while writing the log must never break the pipeline: every
exception is caught and only printed as a warning.
"""

import contextvars
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

# Per-task, so an assessment written while a video renders cannot overwrite
# the video's record. `Optional[dict]` as before; only where it lives changed.
_current: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "anyq_telemetry_current", default=None
)


def new_run(request_id: Any, user_message: str, kind: str = "video") -> None:
    """Start a new run record. Called once, at the top of a request.

    `kind` says which kind of request this line is about. It defaults to
    "video" so every existing caller and every existing reader of the log
    keeps meaning what it did; "assessment" is the other one, and its line
    leaves the video-shaped fields at their defaults rather than inventing
    values for them.
    """
    # Privacy: never store raw user content - only a sha256 and the length.
    # For an assessment that content is the topic.
    user_text = user_message or ""
    _current.set({
        "run_id": str(uuid.uuid4()),
        "request_id": request_id,
        "kind": kind,
        "user_message_sha256": hashlib.sha256(user_text.encode("utf-8")).hexdigest(),
        "user_message_len": len(user_text),
        "language": "",
        "is_science": False,
        "subject": "",
        "video_needed": False,
        # The chosen length and what the narration actually came to. Both are
        # recorded by _fit_narration_budget; both used to be dropped on the
        # way out, because write() copies a fixed list of keys and these two
        # were not on it. So the one question the length control exists to
        # answer - did the video come out the length that was asked for -
        # could not be answered from the log at all.
        "video_length": "",
        "narration_chars": 0,
        "educator_text_len": 0,
        "script_len": 0,
        "guard_rewrites": [],
        "render_attempt": None,
        "render_ok": False,
        "render_error_tail": "",
        "status": "error",
        "error_type": "",
        # Assessments only: how many questions were asked for and how many
        # came back usable. _validate reports a short paper rather than
        # padding it, which is the right behaviour and was until now
        # invisible - nobody could count how often it happened.
        "items_requested": 0,
        "items_produced": 0,
        "_started": time.monotonic(),
    })


def record(**fields: Any) -> None:
    """Add/overwrite fields on the current run. No-op if there is no run."""
    run = _current.get()
    if run is not None:
        run.update(fields)


def note_guard_rewrite(name: str, fixed: bool) -> None:
    """Record that a guard fired, and whether its rewrite was accepted.

    `fixed` is True only when the rewritten script passed the guard's own
    re-check and replaced the script generate_manim_script goes on to use.
    """
    run = _current.get()
    if run is not None:
        run["guard_rewrites"].append({"guard": name, "fired": True, "fixed": fixed})


def write() -> None:
    """Write the current run as one JSON line and clear the slot.

    Never raises - a telemetry failure must not take the pipeline down with it.
    """
    run = _current.get()
    _current.set(None)
    if run is None:
        return
    try:
        entry = {
            "run_id": run["run_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": run["request_id"],
            "kind": run["kind"],
            "user_message_sha256": run["user_message_sha256"],
            "user_message_len": run["user_message_len"],
            "language": run["language"],
            "is_science": run["is_science"],
            "subject": run["subject"],
            "video_needed": run["video_needed"],
            "video_length": run["video_length"],
            "narration_chars": run["narration_chars"],
            "educator_text_len": run["educator_text_len"],
            "script_len": run["script_len"],
            "guard_rewrites": run["guard_rewrites"],
            "render_attempt": run["render_attempt"],
            "render_ok": run["render_ok"],
            "render_error_tail": run["render_error_tail"],
            "duration_ms": int((time.monotonic() - run["_started"]) * 1000),
            "items_requested": run["items_requested"],
            "items_produced": run["items_produced"],
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
