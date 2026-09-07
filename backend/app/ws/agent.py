"""The agent channel: authenticated handshake, then request/response relay."""

import asyncio
import json
import os
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import (
    _SAFE_MEDIA_RE,
    AGENT_HANDSHAKE_TIMEOUT_SEC,
    AGENT_SECRET,
    CACHE_ENABLED,
)
from app.repositories.messages import save_message
from app.services import cache_service, quota
from app.ws.manager import _notify_pending_failures, agent_manager, ui_manager

router = APIRouter()


@router.websocket("/ws/agent")
async def websocket_agent_endpoint(websocket: WebSocket):
    """WebSocket endpoint for AI Agent, protected by AGENT_SECRET handshake."""
    await websocket.accept()
    authed = False
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=AGENT_HANDSHAKE_TIMEOUT_SEC
        )
        data = json.loads(raw)
        if (
            data.get("type") == "auth"
            and AGENT_SECRET
            and secrets.compare_digest(str(data.get("token") or ""), AGENT_SECRET)
        ):
            authed = True
            features = data.get("features")
            agent_manager.agent_features = (
                {str(f) for f in features} if isinstance(features, list) else set()
            )
            await websocket.send_json({"type": "auth_ok"})
            print(f"AI Agent authenticated (features: "
                  f"{sorted(agent_manager.agent_features) or 'none'})")
        else:
            print("Agent handshake failed: wrong or missing AGENT_SECRET")
            await websocket.close(code=1008, reason="auth failed")
            return
    except Exception as e:
        print(f"Agent handshake error: {type(e).__name__}: {e}")
        try:
            await websocket.close(code=1008, reason="handshake failed")
        except Exception:
            pass
        return

    try:
        await agent_manager.connect(websocket)
    except Exception as e:
        print(f"Agent manager connect error: {e}")
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                print("Agent sent non-JSON message; ignoring")
                continue
            if not authed:
                continue

            request_id = data.get("request_id")

            # Embedding replies are internal lookups, not answers to a user:
            # they have no chat, no message and no quota behind them.
            if data.get("type") == "embed_result":
                agent_manager.resolve_embedding(
                    request_id,
                    None if data.get("error") else {
                        "vector": data.get("vector") or [],
                        "language": data.get("language") or "",
                        "model": data.get("model") or "",
                    },
                )
                continue

            # A stage report, not an answer: the request stays open and
            # nothing is saved. Forwarded so the person watching the three
            # steps sees them move instead of one indicator for ninety
            # seconds. `pop=False` matters - popping here would leave the real
            # answer with nowhere to go.
            if data.get("type") == "progress":
                stage = str(data.get("stage") or "")
                if stage in ("understand", "write", "render") and request_id:
                    info = agent_manager.get_request_info(request_id, pop=False)
                    if info:
                        await ui_manager.send_to_user(info["user_id"], {
                            "type": "progress",
                            "data": {"chat_id": info["chat_id"], "stage": stage},
                        })
                continue

            # A written paper, not an answer to a chat message: no chat, no
            # saved message, no quota of its own.
            if data.get("type") == "assessment_result":
                agent_manager.resolve_assessment(request_id, {
                    k: v for k, v in data.items()
                    if k in ("questions", "total_marks", "requested", "error")
                })
                continue

            response_text = data.get("text", "")
            status = data.get("status", "complete")
            video_path = data.get("video_path", "")
            # Free text from the model, passed through rather than validated:
            # it labels a badge, and the client maps what it recognises. A
            # closed set here would just be a second place to keep in step.
            subject = str(data.get("subject") or "")[:40]
            error = data.get("error", "")

            if not request_id:
                print("Agent sent message without request_id")
                continue

            pop_request = (status == "complete" or status == "error")
            request_info = agent_manager.get_request_info(request_id, pop=pop_request)

            if not request_info:
                print(f"Unknown request_id: {request_id}")
                continue

            user_id = request_info["user_id"]
            chat_id = request_info["chat_id"]

            if status == "error":
                # Give the quota back: charging for a video the user never
                # received is charging them for our failure.
                try:
                    await quota.refund(request_id)
                except Exception as e:
                    print(f"quota refund failed: {type(e).__name__}: {e}")
                await ui_manager.send_to_user(user_id, {
                    "type": "error",
                    "data": {
                        "message": error or "Agent processing failed",
                        "chat_id": chat_id,
                    },
                })
                continue

            video_url = None
            if video_path and _SAFE_MEDIA_RE.fullmatch(os.path.basename(video_path)):
                video_url = f"/media/{os.path.basename(video_path)}"

            if status == "complete" and response_text:
                try:
                    msg_data = await save_message(
                        chat_id, "assistant", response_text,
                        video_url=video_url,
                    )
                except Exception as e:
                    print(f"Failed to save assistant message: {type(e).__name__}: {e}")
                    continue

                await ui_manager.send_to_user(user_id, {
                    "type": "ai_response",
                    "data": {
                        "message_id": msg_data["id"],
                        "chat_id": chat_id,
                        "content": response_text,
                        "video_url": video_url,
                        "timestamp": msg_data["timestamp"],
                        "subject": subject,
                    },
                })

                # File the answer under the question that produced it. Done
                # after the user already has their reply, and never allowed to
                # fail the request: a cache write is an optimisation, not part
                # of answering.
                if CACHE_ENABLED:
                    try:
                        await cache_service.remember(
                            prompt=request_info.get("prompt", ""),
                            screenshots=request_info.get("screenshots", []),
                            text=response_text,
                            video_url=video_url,
                            variant=request_info.get("variant", ""),
                        )
                    except Exception as e:
                        print(f"cache write failed: {type(e).__name__}: {e}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Agent WebSocket error: {type(e).__name__}: {e}")
    finally:
        agent_manager.disconnect(websocket)
        # Only when nothing has taken this connection's place. An agent that
        # reconnected is an agent that is there, and telling everybody their
        # request failed because the previous socket finished closing would
        # be a failure we invented.
        if agent_manager.agent_connection is None:
            await _notify_pending_failures(
                "AI Agent is not available. Please try again later."
            )
