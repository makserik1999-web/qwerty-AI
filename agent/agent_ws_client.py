"""
WebSocket AI Agent client wrapper for Science Manim Graph Agent.

This connects to the backend server endpoint (default: ws://backend:8000/ws/agent),
receives JSON requests, runs the existing science_manim_graph_agent pipeline,
and returns JSON responses.

Expected incoming message (JSON):
{
  "request_id": "abc123",
  "text": "Explain X thoroughly",
  "image_data": "<base64 or data-url>"  # optional
}

Outgoing message (JSON):
{
  "request_id": "abc123",
  "status": "complete" | "error",
  "text": "<final_text>",
  "video_path": "<path or empty>",
  "error": "<error string if any>"
}
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import tempfile
from typing import Any, Dict, Optional, Tuple

# Environment and the user-facing failure message now live in the anyq package.
# Importing anyq.config is also what calls load_dotenv().
from anyq.config import (
    DEFAULT_WS_URL,
    RECONNECT_DELAY_SEC,
    WS_PING_INTERVAL_SEC,
    WS_PING_TIMEOUT_SEC,
)
from anyq.language import (  # noqa: F401 - _GENERIC_FAILURE_MESSAGES re-exported
    _GENERIC_FAILURE_MESSAGES,
    _friendly_failure_text,
)
from anyq import telemetry

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<b64>.+)$", re.DOTALL)


def _decode_image_data(image_data: str) -> Tuple[bytes, str]:
    """
    Decode `image_data` which may be either:
    - raw base64 string
    - data URL: data:image/jpeg;base64,....
    Returns (bytes, file_extension).
    """
    s = (image_data or "").strip()
    if not s:
        raise ValueError("empty image_data")

    m = _DATA_URL_RE.match(s)
    if m:
        mime = (m.group("mime") or "").lower().strip()
        b64 = (m.group("b64") or "").strip()
        img_bytes = base64.b64decode(b64, validate=False)
        ext = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }.get(mime, ".jpg")
        return img_bytes, ext

    # Assume it's base64 with no prefix
    img_bytes = base64.b64decode(s, validate=False)
    return img_bytes, ".jpg"


def _materialize_image_to_tempfile(image_data: str) -> str:
    img_bytes, ext = _decode_image_data(image_data)
    fd, path = tempfile.mkstemp(prefix="agent_img_", suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(img_bytes)
    return path


async def process_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs the science manim graph agent for a single websocket request.
    """
    from science_manim_graph_agent import app

    request_id = payload.get("request_id")
    text = (payload.get("text") or "").strip()
    image_data = payload.get("image_data")

    telemetry.new_run(request_id, text)
    tmp_image_path: Optional[str] = None
    try:
        if not request_id:
            raise ValueError("Missing request_id")
        if not text:
            raise ValueError("Missing text")

        initial: Dict[str, Any] = {"user_message": text}
        if image_data:
            tmp_image_path = _materialize_image_to_tempfile(str(image_data))
            initial["image_path"] = tmp_image_path

        result = await app.invoke(initial)
        final_text = (result.get("final_text") or "").strip()
        video_path = (result.get("final_video_path") or "") or ""

        telemetry.record(
            language=str(result.get("output_language") or ""),
            is_science=bool(result.get("is_science")),
            subject=str(result.get("subject") or ""),
            video_needed=bool(result.get("video_needed")),
            render_attempt=result.get("render_attempt"),
            render_ok=bool(result.get("video_path")),
            render_error_tail=(result.get("render_error") or "")[-400:],
            status="complete",
        )

        return {
            "request_id": request_id,
            "status": "complete",
            "text": final_text,
            "video_path": video_path,
        }
    except Exception as e:
        # The response this exception drives (built by agent_client()'s own
        # except block, unchanged) still reads "complete" to the end user;
        # only the telemetry line records what actually happened.
        telemetry.record(status="error", error_type=type(e).__name__)
        raise
    finally:
        if tmp_image_path:
            try:
                os.remove(tmp_image_path)
            except Exception:
                pass
        telemetry.write()


async def agent_client() -> None:
    try:
        import websockets
    except Exception as e:
        raise SystemExit(
            "Missing dependency `websockets`. Install with: pip install websockets"
        ) from e

    url = DEFAULT_WS_URL
    print(f"Agent starting, will connect to: {url}")

    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=WS_PING_INTERVAL_SEC,
                ping_timeout=WS_PING_TIMEOUT_SEC,
                max_size=None,
            ) as websocket:
                print(f"Connected to backend as AI Agent: {url}")

                while True:
                    message = await websocket.recv()
                    data = json.loads(message)

                    request_id = data.get("request_id")
                    preview = (data.get("text") or "")[:80]
                    print(f"Received request {request_id}: {preview!r}")

                    try:
                        resp = await process_request(data)
                    except Exception as e:
                        # The end user must never see a traceback: log the real
                        # error here, hand back a friendly message instead.
                        print(
                            f"Request {request_id} failed: {type(e).__name__}: {e}",
                            flush=True,
                        )
                        resp = {
                            "request_id": request_id,
                            "status": "complete",
                            "text": _friendly_failure_text(data.get("text") or ""),
                            "video_path": "",
                        }

                    await websocket.send(json.dumps(resp, ensure_ascii=False))
                    print(f"Sent response for {request_id}: {resp.get('status')}")

        except Exception as e:
            print(f"Connection error: {type(e).__name__}: {e}")
            print(f"Reconnecting in {RECONNECT_DELAY_SEC:.0f} seconds...")
            await asyncio.sleep(RECONNECT_DELAY_SEC)


if __name__ == "__main__":
    asyncio.run(agent_client())

