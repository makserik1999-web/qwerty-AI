"""
WebSocket AI Agent client wrapper for Science Manim Graph Agent.

This connects to the backend server endpoint (default: ws://backend:8000/ws/agent),
authenticates with the shared AGENT_SECRET handshake, receives JSON requests,
runs the existing science_manim_graph_agent pipeline, and returns JSON responses.

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
  "error": "<short error string if any>"
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
    AGENT_HANDSHAKE_TIMEOUT_SEC,
    AGENT_SECRET,
    DEFAULT_WS_URL,
    MAX_IMAGES,
    MAX_IMAGE_B64_LEN,
    MAX_IMAGE_BYTES,
    RECONNECT_DELAY_SEC,
    REQUEST_DEADLINE_SEC,
    WS_MAX_MESSAGE_SIZE,
    WS_PING_INTERVAL_SEC,
    WS_PING_TIMEOUT_SEC,
    WS_RECV_TIMEOUT_SEC,
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
    # Size limits: base64 text and its decoded bytes.
    if len(image_data) > MAX_IMAGE_B64_LEN:
        raise ValueError(f"Image is too large (max {MAX_IMAGE_BYTES // 1024} KiB)")
    img_bytes, ext = _decode_image_data(image_data)
    if len(img_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(f"Decoded image is too large (max {MAX_IMAGE_BYTES // 1024} KiB)")
    fd, path = tempfile.mkstemp(prefix="agent_img_", suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(img_bytes)
    return path


def _safe_error_text(exc: Exception, limit: int = 300) -> str:
    """Short, content-safe error text for the wire (never the whole traceback)."""
    return f"{type(exc).__name__}: {str(exc)[:limit]}"


async def process_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs the science manim graph agent for a single websocket request.
    Returns a response dict; on failure the response carries status "error"
    with a friendly text and a short error field (never a traceback).
    """
    from science_manim_graph_agent import app

    request_id = payload.get("request_id")
    text = (payload.get("text") or "").strip()
    image_data = payload.get("image_data")

    telemetry.new_run(request_id, text)
    tmp_image_paths: list = []
    try:
        if not request_id:
            raise ValueError("Missing request_id")
        if not text:
            raise ValueError("Missing text")

        initial: Dict[str, Any] = {"user_message": text}
        if image_data:
            if isinstance(image_data, list):
                items = [str(i) for i in image_data if str(i).strip()]
                if len(items) > MAX_IMAGES:
                    raise ValueError(f"Too many images (max {MAX_IMAGES})")
            else:
                items = [str(image_data)]
            for item in items:
                path = _materialize_image_to_tempfile(item)
                tmp_image_paths.append(path)
            initial["image_paths"] = tmp_image_paths
            if len(tmp_image_paths) == 1:
                initial["image_path"] = tmp_image_paths[0]

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
        # Honest status: the backend must know the request failed, not be
        # handed a fake "complete". The user only ever sees the friendly text.
        telemetry.record(status="error", error_type=type(e).__name__)
        return {
            "request_id": request_id,
            "status": "error",
            "text": _friendly_failure_text(text or ""),
            "video_path": "",
            "error": _safe_error_text(e),
        }
    finally:
        for path in tmp_image_paths:
            try:
                os.remove(path)
            except Exception:
                pass
        telemetry.write()


async def _authenticate(websocket) -> bool:
    """Send the AGENT_SECRET handshake and wait for auth_ok / auth_failed."""
    if not AGENT_SECRET:
        print(
            "FATAL: AGENT_SECRET is not set - the backend refuses unauthenticated "
            "agents. Set AGENT_SECRET in .env (same value on backend and agent).",
            flush=True,
        )
        return False
    try:
        await websocket.send(json.dumps({"type": "auth", "token": AGENT_SECRET}))
        raw = await asyncio.wait_for(
            websocket.recv(), timeout=AGENT_HANDSHAKE_TIMEOUT_SEC
        )
        data = json.loads(raw)
        if data.get("type") == "auth_ok":
            print("Agent authenticated (handshake ok)", flush=True)
            return True
        print(f"Agent handshake rejected by backend: {data}", flush=True)
        return False
    except Exception as e:
        print(
            f"Agent handshake failed: {type(e).__name__}: {str(e)[-200:]}",
            flush=True,
        )
        return False


async def agent_client() -> None:
    try:
        import websockets
    except Exception as e:
        raise SystemExit(
            "Missing dependency `websockets`. Install with: pip install websockets"
        ) from e

    url = DEFAULT_WS_URL
    print(f"Agent starting, will connect to: {url}")

    secret_warning_printed = False

    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=WS_PING_INTERVAL_SEC,
                ping_timeout=WS_PING_TIMEOUT_SEC,
                max_size=WS_MAX_MESSAGE_SIZE,
            ) as websocket:
                print(f"Connected to backend as AI Agent: {url}", flush=True)

                if not await _authenticate(websocket):
                    if not AGENT_SECRET and not secret_warning_printed:
                        secret_warning_printed = True
                        print(
                            "Will keep retrying - set AGENT_SECRET and restart the agent.",
                            flush=True,
                        )
                    raise RuntimeError("agent handshake failed")

                while True:
                    try:
                        message = await asyncio.wait_for(
                            websocket.recv(), timeout=WS_RECV_TIMEOUT_SEC
                        )
                    except asyncio.TimeoutError:
                        print(
                            "Idle receive timeout - reconnecting to stay fresh.",
                            flush=True,
                        )
                        break

                    try:
                        data = json.loads(message)
                    except Exception:
                        print("Received non-JSON message; ignoring", flush=True)
                        continue

                    request_id = data.get("request_id")
                    text = data.get("text") or ""
                    has_image = bool(data.get("image_data"))
                    # Redacted preview: never print user content.
                    print(
                        f"Received request {request_id}: "
                        f"{len(text)} chars, image={'yes' if has_image else 'no'}",
                        flush=True,
                    )

                    try:
                        resp = await asyncio.wait_for(
                            process_request(data), timeout=REQUEST_DEADLINE_SEC
                        )
                    except asyncio.TimeoutError:
                        print(
                            f"Request {request_id} timed out after "
                            f"{REQUEST_DEADLINE_SEC:.0f}s",
                            flush=True,
                        )
                        resp = {
                            "request_id": request_id,
                            "status": "error",
                            "text": _friendly_failure_text(text or ""),
                            "video_path": "",
                            "error": "processing timed out",
                        }
                    except Exception as e:  # pragma: no cover - process_request swallows
                        print(
                            f"Request {request_id} failed: {type(e).__name__}: {str(e)[-200:]}",
                            flush=True,
                        )
                        resp = {
                            "request_id": request_id,
                            "status": "error",
                            "text": _friendly_failure_text(text or ""),
                            "video_path": "",
                            "error": _safe_error_text(e),
                        }

                    await websocket.send(json.dumps(resp, ensure_ascii=False))
                    print(
                        f"Sent response for {request_id}: {resp.get('status')}",
                        flush=True,
                    )

        except Exception as e:
            print(f"Connection error: {type(e).__name__}: {str(e)[-200:]}")
            print(f"Reconnecting in {RECONNECT_DELAY_SEC:.0f} seconds...")
            await asyncio.sleep(RECONNECT_DELAY_SEC)


if __name__ == "__main__":
    asyncio.run(agent_client())