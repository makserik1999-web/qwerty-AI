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

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


DEFAULT_WS_URL = os.getenv("AGENT_WS_URL", "ws://backend:8000/ws/agent")
RECONNECT_DELAY_SEC = float(os.getenv("AGENT_WS_RECONNECT_DELAY_SEC", "5"))

# A single video can take minutes to render, during which this connection is
# idle. The default 20s keepalive closes it mid-render (1011 keepalive ping
# timeout) and the finished response is lost, so allow long quiet periods.
WS_PING_INTERVAL_SEC = float(os.getenv("AGENT_WS_PING_INTERVAL_SEC", "600"))
WS_PING_TIMEOUT_SEC = float(os.getenv("AGENT_WS_PING_TIMEOUT_SEC", "600"))

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


# Shown if the pipeline fails for a reason other than rendering (network,
# quota, upstream outage). The real error goes to the log, never to the user.
_GENERIC_FAILURE_MESSAGES = {
    "kk": (
        "Сәтсіз болды :( Жауапты дәл қазір дайындай алмадым. "
        "Сәл кейінірек қайта байқап көріңізші."
    ),
    "ru": (
        "Не получилось :( Сейчас не удалось подготовить ответ. "
        "Попробуйте, пожалуйста, ещё раз чуть позже."
    ),
    "en": (
        "Sorry, I could not prepare an answer right now. "
        "Please try again in a moment."
    ),
}


def _friendly_failure_text(user_text: str) -> str:
    try:
        from science_manim_graph_agent import (
            _detect_language,
            DEFAULT_OUTPUT_LANGUAGE,
        )
        lang = _detect_language(user_text) or DEFAULT_OUTPUT_LANGUAGE
    except Exception:
        lang = "kk"
    return _GENERIC_FAILURE_MESSAGES.get(lang, _GENERIC_FAILURE_MESSAGES["kk"])


async def process_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs the science manim graph agent for a single websocket request.
    """
    from science_manim_graph_agent import app

    request_id = payload.get("request_id")
    text = (payload.get("text") or "").strip()
    image_data = payload.get("image_data")

    if not request_id:
        raise ValueError("Missing request_id")
    if not text:
        raise ValueError("Missing text")

    tmp_image_path: Optional[str] = None
    try:
        initial: Dict[str, Any] = {"user_message": text}
        if image_data:
            tmp_image_path = _materialize_image_to_tempfile(str(image_data))
            initial["image_path"] = tmp_image_path

        result = await app.invoke(initial)
        final_text = (result.get("final_text") or "").strip()
        video_path = (result.get("final_video_path") or "") or ""

        return {
            "request_id": request_id,
            "status": "complete",
            "text": final_text,
            "video_path": video_path,
        }
    finally:
        if tmp_image_path:
            try:
                os.remove(tmp_image_path)
            except Exception:
                pass


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

