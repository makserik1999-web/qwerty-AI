"""The UI socket: chat operations and forwarding questions to the agent."""

import json
import time
import uuid

from bson import ObjectId
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import (
    CACHE_ENABLED,
    COOKIE_NAME,
    NARRATION_DEFAULT,
    NARRATION_VOICE_DEFAULT,
    NARRATION_VOICES,
)
from app.db import db
from app.repositories.chats import create_chat, delete_chat_by_id
from app.repositories.messages import save_message
from app.security.origins import _is_allowed_origin
from app.security.sessions import _user_from_token
from app.services import cache_service, quota
from app.validators import (
    _validate_chat_id,
    _validate_prompt,
    _validate_screenshots,
    _validate_title,
)
from app.ws.manager import agent_manager, ui_manager

router = APIRouter()


async def _handle_ui_frame(websocket: WebSocket, user_id: str, data: dict) -> None:
    msg_type = data.get("type")
    payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}

    if msg_type == "ping":
        await websocket.send_json({"type": "pong"})
        return

    if msg_type == "create_chat":
        title = _validate_title(payload.get("title"))
        chat = await create_chat(user_id, title)
        await websocket.send_json({"type": "chat_created", "data": chat})
        return

    if msg_type == "delete_chat":
        chat_id = payload.get("chat_id")
        if chat_id and _validate_chat_id(chat_id):
            success = await delete_chat_by_id(chat_id, user_id)
            await websocket.send_json({
                "type": "chat_deleted",
                "data": {"chat_id": chat_id, "success": success},
            })
        else:
            await websocket.send_json({
                "type": "chat_deleted",
                "data": {"chat_id": chat_id, "success": False},
            })
        return

    if msg_type == "user_message":
        chat_id = payload.get("chat_id")
        prompt = payload.get("prompt", "")
        screenshots = payload.get("screenshots", [])

        if not chat_id or not _validate_chat_id(chat_id):
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Invalid chat_id", "chat_id": chat_id},
            })
            return

        prompt_err = _validate_prompt(prompt)
        if prompt_err:
            await websocket.send_json({
                "type": "error",
                "data": {"message": prompt_err, "chat_id": chat_id},
            })
            return

        shots_err = _validate_screenshots(screenshots)
        if shots_err:
            await websocket.send_json({
                "type": "error",
                "data": {"message": shots_err, "chat_id": chat_id},
            })
            return

        if not prompt and not screenshots:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Either prompt or screenshots required", "chat_id": chat_id},
            })
            return

        # Ownership check: the chat must belong to the session user.
        chat = await db.db.chats.find_one({"_id": ObjectId(chat_id), "user_id": user_id})
        if not chat:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Chat not found", "chat_id": chat_id},
            })
            return

        # Cache first: a stored answer costs a couple of database reads, while
        # a miss costs three LLM calls and minutes of rendering. This runs
        # BEFORE the agent-availability check on purpose - a question we have
        # already answered can be served even while the agent is down.
        # `force_regenerate` lets the user insist on a fresh answer.
        # What the asker wants made, not just asked. Validated against a
        # closed set before it goes anywhere near a cache key: a voice taken
        # straight from the client would let anyone mint unlimited entries for
        # one question.
        narration = bool(payload.get("narration", NARRATION_DEFAULT))
        voice = str(payload.get("narration_voice") or NARRATION_VOICE_DEFAULT)
        if voice not in NARRATION_VOICES:
            voice = NARRATION_VOICE_DEFAULT
        variant = cache_service.render_variant(narration, voice)

        cached = None
        if CACHE_ENABLED and not payload.get("force_regenerate"):
            try:
                cached = await cache_service.lookup(prompt, screenshots, variant)
            except Exception as e:
                # The cache must never be the reason a question goes unanswered.
                print(f"cache lookup failed, falling through to the agent: {type(e).__name__}: {e}")

        if cached:
            await save_message(chat_id, "user", prompt, screenshots)
            await websocket.send_json({"type": "message_received"})
            msg_data = await save_message(
                chat_id, "assistant", cached.get("educator_text", ""),
                video_url=cached.get("video_url"),
            )
            await websocket.send_json({
                "type": "ai_response",
                "data": {
                    "message_id": msg_data["id"],
                    "chat_id": chat_id,
                    "content": msg_data["content"],
                    "video_url": msg_data["video_url"],
                    "timestamp": msg_data["timestamp"],
                    # The UI marks these, so nobody is left wondering why an
                    # answer that normally takes minutes arrived instantly.
                    "from_cache": True,
                    "cache_tier": cached.get("tier", ""),
                    # "exact" or "semantic". A semantic hit answered a
                    # DIFFERENT wording, so the reader is shown which question
                    # was matched - they can see it is not what they meant.
                    "cache_match": cached.get("match", "exact"),
                    "matched_question": cached.get("matched_question", ""),
                },
            })
            return

        # Only a real generation is charged for, and only once the cache has
        # had its chance: an answer from the library costs a couple of reads,
        # so billing it would penalise exactly what protects the system.
        verdict = await quota.check(
            user_id,
            in_flight=agent_manager.in_flight_for(user_id),
            queue_depth=agent_manager.queue_depth(),
        )
        if not verdict.allowed:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": verdict.reason,
                    "chat_id": chat_id,
                    "quota": {
                        "remaining_hour": verdict.remaining_hour,
                        "remaining_day": verdict.remaining_day,
                        "retry_after_sec": verdict.retry_after_sec,
                    },
                },
            })
            return

        # Check agent availability BEFORE saving anything (no orphan messages).
        if not agent_manager.agent_connection:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": "AI Agent is not available. Please try again later.",
                    "chat_id": chat_id,
                },
            })
            return

        await save_message(chat_id, "user", prompt, screenshots)
        await websocket.send_json({"type": "message_received"})

        request_id = str(uuid.uuid4())
        agent_manager.pending_requests[request_id] = {
            "user_id": user_id,
            "chat_id": chat_id,
            "created_at": time.monotonic(),
            # Carried so the answer can be filed under the question that
            # produced it once the agent replies.
            "prompt": prompt,
            "screenshots": screenshots,
            # The answer must be filed under the same variant it was asked
            # for, or the next asker gets the wrong kind of video.
            "variant": variant,
        }
        await quota.record(user_id, request_id)
        try:
            await agent_manager.send_to_agent(
                request_id=request_id,
                user_id=user_id,
                chat_id=chat_id,
                text=prompt,
                screenshots=screenshots,
                narration=narration,
                narration_voice=voice,
            )
        except Exception as e:
            agent_manager.pending_requests.pop(request_id, None)
            # Nothing was rendered, so nothing is owed.
            await quota.refund(request_id)
            await websocket.send_json({
                "type": "error",
                "data": {
                    "message": f"Failed to send to agent: {e}",
                    "chat_id": chat_id,
                },
            })
        return

    # Unknown message type: ignore silently.


@router.websocket("/ws")
async def websocket_ui_endpoint(websocket: WebSocket):
    """WebSocket endpoint for UI clients; identity from the session cookie."""
    token = websocket.cookies.get(COOKIE_NAME)
    user = await _user_from_token(token)
    if not user:
        await websocket.close(code=1008, reason="not authenticated")
        return

    if not _is_allowed_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008, reason="origin not allowed")
        return

    user_id = str(user["_id"])
    try:
        await ui_manager.connect(websocket, user_id)
    except Exception as e:
        print(f"UI connect failed: {e}")
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("frame must be an object")
            except Exception as e:
                # One malformed frame must not kill the connection.
                try:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": f"Invalid message: {type(e).__name__}"},
                    })
                except Exception:
                    pass
                continue

            try:
                await _handle_ui_frame(websocket, user_id, data)
            except WebSocketDisconnect:
                raise
            except Exception as e:
                print(f"UI frame error for user {user_id}: {type(e).__name__}: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Internal error while processing message"},
                    })
                except Exception:
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"UI WebSocket error for user {user_id}: {type(e).__name__}: {e}")
    finally:
        ui_manager.disconnect(user_id, websocket)
